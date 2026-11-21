"""Flask application: REST API + MJPEG preview + server-sent events for the VisoMaster web UI."""
import hmac
import io
import json
import os
import string
import time
import traceback
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory, send_file, abort, make_response

import app.helpers.miscellaneous as misc_helpers

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
UPLOAD_DIR = os.path.join(os.getcwd(), 'uploads')
MEDIA_EXT = misc_helpers.image_extensions + misc_helpers.video_extensions


def create_server(webapp, token=None):
    flask_app = Flask(__name__, static_folder=None)
    flask_app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024 * 1024
    cookie_name = 'visomaster_token'

    # ------------------------------------------------------------ auth (optional)
    @flask_app.before_request
    def _auth():
        if not token:
            return None
        supplied = request.args.get('token') or request.cookies.get(cookie_name) or ''
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            return Response('Access denied. Open the URL with ?token=...', 401)
        if request.args.get('token') and request.path == '/':
            resp = make_response('', 302)
            resp.headers['Location'] = '/'
            resp.set_cookie(cookie_name, token, httponly=True, samesite='Strict', max_age=31536000)
            return resp
        return None

    @flask_app.after_request
    def _nocache(resp):
        if request.path.startswith('/api/') and not request.path.startswith('/api/thumb'):
            resp.headers['Cache-Control'] = 'no-store'
        return resp

    def ok(**kw):
        return jsonify({'ok': True, **kw})

    def err(message, code=400):
        return jsonify({'ok': False, 'error': str(message)}), code

    def body():
        return request.get_json(silent=True) or {}

    def guarded(fn):
        def wrapper(*a, **k):
            try:
                return fn(*a, **k)
            except (KeyError, FileNotFoundError) as e:
                return err(f'Not found: {e}', 404)
            except ValueError as e:
                return err(e, 400)
            except Exception as e:  # pylint: disable=broad-exception-caught
                traceback.print_exc()
                return err(e, 500)
        wrapper.__name__ = fn.__name__
        return wrapper

    # ------------------------------------------------------------ static
    @flask_app.get('/')
    def index():
        return send_from_directory(STATIC_DIR, 'index.html')

    @flask_app.get('/static/<path:name>')
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    # ------------------------------------------------------------ state
    @flask_app.get('/api/schema')
    def schema():
        s = webapp.reload_schema()
        return jsonify({'tabs': s['tabs'], 'defaults': webapp.default_parameters})

    @flask_app.get('/api/state')
    def state():
        return jsonify(webapp.snapshot())

    @flask_app.get('/api/events')
    def events():
        q = webapp.events.subscribe()

        def gen():
            try:
                yield 'retry: 1500\n\n'
                yield f'data: {json.dumps({"type": "hello"})}\n\n'
                while True:
                    try:
                        yield f'data: {q.get(timeout=15)}\n\n'
                    except Exception:  # queue.Empty -> keep-alive comment
                        yield ': keep-alive\n\n'
            finally:
                webapp.events.unsubscribe(q)
        return Response(gen(), mimetype='text/event-stream', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    @flask_app.get('/api/stream')
    def stream():
        hub = webapp.hub

        def gen():
            hub.client_connected()
            last = 0
            try:
                while True:
                    res = hub.wait_next(last, 10.0)
                    if res is None:
                        res = hub.latest()
                        if not res[1]:
                            continue
                    last, jpeg = res
                    if not jpeg:
                        continue
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
            finally:
                hub.client_disconnected()
        return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame', headers={'Cache-Control': 'no-store'})

    @flask_app.get('/api/outputs')
    @guarded
    def outputs_list():
        return jsonify(ok=True, items=webapp.list_outputs())

    @flask_app.get('/api/outputs/<oid>')
    def outputs_get(oid):
        path = webapp.outputs.get(oid)
        if not path or not os.path.isfile(path):
            abort(404)
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))

    @flask_app.get('/api/frame.jpg')
    def frame_jpg():
        _, jpeg = webapp.hub.latest()
        if not jpeg:
            abort(404)
        return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'no-store'})

    # ------------------------------------------------------------ thumbnails
    def thumb_response(data):
        if not data:
            abort(404)
        return Response(data, mimetype='image/jpeg', headers={'Cache-Control': 'public, max-age=31536000, immutable'})

    @flask_app.get('/api/thumb/media/<mid>')
    def thumb_media(mid):
        m = webapp.target_videos.get(mid)
        return thumb_response(m.thumb if m else None)

    @flask_app.get('/api/thumb/input/<fid>')
    def thumb_input(fid):
        f = webapp.input_faces.get(fid)
        return thumb_response(f.thumb if f else None)

    @flask_app.get('/api/thumb/target/<fid>')
    def thumb_target(fid):
        f = webapp.target_faces.get(fid)
        return thumb_response(f.thumb if f else None)

    # ------------------------------------------------------------ values
    @flask_app.post('/api/parameter')
    @guarded
    def set_parameter():
        d = body()
        webapp.update_parameter(d['name'], d['value'])
        return ok()

    @flask_app.post('/api/control')
    @guarded
    def set_control():
        d = body()
        webapp.update_control(d['name'], d['value'])
        return ok(value=webapp.control[d['name']])

    @flask_app.post('/api/flags')
    @guarded
    def set_flags():
        d = body()
        webapp.set_flags(d.get('swap'), d.get('edit'), d.get('mask'), d.get('compare'))
        return ok()

    # ------------------------------------------------------------ media
    @flask_app.post('/api/media/load')
    @guarded
    def media_load():
        d = body()
        if d.get('folder'):
            webapp.load_media_from_folder(d['folder'])
        else:
            webapp.load_media_from_files(d.get('files', []))
        return ok()

    @flask_app.post('/api/media/webcams')
    @guarded
    def media_webcams():
        webapp.load_webcams(bool(body().get('enabled')))
        return ok()

    @flask_app.post('/api/media/<mid>/select')
    @guarded
    def media_select(mid):
        webapp.select_media(mid)
        return ok()

    @flask_app.delete('/api/media/<mid>')
    @guarded
    def media_remove(mid):
        webapp.remove_media(mid)
        return ok()

    def save_uploads(sub):
        folder = os.path.join(UPLOAD_DIR, sub)
        os.makedirs(folder, exist_ok=True)
        paths = []
        for f in request.files.getlist('files'):
            name = os.path.basename(f.filename or '') or uuid.uuid4().hex
            dest = os.path.join(folder, name)
            if os.path.exists(dest):
                stem, ext = os.path.splitext(name)
                dest = os.path.join(folder, f'{stem}_{uuid.uuid4().hex[:6]}{ext}')
            f.save(dest)
            paths.append(dest)
        return paths

    @flask_app.post('/api/media/upload')
    @guarded
    def media_upload():
        webapp.load_media_from_files(save_uploads('target'))
        return ok()

    # ------------------------------------------------------------ input faces / embeddings
    @flask_app.post('/api/input_faces/load')
    @guarded
    def input_load():
        d = body()
        if d.get('folder'):
            webapp.load_input_faces_from_folder(d['folder'])
        else:
            webapp.load_input_faces_from_files(d.get('files', []))
        return ok()

    @flask_app.post('/api/input_faces/upload')
    @guarded
    def input_upload():
        webapp.load_input_faces_from_files(save_uploads('source'))
        return ok()

    @flask_app.post('/api/input_faces/<fid>/select')
    @guarded
    def input_select(fid):
        webapp.select_input_face(fid, body().get('modifier', ''))
        return ok()

    @flask_app.delete('/api/input_faces/<fid>')
    @guarded
    def input_remove(fid):
        webapp.remove_input_face(fid)
        return ok()

    @flask_app.post('/api/embeddings')
    @guarded
    def embedding_create():
        d = body()
        eid = webapp.create_embedding_from_faces(d.get('name'), d.get('face_ids') or webapp.checked_input_ids,
                                                 d.get('merge') or webapp.control['EmbMergeMethodSelection'])
        return ok(id=eid)

    @flask_app.post('/api/embeddings/<eid>/select')
    @guarded
    def embedding_select(eid):
        webapp.select_embedding(eid, body().get('modifier', ''))
        return ok()

    @flask_app.delete('/api/embeddings/<eid>')
    @guarded
    def embedding_remove(eid):
        webapp.remove_embedding(eid)
        return ok()

    @flask_app.get('/api/embeddings/export')
    @guarded
    def embeddings_export():
        if not webapp.merged_embeddings:
            raise ValueError('No embeddings available to save.')
        data = json.dumps(webapp.export_embeddings(), indent=4)
        return Response(data, mimetype='application/json', headers={'Content-Disposition': 'attachment; filename=embeddings.json'})

    @flask_app.post('/api/embeddings/import')
    @guarded
    def embeddings_import():
        f = request.files.get('file')
        if not f:
            raise ValueError('No file received.')
        webapp.import_embeddings(json.load(io.TextIOWrapper(f.stream, encoding='utf-8')))
        return ok()

    # ------------------------------------------------------------ target faces
    @flask_app.post('/api/target_faces/find')
    @guarded
    def tf_find():
        webapp.find_target_faces()
        return ok()

    @flask_app.post('/api/target_faces/clear')
    @guarded
    def tf_clear():
        webapp.clear_target_faces()
        return ok()

    @flask_app.post('/api/target_faces/<fid>/select')
    @guarded
    def tf_select(fid):
        webapp.select_target_face(fid)
        return ok()

    @flask_app.delete('/api/target_faces/<fid>')
    @guarded
    def tf_remove(fid):
        webapp.remove_target_face(fid)
        return ok()

    @flask_app.post('/api/target_faces/<fid>/copy')
    @guarded
    def tf_copy(fid):
        webapp.copy_parameters(fid)
        return ok()

    @flask_app.post('/api/target_faces/<fid>/paste')
    @guarded
    def tf_paste(fid):
        webapp.paste_parameters(fid)
        return ok()

    @flask_app.get('/api/target_faces/<fid>/parameters')
    @guarded
    def tf_params_export(fid):
        data = json.dumps(webapp.export_parameters(fid), indent=4)
        return Response(data, mimetype='application/json', headers={'Content-Disposition': 'attachment; filename=parameters.json'})

    @flask_app.post('/api/target_faces/<fid>/parameters')
    @guarded
    def tf_params_import(fid):
        f = request.files.get('file')
        if not f:
            raise ValueError('No file received.')
        data = json.load(io.TextIOWrapper(f.stream, encoding='utf-8'))
        webapp.import_parameters(fid, data, request.form.get('settings') == '1')
        return ok()

    # ------------------------------------------------------------ player
    @flask_app.post('/api/player/play')
    @guarded
    def p_play():
        webapp.play(record=bool(body().get('record')))
        return ok()

    @flask_app.post('/api/player/stop')
    @guarded
    def p_stop():
        webapp.stop()
        return ok()

    @flask_app.post('/api/player/seek')
    @guarded
    def p_seek():
        d = body()
        webapp.video_processor.seek(int(d['frame']), process=bool(d.get('process', True)))
        return ok()

    @flask_app.post('/api/player/advance')
    @guarded
    def p_advance():
        webapp.advance(int(body()['n']))
        return ok()

    @flask_app.post('/api/player/marker')
    @guarded
    def p_marker():
        d = body()
        action = d.get('action')
        if action == 'add':
            webapp.add_marker()
        elif action == 'remove':
            webapp.remove_marker()
        elif action in ('next', 'previous'):
            webapp.goto_marker(action)
        else:
            raise ValueError('Unknown marker action')
        return ok()

    @flask_app.post('/api/player/save_frame')
    @guarded
    def p_save_frame():
        return ok(file=webapp.save_current_frame())

    @flask_app.post('/api/player/clear_memory')
    @guarded
    def p_clear_mem():
        webapp.clear_gpu_memory()
        return ok()

    # ------------------------------------------------------------ workspace
    @flask_app.get('/api/workspace/export')
    @guarded
    def ws_export():
        data = json.dumps(webapp.workspace_data(), indent=4)
        return Response(data, mimetype='application/json', headers={'Content-Disposition': 'attachment; filename=workspace.json'})

    @flask_app.post('/api/workspace/save')
    @guarded
    def ws_save():
        return ok(file=webapp.save_workspace(body().get('filename') or 'last_workspace.json'))

    @flask_app.post('/api/workspace/load')
    @guarded
    def ws_load():
        d = body()
        path = d.get('filename') or 'last_workspace.json'
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        with open(path, 'r', encoding='utf-8') as f:
            webapp.load_workspace_async(json.load(f))
        return ok()

    @flask_app.post('/api/workspace/import')
    @guarded
    def ws_import():
        f = request.files.get('file')
        if not f:
            raise ValueError('No file received.')
        webapp.load_workspace_async(json.load(io.TextIOWrapper(f.stream, encoding='utf-8')))
        return ok()

    # ------------------------------------------------------------ server-side file browser
    @flask_app.get('/api/fs')
    @guarded
    def fs_list():
        path = request.args.get('path') or ''
        mode = request.args.get('mode', 'file')  # 'dir' | 'file' | 'media' | 'image' | 'json'
        if not path:
            path = os.getcwd()
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            path = os.path.dirname(path) if os.path.isdir(os.path.dirname(path)) else os.getcwd()
        exts = {'media': MEDIA_EXT, 'image': misc_helpers.image_extensions, 'json': ('.json',), 'video': misc_helpers.video_extensions}.get(mode)
        dirs, files = [], []
        try:
            for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
                try:
                    if entry.name.startswith('.'):
                        continue
                    if entry.is_dir():
                        dirs.append(entry.name)
                    elif mode != 'dir' and (exts is None or entry.name.lower().endswith(exts)):
                        files.append({'name': entry.name, 'size': entry.stat().st_size})
                except OSError:
                    continue
        except PermissionError:
            raise ValueError('Permission denied')
        roots = []
        if os.name == 'nt':
            roots = [f'{d}:\\' for d in string.ascii_uppercase if os.path.exists(f'{d}:\\')]
        else:
            roots = ['/', os.path.expanduser('~')]
        parent = os.path.dirname(path)
        return jsonify({'path': path, 'parent': parent if parent != path else '', 'dirs': dirs, 'files': files, 'roots': roots, 'sep': os.sep})

    @flask_app.post('/api/fs/mkdir')
    @guarded
    def fs_mkdir():
        d = body()
        os.makedirs(d['path'], exist_ok=True)
        return ok()

    @flask_app.get('/api/ping')
    def ping():
        return jsonify({'ok': True, 'time': time.time()})

    return flask_app

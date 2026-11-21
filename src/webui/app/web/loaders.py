"""Background workers that fill the media / input-face lists without blocking the HTTP server."""
import os
import traceback
import uuid
from typing import TYPE_CHECKING

import app.helpers.miscellaneous as misc_helpers
from app.web import media_ops
from app.web.layout.settings import CAMERA_BACKENDS

if TYPE_CHECKING:
    from app.web.state import WebApp


def load_target_media(app: 'WebApp', stop, folder_name=False, files_list=None, media_ids=None, webcam_mode=False):
    files_list = files_list or []
    media_ids = media_ids or []
    app.set_loading('media', True)
    try:
        paths = []
        if folder_name:
            recursive = app.control['TargetMediaFolderRecursiveToggle']
            paths += misc_helpers.get_video_files(folder_name, recursive) + misc_helpers.get_image_files(folder_name, recursive)
        paths += list(files_list)
        for i, path in enumerate(paths):
            if stop.is_set():
                break
            try:
                file_type = misc_helpers.get_file_type(path)
                if not file_type:
                    continue
                thumb = media_ops.extract_thumbnail(path, file_type)
                if thumb:
                    media_id = media_ids[i] if i < len(media_ids) else str(uuid.uuid1().int)
                    app.add_target_media(path, file_type, media_id, thumb)
            except Exception:  # pylint: disable=broad-exception-caught
                traceback.print_exc()
        if webcam_mode and not stop.is_set():
            backend = CAMERA_BACKENDS[app.control['WebcamBackendSelection']]
            for i in range(int(app.control['WebcamMaxNoSelection'])):
                if stop.is_set():
                    break
                try:
                    thumb = media_ops.extract_thumbnail(f'Webcam {i}', 'webcam', webcam_index=i, webcam_backend=backend)
                    if thumb:
                        app.add_target_media(f'Webcam {i}', 'webcam', str(uuid.uuid1().int), thumb,
                                             is_webcam=True, webcam_index=i, webcam_backend=backend)
                except Exception:  # pylint: disable=broad-exception-caught
                    traceback.print_exc()
    finally:
        app.set_loading('media', False)


def load_input_faces(app: 'WebApp', stop, folder_name=False, files_list=None, face_ids=None):
    from app.web import face_ops  # pylint: disable=import-outside-toplevel
    files_list = files_list or []
    face_ids = face_ids or []
    app.set_loading('faces', True)
    was_playing = app.video_processor.processing
    if was_playing:
        app.video_processor.stop_processing()
    try:
        face_ops.preload_detection_models(app)
        if folder_name:
            paths = sorted(misc_helpers.get_image_files(folder_name, app.control['InputFacesFolderRecursiveToggle']))
        else:
            paths = sorted(files_list) if not face_ids else list(files_list)
        for idx, path in enumerate(paths):
            if stop.is_set():
                break
            if not misc_helpers.is_image_file(path):
                continue
            try:
                res = face_ops.detect_input_face(app, path)
            except Exception:  # pylint: disable=broad-exception-caught
                traceback.print_exc()
                continue
            if res is None:
                continue
            face_img, store = res
            face_id = face_ids[idx] if idx < len(face_ids) else str(uuid.uuid1().int)
            app.add_input_face(path, face_img, store, face_id)
    finally:
        try:
            import torch  # pylint: disable=import-outside-toplevel
            torch.cuda.empty_cache()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        app.set_loading('faces', False)
        app.refresh_frame()
        app.update_gpu_memory()

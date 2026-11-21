import argparse
import atexit
import logging
import os
import signal
import sys


def parse_args():
    p = argparse.ArgumentParser(description='VisoMaster WebUI')
    p.add_argument('--host', default=os.environ.get('VISOMASTER_HOST', '127.0.0.1'))
    p.add_argument('--port', type=int, default=int(os.environ.get('VISOMASTER_PORT', '7860')))
    p.add_argument('--token', default=os.environ.get('VISOMASTER_TOKEN') or None,
                   help='Optional access token required to open the UI')
    return p.parse_args()


def main():
    args = parse_args()
    from app.web.state import WebApp
    from app.web.server import create_server

    webapp = WebApp()
    flask_app = create_server(webapp, token=args.token)

    done = {'v': False}

    def shutdown(*_):
        if done['v']:
            return
        done['v'] = True
        try:
            webapp.shutdown()
        except Exception as e:  # pylint: disable=broad-except
            print('Shutdown error:', e)

    atexit.register(shutdown)

    def on_signal(signum, _frame):
        shutdown()
        sys.exit(0)

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, on_signal)
        except Exception:  # pylint: disable=broad-except
            pass

    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    shown = 'localhost' if args.host in ('0.0.0.0', '::') else args.host
    url = f'http://{shown}:{args.port}'
    if args.token:
        url += f'/?token={args.token}'
    print(f'VisoMaster WebUI running on {url}', flush=True)
    print(f'Running on http://{shown}:{args.port}', flush=True)
    flask_app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()

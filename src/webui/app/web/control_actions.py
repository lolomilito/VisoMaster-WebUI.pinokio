"""Functions executed when a control (Settings tab) with an `exec_function` changes value."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.web.state import WebApp


def change_execution_provider(app: 'WebApp', new_provider):
    app.video_processor.stop_processing()
    app.models_processor.switch_providers_priority(new_provider)
    app.models_processor.clear_gpu_memory()
    app.update_gpu_memory()


def change_threads_number(app: 'WebApp', new_threads_number):
    app.video_processor.set_number_of_threads(new_threads_number)
    try:
        import torch  # pylint: disable=import-outside-toplevel
        torch.cuda.empty_cache()
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    app.update_gpu_memory()


def change_theme(app: 'WebApp', new_theme):
    """The theme is applied by the browser; nothing to do on the server."""


def set_video_playback_fps(app: 'WebApp', set_video_fps=False):
    if set_video_fps and app.video_processor.media_capture:
        app.control['VideoPlaybackCustomFpsSlider'] = int(round(app.video_processor.fps)) or 30
        app.invalidate('control')


def toggle_virtualcam(app: 'WebApp', toggle_value=False):
    if toggle_value:
        app.video_processor.enable_virtualcam()
    else:
        app.video_processor.disable_virtualcam()


def enable_virtualcam(app: 'WebApp', backend):
    app.video_processor.enable_virtualcam(backend=backend)


REGISTRY = {
    'change_execution_provider': change_execution_provider,
    'change_threads_number': change_threads_number,
    'change_theme': change_theme,
    'set_video_playback_fps': set_video_playback_fps,
    'toggle_virtualcam': toggle_virtualcam,
    'enable_virtualcam': enable_virtualcam,
}


def run(app: 'WebApp', exec_name: str, value):
    fn = REGISTRY.get(exec_name)
    if fn:
        fn(app, value)

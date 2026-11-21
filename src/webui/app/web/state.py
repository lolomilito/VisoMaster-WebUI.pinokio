"""
Application state + every action of the VisoMaster UI, without any GUI toolkit.

`WebApp` plays the role the Qt MainWindow used to have for the processing core
(`control`, `parameters`, `target_faces`, `models_processor`, `video_processor`, ...)
and exposes the actions that the HTTP API calls.
"""
import copy
import json
import os
import threading
import traceback
import uuid
from pathlib import Path
from typing import Dict

import cv2
import numpy as np
from PIL import Image

import app.helpers.miscellaneous as misc_helpers
from app.helpers.miscellaneous import ParametersDict
from app.web import control_actions, loaders
from app.web.hub import EventBus, FrameHub, Signal
from app.web.models import EmbeddingItem, InputFace, TargetFace, TargetMedia
from app.web.schema import build_schema

LAST_WORKSPACE = 'last_workspace.json'


class WebApp:
    def __init__(self, models_processor_factory=None, video_processor_factory=None):
        self.hub = FrameHub()
        self.events = EventBus()
        self.outputs = {}
        self._outputs_lock = threading.Lock()
        self.hub.on_change = lambda seq: self.events.publish('frame', seq=seq)
        self.lock = threading.RLock()

        # ---- shared with the processing core (names kept from the original main window) ----
        self.control: dict = {}
        self.parameters: Dict[str, ParametersDict] = {}
        self.default_parameters: dict = {}
        self.current_widget_parameters = {}
        self.copied_parameters: dict = {}
        self.markers: dict = {}
        self.target_faces: Dict[str, TargetFace] = {}
        self.dfm_models_data = misc_helpers.DFM_MODELS_DATA
        self.loading_new_media = False
        self.swap_faces_enabled = False
        self.edit_faces_enabled = False
        self.face_mask_enabled = False
        self.face_compare_enabled = False
        self.model_loading_signal = Signal(lambda: self._set_models_loading(True))
        self.model_loaded_signal = Signal(lambda: self._set_models_loading(False))
        self.display_messagebox_signal = Signal(lambda title, msg, *_: self.notify('error', title, msg))

        # ---- web UI state ----
        self.target_videos: Dict[str, TargetMedia] = {}
        self.input_faces: Dict[str, InputFace] = {}
        self.merged_embeddings: Dict[str, EmbeddingItem] = {}
        self.selected_media_id = False
        self.selected_target_face_id = False
        self.checked_input_ids = []
        self.checked_embedding_ids = []
        self.seek_position = 0
        self.ui_locked = False
        self.models_loading = 0
        self.loading = {'media': False, 'faces': False}
        self.last_target_media_folder_path = ''
        self.last_input_media_folder_path = ''
        self.loaded_embedding_filename = ''
        self._media_stop = threading.Event()
        self._faces_stop = threading.Event()
        self._gpu_busy = False
        self.gpu = {'used': 0, 'total': 0}

        # ---- widgets definition + defaults ----
        self.reload_schema()
        for name, w in self.schema['flat'].items():
            if w['kind'] == 'parameter':
                self.default_parameters[name] = w['default']
            else:
                self.control[name] = w['default']
        self.control['OutputMediaFolder'] = ''
        self.current_widget_parameters = ParametersDict(copy.deepcopy(self.default_parameters), self.default_parameters)

        # ---- processing core ----
        if models_processor_factory is None:
            from app.processors.models_processor import ModelsProcessor  # pylint: disable=import-outside-toplevel
            models_processor_factory = ModelsProcessor
        if video_processor_factory is None:
            from app.web.video_processor import VideoProcessor  # pylint: disable=import-outside-toplevel
            video_processor_factory = VideoProcessor
        self.video_processor = video_processor_factory(self)
        self.models_processor = models_processor_factory(self)
        self._limit_providers()

    # ================================================================== infrastructure
    def reload_schema(self):
        try:
            misc_helpers.get_dfm_models_data()
        except FileNotFoundError:
            misc_helpers.DFM_MODELS_DATA.clear()
        self.schema = build_schema()
        opts = getattr(self, '_provider_options', None)
        if opts and 'ProvidersPrioritySelection' in self.schema['flat']:
            self.schema['flat']['ProvidersPrioritySelection']['options'] = opts
        return self.schema

    def _limit_providers(self):
        """Only offer the execution providers that can actually run on this machine (CUDA / TensorRT / CPU)."""
        try:
            import torch  # pylint: disable=import-outside-toplevel
            cuda = bool(torch.cuda.is_available())
        except Exception:  # pylint: disable=broad-exception-caught
            cuda = False
        try:
            from app.processors import models_processor as mp  # pylint: disable=import-outside-toplevel
            trt = bool(getattr(mp, 'TENSORRT_AVAILABLE', False))
        except Exception:  # pylint: disable=broad-exception-caught
            trt = False
        options = (['CUDA'] if cuda else []) + (['TensorRT', 'TensorRT-Engine'] if cuda and trt else []) + ['CPU']
        self._provider_options = options
        w = self.schema['flat'].get('ProvidersPrioritySelection')
        if w:
            w['options'] = options
        if self.control.get('ProvidersPrioritySelection') not in options:
            self.control['ProvidersPrioritySelection'] = options[0]
            try:
                self.models_processor.switch_providers_priority(options[0])
            except Exception:  # pylint: disable=broad-exception-caught
                traceback.print_exc()

    def notify(self, level, title, message=''):
        self.events.publish('toast', level=level, title=title, message=message)

    def invalidate(self, *what):
        self.events.publish('invalidate', what=list(what))

    def player_state(self):
        vp = self.video_processor
        return {
            'frame': self.seek_position,
            'max_frame': int(vp.max_frame_number or 0),
            'fps': float(vp.fps or 0),
            'file_type': vp.file_type,
            'has_media': bool(vp.media_path),
            'playing': bool(vp.processing),
            'recording': bool(vp.recording and vp.processing),
            'markers': sorted(self.markers.keys()),
            'locked': self.ui_locked,
            'width': self.hub.size[0], 'height': self.hub.size[1],
        }

    def notify_player(self):
        self.events.publish('player', **self.player_state())

    def set_seek_position(self, position: int):
        self.seek_position = int(position)
        self.events.publish_throttled('player', **self.player_state())

    def set_ui_locked(self, locked: bool):
        self.ui_locked = bool(locked)
        self.notify_player()

    def set_loading(self, what: str, value: bool):
        self.loading[what] = value
        self.events.publish('loading', what=what, value=value)

    def _set_models_loading(self, loading: bool):
        self.models_loading = max(0, self.models_loading + (1 if loading else -1))
        self.events.publish('models_loading', value=self.models_loading > 0)

    def update_gpu_memory(self):
        if self._gpu_busy:
            return
        self._gpu_busy = True

        def run():
            try:
                used, total = self.models_processor.get_gpu_memory()
                self.gpu = {'used': int(used), 'total': int(total)}
                self.events.publish('gpu', **self.gpu)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            finally:
                self._gpu_busy = False
        threading.Thread(target=run, daemon=True).start()

    def refresh_frame(self):
        self.video_processor.request_refresh()

    # ================================================================== values
    def widget_info(self, name):
        return self.schema['flat'].get(name)

    def coerce(self, name, value):
        info = self.widget_info(name)
        if not info:
            return value
        t = info['type']
        if t == 'toggle':
            return bool(value)
        if t == 'select':
            return str(value)
        if t == 'text':
            return str(value)
        if t == 'slider':
            v = int(round(float(value)))
            return max(info['min'], min(info['max'], v))
        if t == 'decimal':
            v = round(float(value), info['decimals'])
            return max(info['min'], min(info['max'], v))
        return value

    def ui_parameters(self):
        """Parameter values the widgets should show (selected face, or the defaults for a new face)."""
        face_id = self.selected_target_face_id
        if face_id and self.parameters.get(face_id) is not None:
            params = self.parameters[face_id]
        elif self.current_widget_parameters:
            params = self.current_widget_parameters
        else:
            params = self.default_parameters
        data = params.data if isinstance(params, ParametersDict) else params
        return {**self.default_parameters, **data}

    def create_parameter_dict_for_face_id(self, face_id):
        if not self.parameters.get(face_id):
            params = self.parameters.get(self.selected_target_face_id) or self.current_widget_parameters or self.default_parameters
            if isinstance(params, dict):
                params = ParametersDict(params, self.default_parameters)
            self.parameters[face_id] = params.copy()

    def update_parameter(self, name, value):
        value = self.coerce(name, value)
        pos = self.seek_position
        face_id = self.selected_target_face_id
        if self.markers.get(pos) and face_id:
            marker_params = self.markers[pos]['parameters'].get(face_id)
            if marker_params is not None:
                marker_params[name] = value
        if self.target_faces and face_id:
            self.parameters[face_id][name] = value
            self.refresh_frame()
        if self.current_widget_parameters:
            self.current_widget_parameters[name] = value

    def update_control(self, name, value):
        if name not in self.control:
            raise KeyError(name)
        value = self.coerce(name, value) if name != 'OutputMediaFolder' else str(value)
        info = self.widget_info(name) or {}
        exec_name = info.get('exec')
        pos = self.seek_position
        if self.markers.get(pos) and not exec_name:
            self.markers[pos]['control'][name] = value
        if exec_name and self.control[name] != value:
            control_actions.run(self, exec_name, value)
        self.control[name] = value
        self.refresh_frame()

    def update_parameters_and_control_from_marker(self, position):
        if self.markers.get(position):
            self.parameters = copy.deepcopy(self.markers[position]['parameters'])
            self.control.update(self.markers[position]['control'].copy())

    def apply_marker_to_state(self, position):
        """A marker was hit while playing: tell the browser to re-read the widget values."""
        if self.markers.get(position):
            self.invalidate('params', 'control')

    # ================================================================== snapshot
    def snapshot(self):
        return {
            'control': dict(self.control),
            'parameters': self.ui_parameters(),
            'media': [m.to_dict() for m in self.target_videos.values()],
            'selected_media': self.selected_media_id,
            'target_faces': [f.to_dict() for f in self.target_faces.values()],
            'selected_target_face': self.selected_target_face_id,
            'input_faces': [f.to_dict() for f in self.input_faces.values()],
            'checked_input_faces': list(self.checked_input_ids),
            'embeddings': [e.to_dict() for e in self.merged_embeddings.values()],
            'checked_embeddings': list(self.checked_embedding_ids),
            'player': self.player_state(),
            'flags': {'swap': self.swap_faces_enabled, 'edit': self.edit_faces_enabled,
                      'mask': self.face_mask_enabled, 'compare': self.face_compare_enabled},
            'loading': dict(self.loading),
            'models_loading': self.models_loading > 0,
            'gpu': dict(self.gpu),
            'paths': {'target': self.last_target_media_folder_path, 'input': self.last_input_media_folder_path},
            'last_workspace': Path(LAST_WORKSPACE).is_file(),
            'copied_parameters': bool(self.copied_parameters),
        }

    # ================================================================== target media
    def add_target_media(self, path, file_type, media_id, thumb, is_webcam=False, webcam_index=-1, webcam_backend=-1):
        self.target_videos[media_id] = TargetMedia(path, file_type, media_id, thumb, is_webcam, webcam_index, webcam_backend)
        self.invalidate('media')

    def _stop_media_loader(self):
        self._media_stop.set()
        t = getattr(self, '_media_thread', None)
        if t and t.is_alive():
            t.join(timeout=5)
        self._media_stop = threading.Event()

    def load_media_from_folder(self, folder):
        if not os.path.isdir(folder):
            raise FileNotFoundError(folder)
        self.last_target_media_folder_path = folder
        self._start_media_loading(folder_name=folder)

    def load_media_from_files(self, files):
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return
        self.last_target_media_folder_path = misc_helpers.get_dir_of_file(files[0])
        self._start_media_loading(files_list=files)

    def _start_media_loading(self, **kwargs):
        self._stop_media_loader()
        self.clear_target_faces(refresh_frame=False)
        self.unload_selected_media()
        self.target_videos = {}
        self.invalidate('media', 'faces')
        stop = self._media_stop
        self._media_thread = threading.Thread(target=loaders.load_target_media, args=(self, stop), kwargs=kwargs, daemon=True)
        self._media_thread.start()

    def load_webcams(self, enabled: bool):
        if enabled:
            self._stop_media_loader()
            stop = self._media_stop
            self._media_thread = threading.Thread(target=loaders.load_target_media, args=(self, stop), kwargs={'webcam_mode': True}, daemon=True)
            self._media_thread.start()
        else:
            for media_id, media in list(self.target_videos.items()):
                if media.file_type == 'webcam':
                    self.remove_media(media_id)

    def unload_selected_media(self):
        vp = self.video_processor
        vp.stop_processing()
        selected = self.target_videos.get(self.selected_media_id)
        if selected and selected.media_capture:
            selected.media_capture.release()
            selected.media_capture = False
        if vp.media_capture:
            try:
                vp.media_capture.release()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        vp.current_frame_number = 0
        vp.media_path = False
        vp.media_capture = False
        vp.current_frame = []
        vp.fps = 0
        vp.max_frame_number = 0
        vp.file_type = None
        self.parameters = {}
        self.selected_target_face_id = False
        self.selected_media_id = False
        self.seek_position = 0
        self.hub.clear()
        self.notify_player()

    def select_media(self, media_id):
        media = self.target_videos.get(media_id)
        if media is None:
            raise KeyError(media_id)
        vp = self.video_processor
        vp.stop_processing()

        if self.selected_target_face_id and self.parameters.get(self.selected_target_face_id) is not None:
            self.current_widget_parameters = self.parameters[self.selected_target_face_id].copy()

        prev_input, prev_embeddings = [], []
        if self.control.get('AutoSwapToggle'):
            prev_input = [self.input_faces[i] for i in self.checked_input_ids if i in self.input_faces]
            prev_embeddings = [self.merged_embeddings[i] for i in self.checked_embedding_ids if i in self.merged_embeddings]

        vp.current_frame_number = 0
        vp.media_path = media.media_path
        self.parameters = {}
        self.selected_target_face_id = False
        vp.current_frame = []

        if vp.media_capture:
            vp.media_capture.release()
            vp.media_capture = None

        frame = None
        max_frames_number = 0
        if media.file_type == 'video':
            capture = cv2.VideoCapture(media.media_path)
            if not capture.isOpened():
                self.notify('error', 'Error opening video', media.media_path)
                return
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            max_frames_number = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) - 1
            _, frame = misc_helpers.read_frame(capture)
            vp.media_capture = capture
            media.media_capture = capture
            vp.fps = capture.get(cv2.CAP_PROP_FPS)
            vp.max_frame_number = max_frames_number
        elif media.file_type == 'image':
            frame = misc_helpers.read_image_file(media.media_path)
            vp.max_frame_number = 0
        elif media.file_type == 'webcam':
            res_width, res_height = self.control['WebcamMaxResSelection'].split('x')
            capture = cv2.VideoCapture(media.webcam_index, media.webcam_backend)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(res_width))
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(res_height))
            max_frames_number = 999999
            _, frame = misc_helpers.read_frame(capture)
            vp.media_capture = capture
            media.media_capture = capture
            vp.fps = capture.get(cv2.CAP_PROP_FPS)
            vp.max_frame_number = max_frames_number

        self.hub.clear()
        if frame is not None:
            if media.file_type == 'video':
                vp.media_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            vp.current_frame = frame
            vp.publish_frame(frame, 0)

        # reset the things that depend on the media
        self.clear_target_faces(refresh_frame=False)
        self.checked_input_ids = []
        self.checked_embedding_ids = []
        self.delete_all_markers()
        self.cur_target_face_reset()

        vp.file_type = media.file_type
        self.selected_media_id = media_id
        self.seek_position = 0
        self.loading_new_media = True
        self.invalidate('params', 'faces', 'lists')
        self.notify_player()
        self.refresh_frame()

        if self.control.get('AutoSwapToggle'):
            from app.web import face_ops  # pylint: disable=import-outside-toplevel
            face_ops.find_target_faces(self)
            for target_face in self.target_faces.values():
                for f in prev_input:
                    target_face.assigned_input_faces[f.face_id] = f.embedding_store
                for e in prev_embeddings:
                    target_face.assigned_merged_embeddings[e.embedding_id] = e.embedding_store
                target_face.calculate_assigned_input_embedding(self.control)
            self.checked_input_ids = [f.face_id for f in prev_input]
            self.checked_embedding_ids = [e.embedding_id for e in prev_embeddings]
            if self.target_faces:
                self.select_target_face(list(self.target_faces.keys())[0])
            self.refresh_frame()
            self.invalidate('faces', 'lists')

        if self.control['SendVirtCamFramesEnableToggle'] and media.file_type != 'image':
            vp.enable_virtualcam()

    def cur_target_face_reset(self):
        self.selected_target_face_id = False

    def remove_media(self, media_id):
        media = self.target_videos.get(media_id)
        if media is None:
            return
        if self.selected_media_id == media_id:
            self.unload_selected_media()
            self.clear_target_faces(refresh_frame=False)
            self.checked_input_ids = []
            self.checked_embedding_ids = []
            self.delete_all_markers()
        elif media.media_capture:
            media.media_capture.release()
        self.target_videos.pop(media_id, None)
        self.invalidate('media', 'faces', 'lists', 'params')

    # ================================================================== target faces
    def add_target_face(self, cropped_face, embedding_store, face_id):
        self.target_faces[face_id] = TargetFace('', cropped_face, embedding_store, face_id)
        self.create_parameter_dict_for_face_id(face_id)
        self.invalidate('faces')

    def clear_target_faces(self, refresh_frame=True):
        if self.video_processor.processing:
            self.video_processor.stop_processing()
        self.target_faces = {}
        self.parameters = {}
        self.selected_target_face_id = False
        self.invalidate('faces', 'params')
        if refresh_frame:
            self.refresh_frame()

    def select_target_face(self, face_id):
        face = self.target_faces.get(face_id)
        if face is None:
            raise KeyError(face_id)
        self.selected_target_face_id = face_id
        self.checked_input_ids = [i for i in face.assigned_input_faces.keys() if i in self.input_faces]
        self.checked_embedding_ids = [i for i in face.assigned_merged_embeddings.keys() if i in self.merged_embeddings]
        self.current_widget_parameters = self.parameters[face_id].copy()
        self.invalidate('faces', 'lists', 'params')

    def remove_target_face(self, face_id):
        if face_id not in self.target_faces:
            return
        if self.video_processor.processing:
            self.video_processor.stop_processing()
        self.target_faces.pop(face_id)
        self.parameters.pop(face_id, None)
        if self.target_faces:
            self.select_target_face(list(self.target_faces.keys())[0])
        else:
            self.selected_target_face_id = False
            self.checked_input_ids = []
            self.checked_embedding_ids = []
        # remove the face from every marker; with no faces left no marker makes sense
        for marker in list(self.markers.values()):
            marker['parameters'].pop(face_id, None)
            if not marker['parameters']:
                self.delete_all_markers()
                break
        self.invalidate('faces', 'lists', 'params')
        self.notify_player()
        self.refresh_frame()

    def find_target_faces(self):
        from app.web import face_ops  # pylint: disable=import-outside-toplevel
        face_ops.find_target_faces(self)
        self.invalidate('faces', 'lists', 'params')

    def copy_parameters(self, face_id):
        self.copied_parameters = self.parameters[face_id].copy()

    def paste_parameters(self, face_id):
        if not self.copied_parameters:
            raise ValueError('You need to copy parameters from any of the target faces before pasting them.')
        self.parameters[face_id] = self.copied_parameters.copy()
        if self.selected_target_face_id == face_id:
            self.current_widget_parameters = self.parameters[face_id].copy()
        self.invalidate('params')
        self.refresh_frame()

    def export_parameters(self, face_id):
        return {'parameters': dict(self.parameters[face_id].data), 'control': dict(self.control)}

    def import_parameters(self, face_id, data, load_settings=False):
        self.parameters[face_id] = ParametersDict(dict(data['parameters']), self.default_parameters)
        if self.selected_target_face_id == face_id:
            self.current_widget_parameters = self.parameters[face_id].copy()
        if load_settings:
            self.control.update(data['control'])
            self.apply_control_side_effects()
        self.invalidate('params', 'control')
        self.refresh_frame()

    # ================================================================== input faces / embeddings
    def add_input_face(self, path, cropped_face, embedding_store, face_id):
        self.input_faces[face_id] = InputFace(path, cropped_face, embedding_store, face_id)
        self.invalidate('lists')

    def _stop_faces_loader(self):
        self._faces_stop.set()
        t = getattr(self, '_faces_thread', None)
        if t and t.is_alive():
            t.join(timeout=10)
        self._faces_stop = threading.Event()

    def load_input_faces_from_folder(self, folder):
        if not os.path.isdir(folder):
            raise FileNotFoundError(folder)
        self.last_input_media_folder_path = folder
        self._start_faces_loading(folder_name=folder)

    def load_input_faces_from_files(self, files):
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return
        self.last_input_media_folder_path = misc_helpers.get_dir_of_file(files[0])
        self._start_faces_loading(files_list=files)

    def _start_faces_loading(self, **kwargs):
        self._stop_faces_loader()
        self.clear_input_faces()
        stop = self._faces_stop
        self._faces_thread = threading.Thread(target=loaders.load_input_faces, args=(self, stop), kwargs=kwargs, daemon=True)
        self._faces_thread.start()

    def clear_input_faces(self):
        self.input_faces = {}
        self.checked_input_ids = []
        for target_face in self.target_faces.values():
            target_face.assigned_input_faces = {}
            target_face.calculate_assigned_input_embedding(self.control)
        self.invalidate('lists')
        self.refresh_frame()

    def clear_merged_embeddings(self):
        self.merged_embeddings = {}
        self.checked_embedding_ids = []
        for target_face in self.target_faces.values():
            target_face.assigned_merged_embeddings = {}
            target_face.calculate_assigned_input_embedding(self.control)
        self.invalidate('lists')
        self.refresh_frame()

    def remove_input_face(self, face_id):
        self.input_faces.pop(face_id, None)
        if face_id in self.checked_input_ids:
            self.checked_input_ids.remove(face_id)
        for target_face in self.target_faces.values():
            if target_face.assigned_input_faces.pop(face_id, None) is not None:
                target_face.calculate_assigned_input_embedding(self.control)
        self.invalidate('lists')
        self.refresh_frame()

    def remove_embedding(self, embedding_id):
        self.merged_embeddings.pop(embedding_id, None)
        if embedding_id in self.checked_embedding_ids:
            self.checked_embedding_ids.remove(embedding_id)
        for target_face in self.target_faces.values():
            if target_face.assigned_merged_embeddings.pop(embedding_id, None) is not None:
                target_face.calculate_assigned_input_embedding(self.control)
        self.invalidate('lists')
        self.refresh_frame()

    def _cur_target_face(self):
        return self.target_faces.get(self.selected_target_face_id) if self.selected_target_face_id else None

    def select_input_face(self, face_id, modifier=''):
        """Click on an input face. modifier: '' | 'ctrl' | 'shift' (same rules as the desktop UI)."""
        if face_id not in self.input_faces:
            raise KeyError(face_id)
        order = list(self.input_faces.keys())
        checked = set(self.checked_input_ids)
        now_checked = face_id not in checked
        if now_checked:
            checked.add(face_id)
        else:
            checked.discard(face_id)
        target = self._cur_target_face()

        if target is not None:
            if modifier == 'shift':
                current = order.index(face_id)
                second_last = None
                if len(order) >= 2:
                    count = 0
                    for i in range(len(order) - 1, -1, -1):
                        if order[i] in checked:
                            count += 1
                            if count == 2:
                                second_last = i
                                break
                if second_last is not None:
                    selected = []
                    if current >= second_last:
                        trailing = []
                        for i in range(second_last - 1, -1, -1):
                            if order[i] in checked:
                                trailing.append(i)
                            else:
                                break
                        if trailing:
                            for i in range(trailing[-1] - 1, -1, -1):
                                checked.discard(order[i])
                            lo = trailing[-1]
                        else:
                            lo = second_last
                        for i in range(lo, current + 1):
                            checked.add(order[i])
                            selected.append(self.input_faces[order[i]])
                    else:
                        for fid in target.assigned_input_faces.keys():
                            if fid != face_id:
                                checked.discard(fid)
                    target.assigned_input_faces = {}
                    for f in selected:
                        target.assigned_input_faces[f.face_id] = f.embedding_store
            elif modifier != 'ctrl':
                for fid in target.assigned_input_faces.keys():
                    if fid != face_id:
                        checked.discard(fid)
                target.assigned_input_faces = {}

            target.assigned_input_faces[face_id] = self.input_faces[face_id].embedding_store
            if not now_checked:
                target.assigned_input_faces.pop(face_id, None)
            target.calculate_assigned_input_embedding(self.control)
        else:
            if modifier != 'ctrl':
                checked = {face_id} if now_checked else set()

        self.checked_input_ids = [i for i in order if i in checked]
        self.invalidate('lists')
        self.refresh_frame()

    def select_embedding(self, embedding_id, modifier=''):
        if embedding_id not in self.merged_embeddings:
            raise KeyError(embedding_id)
        order = list(self.merged_embeddings.keys())
        checked = set(self.checked_embedding_ids)
        now_checked = embedding_id not in checked
        if now_checked:
            checked.add(embedding_id)
        else:
            checked.discard(embedding_id)
        target = self._cur_target_face()
        if target is not None:
            if modifier != 'ctrl':
                for eid in target.assigned_merged_embeddings.keys():
                    if eid != embedding_id:
                        checked.discard(eid)
                target.assigned_merged_embeddings = {}
            target.assigned_merged_embeddings[embedding_id] = self.merged_embeddings[embedding_id].embedding_store
            if not now_checked:
                target.assigned_merged_embeddings.pop(embedding_id, None)
            target.calculate_assigned_input_embedding(self.control)
        elif modifier != 'ctrl':
            checked = {embedding_id} if now_checked else set()
        self.checked_embedding_ids = [i for i in order if i in checked]
        self.invalidate('lists')
        self.refresh_frame()

    def add_embedding(self, name, store, embedding_id=None):
        embedding_id = embedding_id or str(uuid.uuid1().int)
        self.merged_embeddings[embedding_id] = EmbeddingItem(name, store, embedding_id)
        self.invalidate('lists')
        return embedding_id

    def create_embedding_from_faces(self, name, face_ids, merge_type='Mean'):
        name = (name or '').strip()
        if not name:
            raise ValueError('Embedding name cannot be empty.')
        stores = [self.input_faces[i].embedding_store for i in face_ids if i in self.input_faces]
        if not stores:
            raise ValueError('You need to select at least one face to create a merged embedding.')
        merged: Dict[str, list] = {}
        for store in stores:
            for model, emb in store.items():
                merged.setdefault(model, []).append(emb)
        final = {}
        for model, embs in merged.items():
            final[model] = np.mean(embs, axis=0) if merge_type == 'Mean' else np.median(embs, axis=0)
        return self.add_embedding(name, final)

    def export_embeddings(self):
        return [{'name': e.embedding_name, 'embedding_store': {k: v.tolist() for k, v in e.embedding_store.items()}}
                for e in self.merged_embeddings.values()]

    def import_embeddings(self, embeddings_list):
        self.clear_merged_embeddings()
        for embed_data in embeddings_list:
            store = {k: np.array(v) for k, v in embed_data.get('embedding_store', {}).items()}
            self.add_embedding(embed_data['name'], store)

    # ================================================================== player
    def set_flags(self, swap=None, edit=None, mask=None, compare=None):
        if swap is not None:
            self.swap_faces_enabled = bool(swap)
        if edit is not None:
            self.edit_faces_enabled = bool(edit)
        if mask is not None:
            self.face_mask_enabled = bool(mask)
        if compare is not None:
            self.face_compare_enabled = bool(compare)
        self.refresh_frame()
        self.events.publish('flags', swap=self.swap_faces_enabled, edit=self.edit_faces_enabled,
                            mask=self.face_mask_enabled, compare=self.face_compare_enabled)

    def play(self, record=False):
        vp = self.video_processor
        if not vp.media_path:
            raise ValueError('Select a target media first.')
        if vp.file_type == 'image':
            return
        if vp.processing or vp.current_frame_number == vp.max_frame_number:
            vp.stop_processing()
            return
        if record:
            if vp.file_type == 'webcam':
                raise ValueError('Webcam streams cannot be recorded.')
            if not misc_helpers.is_ffmpeg_in_path():
                raise ValueError('FFMPEG was not found in your system. Check your installation.')
            vp.recording = True
        vp.process_video()

    def stop(self):
        self.video_processor.stop_processing()
        self.video_processor.recording = False
        self.notify_player()

    def advance(self, n):
        vp = self.video_processor
        if vp.media_capture:
            vp.seek(min(self.seek_position + n, vp.max_frame_number))

    def save_current_frame(self):
        folder = self.output_folder()
        frame = self.video_processor.current_frame
        if not isinstance(frame, np.ndarray):
            raise ValueError('Cannot save the current frame.')
        os.makedirs(folder, exist_ok=True)
        filename = misc_helpers.get_output_file_path(self.video_processor.media_path, folder, media_type='image')
        Image.fromarray(frame[..., ::-1].copy()).save(filename, 'PNG')
        self.notify('success', 'Image saved', filename)
        self.register_output(filename)
        return filename

    # ---- outputs (files created on the server that the browser can download)
    def output_folder(self):
        folder = (self.control.get('OutputMediaFolder') or '').strip()
        if not folder:
            folder = os.path.join(os.getcwd(), 'outputs')
        os.makedirs(folder, exist_ok=True)
        return folder

    def register_output(self, path):
        with self._outputs_lock:
            oid = uuid.uuid4().hex[:12]
            self.outputs[oid] = path
            while len(self.outputs) > 100:
                self.outputs.pop(next(iter(self.outputs)))
        self.events.publish('output', id=oid, name=os.path.basename(path))
        return oid

    def list_outputs(self):
        with self._outputs_lock:
            items = [(i, p) for i, p in self.outputs.items() if os.path.isfile(p)]
        return [{'id': i, 'name': os.path.basename(p), 'size': os.path.getsize(p)} for i, p in reversed(items)]

    def clear_gpu_memory(self):
        self.video_processor.stop_processing()
        self.models_processor.clear_gpu_memory()
        self.swap_faces_enabled = False
        self.edit_faces_enabled = False
        self.update_gpu_memory()
        self.delete_all_markers()
        self.events.publish('flags', swap=False, edit=False, mask=self.face_mask_enabled, compare=self.face_compare_enabled)
        self.notify_player()

    # ---- markers
    def add_marker(self, position=None):
        if self.video_processor.file_type != 'video':
            raise ValueError('Markers can only be used for videos.')
        position = self.seek_position if position is None else int(position)
        if not self.target_faces:
            raise ValueError('You need to have at least one target face to create a marker.')
        if self.markers.get(position):
            raise ValueError('A marker already exists for this position.')
        self.markers[position] = {'parameters': copy.deepcopy(self.parameters), 'control': self.control.copy()}
        self.notify_player()

    def remove_marker(self, position=None):
        if self.video_processor.file_type != 'video':
            raise ValueError('Markers can only be used for videos.')
        position = self.seek_position if position is None else int(position)
        if not self.markers.get(position):
            raise ValueError('No marker found for this position.')
        self.markers.pop(position)
        self.notify_player()

    def delete_all_markers(self):
        self.markers = {}

    def goto_marker(self, direction):
        positions = sorted(self.markers.keys())
        cur = self.seek_position
        if direction == 'next':
            cand = [m for m in positions if m > cur]
            new = cand[0] if cand else None
        else:
            cand = [m for m in positions if m < cur]
            new = cand[-1] if cand else None
        if new is not None:
            self.video_processor.seek(new)

    # ================================================================== settings side effects
    def apply_control_side_effects(self):
        """After loading settings from a file, run the exec functions of the controls that have one."""
        for name, info in self.schema['flat'].items():
            if info['kind'] == 'control' and info.get('exec') and name in self.control:
                try:
                    control_actions.run(self, info['exec'], self.control[name])
                except Exception:  # pylint: disable=broad-exception-caught
                    traceback.print_exc()

    # ================================================================== workspace
    def workspace_data(self):
        target_faces_data, embeddings_data, input_faces_data = {}, {}, {}
        for face_id, f in self.input_faces.items():
            input_faces_data[face_id] = {'media_path': f.media_path}
        for face_id, tf in self.target_faces.items():
            target_faces_data[face_id] = {
                'cropped_face': tf.cropped_face.tolist(),
                'embedding_store': {m: e.tolist() for m, e in tf.embedding_store.items()},
                'parameters': self.parameters[face_id].data.copy(),
                'control': self.control.copy(),
                'assigned_input_faces': list(tf.assigned_input_faces.keys()),
                'assigned_merged_embeddings': list(tf.assigned_merged_embeddings.keys()),
                'assigned_input_embedding': {m: e.tolist() for m, e in tf.assigned_input_embedding.items()},
            }
        for emb_id, e in self.merged_embeddings.items():
            embeddings_data[emb_id] = {'embedding_store': {m: v.tolist() for m, v in e.embedding_store.items()},
                                       'embedding_name': e.embedding_name}
        target_medias_data = [{'media_id': mid, 'media_path': m.media_path} for mid, m in self.target_videos.items() if not m.is_webcam]
        markers = copy.deepcopy(self.markers)
        for marker in markers.values():
            for fid, p in list(marker['parameters'].items()):
                marker['parameters'][fid] = p.data if isinstance(p, ParametersDict) else p
        current = self.current_widget_parameters
        return {
            'selected_media_id': self.selected_media_id,
            'target_medias_data': target_medias_data,
            'target_faces_data': target_faces_data,
            'embeddings_data': embeddings_data,
            'input_faces_data': input_faces_data,
            'markers': markers,
            'control': self.control,
            'last_target_media_folder_path': self.last_target_media_folder_path,
            'last_input_media_folder_path': self.last_input_media_folder_path,
            'loaded_embedding_filename': self.loaded_embedding_filename,
            'current_widget_parameters': current.data if isinstance(current, ParametersDict) else current,
        }

    def save_workspace(self, filename=LAST_WORKSPACE):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.workspace_data(), f, indent=4)
        return filename

    def load_workspace_async(self, data):
        threading.Thread(target=self._load_workspace_safe, args=(data,), daemon=True).start()

    def _load_workspace_safe(self, data):
        try:
            self.load_workspace(data)
            self.notify('success', 'Workspace loaded')
        except Exception as e:  # pylint: disable=broad-exception-caught
            traceback.print_exc()
            self.notify('error', 'Could not load the workspace', str(e))

    def load_workspace(self, data):
        self._stop_media_loader()
        self._stop_faces_loader()
        self.unload_selected_media()
        self.target_videos = {}
        self.clear_input_faces()
        self.clear_target_faces(refresh_frame=False)
        self.clear_merged_embeddings()
        self.delete_all_markers()

        # settings first: the detectors/recognition settings are needed to rebuild the input faces
        for name, value in data.get('control', {}).items():
            if name in self.control:
                self.control[name] = value

        # target media (synchronously, we need them selectable below)
        stop = threading.Event()
        medias = data.get('target_medias_data', [])
        loaders.load_target_media(self, stop, files_list=[m['media_path'] for m in medias if os.path.isfile(m['media_path'])],
                                  media_ids=[m['media_id'] for m in medias if os.path.isfile(m['media_path'])])

        # input faces (re-detected from their image files, keeping their ids)
        input_items = [(fid, d['media_path']) for fid, d in data.get('input_faces_data', {}).items()]
        if input_items:
            loaders.load_input_faces(self, stop, files_list=[p for _, p in input_items], face_ids=[i for i, _ in input_items])

        for emb_id, emb in data.get('embeddings_data', {}).items():
            store = {m: np.array(v) for m, v in emb['embedding_store'].items()}
            self.add_embedding(emb['embedding_name'], store, embedding_id=emb_id)

        selected = data.get('selected_media_id')
        if selected is not False and selected in self.target_videos:
            self.select_media(selected)

        for face_id, tf_data in data.get('target_faces_data', {}).items():
            cropped = np.array(tf_data['cropped_face']).astype('uint8')
            store = {m: np.array(v) for m, v in tf_data['embedding_store'].items()}
            self.add_target_face(cropped, store, face_id)
            self.parameters[face_id] = ParametersDict(dict(tf_data['parameters']), self.default_parameters)
            tf = self.target_faces[face_id]
            for emb_id in tf_data.get('assigned_merged_embeddings', []):
                if emb_id in self.merged_embeddings:
                    tf.assigned_merged_embeddings[emb_id] = self.merged_embeddings[emb_id].embedding_store
            for in_id in tf_data.get('assigned_input_faces', []):
                if in_id in self.input_faces:
                    tf.assigned_input_faces[in_id] = self.input_faces[in_id].embedding_store
            tf.assigned_input_embedding = {m: np.array(v) for m, v in tf_data.get('assigned_input_embedding', {}).items()}

        for position, marker in data.get('markers', {}).items():
            params = {fid: ParametersDict(p, self.default_parameters) for fid, p in marker['parameters'].items()}
            self.markers[int(position)] = {'parameters': params, 'control': marker['control']}

        self.last_target_media_folder_path = data.get('last_target_media_folder_path', '')
        self.last_input_media_folder_path = data.get('last_input_media_folder_path', '')
        self.loaded_embedding_filename = data.get('loaded_embedding_filename', '')
        self.control['OutputMediaFolder'] = data.get('control', {}).get('OutputMediaFolder', '')
        self.apply_control_side_effects()

        if self.target_faces:
            self.select_target_face(list(self.target_faces.keys())[0])
        else:
            cwp = data.get('current_widget_parameters', self.default_parameters.copy())
            self.current_widget_parameters = ParametersDict(cwp, self.default_parameters)
        self.invalidate('media', 'faces', 'lists', 'params', 'control')
        self.notify_player()
        self.refresh_frame()

    def shutdown(self):
        try:
            self.video_processor.stop_processing()
            self._stop_media_loader()
            self._stop_faces_loader()
            self.save_workspace(LAST_WORKSPACE)
        except Exception:  # pylint: disable=broad-exception-caught
            traceback.print_exc()

"""Playback / recording engine (no GUI toolkit): reads frames, runs FrameWorkers and publishes previews."""
import gc
import os
import queue
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Dict

import cv2
import numpy

try:
    import pyvirtualcam
except Exception:  # pylint: disable=broad-exception-caught
    pyvirtualcam = None

from app.processors.workers.frame_worker import FrameWorker
import app.helpers.miscellaneous as misc_helpers

if TYPE_CHECKING:
    from app.web.state import WebApp

PREVIEW_MAX_WIDTH = int(os.environ.get('VISOMASTER_PREVIEW_MAX_WIDTH', '1920'))
PREVIEW_QUALITY = int(os.environ.get('VISOMASTER_PREVIEW_QUALITY', '88'))


def _empty_cuda_cache():
    try:
        import torch  # pylint: disable=import-outside-toplevel
        torch.cuda.empty_cache()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


class VideoProcessor:
    def __init__(self, app: 'WebApp', num_threads=2):
        self.main_window = app
        self.app = app
        self.frame_queue = queue.Queue(maxsize=num_threads)
        self.media_capture: cv2.VideoCapture | None = None
        self.file_type = None
        self.fps = 0
        self.processing = False
        self.current_frame_number = 0
        self.max_frame_number = 0
        self.media_path = None
        self.num_threads = num_threads
        self.threads: Dict[int, threading.Thread] = {}

        self.current_frame: numpy.ndarray = []
        self.recording = False
        self.virtcam = None
        self.recording_sp: subprocess.Popen | None = None
        self.temp_file = ''

        self.start_time = 0.0
        self.end_time = 0.0
        self.play_start_time = 0.0
        self.play_end_time = 0.0

        self.next_frame_to_display = 0
        self.frames_to_display: Dict[int, numpy.ndarray] = {}
        self.webcam_frames_to_display = queue.Queue()

        self.op_lock = threading.RLock()
        self._generation = 0
        self._reading = False
        self._read_thread: threading.Thread | None = None
        self._display_thread: threading.Thread | None = None
        self._gpu_thread: threading.Thread | None = None

        # Coalesced "re-process the current frame" requests (slider spam => one render)
        self._refresh_evt = threading.Event()
        self._refresh_thread = threading.Thread(target=self._refresh_loop, name='viso-refresh', daemon=True)
        self._refresh_thread.start()

    # ------------------------------------------------------------------ preview output
    def publish_frame(self, frame: numpy.ndarray, frame_number: int):
        """Encode a BGR frame as JPEG for the browser and update the playback position."""
        try:
            img = frame
            if img.ndim == 3 and img.shape[2] == 2:
                img = img[..., 0]
            h, w = img.shape[:2]
            if PREVIEW_MAX_WIDTH and w > PREVIEW_MAX_WIDTH:
                s = PREVIEW_MAX_WIDTH / w
                img = cv2.resize(img, (PREVIEW_MAX_WIDTH, max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_QUALITY])
            if ok:
                self.app.hub.publish(buf.tobytes(), img.shape[1], img.shape[0])
        except Exception:  # pylint: disable=broad-exception-caught
            traceback.print_exc()
        self.app.set_seek_position(frame_number)

    # ------------------------------------------------------------------ callbacks from FrameWorker
    def frame_processed(self, frame_number, frame):
        self.frames_to_display[frame_number] = frame

    def webcam_frame_processed(self, frame):
        self.webcam_frames_to_display.put(frame)

    def single_frame_processed(self, frame_number, frame):
        self.current_frame = frame
        self.publish_frame(frame, frame_number)
        if self.app.loading_new_media:
            self.app.loading_new_media = False
        _empty_cuda_cache()
        self.app.update_gpu_memory()

    # ------------------------------------------------------------------ display / virtual camera
    def display_next_frame(self):
        if not self.processing or (self.next_frame_to_display > self.max_frame_number):
            self.stop_processing()
        if self.next_frame_to_display not in self.frames_to_display:
            return False
        frame = self.frames_to_display.pop(self.next_frame_to_display)
        self.current_frame = frame
        self.send_frame_to_virtualcam(frame)
        if self.recording and self.recording_sp and self.recording_sp.stdin:
            try:
                self.recording_sp.stdin.write(frame.tobytes())
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"Recording write error: {e}")
        if not self.recording:
            self.app.apply_marker_to_state(self.next_frame_to_display)
        self.publish_frame(frame, self.next_frame_to_display)
        self.threads.pop(self.next_frame_to_display, None)
        self.next_frame_to_display += 1
        return True

    def display_next_webcam_frame(self):
        if not self.processing:
            self.stop_processing()
        if self.webcam_frames_to_display.empty():
            return False
        frame = self.webcam_frames_to_display.get()
        self.current_frame = frame
        self.send_frame_to_virtualcam(frame)
        self.publish_frame(frame, 0)
        return True

    def send_frame_to_virtualcam(self, frame: numpy.ndarray):
        if self.app.control['SendVirtCamFramesEnableToggle'] and self.virtcam:
            height, width, _ = frame.shape
            if self.virtcam.height != height or self.virtcam.width != width:
                self.enable_virtualcam()
            try:
                self.virtcam.send(frame)
                self.virtcam.sleep_until_next_frame()
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(e)

    def set_number_of_threads(self, value):
        self.stop_processing()
        self.app.models_processor.set_number_of_threads(value)
        self.num_threads = value
        self.frame_queue = queue.Queue(maxsize=self.num_threads)
        print(f"Max Threads set as {value} ")

    # ------------------------------------------------------------------ playback loops
    def _read_loop(self, generation, interval_s, webcam):
        while self.processing and self._generation == generation and self._reading:
            t0 = time.perf_counter()
            try:
                if webcam:
                    self.process_next_webcam_frame()
                else:
                    self.process_next_frame()
            except Exception:  # pylint: disable=broad-exception-caught
                traceback.print_exc()
            delay = interval_s - (time.perf_counter() - t0)
            time.sleep(delay if delay > 0 else 0.001)

    def _display_loop(self, generation, webcam):
        while self.processing and self._generation == generation:
            try:
                shown = self.display_next_webcam_frame() if webcam else self.display_next_frame()
            except Exception:  # pylint: disable=broad-exception-caught
                traceback.print_exc()
                shown = False
            if not shown:
                time.sleep(0.001)

    def _gpu_loop(self, generation):
        while self.processing and self._generation == generation:
            self.app.update_gpu_memory()
            for _ in range(50):
                if not self.processing or self._generation != generation:
                    return
                time.sleep(0.1)

    def process_video(self):
        """Start video processing by reading frames and enqueueing them."""
        with self.op_lock:
            if self.processing:
                print("Processing already in progress. Ignoring start request.")
                return
            if self.file_type == 'video':
                if self.media_capture and self.media_capture.isOpened():
                    print("Starting video processing.")
                    self.start_time = time.perf_counter()
                    self.frames_to_display.clear()
                    self.threads.clear()
                    if self.recording:
                        self.app.set_ui_locked(True)
                        self.create_ffmpeg_subprocess()
                    self.play_start_time = float(self.media_capture.get(cv2.CAP_PROP_POS_FRAMES) / float(self.fps))
                    if self.app.control['VideoPlaybackCustomFpsToggle']:
                        fps = self.app.control['VideoPlaybackCustomFpsSlider']
                    else:
                        fps = self.media_capture.get(cv2.CAP_PROP_FPS)
                    interval = 1000 / fps if fps > 0 else 30
                    interval = int(interval * 0.8)  # Process 20% faster to offset loading/processing time
                    print(f"Starting frame reader with an interval of {interval} ms.")
                    self._start_threads(0.0 if self.recording else interval / 1000.0, webcam=False)
                else:
                    print("Error: Unable to open the video.")
                    self.processing = False
                    self.app.notify('error', 'Video', 'Unable to open the video.')
                    self.app.notify_player()
            elif self.file_type == 'webcam':
                print("Calling process_video() on Webcam stream")
                self.frames_to_display.clear()
                self.threads.clear()
                fps = self.media_capture.get(cv2.CAP_PROP_FPS)
                interval = 1000 / fps if fps > 0 else 30
                interval = int(interval * 0.8)
                self._start_threads(interval / 1000.0, webcam=True)
            self.app.notify_player()

    def _start_threads(self, interval_s, webcam):
        self._generation += 1
        gen = self._generation
        self.processing = True
        self._reading = True
        self._read_thread = threading.Thread(target=self._read_loop, args=(gen, interval_s, webcam), name='viso-read', daemon=True)
        self._display_thread = threading.Thread(target=self._display_loop, args=(gen, webcam), name='viso-display', daemon=True)
        self._gpu_thread = threading.Thread(target=self._gpu_loop, args=(gen,), name='viso-gpu', daemon=True)
        self._read_thread.start()
        self._display_thread.start()
        self._gpu_thread.start()

    def process_next_frame(self):
        """Read the next frame and add it to the queue for processing."""
        if self.current_frame_number > self.max_frame_number:
            self._reading = False  # all frames read; the display loop finishes the remaining ones
            return
        if self.frame_queue.qsize() >= self.num_threads:
            return
        if self.file_type == 'video' and self.media_capture:
            ret, frame = misc_helpers.read_frame(self.media_capture, preview_mode=not self.recording)
            if ret:
                frame = frame[..., ::-1]  # BGR -> RGB
                self.frame_queue.put(self.current_frame_number)
                self.start_frame_worker(self.current_frame_number, frame)
                self.current_frame_number += 1
            else:
                print("Cannot read frame!", self.current_frame_number)
                self.stop_processing()
                self.app.notify('error', 'Error Reading Frame', f'Error Reading Frame {self.current_frame_number}. Stopped Processing...!')

    def start_frame_worker(self, frame_number, frame, is_single_frame=False):
        worker = FrameWorker(frame, self.app, frame_number, self.frame_queue, is_single_frame)
        self.threads[frame_number] = worker
        if is_single_frame:
            worker.run()
        else:
            worker.start()

    # ------------------------------------------------------------------ single frame (preview refresh)
    def request_refresh(self):
        """Ask for the current frame to be (re)processed. Many requests collapse into one run."""
        if not self.processing and self.media_path:
            self._refresh_evt.set()

    def _refresh_loop(self):
        while True:
            self._refresh_evt.wait()
            self._refresh_evt.clear()
            try:
                if not self.processing and self.media_path:
                    self.process_current_frame()
            except Exception:  # pylint: disable=broad-exception-caught
                traceback.print_exc()

    def process_current_frame(self):
        with self.op_lock:
            self.next_frame_to_display = self.current_frame_number
            if self.file_type == 'video' and self.media_capture:
                ret, frame = misc_helpers.read_frame(self.media_capture, preview_mode=False)
                if ret:
                    frame = frame[..., ::-1]
                    self.frame_queue.put(self.current_frame_number)
                    self.start_frame_worker(self.current_frame_number, frame, is_single_frame=True)
                    self.media_capture.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_number)
                else:
                    print("Cannot read frame!", self.current_frame_number)
                    self.app.notify('error', 'Error Reading Frame', f'Error Reading Frame {self.current_frame_number}.')
            elif self.file_type == 'image':
                frame = misc_helpers.read_image_file(self.media_path)
                if frame is not None:
                    frame = frame[..., ::-1]
                    self.frame_queue.put(self.current_frame_number)
                    self.start_frame_worker(self.current_frame_number, frame, is_single_frame=True)
                else:
                    print("Error: Unable to read image file.")
            elif self.file_type == 'webcam' and self.media_capture:
                ret, frame = misc_helpers.read_frame(self.media_capture, preview_mode=False)
                if ret:
                    frame = frame[..., ::-1]
                    self.frame_queue.put(self.current_frame_number)
                    self.start_frame_worker(self.current_frame_number, frame, is_single_frame=True)
                else:
                    print("Unable to read Webcam frame!")
            self.join_and_clear_threads()

    def process_next_webcam_frame(self):
        if self.frame_queue.qsize() >= self.num_threads:
            return
        if self.file_type == 'webcam' and self.media_capture:
            ret, frame = misc_helpers.read_frame(self.media_capture, preview_mode=False)
            if ret:
                frame = frame[..., ::-1]
                self.frame_queue.put(self.current_frame_number)
                self.start_frame_worker(self.current_frame_number, frame)

    # ------------------------------------------------------------------ seeking
    def seek(self, position: int, process=True):
        """Move to a frame. Shows the raw frame immediately and optionally re-processes it."""
        with self.op_lock:
            if self.processing:
                self.stop_processing()
            position = max(0, min(int(position), max(self.max_frame_number, 0)))
            self.current_frame_number = position
            self.next_frame_to_display = position
            self.app.set_seek_position(position)
            if self.media_capture and self.file_type == 'video':
                self.media_capture.set(cv2.CAP_PROP_POS_FRAMES, position)
                ret, frame = misc_helpers.read_frame(self.media_capture)
                if ret:
                    self.publish_frame(frame, position)
                    self.media_capture.set(cv2.CAP_PROP_POS_FRAMES, position)
                    self.app.update_parameters_and_control_from_marker(position)
                    self.app.apply_marker_to_state(position)
        if process:
            self.request_refresh()

    # ------------------------------------------------------------------ stop
    def stop_processing(self):
        """Stop video processing and signal completion."""
        if not self.processing:
            self.app.notify_player()
            return False
        with self.op_lock:
            if not self.processing:
                return False
            print("Stopping video processing.")
            self.processing = False
            self._reading = False
            self._generation += 1
            me = threading.current_thread()
            for t in (self._read_thread, self._display_thread, self._gpu_thread):
                if t and t is not me and t.is_alive():
                    t.join(timeout=5)

            if self.file_type in ('video', 'webcam'):
                self.join_and_clear_threads()
                self.threads.clear()
                self.frames_to_display.clear()
                self.webcam_frames_to_display.queue.clear()
                with self.frame_queue.mutex:
                    self.frame_queue.queue.clear()

                self.current_frame_number = self.app.seek_position
                self.media_capture.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_number)

                if self.recording and self.file_type == 'video' and self.recording_sp:
                    try:
                        self.recording_sp.stdin.close()
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass
                    self.recording_sp.wait()

                self.play_end_time = float(self.media_capture.get(cv2.CAP_PROP_POS_FRAMES) / float(self.fps)) if self.fps else 0.0

                if self.file_type == 'video':
                    if self.recording:
                        self._finalize_recording()
                    self.end_time = time.perf_counter()
                    processing_time = max(self.end_time - self.start_time, 1e-6)
                    print(f"\nProcessing completed in {processing_time} seconds")
                    print(f'Average FPS: {((self.play_end_time - self.play_start_time) * self.fps) / processing_time}\n')
                    if self.recording:
                        self.app.set_ui_locked(False)

                self.recording = False
                print("Clearing Cache")
                _empty_cuda_cache()
                gc.collect()
                self.app.notify_player()
                print("Successfully Stopped Processing")
            return True

    def _finalize_recording(self):
        final_file_path = misc_helpers.get_output_file_path(self.media_path, self.app.output_folder())
        if Path(final_file_path).is_file():
            os.remove(final_file_path)
        print("Adding audio...")
        args = ["ffmpeg", '-hide_banner', '-loglevel', 'error',
                "-i", self.temp_file,
                "-ss", str(self.play_start_time), "-to", str(self.play_end_time), "-i", self.media_path,
                "-c", "copy",
                "-map", "0:v:0", "-map", "1:a:0?",
                "-shortest",
                final_file_path]
        subprocess.run(args, check=False)
        try:
            os.remove(self.temp_file)
        except OSError:
            pass
        self.app.notify('success', 'Recording saved', final_file_path)
        if Path(final_file_path).is_file():
            self.app.register_output(final_file_path)

    def join_and_clear_threads(self):
        me = threading.current_thread()
        for _, thread in list(self.threads.items()):
            if thread is not me and thread.is_alive():
                thread.join()
        self.threads.clear()

    def create_ffmpeg_subprocess(self):
        # Use the dimensions of the last processed frame: restorers/enhancers can change them
        frame_height, frame_width, _ = self.current_frame.shape
        self.temp_file = r'temp_output.mp4'
        if Path(self.temp_file).is_file():
            os.remove(self.temp_file)
        args = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{frame_width}x{frame_height}",
            "-r", str(self.fps),
            "-i", "pipe:",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuvj420p",
            "-c:v", "libx264", "-crf", "18",
            self.temp_file,
        ]
        self.recording_sp = subprocess.Popen(args, stdin=subprocess.PIPE)

    # ------------------------------------------------------------------ virtual camera
    def enable_virtualcam(self, backend=False):
        if pyvirtualcam is None:
            self.app.notify('error', 'Virtual camera', 'pyvirtualcam is not installed.')
            return
        if self.media_capture:
            if isinstance(self.current_frame, numpy.ndarray):
                frame_height, frame_width, _ = self.current_frame.shape
            else:
                frame_height = int(self.media_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                frame_width = int(self.media_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.disable_virtualcam()
            try:
                backend = backend or self.app.control['VirtCamBackendSelection']
                self.virtcam = pyvirtualcam.Camera(width=frame_width, height=frame_height, fps=int(self.fps), backend=backend, fmt=pyvirtualcam.PixelFormat.BGR)
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(e)
                self.app.notify('error', 'Virtual camera', str(e))

    def disable_virtualcam(self):
        if self.virtcam:
            self.virtcam.close()
        self.virtcam = None

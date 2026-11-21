"""Media helpers that do not need any GUI toolkit (thumbnails, webcams)."""
import cv2
import numpy as np

import app.helpers.miscellaneous as misc_helpers
from app.web.models import encode_thumbnail


def extract_thumbnail(media_file_path, file_type, webcam_index=False, webcam_backend=False):
    """Return JPEG bytes for a media thumbnail (cached on disk for images and videos) or None."""
    frame = None
    thumbnail_path = None
    if file_type in ('image', 'video'):
        misc_helpers.ensure_thumbnail_dir()
        file_hash = misc_helpers.get_hash_from_filename(media_file_path)
        thumbnail_path = misc_helpers.get_thumbnail_path(file_hash)
        if misc_helpers.is_file_exists(thumbnail_path):
            cached = misc_helpers.read_image_file(thumbnail_path)
            if cached is not None:
                return encode_thumbnail(cached)

    if file_type == 'image':
        frame = misc_helpers.read_image_file(media_file_path)
    elif file_type == 'video':
        cap = cv2.VideoCapture(media_file_path)
        if not cap.isOpened():
            return None
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        _, frame = misc_helpers.read_frame(cap)
        cap.release()
    elif file_type == 'webcam':
        camera = cv2.VideoCapture(webcam_index, webcam_backend)
        if not camera.isOpened():
            return None
        ret, frame = misc_helpers.read_frame(camera)
        camera.release()
        if not ret:
            return None

    if isinstance(frame, np.ndarray):
        if file_type != 'webcam' and thumbnail_path:
            misc_helpers.save_thumbnail(frame, thumbnail_path)
        return encode_thumbnail(frame)
    return None

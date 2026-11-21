"""Plain data objects (no GUI toolkit) used by the web UI state."""
from typing import Dict

import cv2
import numpy as np


def encode_thumbnail(image_bgr: np.ndarray, max_size: int = 140, quality: int = 88) -> bytes:
    """Return a small JPEG (bytes) of a BGR/gray/BGRA image."""
    if image_bgr is None:
        return b''
    img = image_bgr
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    h, w = img.shape[:2]
    scale = min(max_size / max(w, 1), max_size / max(h, 1), 1.0)
    if scale < 1.0:
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b''


class TargetMedia:
    def __init__(self, media_path: str, file_type: str, media_id: str, thumb: bytes = b'',
                 is_webcam=False, webcam_index=-1, webcam_backend=-1):
        self.media_id = media_id
        self.media_path = media_path
        self.file_type = file_type
        self.thumb = thumb
        self.is_webcam = is_webcam
        self.webcam_index = webcam_index
        self.webcam_backend = webcam_backend
        self.media_capture = False

    def to_dict(self):
        return {
            'id': self.media_id,
            'path': self.media_path,
            'name': self.media_path if self.is_webcam else self.media_path.replace('\\', '/').split('/')[-1],
            'type': self.file_type,
        }


class InputFace:
    def __init__(self, media_path: str, cropped_face: np.ndarray, embedding_store: Dict[str, np.ndarray], face_id: str):
        self.face_id = face_id
        self.media_path = media_path
        self.cropped_face = cropped_face
        self.embedding_store = embedding_store
        self.thumb = encode_thumbnail(cropped_face)

    def get_embedding(self, model: str) -> np.ndarray:
        return self.embedding_store.get(model, np.array([]))

    def to_dict(self):
        return {'id': self.face_id, 'path': self.media_path,
                'name': self.media_path.replace('\\', '/').split('/')[-1]}


class EmbeddingItem:
    def __init__(self, embedding_name: str, embedding_store: Dict[str, np.ndarray], embedding_id: str):
        self.embedding_id = embedding_id
        self.embedding_name = embedding_name
        self.embedding_store = embedding_store

    def get_embedding(self, model: str):
        return self.embedding_store.get(model, None)

    def to_dict(self):
        return {'id': self.embedding_id, 'name': self.embedding_name}


class TargetFace:
    def __init__(self, media_path: str, cropped_face: np.ndarray, embedding_store: Dict[str, np.ndarray], face_id: str):
        self.face_id = face_id
        self.media_path = media_path
        self.cropped_face = cropped_face
        self.embedding_store = embedding_store
        self.assigned_input_faces: Dict[str, Dict[str, np.ndarray]] = {}
        self.assigned_merged_embeddings: Dict[str, Dict[str, np.ndarray]] = {}
        self.assigned_input_embedding: Dict[str, np.ndarray] = {}
        self.thumb = encode_thumbnail(cropped_face)

    def set_embedding(self, model: str, embedding: np.ndarray):
        self.embedding_store[model] = embedding

    def get_embedding(self, model: str) -> np.ndarray:
        return self.embedding_store.get(model, np.array([]))

    def calculate_assigned_input_embedding(self, control: dict):
        stores = []
        models = set()
        for store in list(self.assigned_input_faces.values()) + list(self.assigned_merged_embeddings.values()):
            if store:
                models.update(store.keys())
                stores.append(store)
        if stores:
            method = control.get('EmbMergeMethodSelection', 'Mean')
            if method == 'Mean':
                self.assigned_input_embedding = {m: np.mean([s[m] for s in stores if m in s], axis=0) for m in models}
            elif method == 'Median':
                self.assigned_input_embedding = {m: np.median([s[m] for s in stores if m in s], axis=0) for m in models}
        else:
            self.assigned_input_embedding = {}

    def to_dict(self):
        return {
            'id': self.face_id,
            'input_faces': list(self.assigned_input_faces.keys()),
            'embeddings': list(self.assigned_merged_embeddings.keys()),
        }

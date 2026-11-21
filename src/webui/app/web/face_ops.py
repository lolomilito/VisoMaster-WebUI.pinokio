"""Face detection / recognition helpers used by the web UI (they need torch + the models processor)."""
import uuid
from typing import Dict

import cv2
import numpy
import torch
from torchvision.transforms import v2

import app.helpers.miscellaneous as misc_helpers
from app.processors.models_data import detection_model_mapping, landmark_model_mapping
from app.web.layout.settings import SETTINGS_LAYOUT_DATA

RECOGNITION_OPTIONS = SETTINGS_LAYOUT_DATA['Face Recognition']['RecognitionModelSelection']['options']


def _to_tensor(app, frame_bgr):
    frame = frame_bgr[..., ::-1]  # frames must be RGB for the models
    img = torch.from_numpy(frame.astype('uint8')).to(app.models_processor.device)
    return img.permute(2, 0, 1)


def _detect(app, img, control, max_num):
    return app.models_processor.run_detect(
        img, control['DetectorModelSelection'], max_num=max_num,
        score=control['DetectorScoreSlider'] / 100.0, input_size=(512, 512),
        use_landmark_detection=control['LandmarkDetectToggle'],
        landmark_detect_mode=control['LandmarkDetectModelSelection'],
        landmark_score=control['LandmarkDetectScoreSlider'] / 100.0,
        from_points=control['DetectFromPointsToggle'],
        rotation_angles=[0] if not control['AutoRotationToggle'] else [0, 90, 180, 270])


def _embedding_store(app, img, kps, control, main_emb):
    store: Dict[str, numpy.ndarray] = {}
    for option in RECOGNITION_OPTIONS:
        if option != control['RecognitionModelSelection']:
            emb, _ = app.models_processor.run_recognize_direct(img, kps, control['SimilarityTypeSelection'], option)
            store[option] = emb
        else:
            store[option] = main_emb
    return store


def preload_detection_models(app):
    control = app.control.copy()
    detect_model = detection_model_mapping[control['DetectorModelSelection']]
    landmark_model = landmark_model_mapping[control['LandmarkDetectModelSelection']]
    mp = app.models_processor
    if not mp.models[detect_model]:
        mp.models[detect_model] = mp.load_model(detect_model)
    if not mp.models[landmark_model] and control['LandmarkDetectToggle']:
        mp.models[landmark_model] = mp.load_model(landmark_model)
    for recognition_model in ['Inswapper128ArcFace', 'SimSwapArcFace', 'GhostArcFace', 'CSCSArcFace', 'CSCSIDArcFace']:
        if not mp.models[recognition_model]:
            mp.models[recognition_model] = mp.load_model(recognition_model)


def find_target_faces(app):
    """Detect every face of the current frame and add the ones that are not already target faces."""
    control = app.control.copy()
    vp = app.video_processor
    if vp.media_path:
        frame = None
        with vp.op_lock:
            capture = vp.media_capture
            if vp.file_type == 'image':
                frame = misc_helpers.read_image_file(vp.media_path)
            elif vp.file_type in ('video', 'webcam') and capture:
                _, frame = misc_helpers.read_frame(capture)
                capture.set(cv2.CAP_PROP_POS_FRAMES, vp.current_frame_number)

        if frame is not None:
            img = _to_tensor(app, frame)
            if control['ManualRotationEnableToggle']:
                img = v2.functional.rotate(img, angle=control['ManualRotationAngleSlider'], interpolation=v2.InterpolationMode.BILINEAR, expand=True)

            _, kpss_5, _ = _detect(app, img, control, control['MaxFacesToDetectSlider'])

            found_faces = []
            for face_kps in kpss_5:
                face_emb, cropped_img = app.models_processor.run_recognize_direct(img, face_kps, control['SimilarityTypeSelection'], control['RecognitionModelSelection'])
                found_faces.append((face_kps, face_emb, cropped_img))

            for face_kps, face_emb, cropped_img in found_faces:
                already_known = False
                for _, target_face in app.target_faces.items():
                    threshold = app.parameters[target_face.face_id]['SimilarityThresholdSlider']
                    if app.models_processor.findCosineDistance(target_face.get_embedding(control['RecognitionModelSelection']), face_emb) >= threshold:
                        already_known = True
                        break
                if not already_known:
                    face_img = cropped_img.cpu().numpy()[..., ::-1]  # RGB -> BGR
                    face_img = numpy.ascontiguousarray(face_img)
                    store = _embedding_store(app, img, face_kps, control, face_emb)
                    app.add_target_face(face_img, store, str(uuid.uuid1().int))

    if app.target_faces and not app.selected_target_face_id:
        app.select_target_face(list(app.target_faces.keys())[0])

    if vp.processing:
        vp.stop_processing()
    app.refresh_frame()
    app.update_gpu_memory()


def detect_input_face(app, image_path):
    """Return (cropped_face_bgr, embedding_store) for the first face found in an image, or None."""
    control = app.control.copy()
    frame = misc_helpers.read_image_file(image_path)
    if frame is None:
        return None
    img = _to_tensor(app, frame)
    _, kpss_5, _ = _detect(app, img, control, 1)
    try:
        face_kps = kpss_5[0]
    except IndexError:
        return None
    if not face_kps.any():
        return None
    face_emb, cropped_img = app.models_processor.run_recognize_direct(img, face_kps, control['SimilarityTypeSelection'], control['RecognitionModelSelection'])
    face_img = numpy.ascontiguousarray(cropped_img.cpu().numpy()[..., ::-1])
    store = _embedding_store(app, img, face_kps, control, face_emb)
    return face_img, store

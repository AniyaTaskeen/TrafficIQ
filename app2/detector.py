"""Vehicle counting with YOLOv8.

For each video we look at a few frames per second, count the vehicles in each
frame, and report the average (smooth, stable) and the peak count.
"""
import cv2
import threading
from pathlib import Path
from statistics import mean
from PIL import Image, ImageOps, UnidentifiedImageError

# Ultralytics patches PIL.Image.open to attempt optional HEIF installation on
# invalid files. Keep the normal decoder for our explicitly supported formats.
_open_image = Image.open

from config import (CONFIDENCE, MAX_SECONDS, MODEL_PATH, SAMPLE_FPS,
                    VEHICLE_CLASSES)

_model = None
INFERENCE_LOCK = threading.RLock()


def get_model():
    """Load YOLO once and reuse it (first call downloads yolov8n.pt if missing)."""
    global _model
    with INFERENCE_LOCK:
        if _model is None:
            from ultralytics import YOLO
            model_path = Path(MODEL_PATH)
            if not model_path.is_absolute():
                model_path = Path(__file__).parent / model_path
            _model = YOLO(str(model_path))
    return _model


def prepare_image(upload, destination):
    """Decode and normalize actual JPEG/PNG/WebP pixels; discard metadata."""
    try:
        with _open_image(upload, formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Choose a JPEG, PNG, or WebP image.")
            if image.width * image.height > 24_000_000 or min(image.size) < 32:
                raise ValueError("Image must be at least 32 × 32 and at most 24 megapixels.")
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            normalized.save(destination, "JPEG", quality=92)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("This file is not a readable traffic image.") from exc


def detect_image(image_path, annotated_path, confidence=CONFIDENCE):
    """Real YOLO inference. Counts and annotations come from the same boxes."""
    with INFERENCE_LOCK:
        result = get_model().predict(str(image_path), classes=VEHICLE_CLASSES,
                                    conf=confidence, imgsz=640, verbose=False)[0]
        names = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
        categories = dict.fromkeys(names.values(), 0)
        boxes = []
        for box in result.boxes:
            category = names[int(box.cls.item())]
            categories[category] += 1
            boxes.append(dict(category=category, confidence=round(float(box.conf.item()), 4),
                              xyxy=[round(float(v), 1) for v in box.xyxy[0].tolist()]))
        if not cv2.imwrite(str(annotated_path), result.plot()):
            raise RuntimeError("Could not save the annotated image.")
        return dict(count=sum(categories.values()), categories=categories, boxes=boxes,
                    confidence=confidence, model=Path(MODEL_PATH).name)


def count_vehicles(video_path, progress_cb=None):
    """Return {'avg': float, 'peak': int, 'samples': int} for one lane video."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    limit = int(MAX_SECONDS * fps)
    if total_frames > 0:
        limit = min(limit, total_frames)
    step = max(1, round(fps / SAMPLE_FPS))

    model = get_model()
    counts = []
    idx = 0
    while idx < limit:
        if not cap.grab():          # end of video
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                result = model.predict(frame, classes=VEHICLE_CLASSES, conf=CONFIDENCE,
                                       imgsz=640, verbose=False)[0]
                counts.append(len(result.boxes))
        idx += 1
        if progress_cb and idx % step == 0:
            progress_cb(min(1.0, idx / max(limit, 1)))
    cap.release()

    if not counts:
        raise ValueError(f"No readable frames in video: {video_path}")
    if progress_cb:
        progress_cb(1.0)
    return {"avg": round(mean(counts), 1), "peak": max(counts), "samples": len(counts)}

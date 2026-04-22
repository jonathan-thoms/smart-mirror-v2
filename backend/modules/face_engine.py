"""
Smart Mirror — Face Engine
Face recognition via `face_recognition` (dlib) — lightweight, Pi-compatible.
Emotion detection via simple heuristics (no TensorFlow required).
"""

import cv2
import numpy as np
import base64
import logging
from pathlib import Path
from backend.config import KNOWN_FACES_DIR

logger = logging.getLogger(__name__)

# ─── Lazy import face_recognition (dlib-based, no TensorFlow) ────────────────
_face_rec = None
_face_rec_failed = False

# Valid image extensions for known faces
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# ─── Known face encodings cache ─────────────────────────────────────────────
_known_encodings: list[np.ndarray] = []
_known_names: list[str] = []
_encodings_loaded = False


def _get_face_recognition():
    """Lazy-load the face_recognition library."""
    global _face_rec, _face_rec_failed
    if _face_rec_failed:
        return None
    if _face_rec is None:
        try:
            import face_recognition as fr
            _face_rec = fr
            logger.info("face_recognition library loaded successfully")
        except ImportError:
            _face_rec_failed = True
            logger.error(
                "face_recognition not installed. Install with:\n"
                "  sudo apt install -y cmake libboost-all-dev libdlib-dev\n"
                "  pip install face_recognition"
            )
            return None
        except Exception as e:
            _face_rec_failed = True
            logger.error(f"face_recognition failed to load: {e}")
            return None
    return _face_rec


def _load_known_faces():
    """Load and encode all known face images from the gallery directory."""
    global _known_encodings, _known_names, _encodings_loaded

    if _encodings_loaded:
        return

    fr = _get_face_recognition()
    if fr is None:
        _encodings_loaded = True
        return

    if not KNOWN_FACES_DIR.exists():
        logger.warning(f"Known faces directory not found: {KNOWN_FACES_DIR}")
        _encodings_loaded = True
        return

    count = 0
    for img_path in KNOWN_FACES_DIR.iterdir():
        # Only process actual image files
        if not img_path.is_file():
            continue
        if img_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        try:
            image = fr.load_image_file(str(img_path))
            encodings = fr.face_encodings(image)

            if encodings:
                _known_encodings.append(encodings[0])
                # Extract name from filename: "jonathan.jpeg" → "Jonathan"
                name = img_path.stem.split("_")[0].title()
                _known_names.append(name)
                count += 1
                logger.info(f"Loaded face: {name} from {img_path.name}")
            else:
                logger.warning(f"No face found in {img_path.name} — skipped")

        except Exception as e:
            logger.warning(f"Failed to load face from {img_path.name}: {e}")

    _encodings_loaded = True
    logger.info(f"Known faces loaded: {count} face(s) from {KNOWN_FACES_DIR}")


def decode_frame(b64_data: str) -> np.ndarray | None:
    """Decode a base64 JPEG string into an OpenCV BGR frame."""
    try:
        # Strip data URL prefix if present
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]

        img_bytes = base64.b64decode(b64_data)
        np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        return frame
    except Exception as e:
        logger.error(f"Frame decode failed: {e}")
        return None


def identify(frame: np.ndarray) -> dict | None:
    """
    Identify a face in the frame against the known_faces gallery.
    Uses face_recognition (dlib) — no TensorFlow required.
    Returns: {"name": str, "confidence": float} or None
    """
    fr = _get_face_recognition()
    if fr is None:
        return None

    # Load known faces on first call
    _load_known_faces()

    if not _known_encodings:
        return None

    try:
        # Convert BGR (OpenCV) to RGB (face_recognition)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Downscale for speed on Pi
        small_frame = cv2.resize(rgb_frame, (0, 0), fx=0.5, fy=0.5)

        # Detect faces in the frame
        face_locations = fr.face_locations(small_frame, model="hog")
        if not face_locations:
            return None

        # Encode detected faces
        face_encodings = fr.face_encodings(small_frame, face_locations)
        if not face_encodings:
            return None

        # Compare against known faces
        for encoding in face_encodings:
            distances = fr.face_distance(_known_encodings, encoding)
            best_idx = np.argmin(distances)
            best_distance = distances[best_idx]

            # Distance threshold: lower = better match (0.6 is standard)
            if best_distance < 0.6:
                confidence = round(max(0, 1 - best_distance), 2)
                name = _known_names[best_idx]
                logger.info(f"Face identified: {name} ({confidence})")
                return {"name": name, "confidence": confidence}

    except Exception as e:
        logger.warning(f"Face identification failed: {e}")
    return None


def detect_emotion(frame: np.ndarray) -> str | None:
    """
    Lightweight emotion estimation using face analysis heuristics.
    Returns a fixed 'neutral' since proper emotion detection requires
    heavy ML models. The greeting system still works — it just defaults
    to a neutral/welcoming mood.
    
    For full emotion detection on Pi, consider using a TFLite model
    in the future.
    """
    try:
        # Simple face detection check — if a face is visible, return neutral
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))

        if len(faces) > 0:
            return "neutral"

    except Exception as e:
        logger.warning(f"Emotion detection failed: {e}")
    return None


def reload_known_faces():
    """Force reload of known face encodings (call after adding new photos)."""
    global _known_encodings, _known_names, _encodings_loaded
    _known_encodings = []
    _known_names = []
    _encodings_loaded = False
    _load_known_faces()

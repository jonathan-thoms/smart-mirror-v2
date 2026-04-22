"""
Smart Mirror — Face Engine
Face recognition and emotion detection via DeepFace.
"""

import cv2
import numpy as np
import base64
import logging
from pathlib import Path
from backend.config import (
    KNOWN_FACES_DIR,
    FACE_DETECT_BACKEND,
    FACE_RECOGNITION_MODEL,
)

logger = logging.getLogger(__name__)

# ─── Lazy DeepFace Import (avoids TF segfault on Pi at startup) ─────────────
_deepface = None
_deepface_failed = False


def _get_deepface():
    """Lazy-load DeepFace on first use instead of at import time."""
    global _deepface, _deepface_failed
    if _deepface_failed:
        return None
    if _deepface is None:
        try:
            from deepface import DeepFace as _df
            _deepface = _df
            logger.info("DeepFace loaded successfully")
        except Exception as e:
            _deepface_failed = True
            logger.error(f"DeepFace failed to load (face features disabled): {e}")
            return None
    return _deepface


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
    Each file in known_faces/ should be named <person_name>.jpg
    Returns: {"name": str, "confidence": float} or None
    """
    if not KNOWN_FACES_DIR.exists() or not any(KNOWN_FACES_DIR.iterdir()):
        return None

    DF = _get_deepface()
    if DF is None:
        return None

    try:
        results = DF.find(
            img_path=frame,
            db_path=str(KNOWN_FACES_DIR),
            model_name=FACE_RECOGNITION_MODEL,
            detector_backend=FACE_DETECT_BACKEND,
            enforce_detection=False,
            silent=True,
        )

        if results and len(results) > 0 and len(results[0]) > 0:
            df = results[0]
            if not df.empty:
                best_match = df.iloc[0]
                identity_path = best_match.get("identity", "")
                distance = best_match.get("distance", 1.0)

                # Extract person name from filename
                name = Path(identity_path).stem.split("_")[0].title()
                confidence = round(max(0, 1 - distance), 2)

                if confidence > 0.40:  # Minimum confidence threshold
                    logger.info(f"Face identified: {name} ({confidence})")
                    return {"name": name, "confidence": confidence}

    except Exception as e:
        logger.warning(f"Face identification failed: {e}")
    return None


def detect_emotion(frame: np.ndarray) -> str | None:
    """
    Detect the dominant emotion in a face within the frame.
    Returns emotion string: happy, sad, angry, surprise, fear, neutral, disgust
    """
    DF = _get_deepface()
    if DF is None:
        return None

    try:
        analysis = DF.analyze(
            img_path=frame,
            actions=["emotion"],
            detector_backend=FACE_DETECT_BACKEND,
            enforce_detection=False,
            silent=True,
        )

        if analysis:
            result = analysis[0] if isinstance(analysis, list) else analysis
            dominant = result.get("dominant_emotion")
            if dominant:
                return dominant.lower()

    except Exception as e:
        logger.warning(f"Emotion detection failed: {e}")
    return None

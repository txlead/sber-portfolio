"""
Eye tracker — MediaPipe Face Landmarker (Tasks API, mediapipe ≥ 0.10.30)

Signal design:
  H — iris X relative to eye corners (raw ratio, ~0.3–0.7 range)
  V — iris Y relative to nose-bridge (head-pose cancelled).
      Normalised by eye_to_nose distance.  No extra V_AMP — nose-bridge
      normalisation already gives 6-10× stronger signal than old face-height
      approach.  Down boost ×2.0 compensates for lower-lid masking.
  Both: per-eye calculated, EAR-weighted average, smoothed.
"""

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import urllib.request, os

MODEL_URL  = ("https://storage.googleapis.com/mediapipe-models/"
              "face_landmarker/face_landmarker/float16/1/face_landmarker.task")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_landmarker.task")


def _ensure_model():
    if not os.path.exists(MODEL_PATH):
        print("[tracker] Downloading face_landmarker.task (~30 MB)…")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("[tracker] Model downloaded ✓")


# ── Landmark indices ──────────────────────────────────────────────────────────
LEFT_EAR_PTS  = [33, 160, 158, 133, 153, 144]
RIGHT_EAR_PTS = [362, 385, 387, 263, 373, 380]

LEFT_IRIS  = 468
RIGHT_IRIS = 473

L_OUTER, L_INNER = 33,  133
R_INNER, R_OUTER = 362, 263

NOSE_BRIDGE = 168   # glabella — moves with head but NOT with eyes
NOSE_TIP    = 4
CHIN        = 152


def _ear(pts, lm, w, h):
    p     = [np.array([lm[i].x * w, lm[i].y * h]) for i in pts]
    vert  = np.linalg.norm(p[1]-p[5]) + np.linalg.norm(p[2]-p[4])
    horiz = np.linalg.norm(p[0]-p[3]) * 2
    return vert / horiz if horiz > 0 else 0.0


def _raw_h(iris_idx, outer_idx, inner_idx, lm, w):
    """Iris X between eye corners. ~0.3–0.7 range."""
    ix    = lm[iris_idx].x * w
    outer = lm[outer_idx].x * w
    inner = lm[inner_idx].x * w
    span  = abs(inner - outer)
    return abs(ix - outer) / span if span > 1 else 0.5


def _raw_v(iris_idx, lm, h, eye_to_nose):
    """
    Iris Y relative to NOSE BRIDGE — head-pose cancelled.
    Normalised by eye_to_nose (≈50px); no extra V_AMP needed.
    Negative = looking up, positive = looking down.
    Down boost ×2.0: lower lid rises when looking down, masking the iris signal.
    """
    nose_y = lm[NOSE_BRIDGE].y * h
    iris_y = lm[iris_idx].y * h
    # Guard against unreliable eye_to_nose (can be tiny if landmarks coincide)
    denom = max(eye_to_nose, h * 0.04)   # at least 4% of frame height
    raw   = (iris_y - nose_y) / denom
    if raw > 0:
        raw *= 2.0   # compensate for weak down signal
    return raw


class EyeTracker:
    def __init__(self):
        _ensure_model()
        # Lower thresholds so MediaPipe keeps tracking in dim light
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
            num_faces=1,
            min_face_detection_confidence=0.4,
            min_face_presence_confidence=0.4,
            min_tracking_confidence=0.4,
        )
        self._detector = mp_vision.FaceLandmarker.create_from_options(options)
        self._smooth_h = 0.5
        self._smooth_v = 0.0
        self._alpha    = 0.13   # balanced: smooth enough, amplitude preserved
        # Low-light enhancement pipeline
        # tileGridSize=(4,4) = finer local contrast for small iris details
        self._clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
        # gamma=0.42: aggressively lifts shadows — good for screen-only light
        gamma = 0.42
        self._gamma_lut = np.array([
            min(255, int((i / 255.0) ** gamma * 255))
            for i in range(256)
        ], dtype=np.uint8)

    def _enhance(self, bgr):
        """Gamma brighten → CLAHE on L channel. Works in complete darkness."""
        # Step 1: gamma correction — lifts shadows without blowing highlights
        bright = cv2.LUT(bgr, self._gamma_lut)
        # Step 2: CLAHE on L channel for local contrast
        lab = cv2.cvtColor(bright, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = self._clahe.apply(l)
        lab = cv2.merge([l, a, b])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    def process(self, bgr_frame):
        h, w = bgr_frame.shape[:2]
        enhanced = self._enhance(bgr_frame)
        rgb  = cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)
        img  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res  = self._detector.detect(img)

        if not res.face_landmarks:
            return dict(ear=0.3, gaze_ratio=self._smooth_h,
                        gaze_ratio_v=self._smooth_v,
                        gaze_screen=None, landmarks=None)

        lm = res.face_landmarks[0]

        ear_l = _ear(LEFT_EAR_PTS,  lm, w, h)
        ear_r = _ear(RIGHT_EAR_PTS, lm, w, h)
        ear   = (ear_l + ear_r) / 2.0

        # Eye-to-nose distance: outer canthi Y vs nose-bridge Y
        eye_mid_y   = (lm[L_OUTER].y + lm[R_OUTER].y) / 2 * h
        nose_y      = lm[NOSE_BRIDGE].y * h
        eye_to_nose = abs(nose_y - eye_mid_y)   # ~40–70px typically

        # Per-eye raw signals
        rh_l = _raw_h(LEFT_IRIS,  L_OUTER, L_INNER, lm, w)
        rh_r = _raw_h(RIGHT_IRIS, R_INNER, R_OUTER, lm, w)
        rv_l = _raw_v(LEFT_IRIS,  lm, h, eye_to_nose)
        rv_r = _raw_v(RIGHT_IRIS, lm, h, eye_to_nose)

        # EAR-weighted average (trust the more-open eye)
        ws    = ear_l + ear_r if (ear_l + ear_r) > 0 else 1.0
        raw_h = (rh_l * ear_l + rh_r * ear_r) / ws
        raw_v = (rv_l * ear_l + rv_r * ear_r) / ws

        # Smooth
        self._smooth_h = self._alpha * raw_h + (1 - self._alpha) * self._smooth_h
        self._smooth_v = self._alpha * raw_v + (1 - self._alpha) * self._smooth_v

        sx = int((lm[LEFT_IRIS].x + lm[RIGHT_IRIS].x) / 2 * w)
        sy = int((lm[LEFT_IRIS].y + lm[RIGHT_IRIS].y) / 2 * h)

        return dict(
            ear          = round(ear, 3),
            gaze_ratio   = round(self._smooth_h, 4),
            gaze_ratio_v = round(self._smooth_v, 4),
            gaze_screen  = (sx, sy),
            landmarks    = lm,
        )

    def release(self):
        self._detector.close()

"""
Skin tone pipeline

1. Detect the face and a skin mask (MediaPipe Face Landmarker, falls back to OpenCV).
2. White balance from the non-skin background, or from a reference point the user clicks.
3. Measure skin tone in CIELAB and match it to the Monk Skin Tone (MST) scale.
4. Return everything the page needs to show the result and let the user adjust it.
"""

import base64
from pathlib import Path

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, lab2rgb, rgb2lab

# Monk Skin Tone scale, tones 1 (lightest) to 10 (darkest)
MST_PALETTE = [
    "#f6ede4", "#f3e7db", "#f7ead0", "#eadaba", "#d7bd96",
    "#a07e56", "#825c43", "#604134", "#3a312a", "#292420",
]

MODEL_PATH = Path(__file__).parent / "models" / "face_landmarker.task"
MAX_SIDE = 1024          # downscale large photos for speed
SAMPLE = 11              # reference patch size, same as the canvas picker
MIN_SKIN_PIXELS = 500
MIN_BACKGROUND_SHARE = 0.05
GAIN_LIMITS = (0.7, 1.4)  # stop white balance from over-correcting
LUMA = np.array([0.2126, 0.7152, 0.0722])


class SkinToneError(Exception):
    """Raised when the photo can't be analyzed; the message is shown to the user."""


# ---------- colour helpers ----------

def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def hex_to_rgb01(hex_value):
    h = hex_value.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)]) / 255


def rgb01_to_hex(rgb):
    r, g, b = (np.clip(np.round(np.asarray(rgb) * 255), 0, 255)).astype(int)
    return f"#{r:02x}{g:02x}{b:02x}"


MST_LAB = rgb2lab(np.array([[hex_to_rgb01(h) for h in MST_PALETTE]]))[0]


# ---------- step 1: face and skin mask ----------

_landmarker = None


def _get_landmarker():
    """Load the MediaPipe model once. Returns None if it isn't installed."""
    global _landmarker
    if _landmarker is None and MODEL_PATH.exists():
        from mediapipe.tasks.python import BaseOptions, vision
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            num_faces=1,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(options)
    return _landmarker


def _hull_mask(shape, points, dilate=0):
    mask = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(points.astype(np.int32)), 1)
    if dilate > 0:
        mask = cv2.dilate(mask, np.ones((dilate, dilate), np.uint8))
    return mask.astype(bool)


def _person_mask(shape, x, y, w, h):
    """Rough area covered by the person: the face plus hair, neck and shoulders below it."""
    ih, iw = shape
    mask = np.zeros(shape, bool)
    cx = x + w / 2
    left, right = int(max(0, cx - 1.6 * w)), int(min(iw, cx + 1.6 * w))
    top = int(max(0, y - 0.6 * h))
    mask[top:, left:right] = True
    return mask


def _masks_mediapipe(rgb):
    import mediapipe as mp
    from mediapipe.tasks.python import vision

    landmarker = _get_landmarker()
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not result.face_landmarks:
        return None

    h, w = rgb.shape[:2]
    pts = np.array([[lm.x * w, lm.y * h] for lm in result.face_landmarks[0]])
    conn = vision.FaceLandmarksConnections

    def region(connections):
        idx = sorted({c.start for c in connections} | {c.end for c in connections})
        return pts[idx]

    face_w = pts[:, 0].max() - pts[:, 0].min()
    pad = max(3, int(face_w * 0.04))

    skin = _hull_mask((h, w), region(conn.FACE_LANDMARKS_FACE_OVAL))
    for feature in (conn.FACE_LANDMARKS_LEFT_EYE, conn.FACE_LANDMARKS_RIGHT_EYE,
                    conn.FACE_LANDMARKS_LEFT_EYEBROW, conn.FACE_LANDMARKS_RIGHT_EYEBROW,
                    conn.FACE_LANDMARKS_LIPS):
        skin &= ~_hull_mask((h, w), region(feature), dilate=pad)

    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    person = _person_mask((h, w), x0, y0, x1 - x0, y1 - y0)
    return skin, person


def _masks_opencv(rgb):
    """Fallback without the MediaPipe model: Haar face box, sample cheeks and forehead."""
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    if len(faces) == 0:
        return None

    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    skin = np.zeros(gray.shape, bool)
    for fx0, fy0, fx1, fy1 in [
        (0.18, 0.50, 0.40, 0.75),  # left cheek
        (0.60, 0.50, 0.82, 0.75),  # right cheek
        (0.30, 0.12, 0.70, 0.28),  # forehead
    ]:
        skin[y + int(fy0 * h):y + int(fy1 * h), x + int(fx0 * w):x + int(fx1 * w)] = True
    return skin, _person_mask(gray.shape, x, y, w, h)


def detect_masks(rgb):
    if _get_landmarker() is not None:
        masks = _masks_mediapipe(rgb)
        if masks is not None:
            return (*masks, "mediapipe")
    masks = _masks_opencv(rgb)
    if masks is not None:
        return (*masks, "opencv")
    raise SkinToneError("No face found. Try a well-lit, front-facing photo.")


# ---------- step 2: white balance ----------

def _clamp_gains(gains):
    gains = gains / (gains @ LUMA)  # keep overall brightness the same
    return np.clip(gains, *GAIN_LIMITS)


def gains_from_reference(linear, x, y):
    """User clicked a white or grey card: make that patch neutral."""
    h, w = linear.shape[:2]
    half = SAMPLE // 2
    left = int(np.clip(x - half, 0, w - SAMPLE))
    top = int(np.clip(y - half, 0, h - SAMPLE))
    patch = linear[top:top + SAMPLE, left:left + SAMPLE].reshape(-1, 3).mean(axis=0)
    if patch.min() < 0.01:
        raise SkinToneError("The reference point is too dark. Click a white or grey area.")
    return _clamp_gains(patch.mean() / patch)


def gains_from_background(linear, background):
    """Shades-of-grey estimate from everything that isn't the person."""
    pixels = linear[background]
    usable = (pixels.max(axis=1) < 0.95) & (pixels @ LUMA > 0.02)  # skip clipped and near-black
    pixels = pixels[usable]
    if len(pixels) < MIN_BACKGROUND_SHARE * background.size:
        return None
    p = 6
    illuminant = np.mean(pixels ** p, axis=0) ** (1 / p)
    return _clamp_gains(illuminant.mean() / illuminant)


# ---------- step 3: measure and match ----------

def measure_skin(srgb, skin):
    """Median CIELAB of skin pixels, ignoring shadows and highlights."""
    lab = rgb2lab(srgb[skin][None, :, :])[0]
    low, high = np.percentile(lab[:, 0], [15, 85])
    lab = lab[(lab[:, 0] >= low) & (lab[:, 0] <= high)]
    if len(lab) < MIN_SKIN_PIXELS // 2:
        raise SkinToneError("Not enough visible skin. Move closer or remove anything covering the face.")
    return np.median(lab, axis=0)


def match_mst(lab, palette=None):
    """palette: list of hex strings, lightest first. Defaults to the built-in MST scale."""
    palette = palette or MST_PALETTE
    palette_lab = MST_LAB if palette is MST_PALETTE else \
        rgb2lab(np.array([[hex_to_rgb01(h) for h in palette]]))[0]
    distances = deltaE_ciede2000(np.tile(lab, (len(palette_lab), 1)), palette_lab)
    order = np.argsort(distances)
    return [{"tone": int(i) + 1, "hex": palette[i], "distance": round(float(distances[i]), 1)}
            for i in order[:3]]


def lab_to_hex(lab):
    return rgb01_to_hex(lab2rgb(lab[None, None, :])[0, 0])


# ---------- step 4: put it together ----------

def _preview(srgb):
    bgr = cv2.cvtColor((srgb * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def analyze(image_bytes, reference=None, palette=None):
    """
    image_bytes: uploaded file contents.
    reference:   optional (x, y) in 0–1 image coordinates of a white/grey card.
    palette:     optional list of hex values (lightest first), e.g. from the mst_scale table.
    """
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SkinToneError("That file isn't an image we can read. Upload a JPEG or PNG.")

    scale = min(1, MAX_SIDE / max(img.shape[:2]))
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]

    # 1. masks
    skin, person, detector = detect_masks(rgb)
    if skin.sum() < MIN_SKIN_PIXELS:
        raise SkinToneError("The face is too small in the photo. Move closer to the camera.")

    # 2. white balance
    linear = srgb_to_linear(rgb / 255)
    if reference is not None:
        gains = gains_from_reference(linear, reference[0] * w, reference[1] * h)
        wb_method = "reference"
    else:
        gains = gains_from_background(linear, ~person)
        wb_method = "background" if gains is not None else "none"
    if gains is None:
        gains = np.ones(3)
    corrected = linear_to_srgb(linear * gains)

    # 3. measure and match
    raw_lab = measure_skin(rgb / 255, skin)
    lab = measure_skin(corrected, skin)
    matches = match_mst(lab, palette)

    # a small gap between the top two matches means the result is borderline
    gap = matches[1]["distance"] - matches[0]["distance"]
    confidence = "high" if gap > 4 else "medium" if gap > 1.5 else "low"

    return {
        "tone": matches[0]["tone"],
        "matches": matches,
        "confidence": confidence,
        "measured_hex": lab_to_hex(lab),
        "raw_hex": lab_to_hex(raw_lab),
        "lab": [round(float(v), 1) for v in lab],
        "white_balance": {"method": wb_method, "gains": [round(float(g), 3) for g in gains]},
        "detector": detector,
        "preview": _preview(corrected),
    }

"""Reading numbers off video frames.

A small neural network classifies single glyphs as 0-9 or "not a digit". It
is trained on digits rendered from whatever fonts the machine has, pushed
through the same blur / noise / slant a compressed broadcast frame would
show, so it reads on-screen numerals in general rather than one font.
The trained model is cached in data/models.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import cv2
import joblib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..config import MODEL_DIR

GLYPH_W, GLYPH_H = 20, 28
REJECT = 10  # class index for "not a digit"
MODEL_VERSION = 2
_FONT_DIRS = {
    "win32": [Path("C:/Windows/Fonts")],
    "darwin": [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts")],
}
_LINUX_DIRS = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
# Ordinary text families only: symbol and icon fonts have no real digits.
_FAMILIES = (
    "arial", "bahnschrift", "calibri", "cambria", "candara", "consola", "corbel", "cour", "georgia",
    "impact", "segoeui", "tahoma", "times", "trebuc", "verdana", "lucon", "micross", "framd", "pala",
    "sitka", "dejavusans", "liberation", "notosans", "ubuntu", "freesans", "roboto", "helvetica",
    "menlo", "sfns", "geneva", "futura", "avenir", "din",
)
_REJECT_CHARS = "ACEFHJKLMNPRTUVWXY/:.-%+"
_HERSHEY = [cv2.FONT_HERSHEY_SIMPLEX, cv2.FONT_HERSHEY_DUPLEX, cv2.FONT_HERSHEY_TRIPLEX, cv2.FONT_HERSHEY_PLAIN]


def system_fonts() -> list[Path]:
    dirs = _FONT_DIRS.get(sys.platform, _LINUX_DIRS)
    found = []
    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in (".ttf", ".otf") and p.stem.lower().replace("-", "").startswith(_FAMILIES):
                found.append(p)
    return sorted(set(found))


def normalize_glyph(mask: np.ndarray) -> np.ndarray | None:
    """Tight-crop a binary glyph and scale it into a fixed canvas, keeping
    its aspect ratio (so a '1' stays narrow). Returns a flat float vector."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 6:
        return None
    crop = mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].astype(np.uint8) * 255
    h, w = crop.shape
    scale = min((GLYPH_W - 4) / w, (GLYPH_H - 4) / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    small = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((GLYPH_H, GLYPH_W), np.uint8)
    y0, x0 = (GLYPH_H - nh) // 2, (GLYPH_W - nw) // 2
    canvas[y0: y0 + nh, x0: x0 + nw] = small
    return canvas.astype(np.float32).ravel() / 255.0


def binarize(gray: np.ndarray) -> np.ndarray:
    """Bright text on a darker background -> boolean mask."""
    if gray.max() - gray.min() < 40:
        return np.zeros(gray.shape, bool)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th > 0


def _render_char(ch: str, font, size: int, rng: np.random.Generator) -> np.ndarray:
    pad = size
    if isinstance(font, int):  # OpenCV built-in font
        img = np.zeros((size * 3, size * 3), np.uint8)
        scale = size / 22.0 * (2.0 if font == cv2.FONT_HERSHEY_PLAIN else 1.0)
        cv2.putText(img, ch, (pad, size * 2), font, scale, 255, int(rng.integers(1, 4)), cv2.LINE_AA)
    else:
        pil = Image.new("L", (size * 3, size * 3), 0)
        ImageDraw.Draw(pil).text((pad, pad // 2), ch, fill=255, font=font)
        img = np.asarray(pil).copy()
    return img


def _augment(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    h, w = img.shape
    shear = rng.uniform(-0.32, 0.32)  # broadcast numerals are usually italic
    M = np.float32([[1, shear, -shear * h / 2], [0, 1, 0]])
    img = cv2.warpAffine(img, M, (w, h))
    if rng.random() < 0.5:  # stroke weight
        k = np.ones((2, 2), np.uint8)
        img = cv2.dilate(img, k) if rng.random() < 0.5 else cv2.erode(img, k)
    if rng.random() < 0.6:  # resolution loss
        f = rng.uniform(0.3, 0.9)
        small = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        img = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.7:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.4, 1.6))
    out = img.astype(np.float32) * rng.uniform(0.55, 1.0) + rng.uniform(0, 70)
    out += rng.normal(0, rng.uniform(0, 14), out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def build_dataset(fonts: list[Path] | None = None, per_char: int = 36, seed: int = 7):
    """Render training glyphs. Returns (X, y)."""
    rng = np.random.default_rng(seed)
    fonts = system_fonts() if fonts is None else fonts
    sources: list = list(_HERSHEY)
    for path in fonts:
        try:
            ImageFont.truetype(str(path), 40)
            sources.append(path)
        except OSError:
            continue
    X, y = [], []
    reject_n = max(4, per_char // 6)
    for src in sources:
        for ch in "0123456789" + _REJECT_CHARS:
            label = int(ch) if ch.isdigit() else REJECT
            for _ in range(per_char if ch.isdigit() else reject_n):
                size = int(rng.integers(26, 64))
                font = src if isinstance(src, int) else ImageFont.truetype(str(src), size)
                vec = normalize_glyph(binarize(_augment(_render_char(ch, font, size, rng), rng)))
                if vec is not None:
                    X.append(vec)
                    y.append(label)
    # pure clutter: random blobs should never read as a digit
    for _ in range(len(sources) * 20):
        blob = (rng.random((GLYPH_H, GLYPH_W)) > rng.uniform(0.3, 0.8)).astype(np.uint8) * 255
        blob = cv2.GaussianBlur(blob, (0, 0), rng.uniform(0.5, 2.0)) > 110
        vec = normalize_glyph(blob)
        if vec is not None:
            X.append(vec)
            y.append(REJECT)
    return np.asarray(X, np.float32), np.asarray(y, np.int64)


def train(fonts: list[Path] | None = None, per_char: int = 36, seed: int = 7):
    from sklearn.neural_network import MLPClassifier

    X, y = build_dataset(fonts, per_char, seed)
    clf = MLPClassifier(hidden_layer_sizes=(160,), alpha=1e-3, max_iter=60, early_stopping=True,
                        n_iter_no_change=6, random_state=seed)
    clf.fit(X, y)
    return clf


@lru_cache(maxsize=1)
def get_classifier():
    """Load the cached digit model, training it on first use (about 20-40 s)."""
    path = MODEL_DIR / f"digits_v{MODEL_VERSION}.joblib"
    if path.exists():
        try:
            return joblib.load(path)
        except Exception:
            path.unlink(missing_ok=True)
    clf = train()
    joblib.dump(clf, path)
    return clf


def read_number(gray_roi: np.ndarray, max_digits: int = 3, clf=None) -> tuple[int | None, float]:
    """Read an integer from a grayscale crop. Returns (value, confidence 0-1)."""
    clf = clf or get_classifier()
    h, w = gray_roi.shape[:2]
    if h < 4 or w < 4:
        return None, 0.0
    if h < 48:  # upscale small text so glyph shapes survive thresholding
        f = 48.0 / h
        gray_roi = cv2.resize(gray_roi, (int(round(w * f)), 48), interpolation=cv2.INTER_CUBIC)
        h, w = gray_roi.shape
    mask = binarize(gray_roi)
    if not mask.any():
        return None, 0.0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bh >= 0.45 * h and area >= 0.02 * h * h and bw <= 0.9 * h * 1.2:
            boxes.append((x, y, bw, bh, i))
    if not boxes:
        return None, 0.0
    boxes = sorted(sorted(boxes, key=lambda b: -b[3] * b[2])[:max_digits], key=lambda b: b[0])
    feats = []
    for x, y, bw, bh, i in boxes:
        vec = normalize_glyph(labels[y: y + bh, x: x + bw] == i)
        if vec is None:
            return None, 0.0
        feats.append(vec)
    proba = clf.predict_proba(np.asarray(feats))
    classes = clf.classes_[proba.argmax(axis=1)]
    conf = float(proba.max(axis=1).min())
    if (classes == REJECT).any():
        return None, 0.0
    return int("".join(str(int(c)) for c in classes)), conf

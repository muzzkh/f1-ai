"""HUD layout profiles: where each telemetry graphic sits in the video frame.

A profile is a JSON file. All coordinates are fractions of the frame (x of
width, y of height; arc radii are fractions of height) so one profile works
at any resolution. Element kinds:

  digits     a number drawn as text         roi, max_digits
  bar        a straight bar that fills      roi, direction (right/left/up/down), hsv_lo, hsv_hi, scale
  arc        a curved gauge that fills      center, r_inner, r_outer, start_deg, end_deg, hsv_lo, hsv_hi, scale
  indicator  a light that is on or off      roi, hsv_lo, hsv_hi, threshold

Angles are degrees clockwise from the 3 o'clock direction, as drawn on
screen; the gauge fills from start_deg towards end_deg. HSV limits use
OpenCV ranges (H 0-180, S and V 0-255); a hue range may wrap through red
(hsv_lo hue greater than hsv_hi hue).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from ..config import USER_PROFILE_DIR

BUILTIN_DIR = Path(__file__).parent / "profiles"
CHANNELS = ["speed", "gear", "throttle", "brake", "rpm", "drs"]
_REQUIRED = {
    "digits": ["roi"],
    "bar": ["roi", "hsv_lo", "hsv_hi"],
    "arc": ["center", "r_inner", "r_outer", "start_deg", "end_deg", "hsv_lo", "hsv_hi"],
    "indicator": ["roi", "hsv_lo", "hsv_hi"],
}


class LayoutError(ValueError):
    pass


def validate(layout: dict) -> dict:
    """Check a layout and fill in defaults. Returns a normalised copy."""
    if not isinstance(layout, dict) or not isinstance(layout.get("elements"), dict):
        raise LayoutError("A layout needs an 'elements' object.")
    out = copy.deepcopy(layout)
    out.setdefault("name", "custom")
    if "speed" not in out["elements"]:
        raise LayoutError("A layout must at least define the 'speed' element.")
    for name, el in out["elements"].items():
        if name not in CHANNELS:
            raise LayoutError(f"Unknown element '{name}'. Allowed: {', '.join(CHANNELS)}.")
        kind = el.get("kind")
        if kind not in _REQUIRED:
            raise LayoutError(f"Element '{name}' has unknown kind '{kind}'.")
        missing = [k for k in _REQUIRED[kind] if k not in el]
        if missing:
            raise LayoutError(f"Element '{name}' ({kind}) is missing: {', '.join(missing)}.")
        if "roi" in el:
            x0, y0, x1, y1 = el["roi"]
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise LayoutError(f"Element '{name}': roi must be [x0, y0, x1, y1] within 0-1 with x0<x1, y0<y1.")
        if kind == "digits":
            el.setdefault("max_digits", 3 if name == "speed" else 1 if name == "gear" else 5)
        if kind == "bar":
            el.setdefault("direction", "right")
            if el["direction"] not in ("right", "left", "up", "down"):
                raise LayoutError(f"Element '{name}': direction must be right, left, up or down.")
        if kind in ("bar", "arc"):
            el.setdefault("scale", [0, 15000] if name == "rpm" else [0, 100])
        if kind == "indicator":
            el.setdefault("threshold", 0.3)
    return out


def list_profiles() -> list[str]:
    from . import cluster

    names = {p.stem for p in BUILTIN_DIR.glob("*.json")} | {p.stem for p in USER_PROFILE_DIR.glob("*.json")}
    return sorted(names | {cluster.NAME})


def load_profile(name_or_path: str | Path | dict) -> dict:
    """Load a profile by name (user profiles override built-ins), path, or dict."""
    if isinstance(name_or_path, dict):
        return validate(name_or_path)
    p = Path(str(name_or_path))
    candidates = [p] if p.suffix == ".json" else [
        USER_PROFILE_DIR / f"{name_or_path}.json", BUILTIN_DIR / f"{name_or_path}.json"]
    for c in candidates:
        if c.exists():
            return validate(json.loads(c.read_text(encoding="utf-8")))
    from . import cluster

    if str(name_or_path) == cluster.NAME:  # generated from the shared cluster definition
        return validate(cluster.profile())
    raise LayoutError(f"HUD profile '{name_or_path}' not found. Available: {', '.join(list_profiles())}")


def save_profile(layout: dict) -> Path:
    layout = validate(layout)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in layout["name"]).strip("-") or "custom"
    path = USER_PROFILE_DIR / f"{safe}.json"
    path.write_text(json.dumps(layout, indent=2), encoding="utf-8")
    return path


def roi_px(roi: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi
    return (int(round(x0 * width)), int(round(y0 * height)),
            max(int(round(x1 * width)), int(round(x0 * width)) + 2),
            max(int(round(y1 * height)), int(round(y0 * height)) + 2))

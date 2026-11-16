"""Paths and shared settings."""

from __future__ import annotations

import os
from pathlib import Path


def _find_root() -> Path:
    env = os.environ.get("F1AI_HOME")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


ROOT = _find_root()
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"          # cached API responses
VIDEO_DIR = DATA_DIR / "videos"         # rendered / uploaded videos
TELEMETRY_DIR = DATA_DIR / "telemetry"  # extracted telemetry CSVs
MODEL_DIR = DATA_DIR / "models"         # trained digit classifier
USER_PROFILE_DIR = DATA_DIR / "profiles"  # user-calibrated HUD layouts

for _d in (CACHE_DIR, VIDEO_DIR, TELEMETRY_DIR, MODEL_DIR, USER_PROFILE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Seconds of lap time lost per lap of fuel carried is fitted from data, this is
# only the fallback used when a race has too few clean laps to fit it.
DEFAULT_FUEL_EFFECT_S_PER_LAP = 0.055

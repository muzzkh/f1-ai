"""Video -> telemetry: read the HUD graphics of an onboard video frame by frame.

Speed and gear are read with the digit classifier, throttle / brake / RPM by
measuring how far their coloured gauges are filled, DRS by whether its light
is on. A temporal clean-up pass then removes misreads using the fact that a
car's speed cannot jump between frames.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import pandas as pd

from . import digits
from .layout import load_profile, roi_px


def _mask(hsv: np.ndarray, lo, hi) -> np.ndarray:
    lo, hi = [int(x) for x in lo], [int(x) for x in hi]
    if lo[0] <= hi[0]:
        return cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    # hue range wraps around red
    a = cv2.inRange(hsv, np.array([lo[0], lo[1], lo[2]], np.uint8), np.array([180, hi[1], hi[2]], np.uint8))
    b = cv2.inRange(hsv, np.array([0, lo[1], lo[2]], np.uint8), np.array([hi[0], hi[1], hi[2]], np.uint8))
    return a | b


def _leading_fill(coverage: np.ndarray, on: float = 0.5, gap: int = 2) -> float:
    """Fraction of a gauge that is lit, counting from its start and stopping
    at the first real break (small gaps such as tick marks are bridged)."""
    last, miss = 0, 0
    for i, c in enumerate(coverage):
        if c > on:
            last, miss = i + 1, 0
        else:
            miss += 1
            if miss > gap:
                break
    return last / max(len(coverage), 1)


class HudReader:
    """Reads one HUD profile from frames of a fixed size."""

    def __init__(self, layout: str | dict, width: int, height: int):
        self.layout = load_profile(layout)
        self.w, self.h = width, height
        self.el = self.layout["elements"]
        self.clf = digits.get_classifier()
        self._arcs = {}
        for name, el in self.el.items():
            if el["kind"] != "arc":
                continue
            cx, cy = el["center"][0] * width, el["center"][1] * height
            r_in, r_out = el["r_inner"] * height, el["r_outer"] * height
            span = abs(el["end_deg"] - el["start_deg"])
            n = max(40, int(np.radians(span) * (r_in + r_out) / 2))
            ang = np.radians(np.linspace(el["start_deg"], el["end_deg"], n))
            rad = np.linspace(r_in + 0.2 * (r_out - r_in), r_out - 0.2 * (r_out - r_in), 5)
            xs = np.clip(np.round(cx + np.outer(np.cos(ang), rad)).astype(int), 0, width - 1)
            ys = np.clip(np.round(cy + np.outer(np.sin(ang), rad)).astype(int), 0, height - 1)
            x0, y0 = xs.min(), ys.min()
            self._arcs[name] = (x0, y0, xs.max() + 1, ys.max() + 1, xs - x0, ys - y0)

    def _fill(self, frame: np.ndarray, name: str) -> float:
        el = self.el[name]
        if el["kind"] == "arc":
            x0, y0, x1, y1, xs, ys = self._arcs[name]
            m = _mask(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), el["hsv_lo"], el["hsv_hi"])
            cov = (m[ys, xs] > 0).mean(axis=1)
        else:
            x0, y0, x1, y1 = roi_px(el["roi"], self.w, self.h)
            m = _mask(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), el["hsv_lo"], el["hsv_hi"]) > 0
            d = el["direction"]
            cov = m.mean(axis=0) if d in ("right", "left") else m.mean(axis=1)
            if d in ("left", "up"):
                cov = cov[::-1]
        frac = _leading_fill(cov)
        lo, hi = el["scale"]
        return lo + frac * (hi - lo)

    def _number(self, frame: np.ndarray, name: str) -> tuple[float, float]:
        el = self.el[name]
        x0, y0, x1, y1 = roi_px(el["roi"], self.w, self.h)
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        val, conf = digits.read_number(gray, el["max_digits"], self.clf)
        return (np.nan if val is None else float(val)), conf

    def read(self, frame: np.ndarray) -> dict:
        """Raw readings for one BGR frame."""
        out = {}
        out["Speed"], out["SpeedConf"] = self._number(frame, "speed")
        if "gear" in self.el:
            out["nGear"], out["GearConf"] = self._number(frame, "gear")
        for name, col in (("throttle", "Throttle"), ("brake", "Brake"), ("rpm", "RPM")):
            if name not in self.el:
                continue
            if self.el[name]["kind"] == "digits":
                out[col], _ = self._number(frame, name)
            else:
                out[col] = self._fill(frame, name)
        if "drs" in self.el:
            el = self.el["drs"]
            x0, y0, x1, y1 = roi_px(el["roi"], self.w, self.h)
            m = _mask(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV), el["hsv_lo"], el["hsv_hi"])
            out["DRS"] = float((m > 0).mean() > el["threshold"])
        return out


def draw_overlay(frame: np.ndarray, layout: str | dict) -> np.ndarray:
    """Outline every element of a profile on a frame (for calibration)."""
    layout = load_profile(layout)
    out = frame.copy()
    h, w = out.shape[:2]
    colors = {"speed": (0, 255, 255), "gear": (255, 255, 0), "throttle": (0, 255, 0),
              "brake": (0, 0, 255), "rpm": (255, 128, 0), "drs": (255, 0, 255)}
    for name, el in layout["elements"].items():
        col = colors[name]
        if el["kind"] == "arc":
            c = (int(el["center"][0] * w), int(el["center"][1] * h))
            a0, a1 = sorted((el["start_deg"], el["end_deg"]))
            for r in (el["r_inner"], el["r_outer"]):
                cv2.ellipse(out, c, (int(r * h), int(r * h)), 0, a0, a1, col, 1, cv2.LINE_AA)
            ang = np.radians(el["start_deg"])
            anchor = (int(c[0] + el["r_outer"] * h * np.cos(ang)) + 4, int(c[1] + el["r_outer"] * h * np.sin(ang)) + 12)
        else:
            x0, y0, x1, y1 = roi_px(el["roi"], w, h)
            cv2.rectangle(out, (x0, y0), (x1, y1), col, 1)
            anchor = (x0, max(10, y0 - 4))
        cv2.putText(out, name, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.4 * h / 720 + 0.1, col, 1, cv2.LINE_AA)
    return out


def video_info(path: str | Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    info = {"fps": float(fps), "frames": n, "duration_s": round(n / fps, 2) if fps else 0.0,
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    cap.release()
    return info


def grab_frame(path: str | Path, t_s: float = 0.0) -> np.ndarray:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Could not open video: {path}")
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t_s) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise ValueError(f"No frame at {t_s:.2f} s in {path}")
    return frame


def _rolling_mode(s: pd.Series, window: int) -> pd.Series:
    def mode(a):
        a = a[~np.isnan(a)]
        if len(a) == 0:
            return np.nan
        vals, counts = np.unique(a, return_counts=True)
        return vals[counts.argmax()]
    return s.rolling(window, center=True, min_periods=1).apply(mode, raw=True)


def clean(raw: pd.DataFrame, min_conf: float = 0.6) -> pd.DataFrame:
    """Turn raw per-frame readings into a usable telemetry trace."""
    df = pd.DataFrame({"Time": raw["Time"].values, "Frame": raw["Frame"].values})
    dt = float(np.median(np.diff(raw["Time"]))) if len(raw) > 1 else 0.04
    k = max(3, int(round(0.28 / dt)) | 1)  # ~0.3 s window, odd

    speed = raw["Speed"].where(raw["SpeedConf"] >= min_conf)
    med = speed.rolling(k, center=True, min_periods=2).median()
    # a dropped or misread digit shows up as a jump no car can make
    speed = speed.where((speed - med).abs() <= np.maximum(12.0, 0.08 * med))
    read_rate = float(speed.notna().mean())
    df["Speed"] = speed.interpolate(limit_direction="both").rolling(3, center=True, min_periods=1).median()

    if "nGear" in raw:
        gear = raw["nGear"].where((raw["GearConf"] >= min_conf) & raw["nGear"].between(1, 9))
        df["nGear"] = _rolling_mode(gear, k).ffill().bfill()
    for col in ("Throttle", "Brake", "RPM"):
        if col in raw:
            df[col] = raw[col].rolling(3, center=True, min_periods=1).median().interpolate(limit_direction="both")
    if "DRS" in raw:
        df["DRS"] = _rolling_mode(raw["DRS"], k).ffill().bfill()

    v = df["Speed"].fillna(0).values / 3.6
    t = df["Time"].values
    df["Distance"] = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(t))]) if len(df) > 1 else 0.0
    df["LongG"] = np.gradient(v, t) / 9.81 if len(df) > 2 else 0.0
    df["LongG"] = df["LongG"].rolling(k, center=True, min_periods=1).mean()
    df.attrs["speed_read_rate"] = read_rate
    return df


def extract_telemetry(
    video_path: str | Path,
    profile: str | dict = "demo-halo",
    start_s: float = 0.0,
    end_s: float | None = None,
    every: int = 1,
    progress: Callable[[float], None] | None = None,
) -> pd.DataFrame:
    """Read telemetry from a video.

    Returns one row per sampled frame: Time (s from `start_s`), Frame, Speed,
    nGear, Throttle, Brake, RPM, DRS, Distance, LongG. `df.attrs` carries the
    video info and `speed_read_rate`, the share of frames where the speed
    could be read with confidence - a low value means the profile does not
    match the footage.
    """
    info = video_info(video_path)
    cap = cv2.VideoCapture(str(video_path))
    fps = info["fps"]
    first = int(round(start_s * fps))
    last = info["frames"] if end_s is None else min(info["frames"], int(round(end_s * fps)))
    if first:
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    reader = HudReader(profile, info["width"], info["height"])
    rows, i = [], first
    every = max(1, int(every))
    while i < last:
        ok, frame = cap.read()
        if not ok:
            break
        if (i - first) % every == 0:
            r = reader.read(frame)
            r["Frame"], r["Time"] = i, (i - first) / fps
            rows.append(r)
            if progress and len(rows) % 20 == 0:
                progress((i - first) / max(last - first, 1))
        i += 1
    cap.release()
    if progress:
        progress(1.0)
    if not rows:
        raise ValueError("No frames could be read from the video in the requested range.")
    raw = pd.DataFrame(rows)
    out = clean(raw)
    out.attrs.update(video=str(video_path), profile=reader.layout["name"], fps=fps,
                     frames_read=len(raw), width=info["width"], height=info["height"])
    out.attrs["raw"] = raw
    return out

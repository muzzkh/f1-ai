"""Telemetry -> onboard-style video with a HUD overlay.

This is the inverse of the extractor. It gives the video-to-telemetry
pipeline footage with a known ground truth, so its accuracy can be measured,
and it draws whatever HUD profile it is given, so a custom layout can be
tested before pointing it at real footage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .layout import load_profile, roi_px

_RENDER_FONTS = [
    "C:/Windows/Fonts/arialbi.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
]
TRACK_GREY = (58, 58, 58)


def render_font_path() -> Path | None:
    for f in _RENDER_FONTS:
        if Path(f).exists():
            return Path(f)
    return None


def _fill_color(el: dict) -> tuple[int, int, int]:
    """A BGR colour in the middle of the element's HSV detection range."""
    lo, hi = el["hsv_lo"], el["hsv_hi"]
    h = (lo[0] + hi[0]) / 2 if lo[0] <= hi[0] else ((lo[0] + hi[0] + 180) / 2) % 180
    px = np.uint8([[[int(h), 225, 235]]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


def _glyphs(cell_w: int, cell_h: int) -> dict[str, np.ndarray]:
    """Alpha masks for 0-9 and N sized to fit one digit cell."""
    out = {}
    path = render_font_path()
    for ch in "0123456789N":
        if path is not None:
            size = int(cell_h * 1.05)
            while size > 6:
                font = ImageFont.truetype(str(path), size)
                l, t, r, b = font.getbbox(ch)
                if (r - l) <= cell_w * 0.92 and (b - t) <= cell_h * 0.86:
                    break
                size -= 1
            img = Image.new("L", (cell_w, cell_h), 0)
            ImageDraw.Draw(img).text(((cell_w - (r - l)) // 2 - l, (cell_h - (b - t)) // 2 - t), ch, fill=255, font=font)
            out[ch] = np.asarray(img).astype(np.float32) / 255.0
        else:
            img = np.zeros((cell_h, cell_w), np.uint8)
            scale = cell_h / 32.0
            (tw, th), _ = cv2.getTextSize(ch, cv2.FONT_HERSHEY_DUPLEX, scale, 2)
            scale *= min(1.0, cell_w * 0.9 / max(tw, 1))
            (tw, th), _ = cv2.getTextSize(ch, cv2.FONT_HERSHEY_DUPLEX, scale, 2)
            cv2.putText(img, ch, ((cell_w - tw) // 2, (cell_h + th) // 2), cv2.FONT_HERSHEY_DUPLEX, scale, 255, 2, cv2.LINE_AA)
            out[ch] = img.astype(np.float32) / 255.0
    return out


class HudPainter:
    """Draws a HUD profile onto frames of a fixed size."""

    def __init__(self, layout: dict, width: int, height: int):
        self.layout, self.w, self.h = layout, width, height
        self.el = layout["elements"]
        self.glyphs = {}
        for name, el in self.el.items():
            if el["kind"] == "digits":
                x0, y0, x1, y1 = roi_px(el["roi"], width, height)
                self.glyphs[name] = _glyphs((x1 - x0) // el["max_digits"], y1 - y0)

    def _panel(self, frame: np.ndarray) -> None:
        panel = self.layout.get("panel")
        if not panel:
            return
        overlay = frame.copy()
        if panel["shape"] == "circle":
            c = (int(panel["center"][0] * self.w), int(panel["center"][1] * self.h))
            cv2.circle(overlay, c, int(panel["radius"] * self.h), (18, 18, 18), -1, cv2.LINE_AA)
        else:
            x0, y0, x1, y1 = roi_px(panel["roi"], self.w, self.h)
            cv2.rectangle(overlay, (x0, y0), (x1, y1), (18, 18, 18), -1)
        cv2.addWeighted(overlay, 0.86, frame, 0.14, 0, dst=frame)

    def _digits(self, frame, name, text: str) -> None:
        el = self.el[name]
        x0, y0, x1, y1 = roi_px(el["roi"], self.w, self.h)
        n = el["max_digits"]
        cw = (x1 - x0) // n
        text = text[-n:]
        start = x0 + (n - len(text)) * cw  # right-aligned
        for i, ch in enumerate(text):
            a = self.glyphs[name][ch][..., None]
            cell = frame[y0: y0 + a.shape[0], start + i * cw: start + i * cw + a.shape[1]]
            cell[:] = (cell * (1 - a) + 245.0 * a).astype(np.uint8)

    def _bar(self, frame, el, frac: float) -> None:
        x0, y0, x1, y1 = roi_px(el["roi"], self.w, self.h)
        cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), TRACK_GREY, -1)
        frac = float(np.clip(frac, 0, 1))
        col, d = _fill_color(el), el["direction"]
        if frac <= 0:
            return
        if d == "right":
            cv2.rectangle(frame, (x0, y0), (x0 + int(round((x1 - x0) * frac)) - 1, y1 - 1), col, -1)
        elif d == "left":
            cv2.rectangle(frame, (x1 - int(round((x1 - x0) * frac)), y0), (x1 - 1, y1 - 1), col, -1)
        elif d == "up":
            cv2.rectangle(frame, (x0, y1 - int(round((y1 - y0) * frac))), (x1 - 1, y1 - 1), col, -1)
        else:
            cv2.rectangle(frame, (x0, y0), (x1 - 1, y0 + int(round((y1 - y0) * frac)) - 1), col, -1)

    def _arc(self, frame, el, frac: float) -> None:
        c = (int(round(el["center"][0] * self.w)), int(round(el["center"][1] * self.h)))
        r_in, r_out = el["r_inner"] * self.h, el["r_outer"] * self.h
        r, thick = int(round((r_in + r_out) / 2)), max(2, int(round(r_out - r_in)))
        a0, a1 = el["start_deg"], el["end_deg"]
        cv2.ellipse(frame, c, (r, r), 0, min(a0, a1), max(a0, a1), TRACK_GREY, thick, cv2.LINE_AA)
        frac = float(np.clip(frac, 0, 1))
        if frac > 0.004:
            a = a0 + (a1 - a0) * frac
            cv2.ellipse(frame, c, (r, r), 0, min(a0, a), max(a0, a), _fill_color(el), thick, cv2.LINE_AA)

    def _label(self, frame, text: str, cx: int, y: int, scale: float = 0.36, color=(170, 170, 170)) -> None:
        scale *= self.h / 720.0
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        cv2.putText(frame, text, (cx - tw // 2, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)

    def draw(self, frame: np.ndarray, v: dict) -> np.ndarray:
        """v: speed, gear, throttle, brake, rpm, drs (drs may be NaN = car has none)."""
        self._panel(frame)
        el = self.el
        for name in ("throttle", "brake", "rpm"):
            if name not in el:
                continue
            lo, hi = el[name]["scale"]
            frac = (v[name] - lo) / (hi - lo)
            (self._arc if el[name]["kind"] == "arc" else self._bar)(frame, el[name], frac)
        if "drs" in el and np.isfinite(v.get("drs", np.nan)):
            x0, y0, x1, y1 = roi_px(el["drs"]["roi"], self.w, self.h)
            on = v["drs"] > 0.5
            cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), _fill_color(el["drs"]) if on else TRACK_GREY, -1)
            self._label(frame, "DRS", (x0 + x1) // 2, y1 - max(3, (y1 - y0) // 4), 0.4, (20, 20, 20) if on else (120, 120, 120))
        self._digits(frame, "speed", str(int(round(max(v["speed"], 0)))))
        sx0, _, sx1, sy1 = roi_px(el["speed"]["roi"], self.w, self.h)
        self._label(frame, "KM/H", (sx0 + sx1) // 2, sy1 + int(15 * self.h / 720))
        if "gear" in el:
            g = int(round(v["gear"]))
            self._digits(frame, "gear", "N" if g <= 0 else str(g))
        return frame


class _Scene:
    """A cheap moving 'view from the car' so the HUD sits over changing video."""

    def __init__(self, width: int, height: int, noise: float, seed: int = 3):
        rng = np.random.default_rng(seed)
        self.w, self.h = width, height
        y = np.linspace(0, 1, height)[:, None]
        horizon = 0.42
        sky = np.array([205, 170, 120]) * (1 - y / horizon * 0.35)
        road = np.array([72, 70, 68]) * (0.7 + 0.5 * (y - horizon))
        base = np.where(y[..., None] < horizon, sky[:, None, :], road[:, None, :]) * np.ones((1, width, 1))
        grain = cv2.resize(rng.normal(0, 9, (height // 4, width // 4)).astype(np.float32), (width, height))
        base[int(horizon * height):] += grain[int(horizon * height):, :, None]
        self.base = np.clip(base, 0, 255).astype(np.uint8)
        self.horizon = int(horizon * height)
        self.noise = [rng.normal(0, noise, (height, width, 3)).astype(np.int16) for _ in range(6)] if noise > 0 else []
        self.rng = rng

    def frame(self, i: int, distance: float, speed: float) -> np.ndarray:
        f = self.base.copy()
        w, h, hz = self.w, self.h, self.horizon
        cx = w // 2 + int(40 * np.sin(distance / 180.0))  # the road wanders a little
        # dashed centre line and kerbs, streaming towards the camera
        for k in range(14):
            z0 = ((k * 12.0 - distance) % 168.0) + 2.0
            z1 = z0 + 5.0
            ya, yb = hz + (h - hz) * 6.0 / z1, hz + (h - hz) * 6.0 / z0
            if yb <= hz + 2:
                continue
            ya, yb = int(min(ya, h)), int(min(yb, h))
            for side, col in ((-1, (60, 60, 215)), (1, (235, 235, 235))):
                xa, xb = cx + side * w * 2.4 / z1, cx + side * w * 2.4 / z0
                pts = np.array([[xa, ya], [xa + side * w * 0.25 / z1, ya], [xb + side * w * 0.25 / z0, yb], [xb, yb]], np.int32)
                cv2.fillPoly(f, [pts], col)
            wa, wb = w * 0.06 / z1, w * 0.06 / z0
            cv2.fillPoly(f, [np.array([[cx - wa, ya], [cx + wa, ya], [cx + wb, yb], [cx - wb, yb]], np.int32)], (225, 225, 225))
        # car nose
        nose = np.array([[w * 0.36, h], [w * 0.455, h * 0.80], [w * 0.545, h * 0.80], [w * 0.64, h]], np.int32)
        cv2.fillPoly(f, [nose], (30, 30, 34))
        shake = int(round(speed / 110.0))
        if shake:
            dx, dy = (int(v) for v in self.rng.integers(-shake, shake + 1, 2))
            f = cv2.warpAffine(f, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), borderMode=cv2.BORDER_REPLICATE)
        if self.noise:
            f = np.clip(f.astype(np.int16) + self.noise[i % len(self.noise)], 0, 255).astype(np.uint8)
        return f


def _open_writer(path: Path, fps: float, size: tuple[int, int]):
    """Open a writer with the first codec this OpenCV build supports."""
    if path.suffix.lower() != ".mp4":
        raise ValueError("Output video must be an .mp4 file.")
    # H.264 (plays in browsers) when this OpenCV build has it, else MPEG-4.
    for fourcc in ("avc1", "mp4v"):
        wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, size)
        if wr.isOpened():
            return wr, fourcc
        wr.release()
    raise RuntimeError("No usable MP4 video encoder found in this OpenCV build.")


def frame_values(tel: pd.DataFrame, fps: float, max_seconds: float | None = None) -> pd.DataFrame:
    """Telemetry resampled to one row per video frame (the ground truth)."""
    t_end = float(tel["Time"].max())
    if max_seconds:
        t_end = min(t_end, float(tel["Time"].min()) + max_seconds)
    t = np.arange(float(tel["Time"].min()), t_end, 1.0 / fps)
    src = tel["Time"].values
    idx = np.clip(np.searchsorted(src, t, side="right") - 1, 0, len(src) - 1)
    return pd.DataFrame(
        {
            "Time": t - t[0],
            "Speed": np.interp(t, src, tel["Speed"].values),
            "Throttle": np.interp(t, src, tel["Throttle"].values),
            "Brake": tel["Brake"].values[idx],
            "nGear": tel["nGear"].values[idx],
            "RPM": np.interp(t, src, tel["RPM"].values),
            "DRS": tel["DRS"].values[idx],
        }
    )


def render_onboard(
    tel: pd.DataFrame,
    out_path: str | Path,
    profile: str | dict = "demo-halo",
    fps: float = 25.0,
    size: tuple[int, int] = (1280, 720),
    max_seconds: float | None = None,
    noise: float = 5.0,
    caption: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> dict:
    """Render telemetry as an onboard-style video. Returns info about the file."""
    layout = load_profile(profile)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    vals = frame_values(tel, fps, max_seconds)
    dist = np.concatenate([[0.0], np.cumsum(vals["Speed"].values[:-1] / 3.6 / fps)])
    painter, scene = HudPainter(layout, w, h), _Scene(w, h, noise)
    writer, codec = _open_writer(out_path, fps, (w, h))
    try:
        for i, row in enumerate(vals.itertuples(index=False)):
            frame = scene.frame(i, float(dist[i]), float(row.Speed))
            if caption:
                cv2.putText(frame, caption, (int(24 * w / 1280), int(40 * h / 720)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7 * h / 720, (255, 255, 255), 2, cv2.LINE_AA)
            painter.draw(frame, {"speed": row.Speed, "gear": row.nGear, "throttle": row.Throttle,
                                 "brake": row.Brake, "rpm": row.RPM, "drs": row.DRS})
            writer.write(frame)
            if progress and i % 25 == 0:
                progress(i / len(vals))
    finally:
        writer.release()
    if progress:
        progress(1.0)
    return {"path": str(out_path), "frames": len(vals), "fps": fps, "duration_s": round(len(vals) / fps, 2),
            "size": [w, h], "codec": codec, "profile": layout["name"]}

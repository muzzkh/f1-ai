"""The instrument cluster, for video.

`cluster.json` defines the cluster once: where the speed and gear numerals
sit, the pedal and rev gauges, the shift lights. The website draws it live
from that file (docs/js/cluster.js); this module draws the same geometry into
video frames and derives the HUD profile the reader needs to read it back.

The numerals use whatever bold italic face the machine has, so their shapes
differ from the website's; positions and gauges are identical.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

SPEC = json.loads((Path(__file__).parent / "cluster.json").read_text(encoding="utf-8"))
NAME = "cluster"
# where the cluster sits in a 16:9 frame: centre (fractions of width, height)
# and diameter as a fraction of frame height
PLACEMENT = {"cx": 0.5, "cy": 0.79, "diameter": 0.37}
_HSV = {  # colour ranges (OpenCV HSV) that isolate each gauge's fill
    "throttle": ([60, 90, 90], [90, 255, 255]),
    "brake": ([165, 90, 90], [8, 255, 255]),
    "rpm": ([120, 70, 90], [142, 255, 255]),
}


def _bgr(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def profile(aspect: float = 16 / 9) -> dict:
    """HUD profile (see layout.py) describing where to read the cluster."""
    p, size = PLACEMENT, SPEC["size"]
    k = p["diameter"] / size                      # cluster units -> fraction of frame height
    x0 = p["cx"] - (size / 2) * k / aspect        # left edge, fraction of width
    y0 = p["cy"] - (size / 2) * k

    def fx(x):
        return round(x0 + x * k / aspect, 5)

    def fy(y):
        return round(y0 + y * k, 5)

    def box(b):
        return [fx(b[0]), fy(b[1]), fx(b[2]), fy(b[3])]

    def arc(name):
        a = SPEC[name]
        lo, hi = _HSV[name]
        return {"kind": "arc", "center": [fx(SPEC["center"][0]), fy(SPEC["center"][1])],
                "r_inner": round((a["r"] - a["w"] / 2) * k, 5), "r_outer": round((a["r"] + a["w"] / 2) * k, 5),
                "start_deg": a["from"], "end_deg": a["to"], "hsv_lo": lo, "hsv_hi": hi,
                "scale": a.get("scale", [0, 100])}

    return {
        "name": NAME,
        "description": "The project's instrument cluster: speed and gear numerals inside pedal and rev gauges. "
                       "Matches videos made by the f1ai renderer; real footage needs its own calibrated profile.",
        "painter": "cluster",
        "elements": {
            "speed": {"kind": "digits", "roi": box(SPEC["speed"]["box"]), "max_digits": 3},
            "gear": {"kind": "digits", "roi": box(SPEC["gear"]["box"]), "max_digits": 1},
            "throttle": arc("throttle"), "brake": arc("brake"), "rpm": arc("rpm"),
        },
    }


class ClusterPainter:
    """Draws the cluster onto frames of a fixed size."""

    def __init__(self, layout: dict, width: int, height: int):
        from .render import _glyphs  # shared numeral sprites

        self.w, self.h = width, height
        self.k = PLACEMENT["diameter"] * height / SPEC["size"]      # pixels per cluster unit
        self.ox = PLACEMENT["cx"] * width - SPEC["size"] / 2 * self.k
        self.oy = PLACEMENT["cy"] * height - SPEC["size"] / 2 * self.k
        self.c = {name: _bgr(v) for name, v in SPEC["colors"].items()}
        sb, gb = SPEC["speed"]["box"], SPEC["gear"]["box"]
        self.speed_box = [int(round(v)) for v in (*self.pt(sb[0], sb[1]), *self.pt(sb[2], sb[3]))]
        self.gear_box = [int(round(v)) for v in (*self.pt(gb[0], gb[1]), *self.pt(gb[2], gb[3]))]
        self.speed_glyphs = _glyphs((self.speed_box[2] - self.speed_box[0]) // 3, self.speed_box[3] - self.speed_box[1])
        self.gear_glyphs = _glyphs(self.gear_box[2] - self.gear_box[0], self.gear_box[3] - self.gear_box[1])
        self._static()

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.k, self.oy + y * self.k

    def _arc(self, img, spec, colour, frac=1.0, scale=1.0, origin=(0.0, 0.0), cap=True):
        """An arc of the gauge, filled from its start to `frac` of its sweep."""
        from .render import fill_arc

        cx, cy = SPEC["center"]
        centre = ((self.ox - origin[0] + cx * self.k) * scale, (self.oy - origin[1] + cy * self.k) * scale)
        r, half = spec["r"] * self.k * scale, spec["w"] * self.k * scale / 2
        a0, a1 = spec["from"], spec["from"] + (spec["to"] - spec["from"]) * frac
        fill_arc(img, centre, r - half, r + half, a0, a1, colour)
        if cap:  # rounded start; the moving end stays square so its position reads exactly
            ang = np.radians(a0)
            cv2.circle(img, (int(round(centre[0] + r * np.cos(ang))), int(round(centre[1] + r * np.sin(ang)))),
                       int(round(half)), colour, -1, cv2.LINE_AA)

    def _static(self) -> None:
        """Everything that never changes, drawn once at 3x and scaled down for smooth edges."""
        ss, size = 3, SPEC["size"]
        side = int(np.ceil(size * self.k)) + 2
        self.sx, self.sy = int(np.floor(self.ox)), int(np.floor(self.oy))
        origin = (self.sx, self.sy)
        img = np.zeros((side * ss, side * ss, 3), np.uint8)
        alpha = np.zeros((side * ss, side * ss), np.uint8)

        def P(x, y):
            return (int(round((self.ox - origin[0] + x * self.k) * ss)), int(round((self.oy - origin[1] + y * self.k) * ss)))

        cx, cy = SPEC["center"]
        cv2.circle(alpha, P(cx, cy), int(SPEC["panel_r"] * self.k * ss), 235, -1, cv2.LINE_AA)
        cv2.circle(img, P(cx, cy), int(SPEC["panel_r"] * self.k * ss), self.c["panel"], -1, cv2.LINE_AA)
        cv2.circle(img, P(cx, cy), int(SPEC["panel_r"] * self.k * ss), self.c["hairline"], max(1, ss), cv2.LINE_AA)
        for name in ("brake", "throttle", "rpm", "g"):
            self._arc(img, SPEC[name], self.c["track"], 1.0, ss, origin, cap=name != "g")
        led = SPEC["leds"]
        for i in range(led["n"]):
            cv2.rectangle(img, P(led["x"] + i * led["pitch"], led["y"]),
                          P(led["x"] + i * led["pitch"] + led["w"], led["y"] + led["h"]), self.c["track"], -1)
        gb = SPEC["gear"]["box"]
        cv2.rectangle(img, P(gb[0] - 2, gb[1] - 1), P(gb[2] + 2, gb[3] + 1), self.c["hairline"], max(1, ss), cv2.LINE_AA)
        for lab in SPEC["labels"]:
            scale = 0.3 * self.k * ss
            (tw, th), _ = cv2.getTextSize(lab["text"], cv2.FONT_HERSHEY_SIMPLEX, scale, max(1, ss // 2))
            px, py = P(lab["x"], lab["y"])
            cv2.putText(img, lab["text"], (px - tw // 2, py), cv2.FONT_HERSHEY_SIMPLEX, scale, self.c["muted"], max(1, ss // 2), cv2.LINE_AA)
        self.sprite = cv2.resize(img, (side, side), interpolation=cv2.INTER_AREA).astype(np.float32)
        self.alpha = (cv2.resize(alpha, (side, side), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0)[..., None]

    def _numeral(self, frame, glyphs, box, text: str, cells: int) -> None:
        x0, y0, x1, _ = box
        cw = (x1 - x0) // cells
        text = text[-cells:]
        start = x0 + (cells - len(text)) * cw  # right-aligned
        for i, ch in enumerate(text):
            a = glyphs[ch][..., None]
            cell = frame[y0: y0 + a.shape[0], start + i * cw: start + i * cw + a.shape[1]]
            if cell.shape[:2] == a.shape[:2]:
                cell[:] = (cell * (1 - a) + np.array(self.c["paper"], np.float32) * a).astype(np.uint8)

    def draw(self, frame: np.ndarray, v: dict) -> np.ndarray:
        """v: speed, gear, throttle, brake, rpm (drs is ignored: the cluster has none)."""
        side = self.sprite.shape[0]
        y0, x0 = max(0, self.sy), max(0, self.sx)
        y1, x1 = min(self.h, self.sy + side), min(self.w, self.sx + side)
        roi = frame[y0:y1, x0:x1]
        sp = self.sprite[y0 - self.sy: y1 - self.sy, x0 - self.sx: x1 - self.sx]
        al = self.alpha[y0 - self.sy: y1 - self.sy, x0 - self.sx: x1 - self.sx]
        roi[:] = (roi * (1 - al) + sp * al).astype(np.uint8)

        th = float(np.clip(v["throttle"] / 100.0, 0, 1))
        if th > 0.005:
            self._arc(frame, SPEC["throttle"], self.c["throttle"], th)
        if v["brake"] > 50:
            self._arc(frame, SPEC["brake"], self.c["brake"], 1.0)
        lo, hi = SPEC["rpm"]["scale"]
        rf = float(np.clip((v["rpm"] - lo) / (hi - lo), 0, 1))
        if rf > 0.005:
            self._arc(frame, SPEC["rpm"], self.c["rpm"], rf, cap=False)
        led, top = SPEC["leds"], v.get("rpm_max") or 12500.0
        lit = int(round(np.clip((v["rpm"] - led["from"] * top) / ((1 - led["from"]) * top), 0, 1) * led["n"]))
        for i in range(lit):
            p0 = self.pt(led["x"] + i * led["pitch"], led["y"])
            p1 = self.pt(led["x"] + i * led["pitch"] + led["w"], led["y"] + led["h"])
            cv2.rectangle(frame, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])),
                          self.c["rpm"] if i >= led["n"] - led["purple"] else self.c["paper"], -1)
        self._numeral(frame, self.speed_glyphs, self.speed_box, str(int(round(max(v["speed"], 0)))), 3)
        g = int(round(v["gear"]))
        self._numeral(frame, self.gear_glyphs, self.gear_box, "N" if g <= 0 else str(g), 1)
        return frame

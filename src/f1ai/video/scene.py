"""A driver's-eye view of the real circuit, generated from its geometry.

The road in each frame is the actual track ahead of the car at that moment
of the lap: real corner shapes and sequence, real elevation, the car's real
speed. A mini-map shows where on the circuit the car is.

Stylised, because no public source has them: track width, kerbs, verges,
the sky and skyline, and the car's nose. Nothing here is footage.
"""

from __future__ import annotations

import cv2
import numpy as np
from scipy.ndimage import uniform_filter1d

HALF_WIDTH = 6.5      # metres, stylised
KERB = 1.3
VERGE = 9.0
LOOK = 150            # samples of track drawn ahead (600 m at 4 m spacing)
CAM_HEIGHT = 1.15


def _bgr(hex_colour: str) -> np.ndarray:
    h = hex_colour.lstrip("#")
    return np.array([int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)], np.float32)


C = {k: _bgr(v) for k, v in {
    "sky_top": "#070818", "sky_low": "#3a1f5e", "glow": "#ff7a3a", "ground_far": "#23162a", "ground_near": "#0c0d11",
    "fog": "#2a1a33", "asphalt_a": "#30333b", "asphalt_b": "#2c2f37", "line": "#f4f1ea", "kerb_r": "#e23a4a",
    "kerb_w": "#f1eee7", "verge": "#17221d", "skyline": "#090a10", "board": "#14161b", "panel": "#0d0f12", "car": "#15171c", "rubber": "#26292f",
}.items()}


class TrackScene:
    """Renders the view from the car for any moment of a lap."""

    def __init__(self, trk: dict, on: dict, width: int, height: int, colour: str = "#a26bff", seed: int = 5):
        self.w, self.h = width, height
        self.x, self.y, self.z = (np.asarray(trk[k], float) for k in ("x", "y", "z"))
        self.n, self.ds = len(self.x), float(trk["step"])
        self.time = np.maximum.accumulate(np.asarray(on["time"], float))
        self.corners = [(c["i"], c["label"]) for c in trk["corners"]]
        self.colour = _bgr(colour)
        th = np.arctan2(np.roll(self.y, -1) - np.roll(self.y, 1), np.roll(self.x, -1) - np.roll(self.x, 1))
        self.cos = uniform_filter1d(np.cos(th), 5, mode="wrap")
        self.sin = uniform_filter1d(np.sin(th), 5, mode="wrap")
        norm = np.hypot(self.cos, self.sin)
        self.cos, self.sin = self.cos / norm, self.sin / norm
        th = np.arctan2(self.sin, self.cos)
        turn = np.angle(np.exp(1j * (np.roll(th, -1) - np.roll(th, 1)))) / (2 * self.ds)   # rad/m, + = left
        self.turn = uniform_filter1d(turn, 7, mode="wrap")
        self.focal = width * 0.9
        self.hy = int(height * 0.44)
        self._backdrop(np.random.default_rng(seed))
        self._minimap()

    # ---------- static parts ----------
    def _backdrop(self, rng: np.random.Generator) -> None:
        w, h, hy = self.w, self.h, self.hy
        bg = np.zeros((h, w, 3), np.float32)
        t = (np.arange(hy) / max(hy - 1, 1))[:, None, None]
        bg[:hy] = C["sky_top"] * (1 - t) ** 1.6 + C["sky_low"] * (1 - (1 - t) ** 1.6)
        glow = np.exp(-((np.arange(hy) - hy) / (h * 0.085)) ** 2)[:, None, None]
        bg[:hy] += (C["glow"] - bg[:hy]) * glow * 0.8
        g = (np.arange(h - hy) / max(h - hy - 1, 1))[:, None, None]
        bg[hy:] = C["ground_far"] * (1 - g) ** 2 + C["ground_near"] * (1 - (1 - g) ** 2)
        self.bg = np.clip(bg, 0, 255).astype(np.uint8)
        # a skyline wrapped around the full circle, so it slides sideways as the car turns
        fov = 2 * np.arctan(w / 2 / self.focal)
        self.pan_w = int(round(w * 2 * np.pi / fov))
        heights = np.zeros(self.pan_w)
        for scale, amp in ((self.pan_w // 9, 0.030), (self.pan_w // 40, 0.022), (self.pan_w // 150, 0.012)):
            k = max(2, self.pan_w // max(scale, 1))
            knots = rng.random(k + 1)
            heights += amp * np.interp(np.arange(self.pan_w), np.linspace(0, self.pan_w, k + 1), np.append(knots[:-1], knots[0]))
        blocks = np.repeat(rng.random(self.pan_w // 46 + 1), 46)[: self.pan_w] > 0.72   # grandstands
        heights += blocks * 0.022
        self.skyline = (heights * h).astype(int) + 2
        self.stars = (rng.integers(0, self.pan_w, 520), rng.integers(0, int(hy * 0.7), 520), rng.integers(70, 190, 520))

    def _minimap(self) -> None:
        w, h = self.w, self.h
        mw, mh, pad = int(w * 0.17), int(h * 0.2), int(w * 0.012)
        self.map_box = (w - mw - int(w * 0.02), int(h * 0.035), mw, mh)
        xs, ys = self.x, -self.y
        k = min((mw - 2 * pad) / np.ptp(xs), (mh - 2 * pad) / np.ptp(ys))
        ox = self.map_box[0] + mw / 2 - (xs.min() + np.ptp(xs) / 2) * k
        oy = self.map_box[1] + mh / 2 - (ys.min() + np.ptp(ys) / 2) * k
        self.map_pts = np.stack([xs * k + ox, ys * k + oy], axis=1)

    # ---------- per frame ----------
    def _project(self, wx, wy, wz, px, py, cz, ch, sh):
        dx, dy = wx - px, wy - py
        fwd = np.maximum(dx * ch + dy * sh, 1.2)
        right = dx * sh - dy * ch
        return np.stack([self.w / 2 + self.focal * right / fwd, self.hy + self.focal * (cz - wz) / fwd], axis=1), fwd

    def frame(self, i: int, distance: float, speed: float, lap_t: float) -> np.ndarray:
        w, h, hy, n = self.w, self.h, self.hy, self.n
        fi = float(np.interp(lap_t, self.time, np.arange(n)))
        i0, u = int(fi) % n, fi - int(fi)
        i1 = (i0 + 1) % n
        px, py = self.x[i0] + (self.x[i1] - self.x[i0]) * u, self.y[i0] + (self.y[i1] - self.y[i0]) * u
        cz = self.z[i0] + (self.z[i1] - self.z[i0]) * u + CAM_HEIGHT
        ch, sh = self.cos[i0] + (self.cos[i1] - self.cos[i0]) * u, self.sin[i0] + (self.sin[i1] - self.sin[i0]) * u
        heading = np.arctan2(sh, ch)

        f = self.bg.copy()
        # skyline and stars, placed by compass direction
        centre = (-heading / (2 * np.pi)) * self.pan_w
        cols = (np.arange(w) + int(centre) - w // 2) % self.pan_w
        sx = (self.stars[0] - int(centre) + w // 2) % self.pan_w
        vis = sx < w
        f[self.stars[1][vis], sx[vis]] = np.maximum(f[self.stars[1][vis], sx[vis]], self.stars[2][vis, None])
        top = hy - self.skyline[cols]
        rows = np.arange(hy)[:, None]
        f[:hy][rows >= top[None, :]] = C["skyline"].astype(np.uint8)

        j = (i0 + np.arange(LOOK + 1)) % n
        X, Y, Z = self.x[j], self.y[j], self.z[j]
        nx, ny = -self.sin[j], self.cos[j]                      # unit vector to the left of travel
        args = (px, py, cz, ch, sh)
        cl, fwd = self._project(X, Y, Z, *args)
        edges = {}
        for name, off in (("l", HALF_WIDTH), ("r", -HALF_WIDTH), ("li", HALF_WIDTH - 0.28), ("ri", -HALF_WIDTH + 0.28),
                          ("lk", HALF_WIDTH + KERB), ("rk", -HALF_WIDTH - KERB), ("lv", HALF_WIDTH + VERGE), ("rv", -HALF_WIDTH - VERGE),
                          ("gl", 1.7), ("gr", -1.7)):
            edges[name], _ = self._project(X + nx * off, Y + ny * off, Z, *args)
        fog = np.clip(fwd / (LOOK * self.ds), 0, 1) ** 1.25

        def quad(a, b, k, colour):
            pts = np.array([a[k], b[k], b[k + 1], a[k + 1]])
            if np.abs(pts).max() < 30000:
                cv2.fillConvexPoly(f, pts.astype(np.int32), (colour * (1 - fog[k]) + C["fog"] * fog[k]).tolist(), cv2.LINE_AA)

        for k in range(LOOK - 1, -1, -1):                       # far to near
            idx = int(j[k])
            quad(edges["lv"], edges["rv"], k, C["verge"])
            turn = self.turn[idx]
            if abs(turn) > 1 / 110:                             # kerb on the inside of the corner
                a, b = ("l", "lk") if turn > 0 else ("r", "rk")
                quad(edges[a], edges[b], k, C["kerb_r"] if idx % 2 else C["kerb_w"])
            quad(edges["l"], edges["r"], k, C["asphalt_a"] if (idx // 2) % 2 else C["asphalt_b"])
            quad(edges["gl"], edges["gr"], k, C["rubber"])     # the darker, rubbered racing line
            quad(edges["l"], edges["li"], k, C["line"])
            quad(edges["r"], edges["ri"], k, C["line"])
            if idx == 0:                                        # start line
                quad(edges["l"], edges["r"], k, C["line"])

        for ci, label in self.corners:                          # corner boards on the outside
            k = (ci - i0) % n
            if not (3 <= k < LOOK - 2) or fwd[k] > 320:
                continue
            side = -1.0 if self.turn[ci] > 0 else 1.0
            base, _ = self._project(X[k:k + 1] + nx[k] * side * (HALF_WIDTH + 4.5), Y[k:k + 1] + ny[k] * side * (HALF_WIDTH + 4.5), Z[k:k + 1], *args)
            s = self.focal / fwd[k]
            bx, by, bw, bh = base[0][0], base[0][1], 2.6 * s, 1.5 * s
            if bw < 9 or not (0 < bx < w):
                continue
            x0, y0, x1, y1 = int(bx - bw / 2), int(by - 2.9 * s), int(bx + bw / 2), int(by - 2.9 * s + bh)
            cv2.line(f, (int(bx), int(by)), (int(bx), y1), (60, 60, 66), max(1, int(0.12 * s)), cv2.LINE_AA)
            cv2.rectangle(f, (x0, y0), (x1, y1), C["board"].tolist(), -1)
            cv2.rectangle(f, (x0, y0), (x1, y1), C["line"].tolist(), max(1, int(0.05 * s)), cv2.LINE_AA)
            scale = bh / 34.0
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, scale, max(1, int(scale * 1.6)))
            cv2.putText(f, label, (int(bx - tw / 2), int(y0 + bh / 2 + th / 2)), cv2.FONT_HERSHEY_DUPLEX, scale,
                        C["line"].tolist(), max(1, int(scale * 1.6)), cv2.LINE_AA)

        self._car(f, speed)
        self._draw_map(f, fi)
        return f

    def _car(self, f: np.ndarray, speed: float) -> None:
        """The car's nose, wing and front tyres, as a camera above the cockpit sees them."""
        w, h = self.w, self.h
        P = lambda pts: np.array([[x * w, y * h] for x, y in pts], np.int32)  # noqa: E731
        car, team = C["car"].tolist(), self.colour.tolist()
        for x0, x1 in ((0.115, 0.265), (0.735, 0.885)):          # front tyres
            cv2.fillConvexPoly(f, P([(x0 + 0.012, 0.83), (x1 - 0.012, 0.83), (x1, 1.0), (x0, 1.0)]), (14, 14, 16), cv2.LINE_AA)
            mid = P([((x0 + x1) / 2, 0.83)])[0]                 # rounded shoulder
            cv2.ellipse(f, (int(mid[0]), int(mid[1])), (int((x1 - x0 - 0.024) * w / 2), int(0.035 * h)), 0, 180, 360, (14, 14, 16), -1, cv2.LINE_AA)
            cv2.ellipse(f, (int(mid[0]), int(mid[1])), (int((x1 - x0 - 0.05) * w / 2), int(0.022 * h)), 0, 200, 340, (58, 58, 64), 2, cv2.LINE_AA)
        cv2.fillConvexPoly(f, P([(0.20, 0.905), (0.80, 0.905), (0.83, 0.95), (0.17, 0.95)]), car, cv2.LINE_AA)   # wing
        cv2.fillConvexPoly(f, P([(0.17, 0.95), (0.83, 0.95), (0.83, 0.962), (0.17, 0.962)]), team, cv2.LINE_AA)
        cv2.fillConvexPoly(f, P([(0.455, 0.72), (0.545, 0.72), (0.66, 1.0), (0.34, 1.0)]), car, cv2.LINE_AA)       # nose
        cv2.fillConvexPoly(f, P([(0.492, 0.72), (0.508, 0.72), (0.53, 1.0), (0.47, 1.0)]), team, cv2.LINE_AA)

    def _draw_map(self, f: np.ndarray, fi: float) -> None:
        x, y, mw, mh = self.map_box
        roi = f[y:y + mh, x:x + mw]
        roi[:] = (roi * 0.28 + C["panel"] * 0.72).astype(np.uint8)
        cv2.rectangle(f, (x, y), (x + mw - 1, y + mh - 1), (55, 46, 42), 1)
        pts = np.round(self.map_pts * 8).astype(np.int32)
        cv2.polylines(f, [pts], True, (150, 147, 141), 2, cv2.LINE_AA, shift=3)
        done = pts[: int(fi) + 1]
        if len(done) > 1:
            cv2.polylines(f, [done], False, self.colour.tolist(), 3, cv2.LINE_AA, shift=3)
        cx, cy = self.map_pts[int(fi) % self.n]
        cv2.circle(f, (int(cx), int(cy)), max(4, self.w // 190), self.colour.tolist(), -1, cv2.LINE_AA)
        cv2.circle(f, (int(cx), int(cy)), max(4, self.w // 190), C["line"].tolist(), 1, cv2.LINE_AA)


def for_lap(ses, lap, colour: str | None = None):
    """Scene factory for `render_onboard(scene=...)` showing the session's real
    circuit for this lap, or None when the circuit geometry is unavailable."""
    from .. import data, track

    try:
        trk = track.build_track(ses, lap)
        on = track.lap_on_track(trk, lap)
    except (track.TrackError, data.DataError, ValueError):
        return None
    if colour is None:
        row = ses.drivers[ses.drivers["Driver"] == lap.attrs.get("driver")]
        colour = row.iloc[0]["TeamColor"] if len(row) else "#a26bff"
    return lambda w, h: TrackScene(trk, on, w, h, colour)

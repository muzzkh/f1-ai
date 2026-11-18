"""Circuit geometry from real data.

Builds a smooth, evenly sampled centreline for a circuit from the surveyed
outline in the MultiViewer circuit API, oriented the way circuit maps are
normally drawn, and places a lap's telemetry onto it using the car's GPS
position. Everything is in metres; `s` is distance along the lap from the
start/finish line.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.interpolate import splev, splprep
from scipy.ndimage import median_filter, uniform_filter1d

from . import data
from .analysis import _project_onto_path


class TrackError(RuntimeError):
    pass


def _rotate(x, y, degrees: float):
    a = np.radians(degrees)
    return x * np.cos(a) - y * np.sin(a), x * np.sin(a) + y * np.cos(a)


def _closed_spline(x: np.ndarray, y: np.ndarray, step: float, smooth: float = 0.5):
    """Periodic smoothing spline through a loop, resampled every `step` metres.
    Returns x, y (open: the last point is one step before the first) and length."""
    keep = np.concatenate([[True], np.hypot(np.diff(x), np.diff(y)) > 0.5])
    x, y = x[keep], y[keep]
    if np.hypot(x[0] - x[-1], y[0] - y[-1]) > 0.5:
        x, y = np.append(x, x[0]), np.append(y, y[0])
    else:
        x[-1], y[-1] = x[0], y[0]
    tck, _ = splprep([x, y], s=len(x) * smooth ** 2, per=True)
    fx, fy = splev(np.linspace(0, 1, 6000, endpoint=False), tck)
    fx, fy = np.asarray(fx), np.asarray(fy)
    seg = np.hypot(np.diff(np.append(fx, fx[0])), np.diff(np.append(fy, fy[0])))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    length = float(cum[-1])
    n = int(round(length / step))
    grid = np.arange(n) * (length / n)
    return (np.interp(grid, cum, np.append(fx, fx[0])), np.interp(grid, cum, np.append(fy, fy[0])), length)


def build_track(ses: data.Session, lap: pd.DataFrame, step: float = 4.0) -> dict:
    """Centreline, corners and sector marks for the session's circuit.

    `lap` (from `data.lap_telemetry`, with GPS) fixes where the start/finish
    line is and which way round the circuit runs.
    """
    info = data.circuit_info(ses)
    if not info.get("x") or lap["X"].isna().any():
        raise TrackError("No circuit outline or GPS position available for this session.")
    ox, oy = np.asarray(info["x"], float) / 10.0, np.asarray(info["y"], float) / 10.0
    cx, cy, length = _closed_spline(ox, oy, step)
    n = len(cx)
    ds = length / n
    s_all = np.arange(n + 1) * ds
    loop = lambda a: np.append(a, a[0])  # noqa: E731

    # direction of travel: the car must move forwards along the outline
    lx, ly = lap["X"].values, lap["Y"].values
    q = _project_onto_path(lx[[len(lx) // 4, len(lx) // 4 + 8]], ly[[len(ly) // 4, len(ly) // 4 + 8]],
                           loop(cx), loop(cy), s_all)
    forward = ((q[1] - q[0]) % length) < length / 2
    if not forward:
        cx, cy = cx[::-1].copy(), cy[::-1].copy()

    # start/finish: where the car was at lap time zero
    first = _project_onto_path(lx[:1], ly[:1], loop(cx), loop(cy), s_all)[0]
    start = (first - lap["Distance"].iloc[0] * (length / lap["Distance"].iloc[-1])) % length
    k = int(round(start / ds)) % n
    cx, cy = np.roll(cx, -k), np.roll(cy, -k)

    rot = float(info.get("rotation", 0.0))
    rx, ry = _rotate(cx, cy, rot)
    corners = []
    for c in info.get("corners", []):
        px, py = c["trackPosition"]["x"] / 10.0, c["trackPosition"]["y"] / 10.0
        s = float(_project_onto_path(np.array([px]), np.array([py]), loop(cx), loop(cy), s_all)[0])
        i = int(round(s / ds)) % n
        # MultiViewer gives the direction in which to offset each corner's label
        a = np.radians(float(c.get("angle", 0.0)) + rot)
        corners.append({"label": f"{c['number']}{c.get('letter') or ''}", "s": round(s, 1), "i": i,
                        "ax": float(np.cos(a)), "ay": float(np.sin(a))})
    corners.sort(key=lambda c: c["s"])
    return {"length": round(length, 1), "step": ds, "x": rx, "y": ry, "raw_x": cx, "raw_y": cy,
            "corners": corners, "rotation": rot, "circuit": ses.circuit}


def lap_on_track(track: dict, lap: pd.DataFrame, sectors: tuple[float, float] | None = None) -> dict:
    """Resample a lap's telemetry onto the track's sample points.

    Returns arrays aligned with `track["x"]`: time, speed, gear, throttle,
    brake, rpm and longitudinal g at each point of the centreline.
    """
    cx, cy = track["raw_x"], track["raw_y"]
    n, length, ds = len(cx), track["length"], track["step"]
    s_all = np.arange(n + 1) * ds
    own = lap["Distance"].values * (length / lap["Distance"].iloc[-1])
    gps = _project_onto_path(lap["X"].values, lap["Y"].values, np.append(cx, cx[0]), np.append(cy, cy[0]),
                             s_all, expected_s=own)
    # GPS timestamps jitter; use it only for the slow drift (see analysis.compare_laps)
    drift = uniform_filter1d(median_filter(gps - own, size=5, mode="nearest"), size=15, mode="nearest")
    s = np.maximum.accumulate(own + drift)
    lap_time = float(lap.attrs["lap_time"])
    s = np.concatenate([[0.0], s, [length]])
    t = np.concatenate([[0.0], lap["Time"].values, [lap_time]])
    keep = np.concatenate([[True], np.diff(s) > 1e-6])
    s, t = s[keep], t[keep]
    grid = np.arange(n) * ds

    def lin(col):
        v = np.concatenate([[lap[col].iloc[0]], lap[col].values, [lap[col].iloc[-1]]])[keep]
        return np.interp(grid, s, v)

    def step_(col):
        v = np.concatenate([[lap[col].iloc[0]], lap[col].values, [lap[col].iloc[-1]]])[keep]
        return v[np.clip(np.searchsorted(s, grid), 0, len(s) - 1)]

    time = np.interp(grid, s, t)
    speed = lin("Speed")
    v = speed / 3.6
    g = uniform_filter1d(np.gradient(v, np.maximum(time, 1e-6) + np.arange(n) * 1e-9) / 9.81, size=9, mode="nearest")
    out = {"time": time, "speed": speed, "gear": step_("nGear"), "throttle": lin("Throttle"),
           "brake": step_("Brake"), "rpm": lin("RPM"), "g": np.clip(g, -6.5, 2.5), "lap_time": lap_time}
    if sectors:
        s1, s2 = sectors
        out["sectors"] = [float(np.interp(s1, time, grid)), float(np.interp(s1 + s2, time, grid))]
    return out

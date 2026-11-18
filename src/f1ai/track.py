"""Circuit geometry from real data.

Builds a smooth, evenly sampled line around a circuit from the surveyed
outline in the MultiViewer circuit API, oriented the way circuit maps are
normally drawn, and places laps onto it using the cars' GPS positions.
Everything is in metres; `s` is distance along the lap from the start line.

What is real and what is not:
  real      circuit shape, corner numbers, start line, sector points,
            elevation, the pit lane path, where the car was on each lap
  measured  the outline follows a driven line, so its length comes out
            about 2% shorter than the official centreline distance
  absent    track width and kerbs are in no public source; anything drawn
            for them downstream is stylised
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


def rotate(x, y, degrees: float):
    a = np.radians(degrees)
    return x * np.cos(a) - y * np.sin(a), x * np.sin(a) + y * np.cos(a)


def _closed_spline(x: np.ndarray, y: np.ndarray, step: float, smooth: float = 0.5):
    """Periodic smoothing spline through a loop, resampled every ~`step`
    metres. Returns x, y (open: the last point sits one step before the
    first) and the loop length."""
    x, y = np.asarray(x, float).copy(), np.asarray(y, float).copy()
    keep = np.concatenate([[True], np.hypot(np.diff(x), np.diff(y)) > 0.5])
    x, y = x[keep], y[keep]
    if np.hypot(x[0] - x[-1], y[0] - y[-1]) > 0.5:
        x, y = np.append(x, x[0]), np.append(y, y[0])
    else:
        x[-1], y[-1] = x[0], y[0]
    tck, _ = splprep([x, y], s=len(x) * smooth ** 2, per=True)
    fx, fy = (np.asarray(v) for v in splev(np.linspace(0, 1, 6000, endpoint=False), tck))
    cx, cy = np.append(fx, fx[0]), np.append(fy, fy[0])
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(cx), np.diff(cy)))])
    length = float(cum[-1])
    n = max(8, int(round(length / step)))
    grid = np.arange(n) * (length / n)
    return np.interp(grid, cum, cx), np.interp(grid, cum, cy), length


def _loop(a: np.ndarray) -> np.ndarray:
    return np.append(a, a[0])


def outline(circuit_key: int | None, year: int, points: int = 180) -> dict | None:
    """A circuit's shape alone (no lap needed): `points` evenly spaced
    vertices, oriented for display. Used for the season calendar."""
    info = data.circuit_info_by_key(circuit_key, year)
    if not info.get("x"):
        return None
    ox, oy = np.asarray(info["x"], float) / 10.0, np.asarray(info["y"], float) / 10.0
    cx, cy, length = _closed_spline(ox, oy, 4.0)
    idx = np.linspace(0, len(cx), points, endpoint=False).astype(int)
    rx, ry = rotate(cx[idx], cy[idx], float(info.get("rotation", 0.0)))
    return {"x": rx, "y": ry, "length": length}


def _lap_s(cx: np.ndarray, cy: np.ndarray, length: float, lap: pd.DataFrame) -> np.ndarray:
    """Distance along the track for every sample of a lap.

    The car's own integrated distance is smooth but drifts; GPS is unbiased
    but its timestamps jitter. GPS is therefore used only to correct the
    slow drift (the same approach as `analysis.compare_laps`).
    """
    n = len(cx)
    s_all = np.arange(n + 1) * (length / n)
    own = lap["Distance"].values * (length / lap["Distance"].iloc[-1])
    if lap["X"].isna().any():  # no position data: the car's own distance is all there is
        return own
    gps = _project_onto_path(lap["X"].values, lap["Y"].values, _loop(cx), _loop(cy), s_all, expected_s=own)
    drift = uniform_filter1d(median_filter(gps - own, size=5, mode="nearest"), size=15, mode="nearest")
    return np.maximum.accumulate(own + drift)


def build_track(ses: data.Session, lap: pd.DataFrame, step: float = 4.0) -> dict:
    """Geometry of the session's circuit.

    `lap` (from `data.lap_telemetry`, with GPS) fixes where the start line is,
    which way round the circuit runs, and supplies the elevation profile.

    Returns x, y (display orientation), z (metres above the lowest point),
    raw_x, raw_y (survey orientation, for projecting GPS), corners, length.
    """
    info = data.circuit_info(ses)
    gps = not lap["X"].isna().any()
    surveyed = bool(info.get("x"))
    if surveyed:
        ox, oy = np.asarray(info["x"], float) / 10.0, np.asarray(info["y"], float) / 10.0
    elif gps:  # no survey for this circuit: trace the outline from the lap itself
        ox, oy = lap["X"].values, lap["Y"].values
    else:
        raise TrackError("No circuit outline or GPS position available for this session.")
    cx, cy, length = _closed_spline(ox, oy, step)
    n = len(cx)
    ds = length / n
    s_all = np.arange(n + 1) * ds

    if gps and surveyed:
        # direction of travel: the car must move forwards along the outline
        lx, ly = lap["X"].values, lap["Y"].values
        j = len(lx) // 4
        q = _project_onto_path(lx[[j, j + 8]], ly[[j, j + 8]], _loop(cx), _loop(cy), s_all)
        if ((q[1] - q[0]) % length) > length / 2:
            cx, cy = cx[::-1].copy(), cy[::-1].copy()

        # start line: where the car was at lap time zero
        first = _project_onto_path(lx[:1], ly[:1], _loop(cx), _loop(cy), s_all)[0]
        start = (first - lap["Distance"].iloc[0] * (length / lap["Distance"].iloc[-1])) % length
        k = int(round(start / ds)) % n
        cx, cy = np.roll(cx, -k), np.roll(cy, -k)
    # Without GPS the survey is taken as it comes: it is itself a recorded lap,
    # so it starts at the line and runs in the direction of travel.

    rot = float(info.get("rotation", 0.0))
    rx, ry = rotate(cx, cy, rot)
    grid = np.arange(n) * ds

    z = np.zeros(n)
    if gps and "Z" in lap and lap["Z"].notna().all():
        s = _lap_s(cx, cy, length, lap)
        raw = np.interp(grid, s, lap["Z"].values)
        z = uniform_filter1d(median_filter(raw, size=9, mode="wrap"), size=21, mode="wrap")  # ~80 m
        z = z - z.min()

    corners = []
    for c in info.get("corners", []):
        px, py = c["trackPosition"]["x"] / 10.0, c["trackPosition"]["y"] / 10.0
        sc = float(_project_onto_path(np.array([px]), np.array([py]), _loop(cx), _loop(cy), s_all)[0])
        # MultiViewer gives the direction in which to offset each corner's label
        a = np.radians(float(c.get("angle", 0.0)) + rot)
        corners.append({"label": f"{c['number']}{c.get('letter') or ''}", "s": round(sc, 1),
                        "i": int(round(sc / ds)) % n, "ax": float(np.cos(a)), "ay": float(np.sin(a))})
    corners.sort(key=lambda c: c["s"])
    return {"length": round(length, 1), "step": ds, "x": rx, "y": ry, "z": z, "raw_x": cx, "raw_y": cy,
            "corners": corners, "rotation": rot, "circuit": ses.circuit, "gps": gps, "surveyed": surveyed}


def lap_on_track(track: dict, lap: pd.DataFrame, sectors: tuple[float, float] | None = None) -> dict:
    """Resample a lap onto the track's sample points.

    Returns arrays aligned with `track["x"]`: time, speed, gear, throttle,
    brake, rpm, longitudinal g, and the car's own line (line_x, line_y in
    display orientation). `sectors`, the lap's first two sector times, adds
    the distances at which sectors one and two end.
    """
    cx, cy = track["raw_x"], track["raw_y"]
    n, length, ds = len(cx), track["length"], track["step"]
    grid = np.arange(n) * ds
    lap_time = float(lap.attrs["lap_time"])
    s_mid = _lap_s(cx, cy, length, lap)
    s = np.concatenate([[0.0], s_mid, [length]])
    t = np.concatenate([[0.0], lap["Time"].values, [lap_time]])
    keep = np.concatenate([[True], np.diff(s) > 1e-6])
    s, t = s[keep], t[keep]

    def padded(col):
        v = lap[col].values
        return np.concatenate([[v[0]], v, [v[-1]]])[keep]

    def lin(col):
        return np.interp(grid, s, padded(col))

    def stepped(col):
        return padded(col)[np.clip(np.searchsorted(s, grid), 0, len(s) - 1)]

    time = np.interp(grid, s, t)
    speed = lin("Speed")
    dt = np.maximum(np.gradient(time), 1e-3)
    g = uniform_filter1d(np.gradient(speed / 3.6) / dt / 9.81, size=9, mode="nearest")
    if lap["X"].isna().any():
        line_x, line_y = np.asarray(track["x"], float), np.asarray(track["y"], float)
    else:
        lx, ly = rotate(lap["X"].values, lap["Y"].values, track["rotation"])
        line_x = uniform_filter1d(np.interp(grid, s_mid, lx), size=3, mode="wrap")
        line_y = uniform_filter1d(np.interp(grid, s_mid, ly), size=3, mode="wrap")
    out = {
        "time": time, "speed": speed, "gear": stepped("nGear"), "throttle": lin("Throttle"),
        "brake": stepped("Brake"), "rpm": lin("RPM"), "g": np.clip(g, -6.5, 2.5), "lap_time": lap_time,
        "line_x": line_x, "line_y": line_y,
    }
    if sectors:
        s1, s2 = sectors
        out["sectors"] = [float(np.interp(s1, time, grid)), float(np.interp(s1 + s2, time, grid))]
    return out


def pit_lane(ses: data.Session, track: dict) -> dict | None:
    """Path of the pit lane, traced from a car that made a stop: the part of
    its in-lap and out-lap that ran away from the racing surface. None when
    no clean stop is available."""
    laps = ses.laps
    stops = laps[laps["PitIn"] & laps["LapStart"].notna() & laps["LapTime"].notna() & (laps["TrackStatus"] == "GREEN")]
    for _, a in stops.iterrows():
        b = laps[(laps["DriverNumber"] == a["DriverNumber"]) & (laps["LapNumber"] == a["LapNumber"] + 1)]
        if b.empty or pd.isna(b.iloc[0]["LapStart"]) or pd.isna(b.iloc[0]["LapTime"]):
            continue
        b = b.iloc[0]
        t0 = a["LapStart"] + pd.Timedelta(seconds=float(a["LapTime"]) * 0.5)
        t1 = b["LapStart"] + pd.Timedelta(seconds=float(b["LapTime"]) * 0.6)
        loc = data.location(ses, int(a["DriverNumber"]), t0, t1)
        if len(loc) < 40:
            continue
        px, py = loc["X"].values, loc["Y"].values
        d = np.sqrt(((px[:, None] - track["raw_x"][None, :]) ** 2 + (py[:, None] - track["raw_y"][None, :]) ** 2).min(axis=1))
        off = d > 9.0  # further from the driven line than a track is wide
        best, run = (0, 0), None
        for i, flag in enumerate(np.append(off, False)):
            if flag and run is None:
                run = i
            elif not flag and run is not None:
                if i - run > best[1] - best[0]:
                    best = (run, i)
                run = None
        lo, hi = best
        if hi - lo < 25:
            continue
        lo, hi = max(0, lo - 3), min(len(px), hi + 3)  # reach back to where it leaves and rejoins
        sx = uniform_filter1d(px[lo:hi], size=5, mode="nearest")
        sy = uniform_filter1d(py[lo:hi], size=5, mode="nearest")
        rx, ry = rotate(sx, sy, track["rotation"])
        return {"x": rx, "y": ry}
    return None

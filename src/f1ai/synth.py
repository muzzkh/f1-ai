"""A physically plausible made-up lap, for demos and tests that must work offline."""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_lap(seed: int = 0, length_m: float = 4800.0, sample_hz: float = 4.0) -> pd.DataFrame:
    """Telemetry for an invented circuit, in the same shape as `data.lap_telemetry`."""
    rng = np.random.default_rng(seed)
    ds = 2.0
    s = np.arange(0.0, length_m, ds)
    vmax = np.full_like(s, 335.0 / 3.6)
    n_corners = int(rng.integers(10, 15))
    apex_pos = np.sort(rng.uniform(250, length_m - 150, n_corners))
    apex_speed = rng.choice([75, 95, 120, 150, 185, 230, 265], n_corners) / 3.6
    for p, v in zip(apex_pos, apex_speed):
        vmax[np.abs(s - p) < 25] = np.minimum(vmax[np.abs(s - p) < 25], v)

    v = vmax.copy()
    v[0] = min(v[0], 290 / 3.6)
    for i in range(1, len(s)):  # traction / power limited acceleration
        a = max(1.5, 13.0 - 0.115 * v[i - 1])
        v[i] = min(v[i], np.sqrt(v[i - 1] ** 2 + 2 * a * ds))
    for i in range(len(s) - 2, -1, -1):  # braking limit, more grip at speed (downforce)
        b = 22.0 + 0.28 * v[i + 1]
        v[i] = min(v[i], np.sqrt(v[i + 1] ** 2 + 2 * b * ds))

    t = np.concatenate([[0.0], np.cumsum(ds / (0.5 * (v[1:] + v[:-1])))])
    acc = np.gradient(v, t)
    throttle = np.clip(np.where(acc > 0.5, 100.0, np.where(acc < -3, 0.0, 35.0 + acc * 12)), 0, 100)
    throttle[v >= vmax - 0.5] = np.minimum(throttle[v >= vmax - 0.5], 60 + 40 * (vmax[v >= vmax - 0.5] > 300 / 3.6))
    brake = np.where(acc < -6.0, 100.0, 0.0)
    kmh = v * 3.6
    edges = np.array([0, 105, 140, 175, 210, 245, 280, 310, 400])
    gear = np.clip(np.searchsorted(edges, kmh, side="right"), 1, 8)
    lo, hi = edges[gear - 1], edges[gear]
    rpm = 7200 + 4600 * (kmh - lo) / (hi - lo)
    drs = ((kmh > 255) & (throttle > 95)).astype(float)

    ts = np.arange(0.0, t[-1], 1.0 / sample_hz) + rng.uniform(0, 0.02, int(np.ceil(t[-1] * sample_hz)))[: len(np.arange(0.0, t[-1], 1.0 / sample_hz))]
    idx = np.clip(np.searchsorted(t, ts), 0, len(t) - 1)
    out = pd.DataFrame(
        {
            "Time": ts,
            "Distance": np.interp(ts, t, s),
            "Speed": np.round(np.interp(ts, t, kmh)),
            "Throttle": np.round(np.interp(ts, t, throttle)),
            "Brake": brake[idx],
            "nGear": gear[idx].astype(float),
            "RPM": np.round(np.interp(ts, t, rpm)),
            "DRS": drs[idx],
            "X": np.nan,
            "Y": np.nan,
        }
    )
    out.attrs.update(driver="SYN", lap_number=1, lap_time=float(t[-1]), compound="SOFT", tyre_life=1)
    return out

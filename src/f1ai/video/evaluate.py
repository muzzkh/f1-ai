"""Compare telemetry read from video with a reference trace."""

from __future__ import annotations

import numpy as np
import pandas as pd


def estimate_offset(extracted: pd.DataFrame, reference: pd.DataFrame, hz: float = 10.0) -> float:
    """Seconds to add to reference time to line it up with video time.

    Slides the video's speed trace along the reference and keeps the shift
    with the smallest mean speed error, so a clip showing only part of a lap
    is placed correctly within it.
    """
    te = np.arange(extracted["Time"].min(), extracted["Time"].max(), 1 / hz)
    tr = np.arange(reference["Time"].min(), reference["Time"].max(), 1 / hz)
    if len(te) < 10 or len(tr) < 10:
        return 0.0
    e = np.interp(te, extracted["Time"], extracted["Speed"])
    r = np.interp(tr, reference["Time"], reference["Speed"])
    need = max(10, int(0.6 * min(len(e), len(r))))  # minimum overlap
    best, best_lag = np.inf, 0
    for lag in range(-(len(e) - need), len(r) - need + 1):  # e[i] <-> r[i + lag]
        i0, j0 = max(0, -lag), max(0, lag)
        n = min(len(e) - i0, len(r) - j0)
        cost = np.abs(e[i0: i0 + n] - r[j0: j0 + n]).mean()
        if cost < best:
            best, best_lag = cost, lag
    coarse = te[0] - tr[0] - best_lag / hz
    # refine to 10 ms around the coarse answer
    fine = coarse + np.arange(-1.0 / hz, 1.0 / hz + 1e-9, 0.01)
    rt, rv = reference["Time"].values, reference["Speed"].values
    costs = []
    for off in fine:
        m = (rt + off >= te[0]) & (rt + off <= te[-1])
        costs.append(np.abs(np.interp(rt[m] + off, te, e) - rv[m]).mean() if m.sum() > 5 else np.inf)
    return float(fine[int(np.argmin(costs))])


def accuracy(extracted: pd.DataFrame, reference: pd.DataFrame, offset: float | None = None) -> dict:
    """Error of the extracted channels against a reference, after time alignment."""
    if offset is None:
        offset = estimate_offset(extracted, reference)
    t = reference["Time"].values + offset
    inside = (t >= extracted["Time"].min()) & (t <= extracted["Time"].max())
    ref, t = reference[inside], t[inside]
    if len(ref) < 5:
        raise ValueError("The video and the reference lap do not overlap in time.")
    et = extracted["Time"].values
    idx = np.clip(np.searchsorted(et, t), 0, len(et) - 1)
    out = {"offset_s": round(float(offset), 3), "samples": int(len(ref))}
    err = np.abs(np.interp(t, et, extracted["Speed"]) - ref["Speed"].values)
    out["speed_mae_kmh"] = round(float(err.mean()), 2)
    out["speed_p95_kmh"] = round(float(np.percentile(err, 95)), 2)
    if "Throttle" in extracted:
        out["throttle_mae_pct"] = round(float(np.abs(np.interp(t, et, extracted["Throttle"]) - ref["Throttle"].values).mean()), 2)
    if "Brake" in extracted:
        out["brake_agreement_pct"] = round(float(((extracted["Brake"].values[idx] > 50) == (ref["Brake"].values > 50)).mean() * 100), 1)
    if "nGear" in extracted:
        out["gear_accuracy_pct"] = round(float((extracted["nGear"].values[idx] == ref["nGear"].values).mean() * 100), 1)
    if "RPM" in extracted:
        out["rpm_mae"] = round(float(np.abs(np.interp(t, et, extracted["RPM"]) - ref["RPM"].values).mean()), 0)
    if "DRS" in extracted and ref["DRS"].notna().any():
        out["drs_agreement_pct"] = round(float((extracted["DRS"].values[idx] == ref["DRS"].fillna(0).values).mean() * 100), 1)
    out["speed_read_rate_pct"] = round(float(extracted.attrs.get("speed_read_rate", np.nan)) * 100, 1)
    return out

"""Race, pace, tyre and telemetry analysis.

Every function takes a loaded `f1ai.data.Session` and returns plain pandas
DataFrames / dicts with times in seconds, so the dashboard and the MCP server
can share them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.ndimage import median_filter, uniform_filter1d

from .config import DEFAULT_FUEL_EFFECT_S_PER_LAP
from . import data
from .data import Session, driver_list

DRY_COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]
COMPOUND_COLORS = {
    "SOFT": "#e8002d",
    "MEDIUM": "#f5c400",
    "HARD": "#d9d9d9",
    "INTERMEDIATE": "#3bb54a",
    "WET": "#1e6fd9",
    "UNKNOWN": "#888888",
}


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def format_laptime(seconds: float | None) -> str:
    if seconds is None or not np.isfinite(seconds):
        return "-"
    sign = "-" if seconds < 0 else ""
    seconds = abs(float(seconds))
    m, sec = divmod(seconds, 60.0)
    return f"{sign}{int(m)}:{sec:06.3f}" if m else f"{sign}{sec:.3f}"


def team_colors(ses: Session) -> dict[str, str]:
    """Driver abbreviation -> team colour hex."""
    return dict(zip(ses.drivers["Driver"], ses.drivers["TeamColor"]))


# ----------------------------------------------------------------------------
# results and laps
# ----------------------------------------------------------------------------

def results_frame(ses: Session) -> pd.DataFrame:
    return ses.results.copy()


def laps_frame(ses: Session, drivers: list[str] | None = None) -> pd.DataFrame:
    """All laps of the session, times in seconds."""
    laps = ses.laps
    if drivers:
        laps = laps[laps["Driver"].isin(drivers)]
    return laps.copy()


def clean_laps(df: pd.DataFrame, threshold: float = 1.07) -> pd.DataFrame:
    """Representative racing laps: accurate timing, green flag, no pit in/out
    laps, and within `threshold` x the fastest such lap of the session."""
    ok = (
        df["IsAccurate"]
        & ~df["PitIn"]
        & ~df["PitOut"]
        & (df["TrackStatus"] == "GREEN")
        & df["LapTime"].notna()
    )
    c = df[ok]
    if len(c):
        c = c[c["LapTime"] <= threshold * c["LapTime"].min()]
    return c


def position_chart(ses) -> pd.DataFrame:
    """Lap x driver matrix of track position (race sessions)."""
    df = laps_frame(ses).dropna(subset=["Position", "LapNumber"])
    piv = df.pivot_table(index="LapNumber", columns="Driver", values="Position", aggfunc="first")
    order = [d for d in driver_list(ses) if d in piv.columns]
    return piv[order]


def race_pace(ses) -> pd.DataFrame:
    """Per-driver pace on clean laps, sorted fastest first."""
    c = clean_laps(laps_frame(ses))
    if c.empty:
        return pd.DataFrame(columns=["Driver", "Team", "Laps", "Median", "Mean", "Best", "Std", "GapToBest"])
    g = c.groupby("Driver")
    out = pd.DataFrame(
        {
            "Team": g["Team"].first(),
            "Laps": g["LapTime"].size(),
            "Median": g["LapTime"].median(),
            "Mean": g["LapTime"].mean(),
            "Best": g["LapTime"].min(),
            "Std": g["LapTime"].std(),
        }
    )
    out = out[out["Laps"] >= 3].sort_values("Median")
    out["GapToBest"] = out["Median"] - out["Median"].min()
    return out.reset_index()


def stints(ses) -> pd.DataFrame:
    """One row per driver stint with compound, lap range and clean pace."""
    df = laps_frame(ses).dropna(subset=["Stint", "LapNumber"])
    clean_idx = clean_laps(df).index
    rows = []
    for (drv, stint), g in df.groupby(["Driver", "Stint"], sort=True):
        cl = g.loc[g.index.intersection(clean_idx)]
        comp = g["Compound"].mode()
        rows.append(
            {
                "Driver": drv,
                "Stint": int(stint),
                "Compound": comp.iloc[0] if len(comp) else "UNKNOWN",
                "StartLap": int(g["LapNumber"].min()),
                "EndLap": int(g["LapNumber"].max()),
                "Laps": int(len(g)),
                "StartTyreLife": float(g["TyreLife"].min()) if g["TyreLife"].notna().any() else np.nan,
                "FreshTyre": bool(g["FreshTyre"].iloc[0]) if pd.notna(g["FreshTyre"].iloc[0]) else None,
                "CleanLaps": int(len(cl)),
                "MedianPace": float(cl["LapTime"].median()) if len(cl) else np.nan,
            }
        )
    out = pd.DataFrame(rows)
    order = {d: i for i, d in enumerate(driver_list(ses))}
    out["_o"] = out["Driver"].map(order).fillna(99)
    return out.sort_values(["_o", "Stint"]).drop(columns="_o").reset_index(drop=True)


def sector_bests(ses) -> pd.DataFrame:
    """Best sectors per driver and the theoretical best lap they add up to."""
    df = laps_frame(ses)
    g = df.groupby("Driver")
    out = pd.DataFrame(
        {
            "S1": g["Sector1"].min(),
            "S2": g["Sector2"].min(),
            "S3": g["Sector3"].min(),
            "BestLap": g["LapTime"].min(),
            "TopSpeedTrap": g["SpeedTrap"].max(),
        }
    )
    out["Theoretical"] = out[["S1", "S2", "S3"]].sum(axis=1, min_count=3)
    out["LeftOnTable"] = out["BestLap"] - out["Theoretical"]
    return out.sort_values("BestLap").reset_index()


def weather_summary(ses) -> dict:
    w = ses.weather
    if w is None or len(w) == 0:
        return {}
    return {
        "air_temp_c": round(float(w["air_temperature"].mean()), 1),
        "track_temp_c": round(float(w["track_temperature"].mean()), 1),
        "humidity_pct": round(float(w["humidity"].mean()), 0),
        "wind_speed_ms": round(float(w["wind_speed"].mean()), 1),
        "rain": bool((w["rainfall"].fillna(0) > 0).any()),
    }


# ----------------------------------------------------------------------------
# pace model: fuel-corrected tyre degradation
# ----------------------------------------------------------------------------

@dataclass
class PaceModel:
    """lap_time = driver_base + compound_offset + deg * tyre_life + fuel * lap_number"""

    driver_base: dict[str, float]
    compound_offset: dict[str, float]      # seconds vs reference compound, new tyre
    degradation: dict[str, float]          # seconds per lap of tyre age
    fuel_effect: float                     # seconds per lap (negative = getting faster)
    reference_compound: str
    n_laps: int
    r2: float
    residual_std: float
    laps_per_compound: dict[str, int] = field(default_factory=dict)
    fuel_fitted: bool = True

    def predict(self, driver: str, compound: str, tyre_life: float, lap_number: float) -> float:
        return (
            self.driver_base[driver]
            + self.compound_offset.get(compound, 0.0)
            + self.degradation.get(compound, 0.0) * tyre_life
            + self.fuel_effect * lap_number
        )

    def to_dict(self) -> dict:
        return {
            "reference_compound": self.reference_compound,
            "compound_offset_s": {k: round(v, 3) for k, v in self.compound_offset.items()},
            "degradation_s_per_lap": {k: round(v, 4) for k, v in self.degradation.items()},
            "fuel_effect_s_per_lap": round(self.fuel_effect, 4),
            "fuel_effect_fitted": self.fuel_fitted,
            "driver_base_pace_s": {k: round(v, 3) for k, v in sorted(self.driver_base.items(), key=lambda kv: kv[1])},
            "laps_used": self.n_laps,
            "laps_per_compound": self.laps_per_compound,
            "r2": round(self.r2, 3),
            "residual_std_s": round(self.residual_std, 3),
        }


def fit_pace_model(ses, min_laps: int = 40) -> PaceModel:
    """Least-squares fit of a linear pace model on clean dry-tyre race laps.

    Separates three things that are tangled together in raw lap times: how
    quick each driver is, how much each compound degrades per lap, and how
    much the car gains as fuel burns off.
    """
    df = clean_laps(laps_frame(ses))
    df = df[df["Compound"].isin(DRY_COMPOUNDS)].dropna(subset=["TyreLife", "LapNumber"])
    counts = df["Compound"].value_counts()
    # a compound needs a meaningful sample or its coefficients are just noise
    compounds = [c for c in DRY_COMPOUNDS if counts.get(c, 0) >= 30]
    df = df[df["Compound"].isin(compounds)]
    if len(df) < min_laps or not compounds:
        raise ValueError(
            f"Not enough clean dry laps to fit a pace model ({len(df)} found, need {min_laps})."
        )
    drivers = sorted(df["Driver"].unique())
    ref = max(compounds, key=lambda c: counts[c])
    others = [c for c in compounds if c != ref]

    def design(with_fuel: bool) -> np.ndarray:
        cols = [(df["Driver"] == d).astype(float).values for d in drivers]
        cols += [(df["Compound"] == c).astype(float).values for c in others]
        cols += [((df["Compound"] == c) * df["TyreLife"]).astype(float).values for c in compounds]
        if with_fuel:
            cols.append(df["LapNumber"].astype(float).values)
        return np.column_stack(cols)

    y = df["LapTime"].values
    X = design(True)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    fuel = float(beta[-1])
    fuel_fitted = True
    # Fuel burn can only make the car faster. A positive or absurdly large
    # coefficient means the fit could not separate fuel from tyre age (e.g.
    # everyone ran near-identical strategies), so fall back to a typical value.
    if not (-0.15 <= fuel <= 0.0):
        fuel = -DEFAULT_FUEL_EFFECT_S_PER_LAP
        fuel_fitted = False
        X = design(False)
        beta, *_ = np.linalg.lstsq(X, y - fuel * df["LapNumber"].values, rcond=None)
        pred = X @ beta + fuel * df["LapNumber"].values
    else:
        pred = X @ beta

    nd, no = len(drivers), len(others)
    resid = y - pred
    ss_tot = float(((y - y.mean()) ** 2).sum())
    offsets = {ref: 0.0, **{c: float(beta[nd + i]) for i, c in enumerate(others)}}
    deg = {c: float(beta[nd + no + i]) for i, c in enumerate(compounds)}
    return PaceModel(
        driver_base={d: float(beta[i]) for i, d in enumerate(drivers)},
        compound_offset=offsets,
        degradation=deg,
        fuel_effect=fuel,
        reference_compound=ref,
        n_laps=int(len(df)),
        r2=float(1 - (resid ** 2).sum() / ss_tot) if ss_tot > 0 else float("nan"),
        residual_std=float(resid.std()),
        laps_per_compound={c: int(counts[c]) for c in compounds},
        fuel_fitted=fuel_fitted,
    )


def stint_degradation(ses, model: PaceModel | None = None) -> pd.DataFrame:
    """Fuel-corrected lap-time slope for each individual stint (>= 6 clean laps)."""
    fuel = model.fuel_effect if model else -DEFAULT_FUEL_EFFECT_S_PER_LAP
    df = clean_laps(laps_frame(ses)).dropna(subset=["TyreLife", "Stint"])
    rows = []
    for (drv, stint), g in df.groupby(["Driver", "Stint"]):
        if len(g) < 6:
            continue
        corrected = g["LapTime"] - fuel * g["LapNumber"]
        slope, intercept = np.polyfit(g["TyreLife"], corrected, 1)
        rows.append(
            {
                "Driver": drv,
                "Stint": int(stint),
                "Compound": g["Compound"].mode().iloc[0],
                "Laps": int(len(g)),
                "DegPerLap": float(slope),
                "FirstLapPace": float(intercept + slope * g["TyreLife"].min() + fuel * g["LapNumber"].min()),
            }
        )
    return pd.DataFrame(rows)


def pit_loss(ses: Session) -> dict:
    """Time lost by making a pit stop under green-flag running.

    Measured per stop as (in-lap + out-lap) minus the laps either side of
    them, so changing track conditions do not leak into the figure.
    """
    df = laps_frame(ses)
    losses = []
    for _, g in df.groupby("Driver"):
        g = g.sort_values("LapNumber").reset_index(drop=True)
        for i in range(1, len(g) - 2):
            prev, a, b, nxt = g.iloc[i - 1], g.iloc[i], g.iloc[i + 1], g.iloc[i + 2]
            if not (a["PitIn"] and b["PitOut"]):
                continue
            four = [prev, a, b, nxt]
            if any(x["TrackStatus"] != "GREEN" or not np.isfinite(x["LapTime"]) for x in four):
                continue  # stops under SC/VSC are cheaper and would bias this
            if prev["PitIn"] or prev["PitOut"] or nxt["PitIn"] or nxt["PitOut"] or prev["LapNumber"] == 1:
                continue
            if nxt["LapNumber"] - prev["LapNumber"] != 3:
                continue
            losses.append(a["LapTime"] + b["LapTime"] - prev["LapTime"] - nxt["LapTime"])
    losses = [x for x in losses if 10 < x < 45]
    if len(losses) >= 3:
        return {"seconds": float(np.median(losses)), "stops_measured": len(losses), "measured": True}
    return {"seconds": 22.0, "stops_measured": len(losses), "measured": False}


def simulate_strategies(
    ses,
    model: PaceModel | None = None,
    max_stops: int = 2,
    min_stint: int = 6,
    top: int = 10,
) -> dict:
    """Rank dry one- and two-stop strategies by predicted total race time.

    Uses the fitted pace model (compound offsets + linear degradation) and
    the pit loss measured in this race. Stint lengths are capped at what was
    actually run on each compound, because a linear model cannot see the
    'cliff' that ends a real stint.
    """
    if ses.code != "R":
        raise ValueError("Strategy simulation needs a Grand Prix race session.")
    model = model or fit_pace_model(ses)
    if len(model.degradation) < 2:
        only = ", ".join(model.degradation)
        raise ValueError(
            f"Only one dry compound ({only}) has enough clean laps in this race, so there is "
            "nothing to trade off. This usually means a wet or mixed-conditions race."
        )
    df = laps_frame(ses)
    total_laps = int(ses.total_laps or df["LapNumber"].max())
    loss = pit_loss(ses)
    st = stints(ses)
    compounds = list(model.degradation)
    max_len = {}
    for c in compounds:
        ran = st[st["Compound"] == c]
        longest = (ran["Laps"] + ran["StartTyreLife"].fillna(1) - 1).max() if len(ran) else 0
        max_len[c] = int(min(total_laps, np.ceil(longest * 1.1))) if longest else 0
    deg = {c: max(model.degradation[c], 0.0) for c in compounds}
    off = model.compound_offset

    def stint_cost(c: str, n: int) -> float:
        return n * off[c] + deg[c] * n * (n + 1) / 2.0

    found = []
    # one stop
    for c1 in compounds:
        for c2 in compounds:
            if c1 == c2:
                continue
            for n1 in range(min_stint, total_laps - min_stint + 1):
                n2 = total_laps - n1
                if n1 > max_len[c1] or n2 > max_len[c2]:
                    continue
                t = stint_cost(c1, n1) + stint_cost(c2, n2) + loss["seconds"]
                found.append((t, [(c1, n1), (c2, n2)]))
    if max_stops >= 2:
        for c1 in compounds:
            for c2 in compounds:
                for c3 in compounds:
                    if len({c1, c2, c3}) < 2:
                        continue
                    for n1 in range(min_stint, total_laps - 2 * min_stint + 1):
                        if n1 > max_len[c1]:
                            break
                        for n2 in range(min_stint, total_laps - n1 - min_stint + 1):
                            n3 = total_laps - n1 - n2
                            if n2 > max_len[c2] or n3 > max_len[c3]:
                                continue
                            t = stint_cost(c1, n1) + stint_cost(c2, n2) + stint_cost(c3, n3) + 2 * loss["seconds"]
                            found.append((t, [(c1, n1), (c2, n2), (c3, n3)]))
    if not found:
        raise ValueError("No feasible dry strategy found with the compounds run in this race.")

    # keep only the best stint split for each compound sequence
    best: dict[tuple, tuple] = {}
    for t, plan in found:
        key = tuple(c for c, _ in plan)
        if key not in best or t < best[key][0]:
            best[key] = (t, plan)
    ranked = sorted(best.values(), key=lambda x: x[0])[:top]
    t0 = ranked[0][0]
    strategies = []
    for t, plan in ranked:
        stops, lap = [], 0
        for _, n in plan[:-1]:
            lap += n
            stops.append(lap)
        strategies.append(
            {
                "compounds": [c for c, _ in plan],
                "stint_laps": [n for _, n in plan],
                "pit_laps": stops,
                "stops": len(plan) - 1,
                "gap_to_best_s": round(t - t0, 2),
            }
        )
    winner = driver_list(ses)[0] if driver_list(ses) else None
    actual = st[st["Driver"] == winner] if winner else st.iloc[0:0]
    return {
        "total_laps": total_laps,
        "pit_loss_s": round(loss["seconds"], 2),
        "pit_loss_measured": loss["measured"],
        "max_stint_laps": max_len,
        "strategies": strategies,
        "winner": winner,
        "winner_actual": {
            "compounds": actual["Compound"].tolist(),
            "stint_laps": actual["Laps"].tolist(),
        },
    }


# ----------------------------------------------------------------------------
# telemetry
# ----------------------------------------------------------------------------

def lap_telemetry(ses: Session, driver: str, lap_number: int | None = None) -> pd.DataFrame:
    """Telemetry of one lap (fastest by default). See `data.lap_telemetry`."""
    return data.lap_telemetry(ses, driver, lap_number)


def _project_onto_path(px, py, path_x, path_y, path_s, expected_s=None, window=400.0):
    """Along-track coordinate of points (px, py) on a reference polyline.

    Each point is dropped perpendicularly onto its nearest path segment. When
    `expected_s` is given, only segments within `window` metres of it are
    considered, so a track that passes close to itself cannot cause a jump.
    """
    ax, ay = path_x[:-1], path_y[:-1]
    dx, dy = np.diff(path_x), np.diff(path_y)
    seg2 = np.maximum(dx * dx + dy * dy, 1e-9)
    # fraction along each segment of the closest point, for every (point, segment)
    u = ((px[:, None] - ax) * dx + (py[:, None] - ay) * dy) / seg2
    u = np.clip(u, 0.0, 1.0)
    d2 = (px[:, None] - (ax + u * dx)) ** 2 + (py[:, None] - (ay + u * dy)) ** 2
    if expected_s is not None:
        mid = 0.5 * (path_s[:-1] + path_s[1:])
        d2 = np.where(np.abs(mid[None, :] - np.asarray(expected_s)[:, None]) > window, np.inf, d2)
    j = np.argmin(d2, axis=1)
    rows = np.arange(len(px))
    return path_s[j] + u[rows, j] * (path_s[j + 1] - path_s[j])


def resample_distance(tel: pd.DataFrame, grid: np.ndarray, distance: np.ndarray | None = None) -> pd.DataFrame:
    d = tel["Distance"].values if distance is None else np.asarray(distance)
    order = np.argsort(d, kind="stable")
    d = d[order]
    out = {"Distance": grid}
    for col in ["Time", "Speed", "Throttle", "RPM", "X", "Y"]:
        out[col] = np.interp(grid, d, tel[col].values[order])
    idx = np.clip(np.searchsorted(d, grid), 0, len(d) - 1)
    for col in ["Brake", "nGear", "DRS"]:  # step channels: nearest, never blended
        out[col] = tel[col].values[order][idx]
    return pd.DataFrame(out)


def corners(ses: Session, reference: pd.DataFrame) -> pd.DataFrame:
    """Official corners placed on a reference lap's distance axis."""
    crn = data.circuit_corners(ses)
    if crn.empty or reference["X"].isna().any():
        return pd.DataFrame(columns=["Corner", "Distance", "X", "Y"])
    s = _project_onto_path(
        crn["X"].values, crn["Y"].values,
        reference["X"].values, reference["Y"].values, reference["Distance"].values,
    )
    crn = crn.assign(Distance=s)
    return crn.sort_values("Distance").reset_index(drop=True)


def compare_laps(
    ses: Session,
    driver_a: str,
    driver_b: str,
    lap_a: int | None = None,
    lap_b: int | None = None,
    step_m: float = 5.0,
    mini_sectors: int = 25,
) -> dict:
    """Compare two laps point-for-point around the track.

    Driver B's samples are projected onto driver A's racing line using GPS
    position, so both laps share one distance axis. `Delta` is B's elapsed
    time minus A's at the same point on track: positive means A is ahead,
    rising means A is gaining.
    """
    ta = lap_telemetry(ses, driver_a, lap_a)
    tb = lap_telemetry(ses, driver_b, lap_b)
    a, b = ta.attrs["driver"], tb.attrs["driver"]
    if a == b and ta.attrs["lap_number"] == tb.attrs["lap_number"]:
        raise ValueError("Pick two different laps to compare.")
    da = ta["Distance"].values
    have_xy = not (ta["X"].isna().any() or tb["X"].isna().any())
    scale = da.max() / tb["Distance"].max()
    if have_xy:
        own = tb["Distance"].values * scale
        gps = _project_onto_path(
            tb["X"].values, tb["Y"].values, ta["X"].values, ta["Y"].values, da, expected_s=own,
        )
        # Position timestamps jitter by a few tenths of a second, far too
        # noisy to use point by point. B's own integrated distance is smooth
        # but drifts, so use GPS only for the slow drift correction.
        drift = uniform_filter1d(median_filter(gps - own, size=5, mode="nearest"), size=15, mode="nearest")
        db = np.maximum.accumulate(own + drift)
        aligned = "gps"
    else:  # no position data: stretch B's integrated distance to A's lap length
        db = tb["Distance"].values * scale
        aligned = "distance"
    length = float(min(da.max(), db.max()))
    grid = np.arange(max(da.min(), db.min(), 0.0), length, step_m)
    ra, rb = resample_distance(ta, grid), resample_distance(tb, grid, db)
    frame = pd.DataFrame({"Distance": grid, "X": ra["X"], "Y": ra["Y"]})
    for col in ["Time", "Speed", "Throttle", "Brake", "nGear", "RPM", "DRS"]:
        frame[f"{col}_A"] = ra[col]
        frame[f"{col}_B"] = rb[col]
    # Pin the end of the trace to the official lap-time difference; GPS and
    # 3.7 Hz sampling leave a few hundredths of drift that this removes.
    # Sample timestamps carry ~0.1 s of jitter; averaging over ~150 m removes
    # it. Sector-level gains match official timing to a few hundredths, but
    # anything finer than a corner is indicative only.
    raw = uniform_filter1d((frame["Time_B"] - frame["Time_A"]).values, size=max(3, int(150 / step_m)), mode="nearest")
    official = tb.attrs["lap_time"] - ta.attrs["lap_time"]
    frac = (grid - grid[0]) / max(grid[-1] - grid[0], 1.0)
    frame["Delta"] = raw - raw[0] * (1 - frac) + (official - raw[-1]) * frac

    # mini sectors: who gains in each slice of the lap
    edges = np.linspace(grid[0], grid[-1], mini_sectors + 1)
    d_at = np.interp(edges, grid, frame["Delta"])
    ms = pd.DataFrame(
        {
            "MiniSector": np.arange(1, mini_sectors + 1),
            "Start": edges[:-1],
            "End": edges[1:],
            "Gain_A": np.diff(d_at),  # positive: A faster through this slice
        }
    )
    ms["Faster"] = np.where(ms["Gain_A"] > 0, a, b)
    frame["MiniSector"] = np.clip(np.searchsorted(edges, grid, side="right"), 1, mini_sectors)

    # corners: apex speed and the time swing through each corner zone
    crn = corners(ses, ta)
    rows = []
    for _, c in crn.iterrows():
        m = (grid >= c["Distance"] - 75) & (grid <= c["Distance"] + 75)
        if m.sum() < 3:
            continue
        seg = frame[m]
        rows.append(
            {
                "Corner": c["Corner"],
                "Distance": round(float(c["Distance"])),
                f"MinSpeed_{a}": round(float(seg["Speed_A"].min()), 1),
                f"MinSpeed_{b}": round(float(seg["Speed_B"].min()), 1),
                f"Gain_{a}": round(float(seg["Delta"].iloc[-1] - seg["Delta"].iloc[0]), 3),
            }
        )

    def summary(t: pd.DataFrame) -> dict:
        dt = np.gradient(t["Time"].values)
        w = dt / dt.sum()
        return {
            "driver": t.attrs["driver"],
            "lap_number": t.attrs["lap_number"],
            "lap_time_s": round(t.attrs["lap_time"], 3),
            "compound": t.attrs["compound"],
            "tyre_life": t.attrs["tyre_life"],
            "top_speed_kmh": round(float(t["Speed"].max()), 1),
            "min_speed_kmh": round(float(t["Speed"].min()), 1),
            "full_throttle_pct": round(float(((t["Throttle"] >= 98) * w).sum() * 100), 1),
            "braking_pct": round(float(((t["Brake"] > 0) * w).sum() * 100), 1),
        }

    return {
        "driver_a": a,
        "driver_b": b,
        "frame": frame,
        "mini_sectors": ms,
        "corners": pd.DataFrame(rows),
        "corner_positions": crn,
        "summary_a": summary(ta),
        "summary_b": summary(tb),
        "lap_delta_s": round(official, 3),
        "aligned_by": aligned,
    }


# ----------------------------------------------------------------------------
# JSON helpers (MCP / API output)
# ----------------------------------------------------------------------------

def to_records(df: pd.DataFrame, decimals: int = 3) -> list[dict]:
    """DataFrame -> list of JSON-safe dicts (NaN -> None, floats rounded)."""
    out = []
    for rec in df.to_dict(orient="records"):
        clean = {}
        for k, v in rec.items():
            if isinstance(v, (pd.Timestamp,)):
                v = v.isoformat()
            elif isinstance(v, (np.floating, float)):
                v = None if not np.isfinite(v) else round(float(v), decimals)
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.bool_,)):
                v = bool(v)
            elif v is pd.NaT:
                v = None
            clean[str(k)] = v
        out.append(clean)
    return out

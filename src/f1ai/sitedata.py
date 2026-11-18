"""Data files for the static website (docs/data/*.json).

Each function turns loaded sessions into a plain JSON-ready dict. The site's
JavaScript does all the drawing; nothing here knows about presentation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d

from . import analysis as an
from . import data, track


def clean(obj):
    """Make a nested structure JSON-safe: NaN -> None, numpy -> Python."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if obj is pd.NaT or obj is pd.NA:
        return None
    return obj


def r(a, n=1):
    return [None if not np.isfinite(v) else round(float(v), n) for v in a]


def styles(ses: data.Session) -> dict[str, dict]:
    """Team colour per driver; the second driver of each team is flagged so
    charts can dash their line (team-mates are never told apart by colour)."""
    seen: dict[str, int] = {}
    out = {}
    for _, d in ses.drivers.sort_values("DriverNumber").iterrows():
        k = seen.get(d["Team"], 0)
        seen[d["Team"]] = k + 1
        out[d["Driver"]] = {"code": d["Driver"], "name": d["FullName"], "team": d["Team"],
                            "color": d["TeamColor"], "second": k > 0, "number": int(d["DriverNumber"])}
    return out


def event_meta(ses: data.Session) -> dict:
    return {"year": ses.year, "round": ses.round, "name": ses.event_name, "circuit": ses.circuit,
            "country": ses.country, "date": ses.date_start.strftime("%d %b %Y"), "laps": ses.total_laps,
            "weather": an.weather_summary(ses)}


def track_payload(trk: dict, sectors=None, pit=None) -> dict:
    out = {"length": trk["length"], "step": round(trk["step"], 4), "x": r(trk["x"]), "y": r(trk["y"]),
           "z": r(trk["z"]), "sectors": r(sectors or []),
           "corners": [{"label": c["label"], "i": c["i"], "ax": round(c["ax"], 3), "ay": round(c["ay"], 3)}
                       for c in trk["corners"]]}
    if pit:
        out["pit"] = {"x": r(pit["x"]), "y": r(pit["y"])}
    return out


def lap_payload(ses: data.Session, lap: pd.DataFrame, on: dict, st: dict) -> dict:
    drv = lap.attrs["driver"]
    row = ses.laps[(ses.laps["Driver"] == drv) & (ses.laps["LapNumber"] == lap.attrs["lap_number"])].iloc[0]
    return {**st[drv], "lap": lap.attrs["lap_number"], "time": round(on["lap_time"], 3),
            "compound": lap.attrs["compound"], "tyre_life": lap.attrs["tyre_life"],
            "sector_times": [row["Sector1"], row["Sector2"], row["Sector3"]],
            "t": r(on["time"], 3), "speed": r(on["speed"], 0), "gear": [int(v) for v in on["gear"]],
            "throttle": r(on["throttle"], 0), "brake": [int(v > 0) for v in on["brake"]],
            "rpm": r(on["rpm"], 0), "g": r(on["g"], 2), "rpm_max": float(np.percentile(lap["RPM"], 99.5))}


def _sectors(ses, lap):
    row = ses.laps[(ses.laps["Driver"] == lap.attrs["driver"]) & (ses.laps["LapNumber"] == lap.attrs["lap_number"])].iloc[0]
    if pd.isna(row["Sector1"]) or pd.isna(row["Sector2"]):
        return None
    return float(row["Sector1"]), float(row["Sector2"])


def race_payload(race: data.Session) -> dict:
    res = an.results_frame(race)
    st = styles(race)
    laps = an.laps_frame(race)

    results = [
        {**st.get(x.Driver, {"code": x.Driver, "name": x.Name, "team": x.Team, "color": "#888888", "second": False}),
         "pos": x.Pos, "grid": x.Grid, "gap": x.Gap_s, "status": x.Status, "points": x.Points, "best": x.BestLap_s,
         "laps": x.Laps}
        for x in res.itertuples()
    ]

    # showcase lap: the fastest lap of the race, on the real circuit
    best = res.dropna(subset=["BestLap_s"]).sort_values("BestLap_s").iloc[0]
    lap = an.lap_telemetry(race, best["Driver"])
    trk = track.build_track(race, lap)
    on = track.lap_on_track(trk, lap, _sectors(race, lap))
    try:
        pit = track.pit_lane(race, trk)
    except data.DataError:
        pit = None

    # race story: position and gap to the leader at the end of every lap
    order = [d for d in data.driver_list(race) if d in st]
    pos = an.position_chart(race)
    lap_numbers = list(range(1, race.total_laps + 1))
    end = laps["LapStart"] + pd.to_timedelta(laps["LapTime"], unit="s")
    nxt = laps.groupby("Driver")["LapStart"].shift(-1)  # a lap with no start time ends when the next begins
    laps = laps.assign(End=end.fillna(nxt))
    ends = laps.pivot_table(index="LapNumber", columns="Driver", values="End", aggfunc="first")
    leader = ends.min(axis=1)
    story = []
    for d in order:
        p = pos[d].reindex(lap_numbers) if d in pos else pd.Series(np.nan, index=lap_numbers)
        gap = (ends[d] - leader).dt.total_seconds().reindex(lap_numbers) if d in ends else pd.Series(np.nan, index=lap_numbers)
        story.append({"code": d, "pos": r(p.values, 0), "gap": r(gap.values, 2)})

    # neutralised periods, by lap
    status = laps.groupby("LapNumber")["TrackStatus"].agg(lambda s: s.mode().iloc[0] if len(s.mode()) else "GREEN")
    flags, cur = [], None
    for n in lap_numbers:
        k = status.get(n, "GREEN")
        if k != "GREEN" and cur and cur["kind"] == k and cur["to"] == n - 1:
            cur["to"] = n
        elif k != "GREEN":
            cur = {"kind": k, "from": n, "to": n}
            flags.append(cur)

    cl = an.clean_laps(laps)
    pace = an.race_pace(race)
    pace_rows = [
        {"code": x.Driver, "median": x.Median, "best": x.Best, "gap": x.GapToBest, "laps": int(x.Laps),
         "times": r(cl[cl["Driver"] == x.Driver]["LapTime"].values, 3)}
        for x in pace.itertuples() if x.Driver in st
    ]

    stint_rows = []
    for d, g in an.stints(race).groupby("Driver", sort=False):
        stint_rows.append({"code": d, "stints": [
            {"compound": s.Compound, "from": s.StartLap, "to": s.EndLap, "laps": s.Laps,
             "age": None if pd.isna(s.StartTyreLife) else int(s.StartTyreLife) - 1, "pace": s.MedianPace}
            for s in g.itertuples()]})

    strategy: dict = {"available": False}
    if race.code == "R":
        try:
            model = an.fit_pace_model(race)
            sim = an.simulate_strategies(race, model)
            loss = an.pit_loss(race)
            strategy = {"available": True, "fuel_ms": model.fuel_effect * 1000, "fuel_fitted": model.fuel_fitted,
                        "r2": model.r2, "error": model.residual_std, "laps_used": model.n_laps,
                        "deg": model.degradation, "offset": model.compound_offset,
                        "reference": model.reference_compound, "pit_loss": loss["seconds"],
                        "stops_measured": loss["stops_measured"], "options": sim["strategies"][:6],
                        "winner": sim["winner"], "actual": sim["winner_actual"], "total_laps": sim["total_laps"]}
        except ValueError as exc:
            strategy = {"available": False, "reason": str(exc)}

    return clean({
        "event": event_meta(race), "drivers": st, "results": results,
        "track": track_payload(trk, on.get("sectors"), pit), "lap": lap_payload(race, lap, on, st),
        "story": {"laps": lap_numbers, "series": story, "flags": flags},
        "pace": pace_rows, "stints": stint_rows, "strategy": strategy,
    })


def duel_payload(quali: data.Session, a: str | None = None, b: str | None = None, mini: int = 25) -> dict:
    """Two laps on one circuit, point for point: the top two of the session by default."""
    drivers = data.driver_list(quali)
    a, b = a or drivers[0], b or drivers[1]
    st = styles(quali)
    la, lb = an.lap_telemetry(quali, a), an.lap_telemetry(quali, b)
    trk = track.build_track(quali, la)
    oa = track.lap_on_track(trk, la, _sectors(quali, la))
    ob = track.lap_on_track(trk, lb, _sectors(quali, lb))
    n, ds = len(trk["x"]), trk["step"]

    # gap: B's elapsed time minus A's at the same point; positive = A ahead.
    # Timestamps jitter by ~0.1 s, so average over ~150 m and pin the end to
    # the official lap-time difference.
    raw = uniform_filter1d(ob["time"] - oa["time"], size=max(3, int(150 / ds)), mode="nearest")
    official = ob["lap_time"] - oa["lap_time"]
    frac = np.arange(n) / (n - 1)
    delta = raw - raw[0] * (1 - frac) + (official - raw[-1]) * frac

    half = int(round(75 / ds))
    corners = []
    for c in trk["corners"]:
        lo, hi = max(0, c["i"] - half), min(n - 1, c["i"] + half)
        corners.append({"label": c["label"], "i": c["i"], "from": lo, "to": hi,
                        "min_a": float(oa["speed"][lo:hi + 1].min()), "min_b": float(ob["speed"][lo:hi + 1].min()),
                        "gain_a": float(delta[hi] - delta[lo])})
    edges = np.linspace(0, n - 1, mini + 1).round().astype(int)
    minis = [{"from": int(edges[i]), "to": int(edges[i + 1]), "gain_a": float(delta[edges[i + 1]] - delta[edges[i]])}
             for i in range(mini)]

    def side(lap, on):
        p = lap_payload(quali, lap, on, st)
        p.update(line_x=r(on["line_x"]), line_y=r(on["line_y"]), top=float(on["speed"].max()),
                 full_throttle=float((on["throttle"] >= 98).mean() * 100), braking=float((on["brake"] > 0).mean() * 100))
        return p

    return clean({"event": event_meta(quali), "session": quali.name,
                  "track": track_payload(trk, oa.get("sectors")), "a": side(la, oa), "b": side(lb, ob),
                  "delta": r(delta, 3), "gap": round(float(official), 3), "corners": corners, "minis": minis})


def season_payload(year: int, built: set[int], colors: dict[str, str] | None = None) -> dict:
    """Calendar with circuit shapes, championship progression and standings."""
    sched = data.schedule(year)
    done = set(data.completed_events(year)["RoundNumber"])
    winners = data.season_winners(year)
    colors = colors or {}
    rounds = []
    for ev in sched.itertuples():
        shape = track.outline(ev.CircuitKey, year)
        rounds.append({
            "round": int(ev.RoundNumber), "name": ev.EventName, "circuit": ev.Circuit, "country": ev.Country,
            "date": ev.EventDate.strftime("%d %b"), "done": int(ev.RoundNumber) in done,
            "built": int(ev.RoundNumber) in built, "sprint": "S" in ev.Sessions,
            "winner": winners.get(int(ev.RoundNumber)),
            "outline": None if shape is None else {"x": r(shape["x"], 0), "y": r(shape["y"], 0),
                                                    "km": round(shape["length"] / 1000, 2)},
        })

    table: dict[str, dict] = {}
    last = max(done) if done else 0
    for rnd in range(1, last + 1):
        for row in data.standings_after(year, rnd):
            d = table.setdefault(row["code"], {"code": row["code"], "name": row["driver"], "team": row["team"],
                                               "points": [None] * last})
            d["points"][rnd - 1] = row["points"]
            d["team"] = row["team"]
    for d in table.values():  # a driver absent from an early table had no points yet
        filled, prev = [], 0.0
        for p in d["points"]:
            prev = prev if p is None else p
            filled.append(prev)
        d["points"] = filled
        d["color"] = colors.get(d["code"], "#888888")
    drivers = sorted(table.values(), key=lambda d: -d["points"][-1] if d["points"] else 0)
    final = data.standings(year)
    return clean({"year": year, "last_round": last, "rounds": rounds, "drivers": drivers,
                  "constructors": final["constructors"]})

"""Export the data behind the race-page hero (site/data/hero.json).

    python dashboard/export_hero.py [--year 2026 --event "Sao Paulo"]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from f1ai import analysis as an  # noqa: E402
from f1ai import data, track  # noqa: E402
from f1ai.config import ROOT  # noqa: E402


def r(a, n=1):
    return [round(float(v), n) for v in a]


def export(year: int | None, event: str | None, out: Path) -> Path:
    if year and event:
        race = data.load_session(year, event, "R")
    else:
        y, rnd, _ = data.latest_completed_event()
        race = data.load_session(y, rnd, "R")
    res = an.results_frame(race)
    colors = an.team_colors(race)
    names = dict(zip(race.drivers["Driver"], race.drivers["FullName"]))
    teams = dict(zip(race.drivers["Driver"], race.drivers["Team"]))

    # the fastest lap of the race is the showcase lap
    best = res.dropna(subset=["BestLap_s"]).sort_values("BestLap_s").iloc[0]
    lap = an.lap_telemetry(race, best["Driver"])
    row = race.laps[(race.laps["Driver"] == best["Driver"]) & (race.laps["LapNumber"] == lap.attrs["lap_number"])].iloc[0]
    trk = track.build_track(race, lap)
    on = track.lap_on_track(trk, lap, (float(row["Sector1"]), float(row["Sector2"])))

    def num(v):
        return None if pd.isna(v) else float(v)

    results = [
        {"pos": None if pd.isna(x.Pos) else int(x.Pos), "code": x.Driver, "name": x.Name, "team": x.Team,
         "color": colors.get(x.Driver, "#888888"), "grid": None if pd.isna(x.Grid) else int(x.Grid),
         "gap": num(x.Gap_s), "status": x.Status, "points": num(x.Points), "best": num(x.BestLap_s)}
        for x in res.itertuples()
    ]
    payload = {
        "event": {"year": race.year, "round": race.round, "name": race.event_name, "circuit": race.circuit,
                  "country": race.country, "date": race.date_start.strftime("%d %b %Y"), "laps": race.total_laps,
                  "weather": an.weather_summary(race)},
        "results": results,
        "track": {"length": trk["length"], "step": round(trk["step"], 4), "x": r(trk["x"]), "y": r(trk["y"]),
                  "corners": [{"label": c["label"], "i": c["i"], "ax": round(c["ax"], 3), "ay": round(c["ay"], 3)}
                              for c in trk["corners"]],
                  "sectors": r(on.get("sectors", []))},
        "lap": {"code": best["Driver"], "name": names.get(best["Driver"]), "team": teams.get(best["Driver"]),
                "color": colors.get(best["Driver"], "#888888"), "number": lap.attrs["lap_number"],
                "time": round(on["lap_time"], 3), "compound": lap.attrs["compound"], "tyre_life": lap.attrs["tyre_life"],
                "sector_times": [num(row["Sector1"]), num(row["Sector2"]), num(row["Sector3"])],
                "t": r(on["time"], 3), "speed": r(on["speed"], 0), "gear": [int(v) for v in on["gear"]],
                "throttle": r(on["throttle"], 0), "brake": [int(v > 0) for v in on["brake"]],
                "rpm": r(on["rpm"], 0), "g": r(on["g"], 2),
                "rpm_max": float(np.percentile(lap["RPM"], 99.5))},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"{race.title}: {len(trk['x'])} track points, {trk['length']:.0f} m, "
          f"{len(trk['corners'])} corners -> {out} ({out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int)
    p.add_argument("--event")
    p.add_argument("--out", default=str(ROOT / "site" / "data" / "hero.json"))
    a = p.parse_args()
    export(a.year, a.event, Path(a.out))

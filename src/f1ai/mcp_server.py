"""MCP server: gives an AI assistant F1 timing data, analysis and the video tools.

Run with `python -m f1ai.mcp_server` (stdio transport).
"""

from __future__ import annotations

import functools
from pathlib import Path

import numpy as np
import pandas as pd
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import analysis as an
from . import data
from .config import TELEMETRY_DIR, VIDEO_DIR

mcp = MCPServer(
    "f1ai",
    title="F1 AI",
    instructions=(
        "Formula 1 timing data (2023 onwards), race analysis and video-to-telemetry tools. "
        "Events are addressed by year plus a round number or a name fragment such as 'Monza' "
        "or 'British'. Sessions are R (race), Q (qualifying), S (sprint), SQ (sprint "
        "qualifying), FP1, FP2, FP3. Drivers are three-letter codes such as VER, a car number "
        "or part of a name. All times are in seconds. Call get_schedule first if unsure what "
        "exists; data for a session appears shortly after it finishes."
    ),
)


def tool(fn):
    """Register a tool; expected failures reach the model as a readable message."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (data.DataError, ValueError, FileNotFoundError) as exc:
            raise ToolError(str(exc)) from exc

    return mcp.tool()(wrapper)


def _session(year: int, event: str, session: str):
    return data.load_session(year, event, session)


def _header(ses) -> dict:
    return {"event": ses.event_name, "year": ses.year, "round": ses.round, "session": ses.name, "circuit": ses.circuit}


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


@tool
def get_schedule(year: int) -> dict:
    """Race calendar for a season: round numbers, event names, dates, which
    sessions each weekend has, and whether it has already been run."""
    sched = data.schedule(year)
    done = set(data.completed_events(year)["RoundNumber"])
    return {
        "year": year,
        "events": [
            {
                "round": int(r.RoundNumber), "event": r.EventName, "country": r.Country, "circuit": r.Circuit,
                "date": r.EventDate.strftime("%Y-%m-%d"), "sessions": r.Sessions,
                "completed": int(r.RoundNumber) in done,
            }
            for r in sched.itertuples()
        ],
    }


@tool
def get_standings(year: int) -> dict:
    """Current (or final) driver and constructor championship standings for a season."""
    return data.standings(year)


@tool
def get_session_results(year: int, event: str, session: str = "R") -> dict:
    """Classification of a session. Races: position, grid, gap to winner,
    status, points. Qualifying: Q1/Q2/Q3 times. Also weather and each
    driver's best lap."""
    ses = _session(year, event, session)
    return {**_header(ses), "weather": an.weather_summary(ses), "total_laps": ses.total_laps,
            "results": an.to_records(an.results_frame(ses))}


@tool
def get_lap_times(year: int, event: str, driver: str, session: str = "R") -> dict:
    """Every lap of one driver: lap time, sectors, tyre compound and age,
    position, pit in/out flags and track status (GREEN / SC / VSC / RED)."""
    ses = _session(year, event, session)
    drv = data.resolve_driver(ses, driver)
    laps = an.laps_frame(ses, [drv])
    cols = ["LapNumber", "LapTime", "Sector1", "Sector2", "Sector3", "Compound", "TyreLife", "Stint",
            "Position", "PitIn", "PitOut", "TrackStatus", "SpeedTrap"]
    return {**_header(ses), "driver": drv, "laps": an.to_records(laps[cols])}


@tool
def get_race_pace(year: int, event: str, session: str = "R") -> dict:
    """Drivers ranked by representative pace: median of clean laps (green
    flag, no pit laps, within 107% of the fastest), with gap to the quickest."""
    ses = _session(year, event, session)
    return {**_header(ses), "pace": an.to_records(an.race_pace(ses))}


@tool
def get_tyre_strategy(year: int, event: str, session: str = "R") -> dict:
    """What each driver ran: every stint with compound, lap range, tyre age
    at the start and median clean pace."""
    ses = _session(year, event, session)
    return {**_header(ses), "stints": an.to_records(an.stints(ses))}


@tool
def get_tyre_degradation(year: int, event: str) -> dict:
    """Fitted race pace model: how much slower each dry compound gets per lap
    of age, pace offset between compounds, the fuel-burn effect, each
    driver's underlying pace, plus measured pit-stop time loss. A simple
    linear model; treat the numbers as estimates and check r2."""
    ses = _session(year, event, "R")
    model = an.fit_pace_model(ses)
    return {**_header(ses), "model": model.to_dict(), "pit_loss": an.pit_loss(ses),
            "per_stint": an.to_records(an.stint_degradation(ses, model), 4)}


@tool
def simulate_race_strategy(year: int, event: str, max_stops: int = 2) -> dict:
    """Rank dry-tyre pit strategies for a race by predicted total time using
    the fitted degradation model and measured pit loss, and show what the
    winner actually did. Ignores traffic, safety cars and track evolution."""
    ses = _session(year, event, "R")
    return {**_header(ses), **an.simulate_strategies(ses, max_stops=max_stops)}


@tool
def compare_drivers(year: int, event: str, driver_a: str, driver_b: str, session: str = "Q",
                    lap_a: int | None = None, lap_b: int | None = None) -> dict:
    """Head-to-head telemetry comparison of two laps (each driver's fastest
    unless lap numbers are given): lap summaries, minimum speed and time
    gained at every corner, and time gained in each of 25 slices of the lap.
    Positive gain_a values mean driver A was faster there. Corner-level
    numbers are indicative (about +/-0.05 s)."""
    ses = _session(year, event, session)
    c = an.compare_laps(ses, driver_a, driver_b, lap_a, lap_b)
    ms = c["mini_sectors"]
    return {
        **_header(ses), "driver_a": c["summary_a"], "driver_b": c["summary_b"],
        "lap_time_gap_s": c["lap_delta_s"],
        "note": "lap_time_gap_s is B minus A; positive means A was faster",
        "corners": an.to_records(c["corners"]),
        "mini_sectors": [
            {"n": int(r.MiniSector), "from_m": round(r.Start), "to_m": round(r.End),
             "gain_a_s": round(float(r.Gain_A), 3), "faster": r.Faster}
            for r in ms.itertuples()
        ],
    }


@tool
def get_lap_telemetry(year: int, event: str, driver: str, session: str = "Q",
                      lap: int | None = None, points: int = 120) -> dict:
    """Telemetry trace of one lap (fastest if no lap number), resampled to
    `points` evenly spaced distances: speed, throttle, brake, gear, RPM, DRS."""
    ses = _session(year, event, session)
    tel = an.lap_telemetry(ses, driver, lap)
    points = int(np.clip(points, 10, 600))
    grid = np.linspace(tel["Distance"].min(), tel["Distance"].max(), points)
    rs = an.resample_distance(tel, grid)
    return {
        **_header(ses), "driver": tel.attrs["driver"], "lap": tel.attrs["lap_number"],
        "lap_time_s": _r(tel.attrs["lap_time"]), "compound": tel.attrs["compound"],
        "samples": [
            {"distance_m": round(float(r.Distance)), "time_s": _r(r.Time, 2), "speed_kmh": round(float(r.Speed)),
             "throttle_pct": round(float(r.Throttle)), "brake": bool(r.Brake > 0), "gear": int(r.nGear),
             "rpm": round(float(r.RPM)), "drs": None if pd.isna(r.DRS) else bool(r.DRS)}
            for r in rs.itertuples()
        ],
    }


@tool
def list_hud_profiles() -> dict:
    """HUD layout profiles available for video-to-telemetry extraction."""
    from .video import layout

    return {"profiles": [{"name": n, "description": layout.load_profile(n).get("description", "")}
                         for n in layout.list_profiles()]}


@tool
def render_onboard_video(year: int, event: str, driver: str, session: str = "Q", lap: int | None = None,
                         profile: str = "cluster", max_seconds: float | None = None) -> dict:
    """Render a lap from its real telemetry as a view from the car around the
    real circuit (true corners and elevation; width, kerbs and scenery are
    stylised) with an instrument cluster showing speed, gear, throttle, brake
    and revs. Useful as test footage with known ground truth for
    video_to_telemetry. Returns the file path."""
    from .video import render, scene

    ses = _session(year, event, session)
    tel = an.lap_telemetry(ses, driver, lap)
    name = f"{ses.year}-r{ses.round:02d}-{ses.code}-{tel.attrs['driver']}-lap{tel.attrs['lap_number']}-{profile}.mp4"
    caption = f"{tel.attrs['driver']}  {ses.event_name} {ses.year}  {ses.name}  lap {tel.attrs['lap_number']}"
    info = render.render_onboard(tel, VIDEO_DIR / name, profile, max_seconds=max_seconds, caption=caption,
                                 scene=scene.for_lap(ses, tel))
    return {**_header(ses), "driver": tel.attrs["driver"], "lap": tel.attrs["lap_number"], **info}


@tool
def video_to_telemetry(video_path: str, profile: str = "cluster", start_s: float = 0.0,
                       end_s: float | None = None, reference_year: int | None = None,
                       reference_event: str | None = None, reference_session: str = "Q",
                       reference_driver: str | None = None, reference_lap: int | None = None) -> dict:
    """Read telemetry (speed, gear, throttle, brake, RPM, DRS) out of an
    onboard video by analysing its HUD graphics, and save it as CSV. `profile`
    names the HUD layout (see list_hud_profiles); footage with a different
    HUD needs its own calibrated profile. If a reference lap is given the
    result is time-aligned to the official telemetry and its accuracy reported.
    Check speed_read_rate_pct: a low value means the profile does not fit."""
    from . import video

    path = Path(video_path)
    if not path.is_absolute():
        path = VIDEO_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")
    tel = video.extract_telemetry(path, profile, start_s, end_s)
    csv = TELEMETRY_DIR / f"{path.stem}.csv"
    tel.to_csv(csv, index=False, float_format="%.3f")
    out = {
        "video": str(path), "profile": tel.attrs["profile"], "csv": str(csv),
        "frames_read": tel.attrs["frames_read"], "fps": _r(tel.attrs["fps"], 2),
        "duration_s": _r(tel["Time"].max(), 2),
        "speed_read_rate_pct": _r(tel.attrs["speed_read_rate"] * 100, 1),
        "summary": {
            "top_speed_kmh": _r(tel["Speed"].max(), 0), "min_speed_kmh": _r(tel["Speed"].min(), 0),
            "avg_speed_kmh": _r(tel["Speed"].mean(), 1), "distance_m": _r(tel["Distance"].iloc[-1], 0),
            "full_throttle_pct": _r((tel["Throttle"] >= 98).mean() * 100, 1) if "Throttle" in tel else None,
            "braking_pct": _r((tel["Brake"] > 50).mean() * 100, 1) if "Brake" in tel else None,
            "peak_braking_g": _r(-tel["LongG"].min(), 2),
        },
    }
    if reference_year and reference_event and reference_driver:
        ses = _session(reference_year, reference_event, reference_session)
        ref = an.lap_telemetry(ses, reference_driver, reference_lap)
        out["reference"] = {**_header(ses), "driver": ref.attrs["driver"], "lap": ref.attrs["lap_number"]}
        out["accuracy_vs_reference"] = video.accuracy(tel, ref)
    return out


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

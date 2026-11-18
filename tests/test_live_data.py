"""Tests against the live timing API. Run with:  pytest -m network"""

import pytest

from f1ai import analysis as an
from f1ai import data

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def race():
    return data.load_session(2025, "Abu Dhabi", "R")


def test_session_loads(race):
    assert race.event_name == "Abu Dhabi Grand Prix"
    assert race.total_laps == 58
    assert len(race.results) == 20
    assert race.results.iloc[0]["Driver"] == "VER"


def test_pace_model_on_real_race(race):
    m = an.fit_pace_model(race)
    assert -0.15 <= m.fuel_effect <= 0
    assert {"MEDIUM", "HARD"} <= set(m.degradation)


def test_comparison_matches_official_gap():
    q = data.load_session(2025, "Abu Dhabi", "Q")
    c = an.compare_laps(q, "VER", "NOR")
    assert c["frame"]["Delta"].iloc[-1] == pytest.approx(c["lap_delta_s"], abs=0.01)
    assert c["aligned_by"] == "gps"
    assert len(c["corners"]) >= 10


def test_track_geometry_is_a_closed_lap(race):
    import numpy as np

    from f1ai import track

    lap = an.lap_telemetry(race, "VER")
    trk = track.build_track(race, lap)
    x, y = trk["x"], trk["y"]
    gaps = np.hypot(np.diff(np.append(x, x[0])), np.diff(np.append(y, y[0])))
    assert gaps.max() < trk["step"] * 1.5                     # evenly sampled and closed
    assert trk["length"] == pytest.approx(5281, rel=0.03)     # Yas Marina lap distance
    assert len(trk["corners"]) == 16
    assert [c["s"] for c in trk["corners"]] == sorted(c["s"] for c in trk["corners"])

    on = track.lap_on_track(trk, lap, (20.0, 40.0))
    assert len(on["speed"]) == len(x)
    assert (np.diff(on["time"]) >= 0).all()
    assert on["time"][-1] == pytest.approx(on["lap_time"], abs=0.3)
    assert 0 < on["sectors"][0] < on["sectors"][1] < trk["length"]


def test_website_payloads(race):
    from f1ai import sitedata

    p = sitedata.race_payload(race)
    n = len(p["track"]["x"])
    assert len(p["track"]["z"]) == n and len(p["lap"]["speed"]) == n
    assert p["event"]["laps"] == 58 and p["results"][0]["code"] == "VER"
    assert len(p["story"]["series"]) == 20 and len(p["story"]["series"][0]["pos"]) == 58
    assert p["story"]["series"][0]["gap"][-1] == 0            # the winner leads at the flag
    assert p["strategy"]["available"] and p["strategy"]["options"][0]["gap_to_best_s"] == 0
    assert {s["compound"] for row in p["stints"] for s in row["stints"]} >= {"MEDIUM", "HARD"}

    d = sitedata.duel_payload(data.load_session(2025, "Abu Dhabi", "Q"))
    assert d["delta"][-1] == pytest.approx(d["gap"], abs=0.002)   # pinned to the official gap
    assert len(d["a"]["line_x"]) == len(d["track"]["x"]) and len(d["minis"]) == 25
    assert sum(m["gain_a"] for m in d["minis"]) == pytest.approx(d["gap"] - d["delta"][0], abs=0.01)

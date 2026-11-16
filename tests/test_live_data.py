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

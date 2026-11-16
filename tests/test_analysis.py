"""Offline tests: a made-up race with known parameters that the analysis must recover."""

import numpy as np
import pandas as pd
import pytest

from f1ai import analysis as an
from f1ai.data import Session

FUEL = -0.05
DEG = {"MEDIUM": 0.09, "HARD": 0.04}
OFFSET = {"MEDIUM": -0.5, "HARD": 0.0}
PIT_LOSS = 21.0
TOTAL = 56


def make_race(seed: int = 0) -> Session:
    rng = np.random.default_rng(seed)
    names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    base = {n: 90.0 + 0.15 * i for i, n in enumerate(names)}
    plans = [(["MEDIUM", "HARD"], [20]), (["HARD", "MEDIUM"], [34]), (["MEDIUM", "HARD"], [24]),
             (["MEDIUM", "HARD", "MEDIUM"], [15, 40]), (["HARD", "MEDIUM"], [30]), (["MEDIUM", "HARD"], [18])]
    rows = []
    t0 = pd.Timestamp("2025-06-01T13:00:00Z")
    for num, (name, (comps, stops)) in enumerate(zip(names, plans), start=1):
        clock, stint, age = t0, 1, 0
        for lap in range(1, TOTAL + 1):
            comp = comps[stint - 1]
            age += 1
            t = base[name] + OFFSET[comp] + DEG[comp] * age + FUEL * lap + rng.normal(0, 0.12)
            pit_in, pit_out = lap in stops, (lap - 1) in stops
            if lap == 1:
                t += 6.0
            if pit_in:
                t += PIT_LOSS * 0.55
            if pit_out:
                t += PIT_LOSS * 0.45
            rows.append({"DriverNumber": num, "Driver": name, "Team": f"Team {(num + 1) // 2}", "LapNumber": lap,
                         "LapTime": t, "Sector1": t * 0.3, "Sector2": t * 0.4, "Sector3": t * 0.3, "SpeedTrap": 320.0,
                         "PitOut": pit_out, "PitIn": pit_in, "LapStart": clock, "Compound": comp, "Stint": stint,
                         "TyreLife": age, "FreshTyre": True, "TrackStatus": "GREEN", "Position": num,
                         "IsAccurate": lap > 1 and not pit_out})
            clock += pd.Timedelta(seconds=t)
            if pit_in:
                stint, age = stint + 1, 0
    laps = pd.DataFrame(rows)
    drivers = pd.DataFrame({"DriverNumber": range(1, 7), "Driver": names, "FullName": names,
                            "Team": [f"Team {(i + 1) // 2}" for i in range(1, 7)], "TeamColor": ["#888888"] * 6})
    results = pd.DataFrame({"Pos": range(1, 7), "Driver": names, "Name": names, "Team": drivers["Team"],
                            "Grid": range(1, 7), "Laps": TOTAL, "Status": "Finished", "Gap_s": 0.0, "Points": 0,
                            "BestLap_s": laps.groupby("Driver")["LapTime"].min().reindex(names).values})
    return Session(year=2025, round=1, event_name="Test Grand Prix", name="Race", code="R", session_key=1,
                   meeting_key=1, circuit_key=None, circuit="Nowhere", country="Nowhere", date_start=t0,
                   date_end=t0 + pd.Timedelta(hours=2), drivers=drivers, laps=laps, results=results,
                   weather=pd.DataFrame(), race_control=pd.DataFrame(), total_laps=TOTAL)


@pytest.fixture(scope="module")
def race() -> Session:
    return make_race()


def test_clean_laps_drop_pit_and_first_lap(race):
    clean = an.clean_laps(an.laps_frame(race))
    assert not clean["PitIn"].any() and not clean["PitOut"].any()
    assert (clean["LapNumber"] > 1).all()


def test_pace_model_recovers_known_parameters(race):
    m = an.fit_pace_model(race)
    assert m.fuel_fitted
    assert m.fuel_effect == pytest.approx(FUEL, abs=0.01)
    assert m.degradation["MEDIUM"] == pytest.approx(DEG["MEDIUM"], abs=0.015)
    assert m.degradation["HARD"] == pytest.approx(DEG["HARD"], abs=0.015)
    assert m.compound_offset["MEDIUM"] - m.compound_offset["HARD"] == pytest.approx(-0.5, abs=0.2)
    assert m.r2 > 0.9
    assert min(m.driver_base, key=m.driver_base.get) == "AAA"


def test_pit_loss_is_measured(race):
    loss = an.pit_loss(race)
    assert loss["measured"]
    assert loss["seconds"] == pytest.approx(PIT_LOSS, abs=0.6)


def test_race_pace_orders_drivers(race):
    pace = an.race_pace(race)
    assert pace.iloc[0]["GapToBest"] == 0
    assert set(pace["Driver"]) == set(race.drivers["Driver"])


def test_stints_match_plans(race):
    st = an.stints(race)
    ddd = st[st["Driver"] == "DDD"]
    assert ddd["Compound"].tolist() == ["MEDIUM", "HARD", "MEDIUM"]
    assert ddd["Laps"].tolist() == [15, 25, 16]


def test_strategy_simulation_is_consistent(race):
    sim = an.simulate_strategies(race)
    best = sim["strategies"][0]
    assert best["gap_to_best_s"] == 0
    assert sum(best["stint_laps"]) == TOTAL
    assert len(set(best["compounds"])) >= 2
    gaps = [s["gap_to_best_s"] for s in sim["strategies"]]
    assert gaps == sorted(gaps)


def test_projection_onto_path():
    s = np.linspace(0, 1000, 201)
    x, y = s.copy(), np.zeros_like(s)
    out = an._project_onto_path(np.array([102.0, 498.0]), np.array([3.0, -2.0]), x, y, s)
    assert out == pytest.approx([102.0, 498.0], abs=1e-6)


def test_format_laptime():
    assert an.format_laptime(87.47) == "1:27.470"
    assert an.format_laptime(float("nan")) == "-"

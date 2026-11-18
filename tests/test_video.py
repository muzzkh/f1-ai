"""Round trip: telemetry -> rendered video -> telemetry read back from the pixels."""

import pytest

from f1ai import video
from f1ai.synth import synthetic_lap
from f1ai.video import layout


@pytest.fixture(scope="module")
def lap():
    return synthetic_lap(seed=4)


@pytest.mark.parametrize("profile", ["cluster", "demo-halo", "demo-bars"])
def test_round_trip_accuracy(tmp_path, lap, profile):
    info = video.render_onboard(lap, tmp_path / f"{profile}.mp4", profile, max_seconds=14, size=(960, 540))
    assert info["frames"] == 350
    tel = video.extract_telemetry(info["path"], profile)
    acc = video.accuracy(tel, lap)
    assert tel.attrs["speed_read_rate"] > 0.98
    assert abs(acc["offset_s"]) < 0.1
    assert acc["speed_mae_kmh"] < 1.0
    assert acc["gear_accuracy_pct"] > 97
    assert acc["brake_agreement_pct"] > 97
    assert acc["throttle_mae_pct"] < 4
    assert acc["rpm_mae"] < 400


def test_clip_is_located_inside_the_lap(tmp_path, lap):
    """A clip from the middle of a lap must be placed at the right moment of it."""
    part = lap[lap["Time"] >= 20.0].reset_index(drop=True)
    part.attrs.update(lap.attrs)
    info = video.render_onboard(part, tmp_path / "mid.mp4", "demo-bars", max_seconds=12, size=(640, 360))
    tel = video.extract_telemetry(info["path"], "demo-bars")
    assert video.estimate_offset(tel, lap) == pytest.approx(-part["Time"].iloc[0], abs=0.15)


def test_wrong_profile_is_flagged(tmp_path, lap):
    """Reading with a profile that does not fit must show up as a low read rate, not as numbers."""
    info = video.render_onboard(lap, tmp_path / "halo.mp4", "demo-halo", max_seconds=4, size=(640, 360))
    tel = video.extract_telemetry(info["path"], "demo-bars")
    assert tel.attrs["speed_read_rate"] < 0.2


def test_layout_validation():
    good = layout.load_profile("demo-halo")
    assert set(good["elements"]) == set(layout.CHANNELS)
    with pytest.raises(layout.LayoutError):
        layout.validate({"elements": {"gear": {"kind": "digits", "roi": [0, 0, 0.1, 0.1]}}})
    with pytest.raises(layout.LayoutError):
        layout.validate({"elements": {"speed": {"kind": "digits", "roi": [0.5, 0, 0.1, 0.1]}}})
    with pytest.raises(layout.LayoutError):
        layout.load_profile("no-such-profile")

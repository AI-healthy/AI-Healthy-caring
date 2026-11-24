from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from shiyi_api.health_contract import ObservationInput
from shiyi_api.health_state import estimate

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
ZONE = ZoneInfo("UTC")
STREAM = {
    "source": "gadgetbridge", "data_origin": "test.app", "device_scope": "a" * 32,
    "metrics": ["steps", "sleep_minutes", "heart_rate_bpm", "resting_heart_rate_bpm"],
}


def observation(metric, value, end, start=None, scope=None):
    return ObservationInput(
        client_sample_id=f"{metric}-{end.isoformat()}-{value}",
        source="gadgetbridge", data_origin="test.app", device_scope=scope or STREAM["device_scope"],
        metric=metric, value=value, observed_at=end, interval_start=start, is_demo=False,
    )


def features(rows):
    result = estimate(STREAM, "UTC", ZONE, NOW, rows)
    return result, {f.feature: f for f in result.features}


def test_cold_start_and_missing():
    result, f = features([])
    assert result.events == []
    assert result.pressure_status == "insufficient_evidence"
    assert all(x.direction == "insufficient" for x in f.values())
    assert all(p.value is None for x in f.values() for p in x.recent)


def test_robust_baseline_sustained_change_and_no_leakage():
    rows = []
    for i in range(1, 18):
        day = (NOW - timedelta(days=i)).replace(hour=0)
        value = 300 if i <= 3 else (900 if i == 12 else 480)
        start = day - timedelta(hours=2)
        rows.append(observation("sleep_minutes", value, start + timedelta(minutes=value), start))
        rows.append(observation("resting_heart_rate_bpm", 80 if i <= 3 else 60, day + timedelta(hours=8)))
    # Different device, current day and future samples must not alter the windows.
    rows.append(observation("resting_heart_rate_bpm", 200, NOW, scope="b" * 32))
    rows.append(observation("resting_heart_rate_bpm", 200, NOW + timedelta(hours=1)))
    result, f = features(rows)
    assert f["recorded_sleep_minutes"].baseline_median == 480
    assert f["resting_hr_bpm"].baseline_median == 60
    assert f["resting_hr_bpm"].baseline_days == 14
    assert f["resting_hr_bpm"].direction == "higher"
    assert {e.code for e in result.events} == {"recorded_sleep_lower", "resting_hr_higher"}
    assert result.events[0].evidence == "limited"
    assert result.pressure_status == "insufficient_evidence"


def test_missing_recent_day_blocks_event_and_steps_need_coverage():
    rows = []
    for i in range(1, 18):
        day = (NOW - timedelta(days=i)).replace(hour=0)
        if i != 2:
            rows.append(observation("resting_heart_rate_bpm", 85 if i <= 3 else 60,
                                    day + timedelta(hours=8)))
        rows.append(observation("steps", 100, day + timedelta(minutes=1), day))
    result, f = features(rows)
    assert result.events == []
    assert f["resting_hr_bpm"].direction == "insufficient"
    assert f["recorded_steps"].recent[-1].value == 100
    assert not f["recorded_steps"].recent[-1].eligible


def test_low_step_hr_needs_context_and_excludes_movement():
    rows = []
    day = (NOW - timedelta(days=1)).replace(hour=0)
    start = day + timedelta(hours=6)
    for i in range(20):
        a = start + timedelta(minutes=i)
        rows.append(observation("steps", 0, a + timedelta(minutes=1), a))
    for i in range(10, 15):
        rows.append(observation("heart_rate_bpm", 70, start + timedelta(minutes=i)))
    rows.append(observation("heart_rate_bpm", 170, day + timedelta(hours=9)))
    _, f = features(rows)
    low = f["low_step_hr_bpm"].recent[-1]
    assert low.value == 70 and low.observations == 5 and low.eligible
    assert f["resting_hr_bpm"].recent[-1].value is None
    rows.append(observation("steps", 100, start + timedelta(minutes=9), start + timedelta(minutes=8)))
    _, f = features(rows)
    assert f["low_step_hr_bpm"].recent[-1].value is None


def test_fusion_counts_cardiac_once_and_prefers_resting():
    from shiyi_api.health_state import fuse
    from shiyi_api.health_state_contract import FeatureState, StateEvent

    def f(name, direction):
        return FeatureState(feature=name, baseline_days=14, baseline_median=60,
                            baseline_mad=0, recent=[], deviation_z=2, trend_per_day=0,
                            direction=direction, evidence="adequate_for_rule")

    def e(name, code):
        return StateEvent(feature=name, code=code, days=[], baseline_median=60,
                          recent_values=[80, 80, 80], evidence="adequate_for_rule")

    low = e("low_step_hr_bpm", "low_step_hr_higher")
    resting = e("resting_hr_bpm", "resting_hr_higher")
    sleep = e("recorded_sleep_minutes", "recorded_sleep_lower")
    features = [f("resting_hr_bpm", "higher"), f("low_step_hr_bpm", "higher"),
                f("recorded_sleep_minutes", "lower")]
    result = fuse(features, [low, resting, sleep])
    assert result.pattern == "multi_domain_change"
    assert result.domains == ["cardiac", "sleep"]
    assert "low_step_hr_higher" not in result.supporting_events
    assert fuse(features, [low, resting]).pattern == "single_domain_change"
    assert fuse([f("resting_hr_bpm", "within_reference")], [low]).domains == []

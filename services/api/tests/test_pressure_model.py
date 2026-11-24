from datetime import UTC, datetime, timedelta

from shiyi_api.pressure_contract import PressureCheckin, PressurePair
from shiyi_api.pressure_model import evaluate

NOW = datetime(2026, 11, 24, 23, tzinfo=UTC)


def pair(day, slot, label, hr, context="studying"):
    t = NOW - timedelta(days=day, hours=12-slot*2)
    c = PressureCheckin(
        checkin_id=f"{day}-{slot}", client_checkin_id=f"{day}-{slot}",
        source="gadgetbridge", data_origin="test.app", device_scope="a"*32,
        observed_at=t, recorded_at=t, perceived_stress=label, context=context,
    )
    return PressurePair(
        checkin=c, window_start=t-timedelta(minutes=30), window_end=t,
        heart_rate_median=hr+1, heart_rate_samples=20, low_step_hr_median=hr,
        low_step_hr_samples=15, recorded_steps=0, step_coverage_minutes=30,
        eligible_for_research=True, reasons=[],
    )


def synthetic():
    return [
        pair(day, slot, 2+2*((day+slot)%4), 60+8*((day+slot)%4))
        for day in range(12, 0, -1) for slot in range(3)
    ]


def test_cold_start():
    result = evaluate([pair(1, 0, 4, 72)], NOW)
    assert result.status == "insufficient_data"
    assert result.metrics == []
    assert not result.deployable


def test_synthetic_signal_outperforms_baselines():
    result = evaluate(synthetic(), NOW)
    assert result.status == "evaluated_research_only"
    scores = {m.model: m.mae for m in result.metrics}
    assert scores["physiology_context_ridge"] < scores["personal_median"]
    assert scores["physiology_context_ridge"] < scores["context_ridge"]
    assert result.train_days == 8 and result.test_days == 4
    assert result.physiology_improvement_mae > 0
    assert not result.deployable


def test_overlap_and_missing_are_filtered():
    rows = synthetic()
    p = rows[0]
    t = p.checkin.observed_at + timedelta(minutes=15)
    duplicate = p.model_copy(update={
        "checkin": p.checkin.model_copy(update={"checkin_id": "nearby", "observed_at": t}),
        "window_end": t, "window_start": t-timedelta(minutes=30),
    })
    missing = rows[1].model_copy(update={"eligible_for_research": False})
    result = evaluate(rows+[duplicate, missing], NOW)
    assert result.eligible_pairs == len(rows)+1
    assert result.independent_pairs == len(rows)


def test_train_normalization_and_weights_do_not_use_test_labels():
    from shiyi_api.pressure_model import _features, _fit, _normalizer

    rows = synthetic()
    result = evaluate(rows, NOW)
    train = [p for p in rows if p.checkin.observed_at < result.split_at]
    norm = _normalizer(train)
    weights = _fit([_features(p, norm) for p in train],
                   [p.checkin.perceived_stress for p in train])
    changed = [
        p.model_copy(update={"checkin": p.checkin.model_copy(update={"perceived_stress": 10})})
        if p.checkin.observed_at >= result.split_at else p for p in rows
    ]
    second = evaluate(changed, NOW)
    train2 = [p for p in changed if p.checkin.observed_at < second.split_at]
    norm2 = _normalizer(train2)
    assert norm2 == norm
    assert _fit([_features(p, norm2) for p in train2],
                [p.checkin.perceived_stress for p in train2]) == weights
    assert second.split_at == result.split_at
    assert second.metrics != result.metrics

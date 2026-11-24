"""Small-sample within-person evaluation. No data persistence, external model or runtime score."""
from datetime import UTC, timedelta
from math import isfinite, log1p, sqrt
from statistics import median

from .pressure_model_contract import EvaluationMetrics, PressureEvaluation

MIN_TRAIN = 14
MIN_TEST = 6
MIN_TRAIN_DAYS = 7
MIN_TEST_DAYS = 3
# Each pair can depend on up to 40 minutes of observations.
EMBARGO = timedelta(minutes=40)
RIDGE = 1.0


def _raw(pair):
    # Low-step HR plus difference from overall HR captures background vs mixed activity.
    return (
        float(pair.low_step_hr_median),
        float(pair.heart_rate_median - pair.low_step_hr_median),
        log1p(pair.recorded_steps),
    )


def _normalizer(train):
    values = [_raw(p) for p in train]
    floors = (3.0, 3.0, 0.5)
    centers = [median(col) for col in zip(*values)]
    scales = [
        max(floor, 1.4826 * median(abs(v - center) for v in col))
        for col, center, floor in zip(zip(*values), centers, floors)
    ]
    return centers, scales


def _features(pair, normalizer=None):
    context = pair.checkin.context
    # Resting reference category, fixed one-hot design; no fitting from test labels.
    result = [float(context == "studying"), float(context == "working")]
    if normalizer is not None:
        centers, scales = normalizer
        result.extend(
            max(-5.0, min(5.0, (v - center) / scale))
            for v, center, scale in zip(_raw(pair), centers, scales)
        )
    return result


def _fit(x, y):
    """Ridge coordinate descent on centered training features, intercept unpenalized."""
    n = len(y)
    means = [sum(col) / n for col in zip(*x)]
    target = sum(y) / n
    matrix = [[v - m for v, m in zip(row, means)] for row in x]
    residual = [v - target for v in y]
    beta = [0.0] * len(means)
    columns = list(zip(*matrix))
    for _ in range(250):
        max_change = 0.0
        for j, col in enumerate(columns):
            old = beta[j]
            new = sum(v * (r + old * v) for v, r in zip(col, residual)) / (
                sum(v * v for v in col) + RIDGE
            )
            change = new - old
            if change:
                residual = [r - change * v for r, v in zip(residual, col)]
            beta[j] = new
            max_change = max(max_change, abs(change))
        if max_change < 1e-8:
            break
    return target - sum(b * m for b, m in zip(beta, means)), beta


def _predict(params, x):
    intercept, beta = params
    return max(0.0, min(10.0, intercept + sum(b * v for b, v in zip(beta, x))))


def _metrics(name, y, predictions):
    errors = [p - t for p, t in zip(predictions, y)]
    return EvaluationMetrics(
        model=name, mae=round(sum(abs(e) for e in errors) / len(errors), 4),
        rmse=round(sqrt(sum(e * e for e in errors) / len(errors)), 4),
        mean_error=round(sum(errors) / len(errors), 4),
    )


def _day(pair):
    return pair.checkin.observed_at.astimezone(UTC).date()


def _eligible(pair, now):
    if not pair.eligible_for_research or pair.checkin.observed_at > now:
        return False
    vals = (pair.low_step_hr_median, pair.heart_rate_median, pair.recorded_steps)
    return all(v is not None and isfinite(v) and v >= 0 for v in vals) and (
        pair.checkin.context in {"resting", "studying", "working"}
    )


def evaluate(pairs, now, total_checkins=None):
    """Fixed chronological UTC-day split and embargo, no test-driven hyperparameter tuning."""
    eligible = sorted(
        (p for p in pairs if _eligible(p, now)),
        key=lambda p: (p.checkin.observed_at, p.checkin.checkin_id),
    )
    # This pure evaluator accepts only one stream. The service also enforces one account.
    scopes = {(p.checkin.source, p.checkin.data_origin, p.checkin.device_scope) for p in eligible}
    if len(scopes) > 1:
        raise ValueError("Evaluation requires a single wearable stream")
    independent = []
    for p in eligible:
        if not independent or p.checkin.observed_at - independent[-1].checkin.observed_at >= EMBARGO:
            independent.append(p)
    days = sorted({_day(p) for p in independent})
    split_day = days[int(len(days) * 0.7)] if len(days) >= 2 else None
    test = [p for p in independent if split_day is not None and _day(p) >= split_day]
    split_at = test[0].checkin.observed_at if test else None
    train = [
        p for p in independent
        if split_day is not None and _day(p) < split_day
        and p.checkin.observed_at <= split_at - EMBARGO
    ]
    train_days = len({_day(p) for p in train})
    test_days = len({_day(p) for p in test})
    reasons = []
    if len(train) < MIN_TRAIN:
        reasons.append("too_few_training_pairs")
    if len(test) < MIN_TEST:
        reasons.append("too_few_test_pairs")
    if train_days < MIN_TRAIN_DAYS:
        reasons.append("too_few_training_days")
    if test_days < MIN_TEST_DAYS:
        reasons.append("too_few_test_days")
    if len({p.checkin.perceived_stress for p in train}) < 3:
        reasons.append("limited_training_label_variation")
    if test and not {p.checkin.context for p in test} <= {p.checkin.context for p in train}:
        reasons.append("unseen_test_context")
    result = {
        "as_of": now, "total_checkins": len(pairs) if total_checkins is None else total_checkins,
        "eligible_pairs": len(eligible), "independent_pairs": len(independent),
        "train_count": len(train), "test_count": len(test), "train_days": train_days,
        "test_days": test_days, "split_at": split_at, "reasons": reasons,
    }
    if reasons:
        return PressureEvaluation(status="insufficient_data", metrics=[], **result)
    train_y = [p.checkin.perceived_stress for p in train]
    test_y = [p.checkin.perceived_stress for p in test]
    norm = _normalizer(train)
    metrics = [_metrics("personal_median", test_y, [median(train_y)] * len(test))]
    for name, n in (("context_ridge", None), ("physiology_context_ridge", norm)):
        params = _fit([_features(p, n) for p in train], train_y)
        metrics.append(_metrics(name, test_y, [_predict(params, _features(p, n)) for p in test]))
    return PressureEvaluation(
        status="evaluated_research_only", metrics=metrics,
        physiology_improvement_mae=round(metrics[1].mae - metrics[2].mae, 4), **result,
    )

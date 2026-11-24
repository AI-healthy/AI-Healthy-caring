"""Pure feature extraction and robust baseline rules for a single authorized stream."""
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime, time, timedelta
from statistics import median

from .health_state_contract import DayFeature, FeatureState, FusedState, HealthStateView, StateEvent
from .health_summary import _sleep, _steps

BASELINE_DAYS = 14
RECENT_DAYS = 3
MIN_BASELINE_DAYS = 7
MIN_STEP_COVERAGE = 12 * 60  # Recorded intervals, not proof of wearing the device.
MIN_LOW_STEP_POINTS = 5
FEATURES = {
    "recorded_sleep_minutes": (30.0, "lower", "recorded_sleep_lower"),
    "recorded_steps": (500.0, "lower", "recorded_steps_lower"),
    "resting_hr_bpm": (3.0, "higher", "resting_hr_higher"),
    "low_step_hr_bpm": (3.0, "higher", "low_step_hr_higher"),
}


def _at(day, hour, zone):
    return datetime.combine(day, time(hour), zone).astimezone(UTC)


def _merge(intervals):
    merged = []
    for a, b in sorted(set(intervals)):
        if a >= b:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _intervals(rows, start, end):
    return [
        r for r in rows if r.value is not None and r.interval_start is not None
        and r.observed_at > start and r.interval_start < end
    ]


def _day_feature(day, value, count, coverage=None, reasons=()):
    if value is None and not reasons:
        reasons = ("no_valid_observations",)
    return DayFeature(
        day=day, value=value, observations=count, coverage_minutes=coverage,
        eligible=value is not None and not reasons, reasons=list(reasons),
    )


def _low_step_hr(hr, steps, start, end):
    """HR only after 10 consecutive recorded zero-step minutes, in 06:00–10:00.
    This is not a resting measurement; static exercise and other confounders remain.
    """
    zeros = _merge(
        (r.interval_start, r.observed_at) for r in steps if r.value == 0
    )
    positive = _merge(
        (r.interval_start, r.observed_at) for r in steps if r.value > 0
    )
    zero_starts = [a for a, _ in zeros]
    positive_starts = [a for a, _ in positive]
    points = {}
    for r in hr:
        if r.value is None or not start <= r.observed_at < end:
            continue
        t = r.observed_at
        a = t - timedelta(minutes=10)
        i = bisect_right(zero_starts, a) - 1
        if i < 0 or zeros[i][1] < t:
            continue
        j = bisect_left(positive_starts, t) - 1
        if j >= 0 and positive[j][1] > a and positive[j][0] < t:
            continue
        points.setdefault(t, set()).add(r.value)
    # Conflicting measurements at one instant are not counted.
    return [next(iter(values)) for values in points.values() if len(values) == 1]


def extract_day(day, zone, groups):
    start = _at(day, 0, zone)
    end = _at(day + timedelta(days=1), 0, zone)
    sleep_start = _at(day - timedelta(days=1), 18, zone)
    sleep_end = _at(day, 12, zone)
    steps = _intervals(groups.get("steps", []), start, end)
    sleep = _intervals(groups.get("sleep_minutes", []), sleep_start, sleep_end)
    step_issues = []
    step_value = _steps(steps, start, end, step_issues)
    intervals = _merge(
        (max(start, r.interval_start), min(end, r.observed_at)) for r in steps
    )
    coverage = int(sum((b - a).total_seconds() for a, b in intervals) // 60)
    if coverage < MIN_STEP_COVERAGE:
        step_issues.append("limited_recorded_coverage")
    sleep_issues = []
    sleep_value = _sleep(sleep, sleep_start, sleep_end, sleep_issues)
    # Sleep logs alone cannot establish complete overnight wear. Treat this as
    # recorded duration only, never as confirmed sleep deprivation.
    resting = {}
    for r in groups.get("resting_heart_rate_bpm", []):
        if r.value is not None and start <= r.observed_at < end:
            resting.setdefault(r.observed_at, set()).add(r.value)
    resting_values = [next(iter(v)) for v in resting.values() if len(v) == 1]
    morning_start, morning_end = _at(day, 6, zone), _at(day, 10, zone)
    low_steps = _intervals(steps, morning_start - timedelta(minutes=10), morning_end)
    low_hr = _low_step_hr(groups.get("heart_rate_bpm", []), low_steps, morning_start, morning_end)
    return {
        "recorded_sleep_minutes": _day_feature(
            day, sleep_value, len(sleep), reasons=sleep_issues
        ),
        "recorded_steps": _day_feature(day, step_value, len(steps), coverage, step_issues),
        "resting_hr_bpm": _day_feature(
            day, median(resting_values) if resting_values else None, len(resting_values)
        ),
        "low_step_hr_bpm": _day_feature(
            day, median(low_hr) if low_hr else None, len(low_hr),
            reasons=() if len(low_hr) >= MIN_LOW_STEP_POINTS else ("too_few_contextual_hr_points",),
        ),
    }


def _slope(points):
    slopes = [
        (b.value - a.value) / (b.day - a.day).days
        for i, a in enumerate(points) for b in points[i + 1:]
    ]
    return round(median(slopes), 3) if slopes else None


def _feature(name, days):
    floor, expected, code = FEATURES[name]
    historical = [p for p in days[:-RECENT_DAYS] if p.eligible]
    recent = days[-RECENT_DAYS:]
    usable = [p for p in recent if p.eligible]
    center = median([p.value for p in historical]) if historical else None
    mad = median([abs(p.value - center) for p in historical]) if historical else None
    ready = len(historical) >= MIN_BASELINE_DAYS and len(usable) == RECENT_DAYS
    evidence = "insufficient"
    direction = "insufficient"
    z = None
    event = None
    if ready:
        scale = max(1.4826 * mad, floor)
        scores = [(p.value - center) / scale for p in usable]
        z = round(median(scores), 3)
        # Heuristic thresholds, not a calibrated probability or clinical cutoff.
        direction = "lower" if z <= -2 else "higher" if z >= 2 else "within_reference"
        evidence = (
            "limited" if name in {"recorded_sleep_minutes", "low_step_hr_bpm"}
            else "adequate_for_rule"
        )
        sustained = all(v <= -2 for v in scores) if expected == "lower" else all(
            v >= 2 for v in scores
        )
        if sustained:
            event = StateEvent(
                code=code, feature=name, days=[p.day for p in usable],
                baseline_median=center, recent_values=[p.value for p in usable],
                evidence=evidence,
            )
    return FeatureState(
        feature=name, baseline_days=len(historical), baseline_median=center,
        baseline_mad=mad, recent=recent, deviation_z=z,
        trend_per_day=_slope(usable), direction=direction, evidence=evidence,
    ), event


def fuse(features, events):
    """Combine distinct domains, not correlated measurements of the same signal."""
    domains = {
        "recorded_sleep_minutes": "sleep", "recorded_steps": "activity",
        "resting_hr_bpm": "cardiac", "low_step_hr_bpm": "cardiac",
    }
    assessed = sorted({domains[f.feature] for f in features if f.direction != "insufficient"})
    # Prefer explicit resting measurements when they have sufficient evidence.
    resting_ready = any(
        f.feature == "resting_hr_bpm" and f.direction != "insufficient" for f in features
    )
    chosen = [e for e in events if not (resting_ready and e.feature == "low_step_hr_bpm")]
    active = sorted({domains[e.feature] for e in chosen})
    if not assessed:
        pattern = "insufficient"
    elif len(active) >= 2:
        pattern = "multi_domain_change"
    elif active:
        pattern = "single_domain_change"
    else:
        pattern = "no_sustained_pattern"
    evidence = "insufficient" if not assessed else "limited"
    if len(assessed) >= 2 and chosen and all(e.evidence == "adequate_for_rule" for e in chosen):
        evidence = "adequate_for_rule"
    return FusedState(
        pattern=pattern, domains=active, supporting_events=[e.code for e in chosen],
        assessed_domains=assessed, evidence=evidence,
    )


def estimate(stream, timezone, zone, now, observations):
    """Exclude today and the recent window from the baseline; no future samples."""
    recent_end = now.astimezone(zone).date() - timedelta(days=1)
    recent_start = recent_end - timedelta(days=RECENT_DAYS - 1)
    baseline_start = recent_start - timedelta(days=BASELINE_DAYS)
    groups = {}
    valid = [r for r in observations if not r.is_demo and r.observed_at <= now
             and r.source == stream["source"] and r.data_origin == stream["data_origin"]
             and r.device_scope == stream["device_scope"] and r.metric in stream["metrics"]]
    for r in valid:
        groups.setdefault(r.metric, []).append(r)
    all_days = [
        extract_day(baseline_start + timedelta(days=i), zone, groups)
        for i in range(BASELINE_DAYS + RECENT_DAYS)
    ]
    features = []
    events = []
    for name in FEATURES:
        state, event = _feature(name, [day[name] for day in all_days])
        features.append(state)
        if event is not None:
            events.append(event)
    return HealthStateView(
        stream=stream, timezone=timezone, as_of=now,
        last_observed_at=max((r.observed_at for r in valid if r.value is not None), default=None),
        baseline_start=baseline_start, baseline_end=recent_start - timedelta(days=1),
        recent_start=recent_start, recent_end=recent_end, features=features, events=events, fusion=fuse(features, events),
        pressure_reasons=["no_validated_stress_model", "no_rr_intervals_or_hrv",
                          "no_validated_self_report_model"],
    )

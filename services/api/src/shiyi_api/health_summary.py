"""Consent-gated stream summaries; no mixing of devices or inferred measurements."""
import json
from contextlib import closing
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import health_storage, storage
from .health_contract import REAL_POLICY, ObservationInput
from .storage import StoreError

# Explicit source, origin, and scope are required to avoid summing different wearables.
_AUTHORIZED = """
    FROM health_observations o
    JOIN health_consents c ON c.user_id=o.user_id AND c.source=o.source
        AND c.metric=o.metric AND c.granted=1 AND c.policy_version=?
    WHERE o.user_id=? AND o.source IN ('gadgetbridge','health_connect')
        AND json_extract(o.payload_json,'$.is_demo')=0
        AND json_extract(o.payload_json,'$.device_scope') IS NOT NULL
"""


def _enabled(user):
    if not user.startswith("usr_") or not health_storage.real_ingestion_enabled():
        raise StoreError(403, "Wearable context requires enabled real health and a registered user")


def streams(store, user):
    _enabled(user)
    with closing(store.connect()) as db:
        rows = db.execute(
            """SELECT DISTINCT o.source,o.metric,
               json_extract(o.payload_json,'$.data_origin') AS origin,
               json_extract(o.payload_json,'$.device_scope') AS scope """
            + _AUTHORIZED + " ORDER BY o.source,origin,scope,o.metric",
            (REAL_POLICY, user),
        )
        groups = {}
        for row in rows:
            key = (row["source"], row["origin"], row["scope"])
            groups.setdefault(key, []).append(row["metric"])
    return [
        {"source": source, "data_origin": origin, "device_scope": scope, "metrics": metrics}
        for (source, origin, scope), metrics in groups.items()
    ]


def _steps(rows, start, end, issues):
    intervals = sorted({
        (r.interval_start, r.observed_at, r.value)
        for r in rows if r.value is not None and r.interval_start is not None
        and r.observed_at > start and r.interval_start < end
    })
    total = None
    covered = None
    for a, b, value in intervals:
        if a < start or b > end:
            if "steps_cross_boundary" not in issues:
                issues.append("steps_cross_boundary")
            continue
        if covered is not None and a < covered:
            issues.append("steps_overlap")
            return None
        total = (total or 0) + value
        covered = b
    return total


def _sleep(rows, start, end, issues):
    intervals = sorted({
        (r.interval_start, r.observed_at, r.value)
        for r in rows if r.value is not None and r.interval_start is not None
        and r.observed_at > start and r.interval_start < end
    })
    full = []
    partial = []
    for a, b, value in intervals:
        if value == int((b - a).total_seconds() // 60):
            full.append((max(a, start), min(b, end)))
        elif a >= start and b <= end:
            # The source reports a duration inside a larger window, not exact sleep segments.
            partial.append((a, b, value))
        else:
            issues.append("sleep_partial_boundary")
            return None
    for i, (a, b, _) in enumerate(partial):
        if any(a < d and c < b for c, d in full) or any(
            a < d and c < b for c, d, _ in partial[:i]
        ):
            issues.append("sleep_ambiguous_overlap")
            return None
    merged = []
    for a, b in sorted(full):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    if not merged and not partial:
        return None
    return int(sum((b - a).total_seconds() for a, b in merged) // 60) + sum(
        value for _, _, value in partial
    )


def _latest(rows, start, end):
    return max(
        (r for r in rows if r.value is not None and start <= r.observed_at <= end),
        key=lambda r: (r.observed_at, r.client_sample_id), default=None,
    )


def summarize(db, user, source, origin, scope, timezone, day, now):
    """Read within caller's transaction; reusable by a future opt-in Harness tool."""
    _enabled(user)
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise StoreError(422, "Unknown IANA time zone") from None
    local_day = day or now.astimezone(zone).date()
    if local_day > now.astimezone(zone).date():
        raise StoreError(422, "Cannot summarize future dates")
    start = datetime.combine(local_day, time.min, zone).astimezone(UTC)
    end = min(now, datetime.combine(local_day + timedelta(days=1), time.min, zone).astimezone(UTC))
    sleep_start = datetime.combine(
        local_day - timedelta(days=1), time(18), zone
    ).astimezone(UTC)
    sleep_end = min(now, datetime.combine(local_day, time(12), zone).astimezone(UTC))
    # At most 24-hour intervals. Read the window plus any records ending after its boundary.
    rows = db.execute(
        """SELECT o.payload_json """ + _AUTHORIZED + """
        AND o.source=? AND json_extract(o.payload_json,'$.data_origin')=?
        AND json_extract(o.payload_json,'$.device_scope')=?
        AND o.observed_at>=? AND o.observed_at<=?
        ORDER BY o.observed_at,o.observation_id LIMIT 30001""",
        (REAL_POLICY, user, source, origin, scope, storage.stamp(sleep_start),
         storage.stamp(min(now, end + timedelta(days=1)))),
    ).fetchall()
    if len(rows) > 30000:
        raise StoreError(422, "Too many samples in the summary window")
    groups = {}
    for row in rows:
        item = ObservationInput.model_validate_json(row["payload_json"])
        groups.setdefault(item.metric, []).append(item)
    # Do not expose a fabricated stream for a scope owned by another account.
    known = db.execute(
        "SELECT DISTINCT o.metric " + _AUTHORIZED + """
        AND o.source=? AND json_extract(o.payload_json,'$.data_origin')=?
        AND json_extract(o.payload_json,'$.device_scope')=? ORDER BY o.metric""",
        (REAL_POLICY, user, source, origin, scope),
    ).fetchall()
    if not known:
        raise StoreError(404, "Authorized wearable stream not found")
    issues = []
    steps = _steps(groups.get("steps", []), start, end, issues)
    sleep = _sleep(groups.get("sleep_minutes", []), sleep_start, sleep_end, issues)
    hr = _latest(groups.get("heart_rate_bpm", []), start, end)
    resting = _latest(groups.get("resting_heart_rate_bpm", []), start, end)
    return {
        "stream": {"source": source, "data_origin": origin, "device_scope": scope,
                   "metrics": [row["metric"] for row in known]},
        "date": local_day, "timezone": timezone, "as_of": now, "steps": steps,
        "sleep_minutes": sleep, "heart_rate_bpm": hr.value if hr else None,
        "heart_rate_at": hr.observed_at if hr else None,
        "resting_heart_rate_bpm": resting.value if resting else None,
        "resting_heart_rate_at": resting.observed_at if resting else None,
        "sample_counts": {metric: len(items) for metric, items in groups.items()},
        "issues": sorted(set(issues)),
    }


def daily(store, user, source, origin, scope, timezone, day: date | None):
    with store.transaction() as db:
        return summarize(db, user, source, origin, scope, timezone, day, storage.now_utc())

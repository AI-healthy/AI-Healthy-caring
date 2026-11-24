"""User-owned subjective pressure labels, joined on demand with authorized observations."""
import json
from contextlib import closing
from datetime import UTC, timedelta
from statistics import median
from uuid import uuid4

from . import storage
from .health_contract import REAL_POLICY, ObservationInput
from .health_state import _intervals, _low_step_hr, _merge
from .health_summary import _AUTHORIZED, _enabled, _steps
from .pressure_contract import PressureCheckin, PressurePair
from .storage import StoreError

SCHEMA = """
CREATE TABLE IF NOT EXISTS pressure_consent (
    user_id TEXT PRIMARY KEY,
    granted INTEGER NOT NULL CHECK(granted IN (0,1)),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pressure_checkins (
    checkin_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    client_checkin_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(user_id, client_checkin_id)
);
CREATE INDEX IF NOT EXISTS pressure_user_history
    ON pressure_checkins(user_id, recorded_at DESC, checkin_id);
"""


def consent(store, user, payload):
    if payload.granted:
        _enabled(user)
    elif not user.startswith("usr_"):
        raise StoreError(403, "Registered account required")
    with store.transaction() as db:
        db.execute(
            """INSERT INTO pressure_consent VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET granted=excluded.granted,
               updated_at=excluded.updated_at""",
            (user, int(payload.granted), storage.stamp(storage.now_utc())),
        )
    return payload


def get_consent(store, user):
    with closing(store.connect()) as db:
        row = db.execute("SELECT granted FROM pressure_consent WHERE user_id=?", (user,)).fetchone()
    return {"granted": bool(row and row["granted"]), "policy_version": "pressure-checkin-v1"}


def _check(db, user):
    _enabled(user)
    row = db.execute("SELECT granted FROM pressure_consent WHERE user_id=?", (user,)).fetchone()
    if not row or not row["granted"]:
        raise StoreError(403, "Explicit pressure check-in consent required")


def _view(row):
    return PressureCheckin(**json.loads(row["payload_json"]), checkin_id=row["checkin_id"],
                           recorded_at=row["recorded_at"])


def _stream_args(user, item):
    return (REAL_POLICY, user, item.source, item.data_origin, item.device_scope)


_STREAM = """
    AND o.source=? AND json_extract(o.payload_json,'$.data_origin')=?
    AND json_extract(o.payload_json,'$.device_scope')=?
"""


def create(store, user, payload):
    now = storage.now_utc()
    item = payload.model_copy(update={"observed_at": payload.observed_at.astimezone(UTC)})
    encoded = item.model_dump_json()
    with store.transaction() as db:
        _check(db, user)
        prior = db.execute(
            "SELECT * FROM pressure_checkins WHERE user_id=? AND client_checkin_id=?",
            (user, item.client_checkin_id),
        ).fetchone()
        if prior:
            if prior["payload_json"] != encoded:
                raise StoreError(409, "Check-in identifier reused with different content")
            return _view(prior)
        if not now - timedelta(hours=24) <= item.observed_at <= now:
            raise StoreError(422, "Check-in must describe a moment within the past 24 hours")
        known = db.execute(
            "SELECT 1 " + _AUTHORIZED + _STREAM + " LIMIT 1", _stream_args(user, item),
        ).fetchone()
        if not known:
            raise StoreError(404, "Authorized wearable stream not found")
        key = str(uuid4())
        db.execute("INSERT INTO pressure_checkins VALUES (?,?,?,?,?)",
                   (key, user, item.client_checkin_id, encoded, storage.stamp(now)))
        return PressureCheckin(**item.model_dump(), checkin_id=key, recorded_at=now)


def history(store, user, limit, offset):
    # Users can audit and delete their own labels even after consent withdrawal.
    with closing(store.connect()) as db:
        rows = db.execute(
            """SELECT * FROM pressure_checkins WHERE user_id=?
               ORDER BY recorded_at DESC,checkin_id LIMIT ? OFFSET ?""",
            (user, limit, offset),
        ).fetchall()
    return [_view(r) for r in rows]


def delete(store, user, key):
    with store.transaction() as db:
        result = db.execute("DELETE FROM pressure_checkins WHERE user_id=? AND checkin_id=?",
                            (user, key))
        if result.rowcount != 1:
            raise StoreError(404, "Check-in not found")


def extract_pair(item, rows):
    end = item.observed_at
    start = end - timedelta(minutes=30)
    valid = [
        r for r in rows if not r.is_demo and r.value is not None and r.observed_at <= end
        and r.source == item.source and r.data_origin == item.data_origin
        and r.device_scope == item.device_scope
    ]
    points = {}
    for r in valid:
        if r.metric == "heart_rate_bpm" and start <= r.observed_at:
            points.setdefault(r.observed_at, set()).add(r.value)
    hr = [next(iter(values)) for values in points.values() if len(values) == 1]
    steps = [r for r in valid if r.metric == "steps" and r.interval_start is not None]
    window_steps = _intervals(steps, start, end)
    issues = []
    total = _steps(window_steps, start, end, issues)
    coverage = sum((b - a).total_seconds() for a, b in _merge(
        (max(start, r.interval_start), min(end, r.observed_at)) for r in window_steps
    )) // 60
    low = _low_step_hr(
        [r for r in valid if r.metric == "heart_rate_bpm"],
        _intervals(steps, start - timedelta(minutes=10), end), start, end,
    )
    if len(hr) < 5:
        issues.append("too_few_hr_points")
    if len(low) < 5:
        issues.append("too_few_low_step_hr_points")
    if coverage < 25:
        issues.append("limited_step_coverage")
    if item.context not in {"resting", "studying", "working"}:
        issues.append("context_not_comparable")
    return PressurePair(
        checkin=item, window_start=start, window_end=end,
        heart_rate_median=median(hr) if hr else None, heart_rate_samples=len(hr),
        low_step_hr_median=median(low) if len(low) >= 5 else None, low_step_hr_samples=len(low),
        recorded_steps=total, step_coverage_minutes=int(coverage),
        eligible_for_research=not issues, reasons=sorted(set(issues)),
    )


def pair(store, user, key):
    with closing(store.connect()) as db:
        db.execute("BEGIN")
        _check(db, user)
        row = db.execute("SELECT * FROM pressure_checkins WHERE user_id=? AND checkin_id=?",
                         (user, key)).fetchone()
        if not row:
            raise StoreError(404, "Check-in not found")
        item = _view(row)
        known = db.execute(
            "SELECT 1 " + _AUTHORIZED + _STREAM + " LIMIT 1", _stream_args(user, item),
        ).fetchone()
        if not known:
            raise StoreError(404, "Authorized wearable stream not found")
        rows = db.execute(
            "SELECT o.payload_json " + _AUTHORIZED + _STREAM + """
            AND o.metric IN ('steps','heart_rate_bpm')
            AND o.observed_at>=? AND o.observed_at<=? LIMIT 10001""",
            (*_stream_args(user, item), storage.stamp(item.observed_at - timedelta(minutes=40)),
             storage.stamp(item.observed_at)),
        ).fetchall()
    if len(rows) > 10000:
        raise StoreError(422, "Too many samples in check-in window")
    return extract_pair(item, [ObservationInput.model_validate_json(r["payload_json"]) for r in rows])

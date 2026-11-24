"""Read a bounded authorized stream snapshot and evaluate without writing health state."""
from contextlib import closing
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import storage
from .health_contract import REAL_POLICY, ObservationInput
from .health_state import BASELINE_DAYS, RECENT_DAYS, estimate
from .health_summary import _AUTHORIZED, _enabled
from .storage import StoreError

MAX_RECORDS = 100000


def current(store, user, source, origin, scope, timezone):
    _enabled(user)
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise StoreError(422, "Unknown IANA time zone") from None
    now = storage.now_utc()
    first_day = now.astimezone(zone).date() - timedelta(days=BASELINE_DAYS + RECENT_DAYS + 1)
    start = datetime.combine(first_day, time(18), zone).astimezone(UTC)
    criteria = """
        AND o.source=? AND json_extract(o.payload_json,'$.data_origin')=?
        AND json_extract(o.payload_json,'$.device_scope')=?
    """
    args = (REAL_POLICY, user, source, origin, scope)
    # Read-only snapshot, no long write lock. Consent and observations are read together.
    with closing(store.connect()) as db:
        db.execute("BEGIN")
        known = db.execute(
            "SELECT DISTINCT o.metric " + _AUTHORIZED + criteria + " ORDER BY o.metric", args
        ).fetchall()
        if not known:
            raise StoreError(404, "Authorized wearable stream not found")
        rows = db.execute(
            "SELECT o.payload_json " + _AUTHORIZED + criteria
            + " AND o.observed_at>=? AND o.observed_at<=? ORDER BY o.observed_at LIMIT ?",
            (*args, storage.stamp(start), storage.stamp(now), MAX_RECORDS + 1),
        ).fetchall()
    if len(rows) > MAX_RECORDS:
        raise StoreError(422, "Too many observations for state estimation")
    stream = {"source": source, "data_origin": origin, "device_scope": scope,
              "metrics": [row["metric"] for row in known]}
    observations = [ObservationInput.model_validate_json(row["payload_json"]) for row in rows]
    return estimate(stream, timezone, zone, now, observations)

"""Local durable scheduler and pull-only, explicitly synthetic invitation inbox."""
from contextlib import closing
from datetime import timedelta
from uuid import uuid4

from .. import storage
from ..storage import StoreError
from . import repository
from .contracts import RunRequest
from .proactive_contracts import DeviceOffer, OfferView, ScheduleRequest, ScheduleView

SCHEMA = """
CREATE TABLE IF NOT EXISTS proactive_schedules (
    user_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    available_until TEXT,
    next_check_at TEXT,
    last_reason TEXT
);
CREATE INDEX IF NOT EXISTS proactive_due ON proactive_schedules(next_check_at,user_id);
CREATE TABLE IF NOT EXISTS proactive_offers (
    offer_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES harness_runs(run_id),
    channel TEXT NOT NULL CHECK(channel IN ('app','simulator')),
    device_id TEXT,
    acknowledged_at TEXT
);
CREATE INDEX IF NOT EXISTS proactive_inbox ON proactive_offers(user_id,channel,device_id);
"""
CHECK_INTERVAL = timedelta(minutes=15)


def _schedule(db, user):
    row = db.execute("SELECT * FROM proactive_schedules WHERE user_id=?", (user,)).fetchone()
    if row is None:
        return ScheduleView(enabled=False)
    data = ScheduleRequest.model_validate_json(row["payload_json"])
    return ScheduleView(**data.model_dump(), available_until=row["available_until"],
                        next_check_at=row["next_check_at"], last_reason=row["last_reason"])


def get_schedule(store, user):
    with closing(store.connect()) as db:
        return _schedule(db, user)


def _bound(db, user, device_id):
    return device_id is not None and db.execute(
        """SELECT 1 FROM registered_simulators
           WHERE user_id=? AND device_id=? AND revoked_at IS NULL""", (user, device_id)
    ).fetchone() is not None


def _invalidate_offers(db, user):
    db.execute(
        """UPDATE harness_runs SET status='INVALIDATED'
           WHERE user_id=? AND status='AWAITING_CONFIRMATION'
           AND run_id IN (SELECT run_id FROM proactive_offers WHERE user_id=?)""", (user, user)
    )


def put_schedule(store, user, payload):
    with store.transaction() as db:
        now = storage.now_utc()
        settings, _ = repository._settings(db, user)
        if payload.enabled and not settings.proactive_enabled:
            raise StoreError(409, "Enable proactive companionship in harness settings first")
        if payload.enabled and payload.channel == "simulator" and not _bound(
            db, user, payload.device_id
        ):
            raise StoreError(404, "Registered simulator not found")
        # Renewing a lease is an explicit new availability statement; never auto-renew.
        until = storage.stamp(now + timedelta(minutes=payload.available_for_minutes))
        db.execute(
            """INSERT INTO proactive_schedules VALUES (?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET payload_json=excluded.payload_json,
               available_until=excluded.available_until,next_check_at=excluded.next_check_at,
               last_reason=excluded.last_reason""",
            (user, payload.model_dump_json(), until if payload.enabled else None,
             storage.stamp(now) if payload.enabled else None,
             "ready" if payload.enabled else "schedule_disabled"),
        )
        _invalidate_offers(db, user)
        return _schedule(db, user)


def _lease_reason(db, user, schedule, now):
    if not schedule.enabled:
        return "schedule_disabled"
    if schedule.available_until is None or schedule.available_until <= now:
        return "availability_expired"
    settings, _ = repository._settings(db, user)
    if not settings.proactive_enabled:
        return "proactive_disabled"
    if schedule.channel == "simulator" and not _bound(db, user, schedule.device_id):
        return "device_unavailable"
    return None


def _tick_user(store, user):
    with store.transaction() as db:
        now = storage.now_utc()
        schedule = _schedule(db, user)
        if schedule.next_check_at is None or schedule.next_check_at > now:
            return None
        reason = _lease_reason(db, user, schedule, now)
        if reason:
            _invalidate_offers(db, user)
            db.execute(
                "UPDATE proactive_schedules SET next_check_at=NULL,last_reason=? WHERE user_id=?",
                (reason, user),
            )
            return reason
        # No network/model calls in a scheduler transaction. Always use bounded local rules.
        request = RunRequest(client_request_id="schedule:" + uuid4().hex,
                             trigger="scheduled_check", available_minutes=schedule.available_minutes)
        snapshot = repository._snapshot(db, user, request, now)
        data = repository._decide(snapshot, None)
        reason = data["reason"]
        next_at = min(now + CHECK_INTERVAL, schedule.available_until)
        db.execute(
            "UPDATE proactive_schedules SET next_check_at=?,last_reason=? WHERE user_id=?",
            (storage.stamp(next_at), reason, user),
        )
        if not data["options"]:
            return reason
        run = repository.persist_plan(
            db, user, request, data, now, deadline=schedule.available_until
        )
        db.execute(
            """INSERT INTO proactive_offers
               (offer_id,user_id,run_id,channel,device_id,acknowledged_at)
               VALUES (?,?,?,?,?,NULL)""",
            (str(uuid4()), user, run.run_id, schedule.channel, schedule.device_id),
        )
        return "offer_created"


def tick(store, limit=50):
    """One bounded scan; write each user's schedule and invitation atomically."""
    if not 1 <= limit <= 100:
        raise ValueError("Invalid scheduler scan limit")
    with closing(store.connect()) as db:
        users = db.execute(
            """SELECT user_id FROM proactive_schedules WHERE next_check_at<=?
               ORDER BY next_check_at,user_id LIMIT ?""",
            (storage.stamp(storage.now_utc()), limit),
        ).fetchall()
    outcomes = {}
    for row in users:
        reason = _tick_user(store, row["user_id"])
        if reason is not None:
            outcomes[reason] = outcomes.get(reason, 0) + 1
    return outcomes


def _delivery_allowed(db, user, schedule, now):
    reason = _lease_reason(db, user, schedule, now)
    if reason:
        return False
    settings, _ = repository._settings(db, user)
    if repository.is_quiet(settings, now):
        return False
    return db.execute(
        """SELECT 1 FROM activity_sessions WHERE user_id=?
           AND status IN ('CREATED','RUNNING') AND expires_at>? LIMIT 1""",
        (user, storage.stamp(now)),
    ).fetchone() is None


def offer_confirmable(db, user, run_id, now):
    # Legacy manual runs are unaffected; new scheduled offers are rechecked at acceptance.
    if not db.execute(
        "SELECT 1 FROM proactive_offers WHERE user_id=? AND run_id=?", (user, run_id)
    ).fetchone():
        return True
    return _delivery_allowed(db, user, _schedule(db, user), now)


def _current_offer(db, user, now):
    db.execute(
        """UPDATE harness_runs SET status='EXPIRED' WHERE user_id=?
           AND status='AWAITING_CONFIRMATION' AND expires_at<=?
           AND run_id IN (SELECT run_id FROM proactive_offers WHERE user_id=?)""",
        (user, storage.stamp(now), user),
    )
    if not _delivery_allowed(db, user, _schedule(db, user), now):
        _invalidate_offers(db, user)
        return None
    return db.execute(
        """SELECT o.* FROM proactive_offers o JOIN harness_runs r ON r.run_id=o.run_id
           WHERE o.user_id=? AND r.user_id=? AND r.status='AWAITING_CONFIRMATION'
           ORDER BY r.created_at DESC,o.offer_id DESC LIMIT 1""", (user, user),
    ).fetchone()


def pending_offer(store, user):
    with store.transaction() as db:
        now = storage.now_utc()
        row = _current_offer(db, user, now)
        if row is None:
            return None
        return OfferView(offer_id=row["offer_id"], channel=row["channel"],
                         device_id=row["device_id"], acknowledged_at=row["acknowledged_at"],
                         run=repository._view(repository._row(db, user, row["run_id"], now)))


def pending_device_offer(store, user, device_id):
    with store.transaction() as db:
        if not _bound(db, user, device_id):
            raise StoreError(404, "Registered simulator not found")
        now = storage.now_utc()
        row = _current_offer(db, user, now)
        if (row is None or row["channel"] != "simulator" or row["device_id"] != device_id
                or row["acknowledged_at"] is not None):
            return None
        run = repository._row(db, user, row["run_id"], now)
        return DeviceOffer(offer_id=row["offer_id"], expires_at=run["expires_at"])


def acknowledge(store, user, offer_id, device_id=None):
    error = None
    result = None
    with store.transaction() as db:
        if device_id is not None and not _bound(db, user, device_id):
            raise StoreError(404, "Registered simulator not found")
        row = db.execute(
            "SELECT * FROM proactive_offers WHERE user_id=? AND offer_id=?", (user, offer_id)
        ).fetchone()
        if row is None or (
            device_id is None and row["channel"] != "app"
        ) or (
            device_id is not None and (row["channel"] != "simulator" or row["device_id"] != device_id)
        ):
            raise StoreError(404, "Offer not found")
        if row["acknowledged_at"] is not None:
            return {"offer_id": offer_id, "acknowledged_at": row["acknowledged_at"]}
        now = storage.now_utc()
        active = _current_offer(db, user, now)
        if active is None or active["offer_id"] != offer_id:
            error = StoreError(409, "Offer no longer deliverable")
        else:
            when = storage.stamp(now)
            db.execute("UPDATE proactive_offers SET acknowledged_at=? WHERE offer_id=?",
                       (when, offer_id))
            result = {"offer_id": offer_id, "acknowledged_at": when}
    if error:
        raise error
    return result

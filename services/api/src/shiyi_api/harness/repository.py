"""Transactional harness runtime. All operations are user-scoped and local-only."""
import hashlib
import json
from contextlib import closing
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from .. import storage
from ..recommendation import catalog_entries, get_activity
from ..storage import StoreError
from .contracts import RunView, Settings, Trace
from .engine import DecisionContext, RuleRanker, choose
from .memory import SCHEMA as MEMORY_SCHEMA
from .memory import advance_epoch, recall
from .model_adapter import LocalModelRanker

SCHEMA = """
CREATE TABLE IF NOT EXISTS harness_settings (
    user_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    memory_since TEXT
);
CREATE TABLE IF NOT EXISTS harness_context_versions (
    user_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS harness_runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    selected_activity_id TEXT,
    session_id TEXT,
    UNIQUE(user_id,client_request_id),
    FOREIGN KEY(user_id,session_id) REFERENCES activity_sessions(user_id,session_id)
);
CREATE INDEX IF NOT EXISTS harness_proactive
    ON harness_runs(user_id,trigger,created_at);
""" + MEMORY_SCHEMA


def _settings(db, user):
    row = db.execute("SELECT * FROM harness_settings WHERE user_id=?", (user,)).fetchone()
    if row is None:
        return Settings(), None
    return Settings.model_validate_json(row["payload_json"]), row["memory_since"]


def get_settings(store, user):
    with closing(store.connect()) as db:
        return _settings(db, user)[0]


def invalidate_pending(db, user):
    # Revision also invalidates inference whose plan is not yet persisted.
    db.execute(
        """INSERT INTO harness_context_versions VALUES (?,1)
           ON CONFLICT(user_id) DO UPDATE SET revision=revision+1""", (user,)
    )
    db.execute(
        """UPDATE harness_runs SET status='INVALIDATED'
           WHERE user_id=? AND status='AWAITING_CONFIRMATION'""", (user,)
    )


def put_settings(store, user, payload):
    if any(get_activity(aid) is None for aid in payload.blocked_activity_ids):
        raise StoreError(422, "Unknown blocked activity")
    with store.transaction() as db:
        previous, since = _settings(db, user)
        if previous == payload:
            return previous
        now = storage.now_utc()
        if not payload.use_feedback_memory:
            since = None
        elif not previous.use_feedback_memory:
            since = storage.stamp(now)
        if (payload.use_feedback_memory != previous.use_feedback_memory
                or payload.use_behavior_memory != previous.use_behavior_memory):
            advance_epoch(db, user, now,
                          feedback=payload.use_feedback_memory != previous.use_feedback_memory,
                          behavior=payload.use_behavior_memory != previous.use_behavior_memory)
        db.execute(
            """INSERT INTO harness_settings VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
               payload_json=excluded.payload_json,memory_since=excluded.memory_since""",
            (user, payload.model_dump_json(), since),
        )
        invalidate_pending(db, user)
    return payload


def get_memory(store, user, available_minutes=None):
    with store.transaction() as db:
        settings, since = _settings(db, user)
        candidates = None if available_minutes is None else tuple(
            entry for entry in catalog_entries() if entry[2] <= available_minutes
        )
        return recall(db, user, settings, since, storage.now_utc(), candidates)


def reset_memory(store, user):
    """Exclude all existing evidence; preserve business records and invalidate pending plans."""
    with store.transaction() as db:
        settings, _ = _settings(db, user)
        now = storage.now_utc()
        advance_epoch(db, user, now, feedback=True, behavior=True)
        since = storage.stamp(now) if settings.use_feedback_memory else None
        db.execute(
            """INSERT INTO harness_settings VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET memory_since=excluded.memory_since""",
            (user, settings.model_dump_json(), since),
        )
        invalidate_pending(db, user)
        return recall(db, user, settings, since, now)


def _energy(db, user, settings, payload, now):
    if payload.energy_level is not None:
        return payload.energy_level, "explicit_self_report"
    if not settings.use_observations:
        return None, "observation_use_disabled"
    # Latest fresh consented self-report only. Do not infer affect from heart rate.
    row = db.execute(
        """SELECT o.payload_json FROM health_observations o
           JOIN health_consents c ON c.user_id=o.user_id AND c.source=o.source
             AND c.metric=o.metric AND c.granted=1
           WHERE o.user_id=? AND o.metric='energy_level' AND o.source='self_report'
             AND o.observed_at>=? AND o.observed_at<=?
           ORDER BY o.observed_at DESC,o.observation_id DESC LIMIT 1""",
        (user, storage.stamp(now - timedelta(hours=6)), storage.stamp(now)),
    ).fetchone()
    if row is None:
        return None, "no_fresh_authorized_observation"
    item = json.loads(row["payload_json"])
    if item.get("is_demo") is True and type(item.get("value")) is int:
        return item["value"], "authorized_synthetic_self_report"
    return None, "missing_observation"


def is_quiet(settings, now):
    local = now.astimezone(ZoneInfo(settings.timezone)).time()
    start, end = settings.quiet_start, settings.quiet_end
    return start == end or (
        start < end and start <= local < end
    ) or (
        start > end and (local >= start or local < end)
    )


def _proactive_reason(db, user, settings, now):
    if not settings.proactive_enabled:
        return "proactive_disabled"
    if is_quiet(settings, now):
        return "quiet_hours"
    times = db.execute(
        """SELECT created_at FROM harness_runs WHERE user_id=? AND trigger='scheduled_check'
           AND json_extract(plan_json,'$.reason')='awaiting_user_choice'
           AND created_at>=? ORDER BY created_at DESC LIMIT 2""",
        (user, storage.stamp(now - timedelta(hours=24))),
    ).fetchall()
    if len(times) >= 2:
        return "daily_offer_limit"
    if times and times[0]["created_at"] > storage.stamp(now - timedelta(hours=4)):
        return "cooldown"
    if db.execute(
        """SELECT 1 FROM activity_sessions WHERE user_id=? AND status IN ('CREATED','RUNNING')
           AND expires_at>? LIMIT 1""",
        (user, storage.stamp(now)),
    ).fetchone():
        return "active_activity"
    if db.execute(
        """SELECT 1 FROM harness_runs WHERE user_id=? AND status='AWAITING_CONFIRMATION'
           AND expires_at>? LIMIT 1""",
        (user, storage.stamp(now)),
    ).fetchone():
        return "pending_plan"
    return None


def _view(row):
    data = json.loads(row["plan_json"])
    return RunView(**data, run_id=row["run_id"], trigger=row["trigger"],
                   status=row["status"], created_at=row["created_at"],
                   expires_at=row["expires_at"], selected_activity_id=row["selected_activity_id"],
                   session_id=row["session_id"])


def _row(db, user, run_id, now):
    db.execute(
        """UPDATE harness_runs SET status='EXPIRED'
           WHERE user_id=? AND run_id=? AND status='AWAITING_CONFIRMATION' AND expires_at<=?""",
        (user, run_id, storage.stamp(now)),
    )
    row = db.execute("SELECT * FROM harness_runs WHERE user_id=? AND run_id=?",
                     (user, run_id)).fetchone()
    if row is None:
        raise StoreError(404, "Harness run not found")
    return row


def _trace(stage, result):
    return Trace(stage=stage, result=result)


def _existing_run(db, user, payload, digest, now):
    existing = db.execute(
        "SELECT * FROM harness_runs WHERE user_id=? AND client_request_id=?",
        (user, payload.client_request_id),
    ).fetchone()
    if existing:
        if existing["request_digest"] != digest:
            raise StoreError(409, "Harness request ID reused with different input")
        return _view(_row(db, user, existing["run_id"], now))
    return None


def _snapshot(db, user, payload, now):
    settings, since = _settings(db, user)
    revision = db.execute("SELECT revision FROM harness_context_versions WHERE user_id=?",
                          (user,)).fetchone()
    trace = [_trace("intent", payload.trigger)]
    reason = None
    if payload.availability != "ready":
        reason = "user_unavailable"
    elif payload.trigger == "scheduled_check":
        reason = _proactive_reason(db, user, settings, now)
    context = None
    entries = ()
    if not reason:
        energy, source = _energy(db, user, settings, payload, now)
        trace.append(_trace("perception", source))
        trace.append(_trace("memory", "enabled" if settings.use_feedback_memory else "disabled"))
        excluded = set(settings.blocked_activity_ids) | set(payload.skip_activity_ids)
        entries = tuple(e for e in catalog_entries()
                        if e[0] not in excluded and e[2] <= payload.available_minutes)
        trace.append(_trace("candidates", str(len(entries))))
        if not entries:
            reason = "no_eligible_activity"
        else:
            memory = recall(db, user, settings, since, now, entries)
            trace.append(_trace("retrieval", f"feedback:{memory.recalled_events};behavior:{memory.behavior_events}"))
            context = DecisionContext(
                available_minutes=payload.available_minutes, energy_level=energy,
                preference_tags=frozenset(settings.preference_tags),
                memory_scores=tuple((m.activity_id, m.decision_score) for m in memory.entries),
            )
    return (settings, since, revision["revision"] if revision else 0,
            reason, trace, entries, context)


def _decide(snapshot, ranker):
    settings, _since, _revision, reason, trace, entries, context = snapshot
    trace = list(trace)
    options = []
    algorithm = "none"
    if reason:
        trace.append(_trace("gate", reason))
    else:
        if isinstance(ranker, LocalModelRanker) and not settings.use_local_model:
            trace.append(_trace("model", "opt_in_disabled"))
            ranker = None
        options, fallback = choose(context, entries, ranker if ranker is not None else RuleRanker())
        if fallback:
            algorithm = "rules_v1_fallback"
        elif isinstance(ranker, LocalModelRanker):
            algorithm = "local_llm_v1"
        else:
            algorithm = "rules_v1" if ranker is None else "adapter_v1"
        trace.append(_trace("decision", algorithm))
        trace.append(_trace("gate", "user_confirmation_required"))
        reason = "awaiting_user_choice"
    return {
        "algorithm": algorithm, "options": [x.model_dump() for x in options],
        "trace": [x.model_dump() for x in trace], "reason": reason,
    }


def create_run(store, user, payload, ranker=None):
    digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    # Phase 1: short, consistent snapshot. Never run a strategy under the write lock.
    with store.transaction() as db:
        now = storage.now_utc()
        existing = _existing_run(db, user, payload, digest, now)
        if existing:
            return existing
        snapshot = _snapshot(db, user, payload, now)

    # Phase 2: untrusted proposal outside the transaction, or local rules.
    data = _decide(snapshot, ranker)

    # Phase 3: re-check the latest context and idempotency before committing.
    with store.transaction() as db:
        now = storage.now_utc()
        existing = _existing_run(db, user, payload, digest, now)
        if existing:
            return existing
        latest = _snapshot(db, user, payload, now)
        if latest != snapshot:
            # Replan deterministically using fresh server data; never call a model here.
            data = _decide(latest, None)
            data["trace"].append({"stage": "revalidation", "result": "context_changed_replanned"})
        return _persist_plan(db, user, payload, data, now, digest=digest)


def _persist_plan(db, user, payload, data, now, *, digest=None, deadline=None):
    status = "AWAITING_CONFIRMATION" if data["options"] else "NO_ACTION"
    run_id = str(uuid4())
    expires_at = now + timedelta(minutes=10)
    if deadline is not None:
        expires_at = min(expires_at, deadline)
    if digest is None:
        digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    db.execute(
        """INSERT INTO harness_runs
           (run_id,user_id,client_request_id,request_digest,trigger,status,plan_json,
            created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (run_id, user, payload.client_request_id, digest, payload.trigger,
         status, json.dumps(data, ensure_ascii=False),
         storage.stamp(now), storage.stamp(expires_at)),
    )
    return _view(_row(db, user, run_id, now))


def persist_plan(db, user, payload, data, now, *, deadline=None):
    """Internal local scheduler entry point; caller owns the transaction."""
    return _persist_plan(db, user, payload, data, now, deadline=deadline)


def get_run(store, user, run_id):
    with store.transaction() as db:
        return _view(_row(db, user, run_id, storage.now_utc()))


def dismiss(store, user, run_id):
    error = None
    with store.transaction() as db:
        row = _row(db, user, run_id, storage.now_utc())
        if row["status"] == "AWAITING_CONFIRMATION":
            db.execute("UPDATE harness_runs SET status='DISMISSED' WHERE run_id=?", (run_id,))
        elif row["status"] != "DISMISSED":
            error = StoreError(409, "Run cannot be dismissed")
        result = _view(_row(db, user, run_id, storage.now_utc()))
    if error:
        raise error
    return result


def confirm(store, user, run_id, selection):
    error = None
    result = None
    with store.transaction() as db:
        now = storage.now_utc()
        row = _row(db, user, run_id, now)
        run = _view(row)
        if run.status == "CONFIRMED":
            if run.selected_activity_id != selection.activity_id:
                raise StoreError(409, "Run already confirmed with another activity")
            session = store._expire(db, user, run.session_id, now)
            return {"run": run, "session": dict(session)}
        if run.status != "AWAITING_CONFIRMATION":
            error = StoreError(409, "Run cannot be confirmed")
        elif selection.activity_id not in {x.activity_id for x in run.options}:
            error = StoreError(422, "Choose an offered activity")
        else:
            settings, _ = _settings(db, user)
            entry = get_activity(selection.activity_id)
            offered = next(x for x in run.options if x.activity_id == selection.activity_id)
            if (entry is None or entry[2] != offered.duration_minutes
                    or selection.activity_id in settings.blocked_activity_ids):
                db.execute("UPDATE harness_runs SET status='INVALIDATED' WHERE run_id=?", (run_id,))
                error = StoreError(409, "Activity no longer eligible")
            else:
                # Atomic creation in the same transaction as confirmation, not a separate API call.
                session = store.create_in_transaction(
                    db, user, entry[0], entry[1], entry[2], None, now
                )
                db.execute(
                    """UPDATE harness_runs SET status='CONFIRMED',selected_activity_id=?,session_id=?
                       WHERE run_id=?""", (entry[0], session["session_id"], run_id)
                )
                result = {"run": _view(_row(db, user, run_id, now)), "session": session}
    if error:
        raise error
    return result

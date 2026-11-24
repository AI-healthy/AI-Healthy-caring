"""Explicitly opted-in, user-scoped retrospective evaluation; no cross-user learning."""
from contextlib import closing
from datetime import timedelta

from . import storage
from .health_contract import ObservationInput
from .health_summary import _AUTHORIZED, _enabled
from .pressure_model import evaluate
from .pressure_storage import _STREAM, _check, _stream_args, _view, extract_pair
from .storage import StoreError

MAX_CHECKINS = 180
MAX_DAYS = 60
MAX_OBSERVATIONS = 200000


def set_consent(store, user, payload):
    if not user.startswith("usr_"):
        raise StoreError(403, "Registered account required")
    with store.transaction() as db:
        if payload.granted:
            _check(db, user)
        db.execute(
            """INSERT INTO pressure_research_consent VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET granted=excluded.granted,
               updated_at=excluded.updated_at""",
            (user, int(payload.granted), storage.stamp(storage.now_utc())),
        )
    return payload


def get_consent(store, user):
    with closing(store.connect()) as db:
        row = db.execute("SELECT granted FROM pressure_research_consent WHERE user_id=?",
                         (user,)).fetchone()
    return {"granted": bool(row and row["granted"]), "policy_version": "pressure-research-v1"}


def run(store, user, request):
    _enabled(user)
    now = storage.now_utc()
    # Read only one consistent authorization snapshot. No model or features persisted.
    with closing(store.connect()) as db:
        db.execute("BEGIN")
        _check(db, user)
        consent = db.execute("SELECT granted FROM pressure_research_consent WHERE user_id=?",
                             (user,)).fetchone()
        if not consent or not consent["granted"]:
            raise StoreError(403, "Explicit pressure research consent required")
        known = db.execute("SELECT 1 " + _AUTHORIZED + _STREAM + " LIMIT 1",
                           _stream_args(user, request)).fetchone()
        if not known:
            raise StoreError(404, "Authorized wearable stream not found")
        rows = db.execute(
            """SELECT * FROM pressure_checkins WHERE user_id=?
               AND json_extract(payload_json,'$.source')=?
               AND json_extract(payload_json,'$.data_origin')=?
               AND json_extract(payload_json,'$.device_scope')=?
               AND julianday(json_extract(payload_json,'$.observed_at'))>=julianday(?)
               AND julianday(json_extract(payload_json,'$.observed_at'))<=julianday(?)
               ORDER BY julianday(json_extract(payload_json,'$.observed_at')) DESC,checkin_id
               LIMIT ?""",
            (user, request.source, request.data_origin, request.device_scope,
             storage.stamp(now - timedelta(days=MAX_DAYS)), storage.stamp(now), MAX_CHECKINS + 1),
        ).fetchall()
        if len(rows) > MAX_CHECKINS:
            raise StoreError(422, "Too many check-ins in the research window")
        pairs = []
        total = 0
        for row in rows:
            item = _view(row)
            samples = db.execute(
                "SELECT o.payload_json " + _AUTHORIZED + _STREAM + """
                AND o.metric IN ('steps','heart_rate_bpm')
                AND o.observed_at>=? AND o.observed_at<=? LIMIT 10001""",
                (*_stream_args(user, item),
                 storage.stamp(item.observed_at - timedelta(minutes=40)),
                 storage.stamp(item.observed_at)),
            ).fetchall()
            total += len(samples)
            if len(samples) > 10000 or total > MAX_OBSERVATIONS:
                raise StoreError(422, "Too many observations for research evaluation")
            pairs.append(extract_pair(item, [
                ObservationInput.model_validate_json(r["payload_json"]) for r in samples
            ]))
    return evaluate(pairs, now, total_checkins=len(rows))

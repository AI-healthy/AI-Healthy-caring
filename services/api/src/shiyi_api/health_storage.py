"""Consent-gated, user-scoped synthetic health observations."""
import json
from contextlib import closing
from datetime import timedelta
from uuid import uuid4

from . import storage
from .storage import StoreError

SCHEMA = """
CREATE TABLE IF NOT EXISTS health_consents (
    user_id TEXT NOT NULL,
    source TEXT NOT NULL,
    metric TEXT NOT NULL,
    granted INTEGER NOT NULL CHECK(granted IN (0,1)),
    policy_version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, source, metric)
);
CREATE TABLE IF NOT EXISTS health_consent_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source TEXT NOT NULL,
    metric TEXT NOT NULL,
    granted INTEGER NOT NULL CHECK(granted IN (0,1)),
    policy_version TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_observations (
    observation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source TEXT NOT NULL,
    metric TEXT NOT NULL,
    client_sample_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(user_id, source, metric, client_sample_id)
);
CREATE INDEX IF NOT EXISTS health_history
    ON health_observations(user_id, observed_at DESC, observation_id DESC);
"""


def list_consents(store, user):
    with closing(store.connect()) as db:
        return [dict(row) for row in db.execute(
            """SELECT source,metric,granted,policy_version,updated_at
               FROM health_consents WHERE user_id=? ORDER BY source,metric""", (user,)
        )]


def update_consent(store, user, source, metric, payload):
    if metric == "energy_level" and source not in {"demo", "self_report"}:
        raise StoreError(422, "Unsupported source and metric combination")
    now = storage.stamp(storage.now_utc())
    with store.transaction() as db:
        row = db.execute(
            "SELECT * FROM health_consents WHERE user_id=? AND source=? AND metric=?",
            (user, source, metric),
        ).fetchone()
        if row and bool(row["granted"]) == payload.granted:
            return dict(row)
        db.execute(
            """INSERT INTO health_consents VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id,source,metric) DO UPDATE SET
               granted=excluded.granted, policy_version=excluded.policy_version,
               updated_at=excluded.updated_at""",
            (user, source, metric, int(payload.granted), payload.policy_version, now),
        )
        db.execute("INSERT INTO health_consent_events VALUES (?,?,?,?,?,?,?)",
                   (str(uuid4()), user, source, metric, int(payload.granted),
                    payload.policy_version, now))
        return {"source": source, "metric": metric, "granted": payload.granted,
                "policy_version": payload.policy_version, "updated_at": now}


def upload(store, user, batch):
    now = storage.now_utc()
    result = []
    # All-or-nothing ingestion; serialize with consent updates.
    with store.transaction() as db:
        for item in batch.observations:
            if item.observed_at > now + timedelta(minutes=5):
                raise StoreError(422, "Observation timestamp is in the future")
            consent = db.execute(
                """SELECT granted FROM health_consents
                   WHERE user_id=? AND source=? AND metric=?""",
                (user, item.source, item.metric),
            ).fetchone()
            if not consent or not consent["granted"]:
                raise StoreError(403, "Observation source and metric require consent")
            encoded = item.model_dump_json()
            prior = db.execute(
                """SELECT observation_id,payload_json FROM health_observations
                   WHERE user_id=? AND source=? AND metric=? AND client_sample_id=?""",
                (user, item.source, item.metric, item.client_sample_id),
            ).fetchone()
            if prior and prior["payload_json"] != encoded:
                raise StoreError(409, "Sample identifier reused with different data")
            observation_id = prior["observation_id"] if prior else str(uuid4())
            if prior is None:
                db.execute(
                    "INSERT INTO health_observations VALUES (?,?,?,?,?,?,?,?)",
                    (observation_id, user, item.source, item.metric, item.client_sample_id,
                     storage.stamp(item.observed_at), storage.stamp(now), encoded),
                )
            result.append({"observation_id": observation_id,
                           "client_sample_id": item.client_sample_id,
                           "duplicate": prior is not None})
    return {"items": result}


def history(store, user, source, metric, limit, offset):
    conditions = ["user_id=?"]
    args = [user]
    if source is not None:
        conditions.append("source=?")
        args.append(source)
    if metric is not None:
        conditions.append("metric=?")
        args.append(metric)
    with closing(store.connect()) as db:
        rows = db.execute(
            "SELECT * FROM health_observations WHERE " + " AND ".join(conditions)
            + " ORDER BY observed_at DESC, observation_id DESC LIMIT ? OFFSET ?",
            (*args, limit + 1, offset),
        ).fetchall()
    return {
        "items": [
            {**json.loads(row["payload_json"]), "observation_id": row["observation_id"],
             "recorded_at": row["recorded_at"]}
            for row in rows[:limit]
        ],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


def delete_observation(store, user, observation_id):
    with store.transaction() as db:
        deleted = db.execute(
            "DELETE FROM health_observations WHERE user_id=? AND observation_id=?",
            (user, observation_id),
        )
        if deleted.rowcount != 1:
            raise StoreError(404, "Observation not found")

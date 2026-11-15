"""SQLite repository for the local-only activity MVP."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from .schemas import FeedbackRequest

TERMINAL = {"COMPLETED", "CANCELLED", "EXPIRED"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS activity_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    client_request_id TEXT,
    activity_id TEXT NOT NULL,
    title TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
    status TEXT NOT NULL CHECK(status IN ('CREATED','RUNNING','COMPLETED','CANCELLED','EXPIRED')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    expires_at TEXT NOT NULL,
    UNIQUE(user_id, client_request_id),
    UNIQUE(user_id, session_id)
);
CREATE TABLE IF NOT EXISTS activity_feedback (
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    session_id TEXT,
    activity_id TEXT NOT NULL,
    completed INTEGER NOT NULL CHECK(completed IN (0,1)),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(user_id, event_id),
    UNIQUE(user_id, session_id),
    FOREIGN KEY(user_id, session_id) REFERENCES activity_sessions(user_id, session_id)
);
"""


def now_utc() -> datetime:
    return datetime.now(UTC)


def stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


class StoreError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


class SessionStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript(SCHEMA)
            # Local import prevents the storage/device module import cycle.
            from .device_storage import SCHEMA as device_schema

            db.executescript(device_schema)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def transaction(self):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def _get(db, user, session_id):
        return db.execute(
            "SELECT * FROM activity_sessions WHERE user_id=? AND session_id=?",
            (user, session_id),
        ).fetchone()

    def _expire(self, db, user, session_id, now):
        db.execute(
            """UPDATE activity_sessions SET status='EXPIRED', ended_at=expires_at
               WHERE user_id=? AND session_id=? AND status IN ('CREATED','RUNNING')
               AND expires_at<=?""",
            (user, session_id, stamp(now)),
        )
        return self._get(db, user, session_id)

    def create(self, user, activity_id, title, minutes, client_request_id):
        now = now_utc()
        with self.transaction() as db:
            existing = None
            if client_request_id is not None:
                existing = db.execute(
                    """SELECT * FROM activity_sessions
                       WHERE user_id=? AND client_request_id=?""",
                    (user, client_request_id),
                ).fetchone()
            if existing is not None:
                if existing["activity_id"] != activity_id:
                    raise StoreError(409, "client_request_id already used for another activity")
                return dict(self._expire(db, user, existing["session_id"], now))
            session_id = str(uuid4())
            db.execute(
                """INSERT INTO activity_sessions
                   (session_id,user_id,client_request_id,activity_id,title,
                    duration_minutes,status,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,'CREATED',?,?)""",
                (session_id, user, client_request_id, activity_id, title, minutes,
                 stamp(now), stamp(now + timedelta(minutes=30))),
            )
            return dict(self._get(db, user, session_id))

    def get(self, user, session_id):
        with self.transaction() as db:
            row = self._expire(db, user, session_id, now_utc())
            if row is None:
                raise StoreError(404, "Activity session not found")
            return dict(row)

    def transition(self, user, session_id, target):
        now = now_utc()
        conflict = False
        with self.transaction() as db:
            row = self._expire(db, user, session_id, now)
            if row is None:
                raise StoreError(404, "Activity session not found")
            current = row["status"]
            if current == target:
                return dict(row)
            allowed = (
                (current == "CREATED" and target in {"RUNNING", "CANCELLED"})
                or (current == "RUNNING" and target in {"COMPLETED", "CANCELLED"})
            )
            if not allowed:
                conflict = True
            elif target == "RUNNING":
                db.execute(
                    """UPDATE activity_sessions SET status=?, started_at=?, expires_at=?
                       WHERE user_id=? AND session_id=?""",
                    (target, stamp(now), stamp(now + timedelta(
                        minutes=row["duration_minutes"] + 10)), user, session_id),
                )
            else:
                db.execute(
                    """UPDATE activity_sessions SET status=?, ended_at=?
                       WHERE user_id=? AND session_id=?""",
                    (target, stamp(now), user, session_id),
                )
            result = dict(self._get(db, user, session_id))
        # Commit any newly observed expiry even if the requested transition was illegal.
        if conflict:
            raise StoreError(409, f"Cannot transition {current} to {target}")
        return result

    def feedback(self, user: str, payload: FeedbackRequest) -> bool:
        serialized = payload.model_dump_json()
        error = None
        duplicate = False
        with self.transaction() as db:
            existing = db.execute(
                "SELECT payload_json FROM activity_feedback WHERE user_id=? AND event_id=?",
                (user, payload.client_event_id),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] == serialized:
                    return True
                raise StoreError(409, "client_event_id reused with different feedback")
            if payload.session_id is not None:
                row = self._expire(db, user, payload.session_id, now_utc())
                if row is None:
                    error = StoreError(404, "Activity session not found")
                elif row["activity_id"] != payload.activity_id:
                    error = StoreError(409, "Feedback activity does not match session")
                elif row["status"] not in TERMINAL:
                    error = StoreError(409, "Feedback requires a terminal session")
                elif payload.completed != (row["status"] == "COMPLETED"):
                    error = StoreError(409, "Feedback completion does not match session")
                elif db.execute(
                    "SELECT 1 FROM activity_feedback WHERE user_id=? AND session_id=?",
                    (user, payload.session_id),
                ).fetchone():
                    error = StoreError(409, "Feedback already submitted for this session")
            if error is None:
                db.execute(
                    """INSERT INTO activity_feedback
                       (user_id,event_id,session_id,activity_id,completed,payload_json,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (user, payload.client_event_id, payload.session_id, payload.activity_id,
                     int(payload.completed), serialized, stamp(now_utc())),
                )
        if error is not None:
            raise error
        return duplicate


@lru_cache(maxsize=8)
def store_for(path: str) -> SessionStore:
    return SessionStore(path)


def get_store() -> SessionStore:
    # A separate on-disk file per development instance; never commit its contents.
    path = Path(os.environ.get("SHIYI_DB_PATH", "private_data/shiyi.sqlite3")).resolve()
    return store_for(str(path))

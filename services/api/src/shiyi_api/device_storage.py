"""Transactional outbox and receipt handling for the local simulator."""
import json
from datetime import timedelta
from uuid import uuid4

from . import storage
from .device_contract import CommandRequest, CommandView, DeviceEvent, Receipt
from .storage import StoreError

SCHEMA = """
CREATE TABLE IF NOT EXISTS device_commands (
    command_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    preset TEXT NOT NULL,
    command_type TEXT NOT NULL DEFAULT 'SET_EXPRESSION',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    UNIQUE(user_id, client_request_id),
    FOREIGN KEY(user_id, session_id) REFERENCES activity_sessions(user_id, session_id)
);
CREATE TABLE IF NOT EXISTS device_events (
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(user_id, device_id, event_id),
    FOREIGN KEY(command_id) REFERENCES device_commands(command_id)
);
CREATE INDEX IF NOT EXISTS device_commands_poll
    ON device_commands(user_id, device_id, status, created_at);
"""
ACTIVE = {"QUEUED", "ACKNOWLEDGED"}


def ensure_schema(db):
    """Add LAN-02 columns to databases created before the protocol expansion."""
    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(device_commands)").fetchall()
    }
    if "command_type" not in columns:
        db.execute(
            "ALTER TABLE device_commands "
            "ADD COLUMN command_type TEXT NOT NULL DEFAULT 'SET_EXPRESSION'"
        )
    if "payload_json" not in columns:
        db.execute(
            "ALTER TABLE device_commands ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'"
        )
        for row in db.execute("SELECT command_id, preset FROM device_commands").fetchall():
            db.execute(
                "UPDATE device_commands SET payload_json=? WHERE command_id=?",
                (json.dumps({"preset": row["preset"]}), row["command_id"]),
            )


def view(row):
    payload = json.loads(row["payload_json"] or "{}")
    if not payload:
        payload = {"preset": row["preset"]}
    return CommandView(
        command_id=row["command_id"], correlation_id=row["session_id"],
        device_id=row["device_id"], type=row["command_type"], payload=payload,
        status=row["status"], created_at=row["created_at"], expires_at=row["expires_at"],
    )


def _refresh(db, row, store, now):
    if row["status"] not in ACTIVE:
        return row
    session = store._expire(db, row["user_id"], row["session_id"], now)
    if row["expires_at"] <= storage.stamp(now) or session["status"] == "EXPIRED":
        status = "EXPIRED"
    elif session["status"] != "RUNNING":
        status = "CANCELLED"
    else:
        return row
    db.execute("UPDATE device_commands SET status=? WHERE command_id=?",
               (status, row["command_id"]))
    return db.execute("SELECT * FROM device_commands WHERE command_id=?",
                      (row["command_id"],)).fetchone()


def _check_active_simulator(db, user, device_id):
    if device_id.startswith("sim_") and not db.execute(
        """SELECT 1 FROM registered_simulators
           WHERE user_id=? AND device_id=? AND revoked_at IS NULL""",
        (user, device_id),
    ).fetchone():
        raise StoreError(404, "Simulator not active")


def enqueue(store, user, payload: CommandRequest, command_type: str, command_payload: dict):
    now = storage.now_utc()
    problem = None
    result = None
    with store.transaction() as db:
        _check_active_simulator(db, user, payload.device_id)
        row = db.execute(
            "SELECT * FROM device_commands WHERE user_id=? AND client_request_id=?",
            (user, payload.client_request_id),
        ).fetchone()
        if row:
            same_payload = json.loads(row["payload_json"] or "{}") == command_payload
            if (
                row["device_id"] != payload.device_id or row["session_id"] != payload.session_id
                or row["command_type"] != command_type or not same_payload
            ):
                raise StoreError(409, "Command request ID conflict")
            return view(_refresh(db, row, store, now))
        session = store._expire(db, user, payload.session_id, now)
        if session is None:
            problem = StoreError(404, "Activity session not found")
        elif session["status"] != "RUNNING":
            problem = StoreError(409, "Device command requires a running session")
        else:
            command_id = str(uuid4())
            expires = min(session["expires_at"], storage.stamp(now + timedelta(seconds=60)))
            # `preset` remains for pre-LAN-02 databases and readers; it is a
            # placeholder for command types that do not carry a preset.
            if command_type == "SET_EXPRESSION":
                preset = command_payload.get("preset", "neutral")
            else:
                preset = "neutral"
            db.execute(
                """INSERT INTO device_commands
                   (command_id,user_id,device_id,session_id,client_request_id,
                    preset,command_type,payload_json,status,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,'QUEUED',?,?)""",
                (command_id, user, payload.device_id, payload.session_id,
                 payload.client_request_id, preset, command_type,
                 json.dumps(command_payload, ensure_ascii=False),
                 storage.stamp(now), expires),
            )
            result = view(db.execute("SELECT * FROM device_commands WHERE command_id=?",
                                     (command_id,)).fetchone())
    if problem:
        raise problem
    return result


def get_command(store, user, command_id):
    with store.transaction() as db:
        row = db.execute("SELECT * FROM device_commands WHERE user_id=? AND command_id=?",
                         (user, command_id)).fetchone()
        if row is None:
            raise StoreError(404, "Command not found")
        return view(_refresh(db, row, store, storage.now_utc()))


def pending(store, owner, device_id):
    with store.transaction() as db:
        _check_active_simulator(db, owner, device_id)
        rows = db.execute(
            """SELECT * FROM device_commands WHERE user_id=? AND device_id=?
               AND status IN ('QUEUED','ACKNOWLEDGED') ORDER BY created_at, command_id""",
            (owner, device_id),
        ).fetchall()
        now = storage.now_utc()
        for row in rows:
            row = _refresh(db, row, store, now)
            if row["status"] in ACTIVE:
                return view(row)
    return None


def record_event(store, owner, event: DeviceEvent):
    problem = None
    result = None
    payload = event.model_dump_json()
    now = storage.now_utc()
    with store.transaction() as db:
        _check_active_simulator(db, owner, event.device_id)
        row = db.execute(
            "SELECT * FROM device_commands WHERE user_id=? AND device_id=? AND command_id=?",
            (owner, event.device_id, event.command_id),
        ).fetchone()
        if row is None:
            raise StoreError(404, "Command not found")
        prior = db.execute(
            "SELECT payload_json FROM device_events WHERE user_id=? AND device_id=? AND event_id=?",
            (owner, event.device_id, event.event_id),
        ).fetchone()
        row = _refresh(db, row, store, now)
        if prior:
            if prior["payload_json"] != payload:
                raise StoreError(409, "Event ID conflict")
            return Receipt(duplicate=True, command=view(row))
        target = {
            "COMMAND_ACKNOWLEDGED": "ACKNOWLEDGED",
            "COMMAND_COMPLETED": "COMPLETED",
            "COMMAND_FAILED": "FAILED",
        }[event.type]
        allowed = (
            (row["status"] == "QUEUED" and target == "ACKNOWLEDGED")
            or (row["status"] == "ACKNOWLEDGED" and target in {"COMPLETED", "FAILED"})
        )
        if not allowed:
            problem = StoreError(409, f"Cannot apply event to {row['status']}")
        else:
            db.execute("INSERT INTO device_events VALUES (?,?,?,?,?)",
                       (owner, event.device_id, event.event_id, event.command_id, payload))
            db.execute("UPDATE device_commands SET status=? WHERE command_id=?",
                       (target, event.command_id))
            row = db.execute("SELECT * FROM device_commands WHERE command_id=?",
                             (event.command_id,)).fetchone()
            result = Receipt(duplicate=False, command=view(row))
    if problem:
        raise problem
    return result

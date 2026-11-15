"""Local account credentials and revocable opaque sessions."""
import hashlib
import secrets
import sqlite3
from contextlib import closing
from datetime import timedelta
from uuid import uuid4

from . import storage
from .storage import StoreError

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_digest TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_tokens (
    token_digest TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS user_tokens_owner ON user_tokens(user_id);
"""


def password_digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 600_000
    ).hex()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def profile(row):
    return {key: row[key] for key in ("user_id", "username", "display_name", "created_at")}


def register(store, payload):
    username = payload.username.lower()
    salt = secrets.token_hex(16)
    digest = password_digest(payload.password.get_secret_value(), salt)
    user_id = "usr_" + uuid4().hex
    created = storage.stamp(storage.now_utc())
    try:
        with store.transaction() as db:
            db.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?)",
                (user_id, username, payload.display_name, salt, digest, created),
            )
            row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            return profile(row)
    except sqlite3.IntegrityError:
        raise StoreError(409, "Username unavailable") from None


def login(store, payload):
    with closing(store.connect()) as db:
        row = db.execute("SELECT * FROM users WHERE username=?",
                         (payload.username.lower(),)).fetchone()
    # Same password-hashing work even when username does not exist.
    salt = row["password_salt"] if row else "00" * 16
    digest = password_digest(payload.password.get_secret_value(), salt)
    expected = row["password_digest"] if row else "00" * 32
    if not secrets.compare_digest(digest, expected) or row is None:
        raise StoreError(401, "Invalid username or password")
    token = "shiyi_" + secrets.token_urlsafe(32)
    now = storage.now_utc()
    expires = storage.stamp(now + timedelta(hours=24))
    with store.transaction() as db:
        db.execute("DELETE FROM user_tokens WHERE expires_at<=?", (storage.stamp(now),))
        db.execute("INSERT INTO user_tokens VALUES (?,?,?)",
                   (token_digest(token), row["user_id"], expires))
    return {"access_token": token, "expires_at": expires, "user": profile(row)}


def authenticated_account(store, token):
    if not token.startswith("shiyi_") or len(token) != 49:
        return None
    with closing(store.connect()) as db:
        row = db.execute(
            "SELECT user_id FROM user_tokens WHERE token_digest=? AND expires_at>?",
            (token_digest(token), storage.stamp(storage.now_utc())),
        ).fetchone()
    return row["user_id"] if row else None


def logout(store, user, token):
    if not user.startswith("usr_"):
        raise StoreError(400, "Development identities cannot log out via this endpoint")
    with store.transaction() as db:
        db.execute("DELETE FROM user_tokens WHERE user_id=? AND token_digest=?",
                   (user, token_digest(token)))


def get_profile(store, user):
    with closing(store.connect()) as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (user,)).fetchone()
    if row is None:
        raise StoreError(404, "Registered account required")
    return profile(row)


def update_profile(store, user, payload):
    with store.transaction() as db:
        updated = db.execute("UPDATE users SET display_name=? WHERE user_id=?",
                             (payload.display_name, user))
        if updated.rowcount != 1:
            raise StoreError(404, "Registered account required")
        return profile(db.execute("SELECT * FROM users WHERE user_id=?", (user,)).fetchone())

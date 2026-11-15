"""Bounded, on-demand retrieval over consented synthetic activity evidence."""
from datetime import datetime, timedelta

from .. import storage
from ..recommendation import catalog_entries
from .contracts import MemoryEntry, MemoryView

SCHEMA = """
CREATE TABLE IF NOT EXISTS harness_memory_epochs (
    user_id TEXT PRIMARY KEY,
    feedback_floor INTEGER NOT NULL DEFAULT 0,
    behavior_floor INTEGER NOT NULL DEFAULT 0,
    behavior_since TEXT
);
CREATE INDEX IF NOT EXISTS activity_feedback_memory
    ON activity_feedback(user_id,activity_id,created_at);
CREATE INDEX IF NOT EXISTS activity_sessions_memory
    ON activity_sessions(user_id,activity_id,status,ended_at);
"""
PER_ACTIVITY = 4
HALF_LIFE_DAYS = 7
BEHAVIOR_BUDGET = 12


def _epoch(db, user):
    row = db.execute(
        "SELECT * FROM harness_memory_epochs WHERE user_id=?", (user,)
    ).fetchone()
    return (row["feedback_floor"], row["behavior_floor"], row["behavior_since"]) if row else (
        0, 0, None
    )


def advance_epoch(db, user, now, *, feedback=False, behavior=False):
    ff, bf, bs = _epoch(db, user)
    if feedback:
        ff = db.execute(
            "SELECT COALESCE(MAX(rowid),0) FROM activity_feedback WHERE user_id=?", (user,)
        ).fetchone()[0]
    if behavior:
        bf = db.execute(
            "SELECT COALESCE(MAX(rowid),0) FROM activity_sessions WHERE user_id=?", (user,)
        ).fetchone()[0]
        bs = storage.stamp(now)
    db.execute(
        """INSERT INTO harness_memory_epochs VALUES (?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET feedback_floor=excluded.feedback_floor,
           behavior_floor=excluded.behavior_floor,behavior_since=excluded.behavior_since""",
        (user, ff, bf, bs),
    )


def _recent_ratings(db, user, ids, since, floor, now):
    if since is None:
        return []
    lower = max(since, storage.stamp(now - timedelta(days=30)))
    rows = []
    # At most four valid observations per eligible activity; no irrelevant-history starvation.
    for aid in sorted(ids):
        rows.extend(db.execute(
            """SELECT f.activity_id,f.created_at,f.event_id,
                      json_extract(f.payload_json,'$.enjoyment') AS rating
               FROM activity_feedback f
               JOIN activity_sessions s ON s.user_id=f.user_id AND s.session_id=f.session_id
               WHERE f.user_id=? AND f.activity_id=? AND f.rowid>? AND f.completed=1
               AND s.status='COMPLETED' AND f.created_at>=? AND f.created_at<=?
               AND json_type(f.payload_json,'$.enjoyment')='integer'
               AND json_extract(f.payload_json,'$.enjoyment') BETWEEN 1 AND 5
               ORDER BY f.created_at DESC,f.event_id DESC LIMIT ?""",
            (user, aid, floor, lower, storage.stamp(now), PER_ACTIVITY),
        ).fetchall())
    # Prioritize recent evidence; stable tie-breaking. Candidate relevance is a hard filter.
    return sorted(rows, key=lambda r: (r["created_at"], r["event_id"]), reverse=True)


def _behavior(db, user, ids, floor, since, now):
    if since is None:
        return []
    lower = max(since, storage.stamp(now - timedelta(days=2)))
    rows = []
    for aid in sorted(ids):
        rows.extend(db.execute(
            """SELECT activity_id,ended_at,session_id FROM activity_sessions
               WHERE user_id=? AND activity_id=? AND rowid>? AND status='COMPLETED'
               AND ended_at>=? AND ended_at<=?
               ORDER BY ended_at DESC,session_id DESC LIMIT ?""",
            (user, aid, floor, lower, storage.stamp(now), PER_ACTIVITY),
        ).fetchall())
    return sorted(rows, key=lambda r: (r["ended_at"], r["session_id"]), reverse=True)[
        :BEHAVIOR_BUDGET
    ]


def recall(db, user, settings, since, now, candidates=None):
    entries = catalog_entries() if candidates is None else candidates
    ids = {entry[0] for entry in entries}
    ids -= set(settings.blocked_activity_ids)
    ff, bf, bs = _epoch(db, user)
    ratings = (
        _recent_ratings(db, user, ids, since, ff, now)[:settings.memory_budget]
        if settings.use_feedback_memory else []
    )
    behavior = _behavior(db, user, ids, bf, bs, now) if settings.use_behavior_memory else []
    values = {}
    for row in ratings:
        # UTC day buckets keep snapshot equality stable between inference and commit.
        age = max(0, (now.date() - datetime.fromisoformat(row["created_at"]).date()).days)
        weight = 2 ** (-age / HALF_LIFE_DAYS)
        values.setdefault(row["activity_id"], []).append((row["rating"] - 3, weight))
    counts = {}
    for row in behavior:
        aid = row["activity_id"]
        counts[aid] = counts.get(aid, 0) + 1
    result = []
    for aid in sorted(set(values) | set(counts)):
        evidence = values.get(aid, [])
        mass = sum(weight for _, weight in evidence)
        score = sum(value * weight for value, weight in evidence) / (2 + mass)
        # Variety preference only, not evidence of dislike or medical need.
        completed = counts.get(aid, 0)
        penalty = min(1.0, completed * 0.25)
        result.append(MemoryEntry(
            activity_id=aid, count=len(evidence), score=round(score, 4),
            effective_weight=round(mass, 4), recent_completions=completed,
            repetition_penalty=penalty, decision_score=round(score - penalty, 4),
        ))
    return MemoryView(
        enabled=settings.use_feedback_memory, behavior_enabled=settings.use_behavior_memory,
        budget=settings.memory_budget, recalled_events=len(ratings),
        behavior_events=len(behavior), entries=result,
    )

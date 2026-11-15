"""Offline synthetic benchmark for production Harness paths; never open a user database."""
import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from . import storage
from .harness import proactive, repository
from .harness.contracts import RunRequest, Settings
from .harness.engine import RuleRanker
from .harness.memory import _recent_ratings
from .harness.proactive_contracts import ScheduleRequest
from .recommendation import catalog_entries, get_activity
from .schemas import FeedbackRequest

VERSION = "synthetic-v1"
NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
METHODS = ("no_memory", "static_memory", "decay_memory", "decay_and_behavior")
COHORTS = ("stable", "preference_shift", "sparse", "noisy", "variety", "time_budget")


@dataclass(frozen=True)
class Event:
    activity: str
    days: float
    rating: int


@dataclass(frozen=True)
class Scenario:
    case_id: str
    cohort: str
    minutes: int
    energy: int | None
    tags: tuple[str, ...]
    blocked: tuple[str, ...]
    utility: dict
    events: tuple[Event, ...]


def scenarios(seed, per_cohort):
    rng = random.Random(seed)
    catalog = catalog_entries()
    for cohort in COHORTS:
        for index in range(per_cohort):
            minutes = 5 if cohort == "time_budget" else rng.choice([5, 8, 10])
            eligible = [e[0] for e in catalog if e[2] <= minutes]
            blocked = (rng.choice(eligible),) if index % 5 == 0 else ()
            eligible = [aid for aid in eligible if aid not in blocked]
            target = rng.choice(eligible)
            former = rng.choice([aid for aid in eligible if aid != target])
            tags = tuple(rng.choice([(), ("gentle",), ("culture",), ("movement",)]))
            energy = rng.choice([None, 2, 3, 4])
            # Synthetic held-out utilities; never provided to the rankers. Preferences can
            # disagree with explicit tags/energy, and noisy ratings may disagree with utility.
            utility = {aid: rng.choice([2, 3, 4]) for aid in eligible}
            utility[target] = 5
            events = []
            for j in range(1 if cohort == "sparse" else 12):
                age = 1 + j * 1.7
                if cohort == "preference_shift":
                    aid = former if j >= 3 else target
                    rating = 5 if j >= 3 else rng.choice([4, 5])
                elif cohort == "variety":
                    aid = former if j < 4 else rng.choice(eligible)
                    age = 0.2 + j * 0.3 if j < 4 else age
                    rating = 5 if j < 4 else utility[aid]
                elif cohort == "time_budget" and j < 8:
                    aid = rng.choice(["walk", "music"])
                    rating = rng.choice([2, 4, 5])
                    age = 0.2 + j * 0.2
                else:
                    aid = rng.choice(eligible)
                    rating = utility[aid]
                    if cohort == "noisy":
                        rating += rng.choice([-2, -1, 0, 1, 2])
                    else:
                        rating += rng.choice([-1, 0, 0, 1])
                events.append(Event(aid, age, max(1, min(5, rating))))
            # Variety cohort explicitly assigns lower held-out utility to recently repeated activity.
            if cohort == "variety":
                utility[former] = 2
            yield Scenario(f"{cohort}-{index:03d}", cohort, minutes, energy, tags,
                           blocked, utility, tuple(events))


def seed_history(store, user, events, settings):
    # Test fixtures only: use the real settings and storage schema, with fixed historic timestamps.
    with patch.object(storage, "now_utc", return_value=NOW - timedelta(days=31)):
        repository.put_settings(store, user, settings)
    with store.transaction() as db:
        for i, event in enumerate(sorted(events, key=lambda x: -x.days)):
            when = NOW - timedelta(days=event.days, seconds=i)
            activity = get_activity(event.activity)
            session = store.create_in_transaction(
                db, user, activity[0], activity[1], activity[2], f"fixture-{i}", when
            )
            sid = session["session_id"]
            done = storage.stamp(when)
            db.execute(
                """UPDATE activity_sessions SET status='COMPLETED',started_at=?,ended_at=?
                   WHERE session_id=? AND user_id=?""", (done, done, sid, user)
            )
            feedback = FeedbackRequest(
                session_id=sid, activity_id=event.activity, client_event_id=f"fixture-{i}",
                completed=True, enjoyment=event.rating,
            )
            db.execute(
                """INSERT INTO activity_feedback
                   (user_id,event_id,session_id,activity_id,completed,payload_json,created_at)
                   VALUES (?,?,?,?,1,?,?)""",
                (user, feedback.client_event_id, sid, event.activity,
                 feedback.model_dump_json(), done),
            )


class StaticRanker:
    """Uniform weights, identical eligible evidence and budget; decay ablation only."""

    def __init__(self, store, user):
        self.store = store
        self.user = user

    def rank(self, context, candidates):
        with self.store.transaction() as db:
            rows = _recent_ratings(
                db, self.user, {e[0] for e in candidates},
                storage.stamp(NOW - timedelta(days=31)), 0, NOW
            )[:12]
        values = defaultdict(list)
        for row in rows:
            values[row["activity_id"]].append(row["rating"] - 3)
        scores = tuple((aid, sum(ratings) / (2 + len(ratings)))
                       for aid, ratings in sorted(values.items()))
        return RuleRanker().rank(replace(context, memory_scores=scores), candidates)


def evaluate_memory(store, cases):
    results = []
    for case in cases:
        for method in METHODS:
            user = f"bench:{case.case_id}:{method}"
            settings = Settings(
                preference_tags=list(case.tags), blocked_activity_ids=list(case.blocked),
                use_feedback_memory=method != "no_memory",
                use_behavior_memory=method == "decay_and_behavior",
                memory_budget=12,
            )
            seed_history(store, user, case.events, settings)
            ranker = StaticRanker(store, user) if method == "static_memory" else None
            request = RunRequest(client_request_id="eval", available_minutes=case.minutes,
                                 energy_level=case.energy)
            with patch.object(storage, "now_utc", return_value=NOW):
                run = repository.create_run(store, user, request, ranker)
                mem = repository.get_memory(store, user, case.minutes)
            ids = [item.activity_id for item in run.options]
            valid = bool(ids) and len(ids) == len(set(ids)) and all(
                aid in case.utility and get_activity(aid)[2] <= case.minutes for aid in ids
            )
            if not valid or run.session_id is not None or run.status != "AWAITING_CONFIRMATION":
                raise AssertionError("Invalid ranking or unconfirmed execution")
            scores = [case.utility[aid] for aid in ids]
            best = max(case.utility.values())
            results.append({
                "case_id": case.case_id, "cohort": case.cohort, "method": method,
                "top1": ids[0], "top1_utility": scores[0], "top1_hit": int(scores[0] == best),
                "hit_at_3": int(best in scores), "regret": best - scores[0],
                "feedback_recalled": mem.recalled_events, "behavior_recalled": mem.behavior_events,
            })
    return results


def summarize(rows):
    result = {}
    for cohort in ("all", *COHORTS):
        result[cohort] = {}
        for method in METHODS:
            group = [r for r in rows if r["method"] == method
                     and (cohort == "all" or r["cohort"] == cohort)]
            if not group:
                continue
            result[cohort][method] = {
                "n": len(group),
                **{key: round(statistics.fmean(r[key] for r in group), 4) for key in (
                    "top1_utility", "top1_hit", "hit_at_3", "regret",
                    "feedback_recalled", "behavior_recalled"
                )},
            }
    return result


def paired_deltas(rows):
    """Paired outcome comparisons, preserving ties and unfavorable results."""
    comparisons = (
        ("static_memory", "no_memory"),
        ("decay_memory", "static_memory"),
        ("decay_and_behavior", "decay_memory"),
        ("decay_and_behavior", "no_memory"),
    )
    indexed = {(row["case_id"], row["method"]): row for row in rows}
    out = {}
    for cohort in ("all", *COHORTS):
        out[cohort] = {}
        for method, baseline in comparisons:
            group = [
                row["top1_utility"] - indexed[(row["case_id"], baseline)]["top1_utility"]
                for row in rows if row["method"] == method
                and (cohort == "all" or row["cohort"] == cohort)
            ]
            out[cohort][f"{method}_vs_{baseline}"] = {
                "n": len(group), "wins": sum(delta > 0 for delta in group),
                "ties": sum(delta == 0 for delta in group),
                "losses": sum(delta < 0 for delta in group),
                "mean_utility_delta": round(statistics.fmean(group), 4),
            }
    return out


# Independent fixture labels are scenario assumptions, not outputs from the gate.
GATE_CASES = (
    ("available", True), ("disabled", False), ("no_lease", False),
    ("quiet", False), ("active", False), ("pending", False),
    ("short", False), ("paused", False), ("expired", False),
    ("cooldown", False), ("daily_limit", False), ("quiet_boundary", True),
    ("after_cooldown", True),
)


def evaluate_proactive(store):
    rows = []
    for name, expected in GATE_CASES:
        user = "gate:" + name
        now = NOW
        settings = Settings(proactive_enabled=True, timezone="UTC",
                            quiet_start="11:00" if name in {"quiet", "quiet_boundary"} else
                            "22:00",
                            quiet_end="12:00" if name == "quiet_boundary" else
                            "13:00" if name == "quiet" else "01:00")
        with patch.object(storage, "now_utc", return_value=NOW):
            repository.put_settings(store, user, settings)
            if name != "no_lease":
                if name in {"cooldown", "daily_limit", "after_cooldown"}:
                    offsets = [1] if name == "cooldown" else [9, 5] if name == "daily_limit" else [5]
                    for offset in offsets:
                        with patch.object(storage, "now_utc",
                                          return_value=NOW - timedelta(hours=offset)):
                            historical = repository.create_run(store, user, RunRequest(
                                client_request_id=f"old-{offset}", trigger="scheduled_check"
                            ))
                            if historical.status != "AWAITING_CONFIRMATION":
                                raise AssertionError("Gate fixture failed")
                            repository.dismiss(store, user, historical.run_id)
                if name == "active":
                    store.create(user, "stretch", get_activity("stretch")[1], 5, "active")
                if name == "pending":
                    repository.create_run(store, user, RunRequest(client_request_id="pending"))
                proactive.put_schedule(store, user, ScheduleRequest(
                    enabled=True, available_minutes=1 if name == "short" else 5,
                    available_for_minutes=15
                ))
                if name == "paused":
                    proactive.put_schedule(store, user, ScheduleRequest(enabled=False))
                if name == "disabled":
                    repository.put_settings(store, user, settings.model_copy(
                        update={"proactive_enabled": False}
                    ))
                if name == "expired":
                    now = NOW + timedelta(minutes=16)
        with patch.object(storage, "now_utc", return_value=now):
            # Exercise the actual atomic worker for the fixture, followed by delivery gate.
            outcome = proactive._tick_user(store, user)
            offer = proactive.pending_offer(store, user)
            actual = offer is not None
            rows.append({"case_id": name, "expected": expected, "harness": actual,
                         "ungated_counterfactual": True, "reason": outcome or "not_due"})
            if offer:
                repository.dismiss(store, user, offer.run.run_id)
    return rows


def gate_metrics(rows, key):
    tp = sum(row[key] and row["expected"] for row in rows)
    fp = sum(row[key] and not row["expected"] for row in rows)
    tn = sum(not row[key] and not row["expected"] for row in rows)
    fn = sum(not row[key] and row["expected"] for row in rows)
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "n": len(rows),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None}


def evaluate(seed=42, per_cohort=12):
    if not 1 <= per_cohort <= 100:
        raise ValueError("per_cohort must be in 1..100")
    with TemporaryDirectory(prefix="shiyi-benchmark-") as tmp:
        store = storage.SessionStore(str(Path(tmp) / "synthetic.sqlite3"))
        cases = list(scenarios(seed, per_cohort))
        rows = evaluate_memory(store, cases)
        gates = evaluate_proactive(store)
    return {"benchmark": VERSION, "is_synthetic": True, "seed": seed,
            "cases_per_cohort": per_cohort, "scenario_count": len(cases),
            "rankings": len(rows), "memory": summarize(rows), "paired": paired_deltas(rows),
            "gates": {
                key: gate_metrics(gates, key) for key in ("harness", "ungated_counterfactual")
            }, "ranking_rows": rows, "gate_rows": gates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-cohort", type=int, default=12)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--assert-gates", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.seed, args.per_cohort)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for name in ("ranking_rows", "gate_rows"):
            rows = result[name]
            with (args.output / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    print("SHIYI_BENCHMARK " + json.dumps({
        key: value for key, value in result.items() if key not in {"ranking_rows", "gate_rows"}
    }, ensure_ascii=False, sort_keys=True))
    if args.assert_gates and any(row["harness"] != row["expected"] for row in result["gate_rows"]):
        raise SystemExit("Proactive scenario gate mismatch")


if __name__ == "__main__":
    main()

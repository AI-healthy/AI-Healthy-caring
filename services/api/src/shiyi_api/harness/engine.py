"""Pure bounded policy interface; no side effects, networking or private identity."""
from dataclasses import dataclass
from typing import Protocol

from ..schemas import ActivityOption

CatalogEntry = tuple[str, str, int, frozenset[str]]


@dataclass(frozen=True)
class DecisionContext:
    available_minutes: int
    energy_level: int | None
    preference_tags: frozenset[str]
    memory_scores: tuple[tuple[str, float], ...]


class Ranker(Protocol):
    def rank(self, context: DecisionContext, candidates: tuple[CatalogEntry, ...]) -> list[str]:
        """Return at most three distinct allowed activity IDs in preferred order."""
        ...


class RuleRanker:
    def rank(self, context: DecisionContext, candidates: tuple[CatalogEntry, ...]) -> list[str]:
        history = dict(context.memory_scores)
        scored = []
        for order, (aid, _title, _minutes, tags) in enumerate(candidates):
            score = len(tags & context.preference_tags) * 2.0 + history.get(aid, 0.0)
            if context.energy_level is not None:
                if context.energy_level <= 2 and "gentle" in tags:
                    score += 3
                elif context.energy_level >= 4 and "movement" in tags:
                    score += 2
            scored.append((score, -order, aid))
        scored.sort(reverse=True)
        return [aid for _, _, aid in scored[:3]]


def choose(context, candidates, ranker: Ranker):
    """Treat proposed IDs as untrusted; reject invalid/duplicate/too many IDs."""
    allowed = {item[0]: item for item in candidates}
    fallback = False
    try:
        ids = ranker.rank(context, candidates)
        if (
            not isinstance(ids, list) or not 1 <= len(ids) <= min(3, len(allowed))
            or not all(isinstance(aid, str) and aid in allowed for aid in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("Invalid candidate selection")
    except Exception:
        # Never persist exception contents or user data. Trusted in-process adapters only.
        ids = RuleRanker().rank(context, candidates)
        fallback = True
    options = [
        ActivityOption(
            activity_id=aid, title=allowed[aid][1], duration_minutes=allowed[aid][2],
            reason="符合可用时间和活动偏好；请选择适合自己的体验。",
        )
        for aid in ids
    ]
    return options, fallback

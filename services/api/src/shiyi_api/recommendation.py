"""Deterministic low-risk demo recommender, not a medical tool."""
from .schemas import ActivityOption, RecommendationRequest

_CATALOG: list[tuple[str, str, int, frozenset[str]]] = [
    ("stretch", "5 分钟肩颈放松", 5, frozenset({"gentle", "movement"})),
    ("walk", "8 分钟轻松散步", 8, frozenset({"outdoor", "movement"})),
    ("music", "6 分钟听一首喜欢的音乐", 6, frozenset({"music", "gentle"})),
    ("culture", "5 分钟认识一张节气卡", 5, frozenset({"culture", "gentle"})),
    ("baduanjin_intro", "5 分钟八段锦入门", 5, frozenset({"movement", "culture"})),
]


def get_recommendations(request: RecommendationRequest) -> list[ActivityOption]:
    prefs = set(request.preference_tags)
    available = request.context.available_minutes
    energy = request.context.energy_level
    excluded = set(request.skip_activity_ids)

    scored: list[tuple[int, int, ActivityOption]] = []
    for order, (activity_id, title, minutes, tags) in enumerate(_CATALOG):
        if activity_id in excluded or minutes > available:
            continue
        score = len(prefs & tags) * 2
        if energy is not None and energy <= 2 and "gentle" in tags:
            score += 3
        if energy is not None and energy >= 4 and "movement" in tags:
            score += 2
        scored.append(
            (score, -order, ActivityOption(
                activity_id=activity_id,
                title=title,
                duration_minutes=minutes,
                reason="根据你选择的时间与偏好提供的低门槛体验选项。",
            ))
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:3]]

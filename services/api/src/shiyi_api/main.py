from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI

from .activity_api import router as activity_router
from .device_api import router as device_router
from .recommendation import get_recommendations
from .schemas import (
    RecommendationRequest,
    RecommendationResponse,
)

app = FastAPI(
    title="ShiYi API (local activity MVP)",
    description="Local demo only. Activity records use SQLite and development bearer identities.",
    version="0.3.0",
)

app.include_router(activity_router)
app.include_router(device_router)


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok", "mode": "local_demo", "service": "shiyi-api"}


@app.get("/api/v1/seasons/current")
def current_season() -> dict:
    # Example card, NOT a verified solar-term calendar implementation.
    return {
        "term": "立冬",
        "title": "四时生活 · 立冬",
        "summary": "了解当季习俗，探索适合自己的生活小体验。",
        "suggested_experience": "认识一种家乡冬季饮食文化",
        "calendar_status": "sample_only",
        "is_demo": True,
        "notice": "示例主题；未按当前日期查询精确节气历。",
    }


@app.post("/api/v1/recommendations", response_model=RecommendationResponse)
def recommend(payload: RecommendationRequest) -> RecommendationResponse:
    return RecommendationResponse(
        request_id=str(uuid4()),
        options=get_recommendations(payload),
        explanation="活动由演示规则排序，不进行疾病判断。",
        is_demo=True,
        data_notice="规则推荐演示，不代表穿戴数据已经接入。",
    )


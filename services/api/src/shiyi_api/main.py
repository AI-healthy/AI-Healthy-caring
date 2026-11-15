from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .activity_api import router as activity_router
from .device_api import router as device_router
from .harness.api import router as harness_router
from .health_api import router as health_router
from .identity_api import router as identity_router
from .recommendation import get_recommendations
from .schemas import (
    RecommendationRequest,
    RecommendationResponse,
)

app = FastAPI(
    title="ShiYi API (local activity MVP)",
    description="Local demo only. Accounts, activities and synthetic observations use SQLite.",
    version="0.7.0",
)

app.include_router(activity_router)
app.include_router(device_router)
app.include_router(identity_router)
app.include_router(health_router)
app.include_router(harness_router)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    # Never reflect raw password, credential or observation values in errors.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(error["loc"]), "type": error["type"], "msg": "Invalid input"}
        for error in exc.errors()
    ]})


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


"""Read-only, synthetic-data tools for the XiaoZhi pilot."""
import os
from urllib.parse import urlparse

import httpx

from .schemas import RecommendationRequest, RecommendationResponse


def _request(method, path, body=None):
    base = os.environ.get("SHIYI_API_URL", "http://127.0.0.1:8000").rstrip("/")
    url = urlparse(base)
    if (
        url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1", "localhost"}
        or url.username or url.password or url.path or url.query or url.fragment
    ):
        return {"ok": False, "error": "local_api_only"}
    try:
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = client.request(method, base + path, json=body)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid_api_response"}
        return {"ok": True, "data": data}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "error": "shiyi_api_unavailable"}


def get_shiyi_season_card() -> dict:
    """获取时宜固定演示节气卡，不代表今天真实节气，不提供医疗建议。"""
    result = _request("GET", "/api/v1/seasons/current")
    if not result["ok"]:
        return result
    data = result["data"]
    if data.get("is_demo") is not True or data.get("calendar_status") != "sample_only":
        return {"ok": False, "error": "expected_demo_card"}
    keys = ("term", "title", "summary", "suggested_experience", "notice")
    if not all(isinstance(data.get(key), str) for key in keys):
        return {"ok": False, "error": "invalid_api_response"}
    return {"ok": True, "is_demo": True, "calendar_status": "sample_only",
            **{key: data[key] for key in keys}}


def recommend_shiyi_activity(available_minutes: int = 5) -> dict:
    """仅按演示可用时间推荐低风险微活动；不发送真实健康或身份信息。"""
    if type(available_minutes) is not int or not 1 <= available_minutes <= 120:
        return {"ok": False, "error": "available_minutes_out_of_range"}
    request = RecommendationRequest(
        context={"available_minutes": available_minutes, "source": "demo", "is_demo": True}
    )
    result = _request("POST", "/api/v1/recommendations", request.model_dump(mode="json"))
    if not result["ok"]:
        return result
    try:
        data = RecommendationResponse.model_validate(result["data"])
        if not data.is_demo:
            raise ValueError
    except ValueError:
        return {"ok": False, "error": "invalid_demo_response"}
    return {"ok": True, "is_demo": True, "algorithm": data.algorithm,
            "options": [option.model_dump() for option in data.options],
            "notice": data.data_notice}

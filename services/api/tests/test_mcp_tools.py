import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from shiyi_api import mcp_tools
from shiyi_api.main import app


@pytest.fixture
def backend(monkeypatch):
    with TestClient(app) as local:
        def dispatch(request):
            response = local.request(
                request.method, request.url.path, content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(response.status_code, content=response.content)

        real_client = httpx.Client
        monkeypatch.setattr(mcp_tools.httpx, "Client", lambda **kwargs: real_client(
            transport=httpx.MockTransport(dispatch), **kwargs
        ))
        yield


def test_mcp_uses_api_and_preserves_demo_flag(backend):
    card = mcp_tools.get_shiyi_season_card()
    assert card["ok"] and card["is_demo"]
    assert card["calendar_status"] == "sample_only"
    assert "立冬" in card["title"]
    result = mcp_tools.recommend_shiyi_activity(5)
    assert result["ok"] and result["options"] and result["is_demo"]
    assert all(option["duration_minutes"] <= 5 for option in result["options"])


def test_mcp_errors_and_loopback_only(backend, monkeypatch):
    assert not mcp_tools.recommend_shiyi_activity(0)["ok"]
    monkeypatch.setenv("SHIYI_API_URL", "https://example.org")
    assert mcp_tools.get_shiyi_season_card()["error"] == "local_api_only"


def test_mcp_unavailable(monkeypatch):
    def reject(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(mcp_tools.httpx, "Client", reject)
    assert mcp_tools.get_shiyi_season_card()["error"] == "shiyi_api_unavailable"


def test_mcp_registered_tools():
    pytest.importorskip("mcp")
    from shiyi_api.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "get_shiyi_season_card", "recommend_shiyi_activity"
    }

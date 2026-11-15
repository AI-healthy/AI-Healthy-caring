"""Explicitly enabled, loopback-only developer workbench; not the product UI."""
import os
from importlib.resources import files

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter(include_in_schema=False)
HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    ),
}


def _asset(request: Request, name: str, media_type: str):
    if (
        os.environ.get("SHIYI_DEBUG_WORKBENCH") != "1"
        or request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.url.hostname not in {"127.0.0.1", "::1", "localhost"}
    ):
        raise HTTPException(404)
    asset = files("shiyi_api").joinpath("workbench_assets", name)
    return Response(asset.read_bytes(), media_type=media_type, headers=HEADERS)


@router.get("/workbench")
def workbench(request: Request):
    return _asset(request, "index.html", "text/html")


@router.get("/workbench/app.js")
def javascript(request: Request):
    return _asset(request, "app.js", "application/javascript")

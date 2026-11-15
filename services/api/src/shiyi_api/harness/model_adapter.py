"""Loopback-only OpenAI-compatible ranking adapter. No user identity or raw history."""
import json
import os
from threading import BoundedSemaphore
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .engine import CatalogEntry, DecisionContext

_CAPACITY = BoundedSemaphore(2)
MAX_RESPONSE_BYTES = 24_576
MAX_CONTEXT_BYTES = 4096
SYSTEM_PROMPT = (
    "You are a bounded optional ranker for synthetic student wellbeing activities. "
    "Choose one to three distinct IDs from candidates only, using time, preferences, "
    "optional coarse self-reported energy and optional preference scores. "
    "Do not diagnose, prescribe, suggest new activities or perform actions. "
    'Return a JSON object only: {"tool":"rank_activities","activity_ids":["candidate_id"]}.'
)


class ToolProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["rank_activities"]
    activity_ids: list[StrictStr] = Field(min_length=1, max_length=3)


def build_context(context: DecisionContext, candidates: tuple[CatalogEntry, ...]) -> dict:
    """Only bounded selection features; never include identity, timestamps or raw records."""
    energy = context.energy_level
    band = "unknown" if energy is None else "low" if energy <= 2 else (
        "high" if energy >= 4 else "medium"
    )
    allowed = {entry[0] for entry in candidates}
    return {
        "available_minutes": context.available_minutes,
        "self_reported_energy_band": band,
        "preference_tags": sorted(context.preference_tags),
        "memory_scores": {
            aid: round(score, 2) for aid, score in context.memory_scores if aid in allowed
        },
        "candidates": [
            {"id": aid, "duration_minutes": minutes, "tags": sorted(tags)}
            for aid, _title, minutes, tags in candidates
        ],
    }


def route_tool(text: str, candidates: tuple[CatalogEntry, ...]) -> list[str]:
    """Accept exactly one known, read-only proposal; reject arbitrary tool parameters."""
    proposal = ToolProposal.model_validate_json(text)
    allowed = {entry[0] for entry in candidates}
    ids = proposal.activity_ids
    if len(set(ids)) != len(ids) or any(aid not in allowed for aid in ids):
        raise ValueError("Invalid tool candidate")
    return ids


class LocalModelRanker:
    requires_model_opt_in = True

    def __init__(self, endpoint: str, model: str, timeout: float = 5.0):
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_environment(cls):
        return cls(
            os.environ.get(
                "SHIYI_LOCAL_MODEL_URL", "http://127.0.0.1:11434/v1/chat/completions"
            ),
            os.environ.get("SHIYI_LOCAL_MODEL_NAME", ""),
        )

    def _validate_config(self):
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
            or url.username or url.password or url.query or url.fragment
            or url.path != "/v1/chat/completions" or not url.port
            or not self.model or len(self.model) > 128
            or not 0 < self.timeout <= 10
        ):
            raise ValueError("Invalid local model configuration")

    def rank(self, context: DecisionContext, candidates: tuple[CatalogEntry, ...]) -> list[str]:
        self._validate_config()
        encoded = json.dumps(build_context(context, candidates), ensure_ascii=False)
        if len(encoded.encode()) > MAX_CONTEXT_BYTES:
            raise ValueError("Context budget exceeded")
        body = {
            "model": self.model, "temperature": 0, "max_tokens": 256, "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": encoded},
            ],
        }
        if not _CAPACITY.acquire(blocking=False):
            raise RuntimeError("Local inference capacity exhausted")
        try:
            deadline = monotonic() + self.timeout
            # Single attempt; no proxy, redirects, arbitrary host or streamed tool actions.
            with (
                httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False) as client,
                client.stream("POST", self.endpoint, json=body) as response,
            ):
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    if monotonic() > deadline:
                        raise TimeoutError("Local inference deadline exceeded")
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError("Model response too large")
                if monotonic() > deadline:
                    raise TimeoutError("Local inference deadline exceeded")
            content = json.loads(raw)["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content.encode()) > MAX_CONTEXT_BYTES:
                raise ValueError("Invalid model content")
            return route_tool(content, candidates)
        finally:
            _CAPACITY.release()

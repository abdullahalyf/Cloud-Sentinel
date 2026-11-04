"""
The ONLY way the dashboard talks to CloudSentinel: HTTP calls to the C2 API (CONTRACTS §6).
Works the same against the real brain (python -m brain --fake) and the mock (python -m shared.mocks.mock_api).
Owner: Tamjid.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

API_URL = os.getenv("CS_API_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.getenv("CS_API_TOKEN", "")


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def _request(method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
    try:
        r = httpx.request(method, API_URL + path, json=body, params=params, timeout=5.0,
                          headers={"X-CS-Token": TOKEN} if TOKEN else {})
    except httpx.HTTPError as exc:
        raise ApiError(0, f"cannot reach the API at {API_URL} ({exc.__class__.__name__})")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise ApiError(r.status_code, str(detail))
    return r.json()


# ── reads ──
def health() -> dict:
    return _request("GET", "/v1/health")


def fleet() -> list[dict]:
    return _request("GET", "/v1/fleet")["agents"]


def agent(agent_id: str) -> dict:
    return _request("GET", f"/v1/agents/{agent_id}")


def metrics(minutes: float = 5, agent_id: Optional[str] = None) -> list[dict]:
    params = {"minutes": minutes, **({"agent_id": agent_id} if agent_id else {})}
    return _request("GET", "/v1/metrics", params=params)["metrics"]


def graph(minutes: float = 2) -> dict:
    return _request("GET", "/v1/graph", params={"minutes": minutes})


def verdicts(limit: int = 20) -> list[dict]:
    return _request("GET", "/v1/verdicts", params={"limit": limit})["items"]


def actions(limit: int = 50) -> list[dict]:
    return _request("GET", "/v1/actions", params={"limit": limit})["items"]


def alerts(limit: int = 50) -> list[dict]:
    return _request("GET", "/v1/alerts", params={"limit": limit})["items"]


def memory(agent_id: str) -> Optional[dict]:
    try:
        return _request("GET", f"/v1/agents/{agent_id}/memory")
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise


def tool_calls(status: Optional[str] = None) -> list[dict]:
    return _request("GET", "/v1/tool-calls", params={"status": status} if status else None)["items"]


def roi() -> dict:
    return _request("GET", "/v1/roi")


# ── writes ──
def command(agent_id: str, command: str, reason: str = "", params: Optional[dict] = None) -> dict:
    return _request("POST", f"/v1/agents/{agent_id}/commands",
                    {"command": command, "params": params or {}, "requested_by": "dashboard", "reason": reason})


def save_memory(agent_id: str, content: dict, reason: str, base_version: Optional[int] = None) -> dict:
    return _request("PUT", f"/v1/agents/{agent_id}/memory",
                    {"content": content, "edited_by": "human", "reason": reason, "base_version": base_version})


def decide(call_id: int, decision: str, final_args: Optional[dict] = None, reason: str = "") -> dict:
    return _request("POST", f"/v1/tool-calls/{call_id}/decision",
                    {"decision": decision, "final_args": final_args, "decided_by": "human", "reason": reason})

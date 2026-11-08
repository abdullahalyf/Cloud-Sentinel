"""
The API client for the CloudSentinel MCP server.

One place that knows how to talk to the C2 REST API, so the tool functions stay short.
Errors from the API come back as `ToolError` with the API's own message — the model sees
"agent 'x' not found", not a stack trace.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .hardening import ToolError


class ApiClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 10.0):
        self.base_url = (base_url or "http://localhost:8000").rstrip("/")
        self.token = token or ""
        self.timeout = timeout

    def _headers(self) -> dict:
        # The API accepts X-CS-Token. Authorization: Bearer is sent too, because the API
        # may be behind a proxy that only understands the standard header.
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-CS-Token"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout,
                              headers=self._headers()) as client:
                response = client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise ToolError(f"cannot reach the CloudSentinel API at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise ToolError(self._detail(response))
        try:
            return response.json()
        except ValueError:
            return {"result": response.text}

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail", payload.get("message"))
            if isinstance(detail, str) and detail:
                return f"CloudSentinel API {response.status_code}: {detail}"
            if detail:
                return f"CloudSentinel API {response.status_code}: {detail}"
        text = (response.text or "").strip()
        return f"CloudSentinel API {response.status_code}: {text[:300] or 'no detail'}"

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Optional[dict] = None) -> Any:
        return self.request("POST", path, body if body is not None else {})

    def put(self, path: str, body: Optional[dict] = None) -> Any:
        return self.request("PUT", path, body if body is not None else {})

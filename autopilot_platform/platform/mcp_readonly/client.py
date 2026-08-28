"""对 Platform REST 的只读 httpx 封装。"""

from __future__ import annotations

import os
from typing import Any

import httpx


class PlatformReadonlyClient:
    """用用户 JWT 或 API Token 调用既有只读接口。"""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("MC_BASE_URL")
            or os.environ.get("MC_PLATFORM_URL")
            or os.environ.get("MC_SERVER")
            or ""
        ).strip().rstrip("/")
        if not self.base_url:
            from autopilot_platform.platform.core.urls import platform_base_url

            self.base_url = platform_base_url()
        self.token = (token or os.environ.get("MC_MCP_TOKEN") or os.environ.get("MC_API_TOKEN") or "").strip()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if not self.token:
            return h
        if self.token.lower().startswith("bearer "):
            h["Authorization"] = self.token
        elif len(self.token.split(".")) >= 3:
            h["Authorization"] = f"Bearer {self.token}"
        else:
            h["X-API-Token"] = self.token
        return h

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers=self._headers(), params=params or {})
            r.raise_for_status()
            if not r.content:
                return None
            return r.json()

    def list_jobs(
        self, *, limit: int = 20, offset: int = 0, project_id: str = ""
    ) -> Any:
        from autopilot_platform.platform.core.list_page import unwrap_items

        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id:
            params["project_id"] = project_id
        return unwrap_items(self._get("/api/v1/jobs", params))

    def get_job(self, job_id: str) -> Any:
        return self._get(f"/api/v1/jobs/{job_id}")

    def list_devices(self, *, limit: int = 50) -> Any:
        from autopilot_platform.platform.core.list_page import unwrap_items

        body = self._get("/api/v1/devices", {"limit": limit})
        return unwrap_items(body)

    def get_report(self, job_id: str) -> Any:
        return self._get(f"/api/v1/jobs/{job_id}/report")

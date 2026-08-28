"""Platform HTTP 客户端。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import httpx

from autopilot_platform.core.constants import API_V1_PREFIX, DEFAULT_API_TOKEN
from autopilot_platform.core.http_ssl import httpx_verify
from autopilot_platform.core.schemas import (
    DeviceInfo,
    HeartbeatIn,
    JobOut,
    JobResultIn,
    RunnerRegister,
)


def _raise_for_status(r: httpx.Response) -> None:
    """优先抛出后端错误信封中的 message（中文用户文案）。"""
    if r.is_success:
        return
    detail = ""
    try:
        body = r.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("detail") or "").strip()
    except (ValueError, TypeError):
        detail = (r.text or "").strip()
    if detail:
        raise httpx.HTTPStatusError(
            detail,
            request=r.request,
            response=r,
        )
    r.raise_for_status()


class PlatformClient:
    def __init__(
        self,
        base_url: str,
        token: str = DEFAULT_API_TOKEN,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = token
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Token": token},
            timeout=timeout,
            verify=httpx_verify(),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PlatformClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _url(path: str) -> str:
        return f"{API_V1_PREFIX}{path}"

    def register(self, body: RunnerRegister) -> dict[str, Any]:
        r = self._client.post(self._url("/runners/register"), json=body.model_dump())
        _raise_for_status(r)
        return r.json()

    def heartbeat(self, body: HeartbeatIn) -> dict[str, Any]:
        r = self._client.post(
            self._url("/runners/heartbeat"),
            json=body.model_dump(exclude_none=True),
        )
        _raise_for_status(r)
        return r.json()

    def claim(self, runner_id: str, *, wait_sec: int = 0) -> Optional[JobOut]:
        """领取任务。``wait_sec>0`` 启用服务端长轮询（需 timeout ≥ wait_sec）。"""
        params: dict[str, Any] = {"runner_id": runner_id}
        sec = max(0, min(30, int(wait_sec or 0)))
        timeout: float | httpx.Timeout | None = None
        if sec > 0:
            params["wait_sec"] = sec
            timeout = float(sec) + 10.0
        r = self._client.post(
            self._url("/jobs/claim"),
            params=params,
            timeout=timeout,
        )
        _raise_for_status(r)
        if r.status_code == 204 or not r.content or r.text in ("", "null"):
            return None
        data = r.json()
        if data is None:
            return None
        return JobOut.model_validate(data)

    def get_job(self, job_id: str) -> JobOut:
        r = self._client.get(self._url(f"/jobs/{job_id}"))
        _raise_for_status(r)
        return JobOut.model_validate(r.json())

    def mark_running(self, job_id: str, runner_id: str) -> JobOut:
        r = self._client.post(
            self._url(f"/jobs/{job_id}/running"),
            params={"runner_id": runner_id},
        )
        _raise_for_status(r)
        return JobOut.model_validate(r.json())

    def nack(self, job_id: str, runner_id: str, *, reason: str = "") -> JobOut:
        params: dict[str, Any] = {"runner_id": runner_id}
        note = (reason or "").strip()
        if note:
            params["reason"] = note
        r = self._client.post(
            self._url(f"/jobs/{job_id}/nack"),
            params=params,
        )
        _raise_for_status(r)
        return JobOut.model_validate(r.json())

    def complete(self, job_id: str, runner_id: str, body: JobResultIn) -> JobOut:
        payload = (
            body.model_dump(mode="json")
            if hasattr(body, "model_dump")
            else body.to_dict()
        )
        r = self._client.post(
            self._url(f"/jobs/{job_id}/complete"),
            params={"runner_id": runner_id},
            json=payload,
        )
        _raise_for_status(r)
        return JobOut.model_validate(r.json())

    def upload_report(self, job_id: str, runner_id: str, html_path: str) -> dict[str, Any]:
        p = Path(html_path)
        files = {"file": (p.name or "report.html", p.read_bytes(), "text/html")}
        r = self._client.post(
            self._url(f"/jobs/{job_id}/report"),
            params={"runner_id": runner_id},
            files=files,
        )
        _raise_for_status(r)
        return r.json()

    def upload_result_json(self, job_id: str, runner_id: str, json_path: str) -> dict[str, Any]:
        p = Path(json_path)
        files = {"file": ("result.json", p.read_bytes(), "application/json")}
        r = self._client.post(
            self._url(f"/jobs/{job_id}/report"),
            params={"runner_id": runner_id},
            files=files,
        )
        _raise_for_status(r)
        return r.json()

    def upload_evidence_zip(self, job_id: str, runner_id: str, zip_path: str) -> dict[str, Any]:
        """上传 D3 evidence.zip（内含 reports/evidence/**）。"""
        p = Path(zip_path)
        files = {"file": ("evidence.zip", p.read_bytes(), "application/zip")}
        r = self._client.post(
            self._url(f"/jobs/{job_id}/report"),
            params={"runner_id": runner_id},
            files=files,
        )
        _raise_for_status(r)
        return r.json()

    def append_job_log(
        self,
        job_id: str,
        runner_id: str,
        text: str,
        *,
        replace: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"runner_id": runner_id, "replace": "true" if replace else "false"}
        r = self._client.post(
            self._url(f"/jobs/{job_id}/logs"),
            params=params,
            content=(text or "").encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        _raise_for_status(r)
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {}

    def download_artifact(self, artifact_id: str, dest_dir: str) -> str:
        import zipfile
        from autopilot_platform.core.safe_zip import safe_extractall

        r = self._client.get(self._url(f"/artifacts/{artifact_id}/download"))
        _raise_for_status(r)
        root = Path(dest_dir)
        root.mkdir(parents=True, exist_ok=True)
        zip_path = root / "project.zip"
        zip_path.write_bytes(r.content)
        extract = root / "project"
        extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extractall(zf, extract)
        children = [p for p in extract.iterdir() if not p.name.startswith(".")]
        if len(children) == 1 and children[0].is_dir():
            return str(children[0].resolve())
        return str(extract.resolve())

    def download_app_build(self, build_id: str, dest_dir: str) -> str:
        from urllib.parse import unquote

        r = self._client.get(self._url(f"/app-builds/{build_id}/download"))
        _raise_for_status(r)
        root = Path(dest_dir)
        root.mkdir(parents=True, exist_ok=True)
        name = "app.bin"
        cd = r.headers.get("content-disposition") or ""
        if "filename=" in cd:
            part = cd.split("filename=", 1)[1].strip().strip("\"'")
            if part:
                name = Path(unquote(part)).name or name
        path = root / name
        path.write_bytes(r.content)
        return str(path.resolve())

    # ---- device remote (Platform Web 远控) ----

    def list_remote_commands(self, runner_id: str = "") -> list[dict[str, Any]]:
        params = {}
        if runner_id:
            params["runner_id"] = runner_id
        r = self._client.get(self._url("/runners/me/remote-commands"), params=params)
        _raise_for_status(r)
        data = r.json()
        return list(data) if isinstance(data, list) else []

    def list_prewarm_hints(self, runner_id: str = "") -> list[dict[str, Any]]:
        params = {}
        if runner_id:
            params["runner_id"] = runner_id
        r = self._client.get(self._url("/runners/me/remote-prewarm-hints"), params=params)
        _raise_for_status(r)
        data = r.json()
        return list(data) if isinstance(data, list) else []

    def post_remote_signaling(
        self, session_id: str, path: str, body: dict[str, Any]
    ) -> None:
        suffix = path if path.startswith("/") else f"/{path}"
        if not suffix.startswith("/"):
            suffix = "/" + suffix
        # path is offer|answer|ice
        kind = suffix.strip("/").split("/")[-1]
        r = self._client.post(
            self._url(f"/device-remote-sessions/{session_id}/{kind}"),
            json=body,
        )
        _raise_for_status(r)

    def poll_remote_signaling(self, session_id: str) -> dict[str, Any]:
        r = self._client.get(
            self._url(f"/device-remote-sessions/{session_id}/signaling-poll")
        )
        _raise_for_status(r)
        data = r.json()
        return data if isinstance(data, dict) else {}

    def post_remote_media(self, session_id: str, body: dict[str, Any]) -> None:
        r = self._client.post(
            self._url(f"/device-remote-sessions/{session_id}/media"),
            json=body,
        )
        _raise_for_status(r)

    def poll_remote_media(self, session_id: str) -> dict[str, Any]:
        r = self._client.get(
            self._url(f"/device-remote-sessions/{session_id}/media-poll")
        )
        _raise_for_status(r)
        data = r.json()
        return data if isinstance(data, dict) else {}

    def post_remote_device_logs(self, session_id: str, body: dict[str, Any]) -> None:
        r = self._client.post(
            self._url(f"/device-remote-sessions/{session_id}/logs"),
            json=body,
        )
        _raise_for_status(r)

    def report_remote_status(
        self,
        session_id: str,
        *,
        status: str,
        error_message: str = "",
        capabilities: list[str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "status": status,
            "error_message": error_message or "",
            "capabilities": list(capabilities or []),
        }
        r = self._client.post(
            self._url(f"/device-remote-sessions/{session_id}/runner-status"),
            json=payload,
        )
        _raise_for_status(r)


def devices_to_payload(devices: list[DeviceInfo]) -> list[dict[str, Any]]:
    return [d.model_dump() for d in devices]

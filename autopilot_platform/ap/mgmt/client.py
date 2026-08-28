"""桌面 IDE → Platform HTTP 客户端（仅投递所需 API，不依赖服务端包）。

当前实际调用：health / login / me / projects / artifacts / app-builds / jobs /
design logical-cases export。
计划、ACL、任务取消重试等一律走 Web Platform，不在此残留。
"""

from __future__ import annotations

from typing import Any


class MgmtClientError(RuntimeError):
    """管理台 HTTP 错误；可附带 status_code 便于 403 特判。"""

    def __init__(self, message: str = "", *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = int(status_code or 0)


def mgmt_error_message(err: object) -> str:
    """统一展示管理台相关错误：优先后端 message；网络失败用中文兜底。"""
    if err is None:
        return "请求失败，请重试。"
    if isinstance(err, MgmtClientError):
        text = str(err).strip()
        code = int(getattr(err, "status_code", 0) or 0)
        if code == 403:
            low = text.lower()
            if "成员" in text or "project" in low or "access" in low or "无权" in text:
                return text or "当前账号不是该项目成员，无法写入该空间。"
            return text or "权限不足（403）。"
        return text or "请求失败，请重试。"
    try:
        import httpx
    except ImportError:
        httpx = None
    if httpx is not None:
        if isinstance(err, httpx.ConnectError):
            return "无法连接服务器，请检查网络或服务是否已启动。"
        if isinstance(err, httpx.TimeoutException):
            return "请求超时，请稍后重试。"
        if isinstance(err, httpx.HTTPStatusError):
            # Runner/其它路径可能已把信封 message 放进异常字符串
            text = str(err).strip()
            if text and not text.startswith("Client error") and not text.startswith("Server error"):
                return text
            return f"请求失败（{err.response.status_code}）"
        if isinstance(err, httpx.HTTPError):
            return "网络请求失败，请重试。"
    if isinstance(err, (ConnectionError, TimeoutError, OSError)):
        return "无法连接服务器，请检查网络或服务是否已启动。"
    text = str(err).strip()
    return text or "请求失败，请重试。"


def _httpx():
    try:
        import httpx
        return httpx
    except ImportError as exc:
        raise MgmtClientError(
            "需要 httpx：pip install httpx 或 pip install -e \".[http]\""
        ) from exc


def _is_conflict_exists(msg: str) -> bool:
    low = (msg or "").lower()
    return (
        "already" in low
        or "exists" in low
        or "已存在" in msg
        or low.startswith("409")
    )


class MgmtClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_token: str = "",
        jwt: str = "",
        timeout: float = 60.0,
        org_id: str = "",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url:
            raise MgmtClientError("未配置管理台地址")
        httpx = _httpx()
        headers: dict[str, str] = {}
        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"
        elif api_token:
            headers["X-API-Token"] = api_token
        oid = (org_id or "").strip()
        if not oid:
            try:
                from ..runtime import settings

                oid = settings.mc_org_id() if hasattr(settings, "mc_org_id") else ""
            except (ImportError, AttributeError, TypeError, RuntimeError, ValueError):
                oid = ""
        if oid:
            headers["X-Org-Id"] = oid
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MgmtClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _items(body: Any) -> list[dict]:
        """兼容 ListPage 信封与旧版裸数组。

        Platform 的 projects / orgs / artifacts / app-builds / devices 均返回
        ``{items, total, page, page_size}``，直接 ``list()`` 会拿到键名而不是数据。
        """
        if isinstance(body, dict) and isinstance(body.get("items"), list):
            rows = body["items"]
        elif isinstance(body, list):
            rows = body
        else:
            return []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def _check(r) -> Any:  # noqa: ANN001
        if r.status_code >= 400:
            detail = r.text
            try:
                body = r.json()
                if isinstance(body, dict):
                    detail = body.get("message") or body.get("detail") or detail
            except (ValueError, TypeError):
                pass
            raise MgmtClientError(
                str(detail) if detail else f"请求失败（{r.status_code}）",
                status_code=int(r.status_code),
            )
        if not r.content or r.text in ("", "null"):
            return None
        return r.json()

    def health(self) -> dict:
        r = self._client.get("/health")
        return self._check(r) or {}

    def login(self, username: str, password: str) -> dict:
        r = self._client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        return self._check(r) or {}

    def me(self) -> dict:
        r = self._client.get("/api/v1/auth/me")
        return self._check(r) or {}

    def create_ide_handoff(self) -> str:
        """换一次性短码，供浏览器打开管理台（不把 JWT 写进 URL）。"""
        r = self._client.post("/api/v1/auth/ide-handoff")
        data = self._check(r) or {}
        return str(data.get("code") or "").strip()

    def refresh(self, refresh_token: str) -> dict:
        """POST /auth/refresh → 新 access + 轮换后的 refresh。"""
        rt = (refresh_token or "").strip()
        if not rt:
            raise MgmtClientError("refresh_token 不能为空", status_code=400)
        r = self._client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": rt},
        )
        return self._check(r) or {}

    def logout(self, refresh_token: str = "") -> None:
        """POST /auth/logout 吊销 refresh（无 token 也返回 204）。"""
        body: dict[str, str] = {}
        rt = (refresh_token or "").strip()
        if rt:
            body["refresh_token"] = rt
        r = self._client.post("/api/v1/auth/logout", json=body or None)
        if r.status_code >= 400:
            self._check(r)

    def list_projects(self) -> list[dict]:
        r = self._client.get("/api/v1/projects")
        return self._items(self._check(r))

    def list_orgs(self) -> list[dict]:
        r = self._client.get("/api/v1/orgs")
        return self._items(self._check(r))

    def upload_artifact(
        self,
        zip_bytes: bytes,
        *,
        filename: str = "project.zip",
        name: str = "",
        project_id: str = "",
    ) -> dict:
        files = {"file": (filename, zip_bytes, "application/zip")}
        data: dict[str, str] = {}
        if name:
            data["name"] = name
        if project_id:
            data["project_id"] = project_id
        r = self._client.post("/api/v1/artifacts", files=files, data=data)
        return self._check(r) or {}

    def upload_app_build(
        self,
        file_bytes: bytes,
        *,
        filename: str = "app.apk",
        name: str = "",
        project_id: str = "",
        platform: str = "",
        version_name: str = "",
        version_code: int = 0,
    ) -> dict:
        files = {"file": (filename, file_bytes, "application/octet-stream")}
        data: dict[str, str] = {}
        if name:
            data["name"] = name
        if project_id:
            data["project_id"] = project_id
        if platform:
            data["platform"] = platform
        if version_name:
            data["version_name"] = version_name
        if version_code:
            data["version_code"] = str(int(version_code))
        r = self._client.post("/api/v1/app-builds", files=files, data=data)
        return self._check(r) or {}

    def list_artifacts(self, *, project_id: str = "", limit: int = 50) -> list[dict]:
        params: dict[str, str | int] = {"limit": limit}
        if project_id:
            params["project_id"] = project_id
        r = self._client.get("/api/v1/artifacts", params=params)
        return self._items(self._check(r))

    def list_app_builds(
        self,
        *,
        project_id: str = "",
        platform: str = "",
        limit: int = 50,
    ) -> list[dict]:
        params: dict[str, str | int] = {"limit": limit}
        if project_id:
            params["project_id"] = project_id
        if platform:
            params["platform"] = platform
        r = self._client.get("/api/v1/app-builds", params=params)
        return self._items(self._check(r))

    def list_devices(self) -> list[dict]:
        r = self._client.get("/api/v1/devices")
        return self._items(self._check(r))

    def create_job(self, body: dict) -> dict:
        r = self._client.post("/api/v1/jobs", json=body)
        return self._check(r) or {}

    def get_job(self, job_id: str) -> dict:
        jid = (job_id or "").strip()
        if not jid:
            raise MgmtClientError("job_id 不能为空", status_code=400)
        r = self._client.get(f"/api/v1/jobs/{jid}")
        return self._check(r) or {}

    def enqueue_approved_cases_job(self, body: dict) -> dict:
        """把 APPROVED 逻辑用例通过专用设计域端点入队。"""
        r = self._client.post(
            "/api/v1/design/logical-cases/enqueue-job",
            json=body,
        )
        return self._check(r) or {}

    def ai_codegen(
        self,
        prompt: str,
        *,
        purpose: str = "authoring",
        project_id: str = "",
    ) -> dict:
        """链路 3：平台 LLM 网关 ``POST /ops/ai/codegen``（服务端持钥）。"""
        body: dict[str, Any] = {
            "prompt": prompt,
            "purpose": purpose or "authoring",
        }
        pid = (project_id or "").strip()
        if pid:
            body["project_id"] = pid
        r = self._client.post("/api/v1/ops/ai/codegen", json=body)
        return self._check(r) or {}

    def ai_codegen_capabilities(self) -> dict:
        """读取平台当前模型能力与链路 3 消耗边界；该调用不触发厂商 LLM。"""
        r = self._client.get("/api/v1/ops/ai/capabilities")
        return self._check(r) or {}

    def runtime_version(self) -> dict:
        """读取 Platform 执行核版本契约（普通已登录用户可读）。"""
        r = self._client.get("/api/v1/ops/runtime-version")
        return self._check(r) or {}

    def register_runner(self, body: dict) -> dict:
        r = self._client.post("/api/v1/runners/register", json=body)
        return self._check(r) or {}

    def issue_scoped_runner_token(
        self,
        runner_id: str,
        *,
        org_id: str = "",
        project_ids: list[str] | None = None,
    ) -> dict:
        rid = (runner_id or "").strip()
        if not rid:
            raise MgmtClientError("runner_id 不能为空")
        body = {
            "org_id": (org_id or "").strip(),
            "project_ids": list(project_ids or []),
        }
        r = self._client.post(f"/api/v1/runners/{rid}/scoped-token", json=body)
        return self._check(r) or {}

    def generate_logical_cases(self, body: dict) -> list[dict]:
        """AI / 启发式生成逻辑用例。"""
        r = self._client.post("/api/v1/design/logical-cases/generate", json=body or {})
        out = self._check(r)
        return list(out or [])

    def create_logical_case(self, body: dict) -> dict:
        """手工创建逻辑用例（可带 intent_steps）。"""
        r = self._client.post("/api/v1/design/logical-cases", json=body or {})
        return self._check(r) or {}

    def export_approved_logical_cases(self, project_id: str) -> dict:
        """拉取 Platform 已 APPROVED 的逻辑用例导出包。"""
        pid = (project_id or "").strip()
        if not pid:
            raise MgmtClientError("project_id 不能为空")
        r = self._client.get(f"/api/v1/design/projects/{pid}/logical-cases/export")
        return self._check(r) or {}

    def list_logical_cases(
        self,
        *,
        project_id: str = "",
        review_status: str = "",
    ) -> list[dict]:
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        if review_status:
            params["review_status"] = review_status
        r = self._client.get("/api/v1/design/logical-cases", params=params)
        return self._items(self._check(r))

    def update_logical_case(self, case_id: str, body: dict) -> dict:
        """PATCH 逻辑用例（如 automation_status）。"""
        cid = (case_id or "").strip()
        if not cid:
            raise MgmtClientError("logical_case_id 不能为空")
        r = self._client.patch(f"/api/v1/design/logical-cases/{cid}", json=body or {})
        return self._check(r) or {}

    def set_automation_status(self, case_id: str, status: str) -> dict:
        return self.update_logical_case(case_id, {"automation_status": status})

    def create_project(
        self,
        project_id: str,
        *,
        name: str = "",
        description: str = "",
    ) -> dict:
        body = {
            "id": project_id,
            "name": name or project_id,
            "description": description or "",
        }
        r = self._client.post("/api/v1/projects", json=body)
        return self._check(r) or {}

    def ensure_project(self, project_id: str, *, name: str = "") -> dict | None:
        """若不存在则创建项目空间；已存在则返回 None（忽略 409/冲突类错误）。"""
        pid = (project_id or "").strip()
        if not pid:
            return None
        try:
            return self.create_project(pid, name=name or pid)
        except MgmtClientError as exc:
            if _is_conflict_exists(str(exc)):
                return None
            raise

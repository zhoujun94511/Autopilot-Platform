"""创建用户请求体：统一走 duty，不再发 role/org_role/project_role。"""

from __future__ import annotations


def user_create_body(
    username: str,
    password: str,
    *,
    duty: str = "user",
    project_id: str | None = None,
) -> dict[str, str]:
    body = {"username": username, "password": password, "duty": duty}
    if project_id:
        body["project_id"] = project_id
    return body

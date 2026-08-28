"""人设 RBAC 白盒：直接测 tenancy / design_access / 删除服务，不经完整 HTTP 栈。

覆盖 ORG_RBAC_PLAN §8 与落地硬化：
- 空 project 读写门禁
- project_to_out.my_role
- viewer 写拒绝 / member 写放行
- 跨项目 batch-delete 预检
- 建组织仅 platform admin
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from typing import cast

from fastapi.testclient import TestClient

from autopilot_platform.core.schemas import OrganizationCreate
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.core import api_messages as msg
from autopilot_platform.platform.core.db import get_engine, reset_engine
from autopilot_platform.platform.core.models import (
    OrganizationMemberRow,
    OrganizationRow,
    ProjectMemberRow,
    ProjectRow,
    UserRow,
    new_id,
)
from autopilot_platform.platform.design.design_models import LogicalCaseRow
from autopilot_platform.platform.services.design.cases import crud as design_svc
from autopilot_platform.platform.services.design import access as design_access
from autopilot_platform.platform.services.design.requirements import crud as req_svc
from autopilot_platform.platform.tenancy import organizations as org_svc
from autopilot_platform.platform.tenancy import projects as proj_svc


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "persona_wb.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _user_auth(
    *,
    user_id: str,
    username: str,
    role: str = "operator",
    org_id: str = "",
) -> AuthContext:
    return AuthContext(
        kind="user",
        user_id=user_id,
        username=username,
        role=role,
        org_id=org_id,
    )


def _seed_project_with_roles(db: Session) -> dict[str, AuthContext]:
    """pa: alice=member, bob=viewer；pb: 仅 admin 旁路。项目必须落在组织内。"""
    admin = UserRow(
        id=new_id(), username="admin-wb", password_hash="x", role="admin"
    )
    alice = UserRow(
        id=new_id(), username="alice-wb", password_hash="x", role="operator"
    )
    bob = UserRow(
        id=new_id(), username="bob-wb", password_hash="x", role="operator"
    )
    db.add_all([admin, alice, bob])
    db.flush()
    db.add(OrganizationRow(id="org-wb", name="WB", created_by=admin.id))
    db.flush()
    db.add_all(
        [
            OrganizationMemberRow(
                id=new_id(), org_id="org-wb", user_id=alice.id, role="member"
            ),
            OrganizationMemberRow(
                id=new_id(), org_id="org-wb", user_id=bob.id, role="member"
            ),
        ]
    )
    db.flush()
    for pid in ("pa-wb", "pb-wb"):
        db.add(
            ProjectRow(
                id=pid,
                name=pid,
                description="",
                owner_user_id=admin.id,
                org_id="org-wb",
            )
        )
    db.flush()
    db.add_all(
        [
            ProjectMemberRow(
                id=new_id(),
                project_id="pa-wb",
                user_id=alice.id,
                role="member",
            ),
            ProjectMemberRow(
                id=new_id(),
                project_id="pa-wb",
                user_id=bob.id,
                role="viewer",
            ),
            ProjectMemberRow(
                id=new_id(),
                project_id="pa-wb",
                user_id=admin.id,
                role="owner",
            ),
            ProjectMemberRow(
                id=new_id(),
                project_id="pb-wb",
                user_id=admin.id,
                role="owner",
            ),
        ]
    )
    db.commit()
    return {
        "admin": _user_auth(user_id=admin.id, username=admin.username, role="admin"),
        "alice": _user_auth(user_id=alice.id, username=alice.username),
        "bob": _user_auth(user_id=bob.id, username=bob.username),
    }


# ---------------------------------------------------------------------------
# tenancy 白盒
# ---------------------------------------------------------------------------


def test_assert_empty_project_write_denied_for_operator(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auth = _user_auth(user_id="u1", username="op")
        with pytest.raises(PermissionError, match=msg.PROJECT_ID_REQUIRED):
            proj_svc.assert_can_write_project(db, auth, "")
        with pytest.raises(PermissionError, match=msg.PROJECT_ID_REQUIRED):
            proj_svc.assert_can_access_project(db, auth, "")


def test_assert_empty_project_denied_for_admin(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auth = _user_auth(user_id="a1", username="admin", role="admin")
        with pytest.raises(PermissionError, match=msg.PROJECT_ID_REQUIRED):
            proj_svc.assert_can_write_project(db, auth, "")
        with pytest.raises(PermissionError, match=msg.PROJECT_ID_REQUIRED):
            proj_svc.assert_can_access_project(db, auth, "")


def test_viewer_cannot_write_member_can(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auths = _seed_project_with_roles(db)
        proj_svc.assert_can_access_project(db, auths["bob"], "pa-wb")
        with pytest.raises(PermissionError):
            proj_svc.assert_can_write_project(db, auths["bob"], "pa-wb")
        proj_svc.assert_can_write_project(db, auths["alice"], "pa-wb")


def test_project_to_out_my_role_matrix(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auths = _seed_project_with_roles(db)
        row = db.get(ProjectRow, "pa-wb")
        assert row is not None
        proj_row = cast(ProjectRow, row)
        assert proj_svc.project_to_out(proj_row, db, auths["admin"]).my_role == "owner"
        assert proj_svc.project_to_out(proj_row, db, auths["alice"]).my_role == "member"
        assert proj_svc.project_to_out(proj_row, db, auths["bob"]).my_role == "viewer"
        # 无 auth 时不下发角色
        assert proj_svc.project_to_out(proj_row).my_role == ""


# ---------------------------------------------------------------------------
# design_access / 删除服务白盒
# ---------------------------------------------------------------------------


def test_ensure_row_project_write_viewer_403(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auths = _seed_project_with_roles(db)
        with pytest.raises(HTTPException) as ei:
            design_access.ensure_row_project_write(db, auths["bob"], "pa-wb")
        assert ei.value.status_code == 403
        design_access.ensure_row_project_write(db, auths["alice"], "pa-wb")


def test_batch_delete_requirements_cross_project_aborts(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auths = _seed_project_with_roles(db)
        from autopilot_platform.platform.design.design_schemas import RequirementCreate

        own = req_svc.create_requirement(
            db,
            RequirementCreate(project_id="pa-wb", title="own", content="a"),
            auths["alice"],
        )
        other = req_svc.create_requirement(
            db,
            RequirementCreate(project_id="pb-wb", title="other", content="b"),
            auths["admin"],
        )
        with pytest.raises(HTTPException) as ei:
            req_svc.batch_delete_requirements(
                db, [own.id, other.id], auths["alice"]
            )
        assert ei.value.status_code == 403
        # 预检失败：两侧仍在
        assert req_svc.get_requirement(db, own.id).id == own.id
        assert req_svc.get_requirement(db, other.id).id == other.id


def test_batch_delete_logical_cases_cross_project_aborts(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auths = _seed_project_with_roles(db)
        own = LogicalCaseRow(
            id=new_id(),
            project_id="pa-wb",
            title="own-case",
            description="",
            review_status="AI_DRAFT",
            automation_status="DRAFT",
        )
        other = LogicalCaseRow(
            id=new_id(),
            project_id="pb-wb",
            title="other-case",
            description="",
            review_status="AI_DRAFT",
            automation_status="DRAFT",
        )
        db.add_all([own, other])
        db.commit()
        with pytest.raises(HTTPException) as ei:
            design_svc.batch_delete_logical_cases(
                db, [own.id, other.id], auths["alice"]
            )
        assert ei.value.status_code == 403
        assert db.get(LogicalCaseRow, own.id) is not None
        assert db.get(LogicalCaseRow, other.id) is not None


def test_delete_requirement_viewer_denied(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auths = _seed_project_with_roles(db)
        from autopilot_platform.platform.design.design_schemas import RequirementCreate

        row = req_svc.create_requirement(
            db,
            RequirementCreate(project_id="pa-wb", title="v", content="x"),
            auths["alice"],
        )
        with pytest.raises(HTTPException) as ei:
            req_svc.delete_requirement(db, row.id, auths["bob"])
        assert ei.value.status_code == 403
        assert req_svc.get_requirement(db, row.id).id == row.id


def test_create_organization_operator_denied_admin_ok(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        op = UserRow(
            id=new_id(), username="org-op", password_hash="x", role="operator"
        )
        adm = UserRow(
            id=new_id(), username="org-adm", password_hash="x", role="admin"
        )
        db.add_all([op, adm])
        db.commit()
        op_auth = _user_auth(user_id=op.id, username=op.username)
        adm_auth = _user_auth(user_id=adm.id, username=adm.username, role="admin")
        with pytest.raises(PermissionError, match=msg.AUTH_ADMIN_REQUIRED):
            org_svc.create_organization(
                db, OrganizationCreate(id="bu-op", name="Op"), op_auth
            )
        out = org_svc.create_organization(
            db, OrganizationCreate(id="bu-ok", name="Ok"), adm_auth
        )
        assert out.id == "bu-ok"
        assert out.my_role == "owner"


# ---------------------------------------------------------------------------
# HTTP 补充：知识库跨项目 batch-delete + viewer 用例删除
# ---------------------------------------------------------------------------


def _login(client: TestClient, user="admin", password="admin") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_http_knowledge_batch_delete_cross_project(client: TestClient):
    ah = _login(client)
    assert (
        client.post("/api/v1/orgs", headers=ah, json={"id": "org-k", "name": "K"}).status_code
        == 200
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "k-alice", "password": "Alice123", "duty": "user"},
    )
    for pid in ("k-a", "k-b"):
        assert (
            client.post(
                "/api/v1/projects",
                headers={**ah, "X-Org-Id": "org-k"},
                json={"id": pid, "name": pid, "org_id": "org-k"},
            ).status_code
            == 200
        )
    assert (
        client.post(
            "/api/v1/projects/k-a/members",
            headers=ah,
            json={"username": "k-alice", "role": "member"},
        ).status_code
        == 200
    )
    alice = _login(client, "k-alice", "Alice123")
    r = client.post(
        "/api/v1/design/knowledge",
        headers=alice,
        json={"project_id": "k-a", "title": "own", "content": "c1", "category": "rule"},
    )
    assert r.status_code == 200, r.text
    own_id = r.json()["id"]
    r = client.post(
        "/api/v1/design/knowledge",
        headers=ah,
        json={"project_id": "k-b", "title": "other", "content": "c2", "category": "rule"},
    )
    assert r.status_code == 200, r.text
    other_id = r.json()["id"]
    r = client.post(
        "/api/v1/design/knowledge/batch-delete",
        headers=alice,
        json={"item_ids": [own_id, other_id]},
    )
    assert r.status_code == 403, r.text
    assert client.get(f"/api/v1/design/knowledge/{own_id}", headers=alice).status_code == 200
    assert client.get(f"/api/v1/design/knowledge/{other_id}", headers=ah).status_code == 200


def test_http_viewer_cannot_delete_logical_case(client: TestClient):
    ah = _login(client)
    assert (
        client.post("/api/v1/orgs", headers=ah, json={"id": "org-v", "name": "V"}).status_code
        == 200
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "v-bob", "password": "Bob12345", "duty": "user"},
    )
    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": "org-v"},
            json={"id": "v-p", "name": "V", "org_id": "org-v"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/v-p/members",
            headers=ah,
            json={"username": "v-bob", "role": "viewer"},
        ).status_code
        == 200
    )
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=ah,
        json={
            "project_id": "v-p",
            "title": "case-1",
            "description": "",
            "logical_steps": ["step-1"],
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json().get("logical_case_id") or r.json().get("id")
    assert case_id
    bob = _login(client, "v-bob", "Bob12345")
    r = client.delete(f"/api/v1/design/logical-cases/{case_id}", headers=bob)
    assert r.status_code == 403, r.text
    assert client.get(f"/api/v1/design/logical-cases/{case_id}", headers=bob).status_code == 200

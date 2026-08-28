"""RBAC 矩阵：ROLE_POLICIES 常量 + can() 关键单元格。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.core.db import get_engine, reset_engine
from autopilot_platform.platform.core.models import (
    OrganizationMemberRow,
    OrganizationRow,
    ProjectMemberRow,
    ProjectRow,
    UserRow,
    new_id,
)
from autopilot_platform.platform.authz import rbac
from autopilot_platform.platform.tenancy.projects import visible_project_filter


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "rbac.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
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


def test_org_policies_never_grant_project_content():
    """进组织 ≠ 进项目：org:* 策略不含 design/artifact/job 读。"""
    for key in ("org:owner", "org:admin", "org:member"):
        allowed = rbac.ROLE_POLICIES[key]
        for res in rbac.PROJECT_CONTENT_RESOURCES:
            if res == rbac.RESOURCE_PROJECT:
                # project.create：owner/admin 在策略表；member 由组织开关放行，不在 ROLE_POLICIES
                assert (res, rbac.ACTION_META_READ) not in allowed
                assert (res, rbac.ACTION_READ) not in allowed
                assert (res, rbac.ACTION_WRITE) not in allowed
                continue
            assert (res, rbac.ACTION_READ) not in allowed, f"{key} leaked {res}.read"
            assert (res, rbac.ACTION_WRITE) not in allowed, f"{key} leaked {res}.write"


def test_viewer_read_only_in_policies():
    allowed = rbac.ROLE_POLICIES["project:viewer"]
    assert (rbac.RESOURCE_DESIGN, rbac.ACTION_READ) in allowed
    assert (rbac.RESOURCE_DESIGN, rbac.ACTION_WRITE) not in allowed
    assert (rbac.RESOURCE_ARTIFACT, rbac.ACTION_WRITE) not in allowed
    assert (rbac.RESOURCE_JOB, rbac.ACTION_WRITE) not in allowed
    assert (rbac.RESOURCE_POOL, rbac.ACTION_READ) in allowed
    assert (rbac.RESOURCE_POOL, rbac.ACTION_MANAGE) not in allowed
    assert (rbac.RESOURCE_POOL, rbac.ACTION_MANAGE) in rbac.ROLE_POLICIES["org:admin"]
    assert (rbac.RESOURCE_POOL, rbac.ACTION_MANAGE) not in rbac.ROLE_POLICIES["org:member"]


def test_can_assign_role_rank():
    assert rbac.can_assign_org_role("admin", "member")
    assert rbac.can_assign_org_role("admin", "admin")
    assert not rbac.can_assign_org_role("admin", "owner")
    assert rbac.can_assign_org_role("owner", "owner")
    assert rbac.can_assign_project_role("owner", "viewer")
    assert not rbac.can_assign_project_role("member", "owner")


@pytest.mark.parametrize(
    ("project_role", "design_read", "design_write"),
    [
        ("owner", True, True),
        ("member", True, True),
        ("viewer", True, False),
        (None, False, False),
    ],
)
def test_can_design_by_project_role(client: TestClient, project_role, design_read, design_write):
    eng = get_engine()
    suffix = f"{project_role or 'none'}-{new_id()[:8]}"
    oid = f"org-m-{suffix}"
    pid = f"proj-m-{suffix}"
    with Session(eng) as db:
        u = UserRow(
            id=new_id(),
            username=f"u-{suffix}",
            password_hash="x",
            role="operator",
        )
        db.add(u)
        db.add(OrganizationRow(id=oid, name="M", created_by="admin"))
        db.flush()
        db.add(
            OrganizationMemberRow(
                id=new_id(), org_id=oid, user_id=u.id, role="member"
            )
        )
        db.add(
            ProjectRow(
                id=pid, name="P", org_id=oid, owner_user_id=u.id
            )
        )
        db.flush()
        if project_role:
            db.add(
                ProjectMemberRow(
                    id=new_id(),
                    project_id=pid,
                    user_id=u.id,
                    role=project_role,
                )
            )
        db.commit()
        auth = AuthContext(
            kind="user",
            username=u.username,
            user_id=u.id,
            role="operator",
            org_id=oid,
        )
        assert (
            rbac.can(
                db, auth, rbac.RESOURCE_DESIGN, rbac.ACTION_READ, project_id=pid
            )
            is design_read
        )
        assert (
            rbac.can(
                db, auth, rbac.RESOURCE_DESIGN, rbac.ACTION_WRITE, project_id=pid
            )
            is design_write
        )
        # 组织角色不授予内容（无 project_id 时 design 直接 deny）
        assert not rbac.can(
            db, auth, rbac.RESOURCE_DESIGN, rbac.ACTION_READ, org_id=oid
        )


def test_org_admin_has_project_owner_on_own_org(client: TestClient):
    """本组织 owner/admin 对本组织全部项目可写（含未加入 project_members 的脏 viewer 行）。"""
    eng = get_engine()
    suffix = new_id()[:8]
    oid = f"org-adm-{suffix}"
    pid_v = f"proj-v-{suffix}"
    pid_n = f"proj-n-{suffix}"
    with Session(eng) as db:
        u = UserRow(
            id=new_id(),
            username=f"oa-{suffix}",
            password_hash="x",
            role="operator",
        )
        db.add(u)
        db.add(OrganizationRow(id=oid, name="A", created_by="admin"))
        db.flush()
        db.add(
            OrganizationMemberRow(
                id=new_id(), org_id=oid, user_id=u.id, role="admin"
            )
        )
        db.add(ProjectRow(id=pid_v, name="V", org_id=oid, owner_user_id="admin"))
        db.add(ProjectRow(id=pid_n, name="N", org_id=oid, owner_user_id="admin"))
        db.flush()
        db.add(
            ProjectMemberRow(
                id=new_id(),
                project_id=pid_v,
                user_id=u.id,
                role="viewer",
            )
        )
        db.commit()
        auth = AuthContext(
            kind="user",
            username=u.username,
            user_id=u.id,
            role="operator",
            org_id=oid,
        )
        assert rbac.can(
            db, auth, rbac.RESOURCE_DESIGN, rbac.ACTION_WRITE, project_id=pid_v
        )
        assert rbac.can(
            db, auth, rbac.RESOURCE_DESIGN, rbac.ACTION_WRITE, project_id=pid_n
        )
        assert rbac.org_admin_elevates_project(db, auth, project_id=pid_v)


def test_cross_org_project_member_is_ignored(client: TestClient):
    """隔壁组织的人即使被误写成 project viewer，也不能读本组织项目。"""
    eng = get_engine()
    suffix = new_id()[:8]
    oid_a = f"org-a-{suffix}"
    oid_b = f"org-b-{suffix}"
    pid = f"proj-a-{suffix}"
    with Session(eng) as db:
        ua = UserRow(
            id=new_id(), username=f"a-{suffix}", password_hash="x", role="operator"
        )
        ub = UserRow(
            id=new_id(), username=f"b-{suffix}", password_hash="x", role="operator"
        )
        db.add_all([ua, ub])
        db.add(OrganizationRow(id=oid_a, name="A", created_by="admin"))
        db.add(OrganizationRow(id=oid_b, name="B", created_by="admin"))
        db.flush()
        db.add(OrganizationMemberRow(id=new_id(), org_id=oid_a, user_id=ua.id, role="member"))
        db.add(OrganizationMemberRow(id=new_id(), org_id=oid_b, user_id=ub.id, role="admin"))
        db.add(ProjectRow(id=pid, name="PA", org_id=oid_a, owner_user_id=ua.id))
        db.flush()
        db.add(
            ProjectMemberRow(
                id=new_id(), project_id=pid, user_id=ub.id, role="viewer"
            )
        )
        db.commit()
        auth_b = AuthContext(
            kind="user",
            username=ub.username,
            user_id=ub.id,
            role="operator",
            org_id=oid_b,
        )
        assert not rbac.user_in_project_org(db, ub.id, pid)
        assert not rbac.can(
            db, auth_b, rbac.RESOURCE_DESIGN, rbac.ACTION_READ, project_id=pid
        )
        vis = visible_project_filter(db, auth_b)
        assert vis is not None and pid not in vis


def test_platform_admin_bypasses(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        auth = AuthContext(kind="user", username="admin", user_id="1", role="admin")
        assert rbac.can(
            db, auth, rbac.RESOURCE_DESIGN, rbac.ACTION_WRITE, project_id="any"
        )
        assert rbac.can(db, auth, rbac.RESOURCE_ORG, rbac.ACTION_MANAGE_USERS, org_id="x")


def test_policy_allows_unknown_role_false():
    assert not rbac.policy_allows("org:ghost", rbac.RESOURCE_ORG, rbac.ACTION_READ)
    assert rbac.policy_allows("org:member", rbac.RESOURCE_ORG, rbac.ACTION_READ)
    assert not rbac.policy_allows("org:member", rbac.RESOURCE_PROJECT, rbac.ACTION_CREATE)
    assert rbac.policy_allows("org:admin", rbac.RESOURCE_PROJECT, rbac.ACTION_CREATE)
    assert rbac.policy_allows("org:owner", rbac.RESOURCE_PROJECT, rbac.ACTION_CREATE)

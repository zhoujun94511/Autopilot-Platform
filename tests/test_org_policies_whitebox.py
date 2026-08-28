"""组织权限策略白盒：服务层 + rbac.can + 源码/契约钉死。

覆盖上两轮改动：
- policies_json 解析 / org_policy_enabled（经 db_get）
- org:member 默认无 project.create；策略打开后 can() 放行
- update_org_policies / assert_can_add_org_member
- create_project 对 member 的明确拒绝文案
- OrganizationRow 查询统一 db_get（消除 Session.get 类型误判）
- SCHEMA_ADDS / Alembic / OpenAPI / 前端能力档与组织设置 UI
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.schemas import (
    OrganizationMemberIn,
    OrganizationPoliciesPatch,
    ProjectCreate,
)
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.core import api_messages as msg
from autopilot_platform.platform.core.db import get_engine, reset_engine
from autopilot_platform.platform.core.models import (
    OrganizationMemberRow,
    OrganizationRow,
    UserRow,
    db_get,
    new_id,
)
from autopilot_platform.platform.tenancy import organizations as org_svc
from autopilot_platform.platform.authz import rbac
from autopilot_platform.platform.tenancy import projects as proj_svc

FE = ROOT / "autopilot_platform" / "frontend" / "src"
ORG_SVC = (
    ROOT
    / "autopilot_platform"
    / "platform"
    / "tenancy"
    / "organizations.py"
)
RBAC_PY = ROOT / "autopilot_platform" / "platform" / "authz" / "rbac.py"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "org_pol_wb.db"
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


def _auth(
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


def _seed_org_roles(db: Session) -> dict:
    """owner / admin / member 同组织；policies 默认 {}。"""
    owner = UserRow(id=new_id(), username="own-wb", password_hash="x", role="operator")
    admin = UserRow(id=new_id(), username="adm-wb", password_hash="x", role="operator")
    member = UserRow(id=new_id(), username="mem-wb", password_hash="x", role="operator")
    outsider = UserRow(id=new_id(), username="out-wb", password_hash="x", role="operator")
    padmin = UserRow(id=new_id(), username="padm-wb", password_hash="x", role="admin")
    db.add_all([owner, admin, member, outsider, padmin])
    oid = f"org-wb-{new_id()[:8]}"
    db.add(
        OrganizationRow(
            id=oid,
            name="WB Org",
            created_by=owner.username,
            policies_json="{}",
        )
    )
    db.flush()
    for u, role in (
        (owner, "owner"),
        (admin, "admin"),
        (member, "member"),
    ):
        db.add(
            OrganizationMemberRow(
                id=new_id(), org_id=oid, user_id=u.id, role=role
            )
        )
    db.commit()
    return {
        "org_id": oid,
        "owner": _auth(user_id=owner.id, username=owner.username, org_id=oid),
        "admin": _auth(user_id=admin.id, username=admin.username, org_id=oid),
        "member": _auth(user_id=member.id, username=member.username, org_id=oid),
        "outsider": _auth(user_id=outsider.id, username=outsider.username),
        "platform_admin": _auth(
            user_id=padmin.id, username=padmin.username, role="admin", org_id=oid
        ),
        "invitee": outsider,
    }


# ---------------------------------------------------------------------------
# 纯函数：策略 JSON 解析
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expect_create", "expect_invite"),
    [
        (None, False, False),
        ("", False, False),
        ("{}", False, False),
        ("not-json", False, False),
        ("[]", False, False),
        ('{"members_can_create_projects": true}', True, False),
        ('{"members_can_invite": 1}', False, True),
        (
            '{"members_can_create_projects": true, "members_can_invite": true, "extra": 1}',
            True,
            True,
        ),
        ('{"members_can_create_projects": false, "members_can_invite": false}', False, False),
    ],
)
def test_parse_org_policies_matrix(raw, expect_create, expect_invite):
    got = org_svc.parse_org_policies(raw)
    assert set(got) == set(org_svc.ORG_POLICY_KEYS)
    assert got["members_can_create_projects"] is expect_create
    assert got["members_can_invite"] is expect_invite


def test_org_to_out_embeds_policies():
    row = OrganizationRow(
        id="o1",
        name="N",
        policies_json='{"members_can_create_projects": true}',
    )
    out = org_svc.org_to_out(row, my_role="member")
    assert out.policies.members_can_create_projects is True
    assert out.policies.members_can_invite is False
    assert out.my_role == "member"


# ---------------------------------------------------------------------------
# 服务层 + rbac.can（不经 HTTP）
# ---------------------------------------------------------------------------


def test_org_policy_enabled_via_db_get(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        ctx = _seed_org_roles(db)
        oid = str(ctx["org_id"])
        assert org_svc.org_policy_enabled(db, oid, "members_can_create_projects") is False
        assert org_svc.org_policy_enabled(db, "", "members_can_create_projects") is False
        assert org_svc.org_policy_enabled(db, oid, "unknown_key") is False
        assert org_svc.org_policy_enabled(db, "missing-org", "members_can_create_projects") is False

        row = db_get(db, OrganizationRow, oid)
        assert row is not None
        assert isinstance(row, OrganizationRow)
        row.policies_json = json.dumps(
            {"members_can_create_projects": True, "members_can_invite": True}
        )
        db.commit()
        assert org_svc.org_policy_enabled(db, oid, "members_can_create_projects") is True
        assert org_svc.org_policy_enabled(db, oid, "members_can_invite") is True


def test_rbac_can_project_create_respects_org_policy(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        ctx = _seed_org_roles(db)
        oid = str(ctx["org_id"])
        member = ctx["member"]
        owner = ctx["owner"]

        assert rbac.can(
            db, owner, rbac.RESOURCE_PROJECT, rbac.ACTION_CREATE, org_id=oid
        )
        assert not rbac.can(
            db, member, rbac.RESOURCE_PROJECT, rbac.ACTION_CREATE, org_id=oid
        )

        row = db_get(db, OrganizationRow, oid)
        assert row is not None
        row.policies_json = '{"members_can_create_projects": true}'
        db.commit()
        assert rbac.can(
            db, member, rbac.RESOURCE_PROJECT, rbac.ACTION_CREATE, org_id=oid
        )


def test_create_project_member_denied_message(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        ctx = _seed_org_roles(db)
        oid = str(ctx["org_id"])
        member = ctx["member"]
        with pytest.raises(PermissionError) as exc:
            proj_svc.create_project(
                db,
                ProjectCreate(id=f"p-{new_id()[:8]}", name="X", org_id=oid),
                member,
            )
        assert str(exc.value) == msg.ORG_PROJECT_CREATE_DENIED


def test_update_org_policies_owner_only(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        ctx = _seed_org_roles(db)
        oid = str(ctx["org_id"])
        owner = ctx["owner"]
        member = ctx["member"]

        out = org_svc.update_org_policies(
            db,
            oid,
            OrganizationPoliciesPatch(members_can_invite=True),
            owner,
        )
        assert out.policies.members_can_invite is True
        assert out.policies.members_can_create_projects is False

        with pytest.raises(PermissionError):
            org_svc.update_org_policies(
                db,
                oid,
                OrganizationPoliciesPatch(members_can_create_projects=True),
                member,
            )


def test_assert_can_add_org_member_invite_switch(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        ctx = _seed_org_roles(db)
        oid = str(ctx["org_id"])
        member = ctx["member"]
        owner = ctx["owner"]

        with pytest.raises(PermissionError) as exc:
            org_svc.assert_can_add_org_member(
                db, member, oid, target_role="member"
            )
        assert str(exc.value) == msg.ORG_OWNER_ADMIN_REQUIRED

        org_svc.assert_can_add_org_member(db, owner, oid, target_role="admin")

        row = db_get(db, OrganizationRow, oid)
        assert row is not None
        row.policies_json = '{"members_can_invite": true}'
        db.commit()

        org_svc.assert_can_add_org_member(db, member, oid, target_role="member")
        with pytest.raises(PermissionError) as exc2:
            org_svc.assert_can_add_org_member(
                db, member, oid, target_role="admin"
            )
        assert str(exc2.value) == msg.ORG_ROLE_CANNOT_ELEVATE


def test_add_org_member_member_cannot_elevate_existing(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        ctx = _seed_org_roles(db)
        oid = str(ctx["org_id"])
        member = ctx["member"]
        invitee = ctx["invitee"]

        row = db_get(db, OrganizationRow, oid)
        assert row is not None
        row.policies_json = '{"members_can_invite": true}'
        db.commit()

        out = org_svc.add_org_member(
            db,
            oid,
            OrganizationMemberIn(username=invitee.username, role="member"),
            member,
        )
        assert out.role == "member"

        with pytest.raises(PermissionError):
            org_svc.add_org_member(
                db,
                oid,
                OrganizationMemberIn(username=invitee.username, role="admin"),
                member,
            )


def test_member_create_project_after_policy_service(client: TestClient):
    eng = get_engine()
    with Session(eng) as db:
        ctx = _seed_org_roles(db)
        oid = str(ctx["org_id"])
        member = ctx["member"]
        owner = ctx["owner"]

        org_svc.update_org_policies(
            db,
            oid,
            OrganizationPoliciesPatch(members_can_create_projects=True),
            owner,
        )
        pid = f"p-mem-{new_id()[:8]}"
        out = proj_svc.create_project(
            db,
            ProjectCreate(id=pid, name="ByMember", org_id=oid),
            member,
        )
        assert out.id == pid
        assert out.org_id == oid
        assert out.my_role == "owner"


# ---------------------------------------------------------------------------
# 源码 / 契约白盒
# ---------------------------------------------------------------------------


def test_organizations_uses_db_get_not_session_get():
    """第二轮类型修复：OrganizationRow 查询必须走 db_get。"""
    text = ORG_SVC.read_text(encoding="utf-8")
    assert "from ..core.models import" in text
    assert "db_get" in text
    assert "db.get(OrganizationRow" not in text
    assert text.count("db_get(db, OrganizationRow") >= 5


def test_rbac_member_create_delegates_to_org_policy():
    text = RBAC_PY.read_text(encoding="utf-8")
    assert "ROLE_POLICIES" in text
    member_block = text.split('"org:member":')[1].split('"project:owner":')[0]
    assert "ACTION_CREATE" not in member_block
    assert "org_policy_enabled" in text
    assert "members_can_create_projects" in text


def test_schema_adds_and_alembic_policies_json():
    from autopilot_platform.platform.core.schema_adds import SCHEMA_ADDS

    assert ("organizations", "policies_json", "TEXT DEFAULT '{}'") in SCHEMA_ADDS
    rev = ROOT / "alembic" / "versions" / "f8c1d4a27e90_org_policies_json.py"
    assert rev.is_file()
    body = rev.read_text(encoding="utf-8")
    assert 'revision: str = "f8c1d4a27e90"' in body
    assert "policies_json" in body
    assert "down_revision" in body and "e4f8a1c209b7" in body


def test_openapi_exposes_org_policies_patch():
    contract = ROOT / "contracts" / "openapi" / "openapi.v1.json"
    assert contract.is_file()
    spec = json.loads(contract.read_text(encoding="utf-8"))
    assert "/api/v1/orgs/{org_id}/policies" in spec["paths"]
    assert "patch" in spec["paths"]["/api/v1/orgs/{org_id}/policies"]
    schemas = spec["components"]["schemas"]
    assert "OrganizationPolicies" in schemas
    assert "OrganizationPoliciesPatch" in schemas
    props = schemas["OrganizationOut"]["properties"]
    assert "policies" in props


def test_frontend_org_policies_capability_wiring():
    orgs_ts = (FE / "api" / "orgs.ts").read_text(encoding="utf-8")
    assert "export type OrganizationPolicies" in orgs_ts
    assert "members_can_create_projects" in orgs_ts
    assert "members_can_invite" in orgs_ts
    assert "export function orgPoliciesOf" in orgs_ts
    assert "export async function patchOrgPolicies" in orgs_ts
    assert "/policies" in orgs_ts

    caps = (FE / "composables" / "useCapabilities.ts").read_text(encoding="utf-8")
    assert "canCreateProject" in caps
    assert "canInviteOrgMember" in caps
    assert "orgPoliciesOf" in caps
    assert "members_can_create_projects" in caps
    assert "members_can_invite" in caps

    panel = (FE / "components" / "ProjectsPanel.vue").read_text(encoding="utf-8")
    assert "caps.canCreateProject" in panel

    plist = (FE / "components" / "projects" / "ProjectList.vue").read_text(
        encoding="utf-8"
    )
    assert "caps.canCreateProject" in plist

    org = (FE / "components" / "projects" / "OrgSettingsSection.vue").read_text(
        encoding="utf-8"
    )
    assert "patchOrgPolicies" in org
    assert "onPolicyToggle" in org
    assert "caps.canInviteOrgMember" in org
    assert "members_can_create_projects" in org
    assert "members_can_invite" in org


def test_boundary_contract_documents_org_policy_switches():
    text = (
        ROOT / "docs" / "architecture" / "RBAC_BOUNDARY_CONTRACT.md"
    ).read_text(encoding="utf-8")
    assert "members_can_create_projects" in text
    assert "members_can_invite" in text
    assert "组织权限开关" in text

    plan = (ROOT / "docs" / "architecture" / "ORG_RBAC_PLAN.md").read_text(
        encoding="utf-8"
    )
    assert "默认 ✗，组织策略可开" in plan
    assert "members_can_create_projects" in plan

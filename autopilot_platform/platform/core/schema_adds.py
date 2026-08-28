"""增量列清单（AUD-P2-004 / AUD-2026-07）：``migrate_schema`` 兼容补列层。

切流后**新** DDL 以 Alembic revision 为准；本清单冻结为旧库补列 +
``device_reservations`` 索引修复的幂等来源。确需双写时：先 revision，再追加此处。
"""

from __future__ import annotations

SCHEMA_ADDS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "artifact_id", "VARCHAR(64)"),
    ("jobs", "project_id", "VARCHAR(128) DEFAULT ''"),
    ("jobs", "webhook_url", "TEXT DEFAULT ''"),
    ("jobs", "parent_job_id", "VARCHAR(64)"),
    ("jobs", "depends_on_json", "TEXT DEFAULT '[]'"),
    ("jobs", "web_engine", "VARCHAR(32) DEFAULT 'selenium'"),
    ("jobs", "created_by", "VARCHAR(64) DEFAULT ''"),
    ("jobs", "claimed_at", "DATETIME"),
    ("users", "disabled", "BOOLEAN DEFAULT 0"),
    ("users", "oidc_sub", "VARCHAR(256) DEFAULT ''"),
    ("users", "saml_nameid", "VARCHAR(256) DEFAULT ''"),
    ("reports", "stored_path", "TEXT DEFAULT ''"),
    ("runners", "token_hash", "VARCHAR(128) DEFAULT ''"),
    ("artifacts", "project_id", "VARCHAR(128) DEFAULT ''"),
    ("artifacts", "manifest_status", "VARCHAR(32) DEFAULT ''"),
    ("artifacts", "manifest_version", "VARCHAR(64) DEFAULT ''"),
    ("artifacts", "manifest_notes_json", "TEXT DEFAULT '[]'"),
    ("devices", "busy_job_id", "VARCHAR(64)"),
    ("devices", "os_version", "VARCHAR(64) DEFAULT ''"),
    ("devices", "state", "VARCHAR(32) DEFAULT 'ready'"),
    ("devices", "backends_json", "TEXT DEFAULT '[]'"),
    ("devices", "health_note", "VARCHAR(512) DEFAULT ''"),
    ("devices", "admin_disabled", "BOOLEAN DEFAULT 0"),
    ("devices", "reservation_id", "VARCHAR(64)"),
    ("jobs", "app_build_id", "VARCHAR(64)"),
    ("jobs", "entry_paths_json", "TEXT DEFAULT '[]'"),
    ("schedules", "app_build_id", "VARCHAR(64)"),
    ("schedules", "entry_paths_json", "TEXT DEFAULT '[]'"),
    ("schedules", "web_engine", "VARCHAR(32) DEFAULT 'selenium'"),
    ("reports", "artifact_id", "VARCHAR(64)"),
    ("reports", "artifact_name", "VARCHAR(256) DEFAULT ''"),
    ("reports", "app_build_id", "VARCHAR(64)"),
    ("reports", "app_build_name", "VARCHAR(256) DEFAULT ''"),
    ("reports", "app_version_name", "VARCHAR(128) DEFAULT ''"),
    ("reports", "app_platform", "VARCHAR(32) DEFAULT ''"),
    ("reports", "result_json_path", "TEXT DEFAULT ''"),
    ("projects", "org_id", "VARCHAR(128) DEFAULT ''"),
    ("audit_logs", "org_id", "VARCHAR(128) DEFAULT ''"),
    ("design_logical_cases", "intent_steps_json", "TEXT DEFAULT '[]'"),
    ("runners", "org_id", "VARCHAR(128) DEFAULT ''"),
    ("runners", "project_ids_json", "TEXT DEFAULT '[]'"),
    ("runners", "owner_user_id", "VARCHAR(64) DEFAULT ''"),
    ("runners", "registration_source", "VARCHAR(32) DEFAULT 'platform'"),
    ("runners", "device_inventory_json", "TEXT DEFAULT '[]'"),
    ("runners", "device_selection_mode", "VARCHAR(16) DEFAULT 'all'"),
    ("runners", "selected_device_udids_json", "TEXT DEFAULT '[]'"),
    ("runners", "device_policy_revision", "INTEGER DEFAULT 0"),
    ("organizations", "policies_json", "TEXT DEFAULT '{}'"),
    ("device_remote_sessions", "max_viewers", "INTEGER DEFAULT 5"),
)

# 兼容旧名
_SCHEMA_ADDS = SCHEMA_ADDS

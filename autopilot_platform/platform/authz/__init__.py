"""授权域：资源 ACL + RBAC 策略求值入口。"""
from __future__ import annotations

from . import acl, rbac
from .acl import (
    RESOURCE_TYPES,
    assert_can_access_resource,
    can_access_resource,
    filter_resources_by_acl,
    has_acl,
    runner_can_access_assigned_resource,
)

__all__ = [
    "acl",
    "rbac",
    "RESOURCE_TYPES",
    "assert_can_access_resource",
    "can_access_resource",
    "filter_resources_by_acl",
    "has_acl",
    "runner_can_access_assigned_resource",
]

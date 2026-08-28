"""HTTP API routers assembled by domain submodule."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from autopilot_platform.core.constants import API_V1_PREFIX

from ..auth import require_auth
from . import (
    acl,
    app_builds,
    artifacts,
    auth,
    design,
    devices,
    invites,
    jobs,
    ops,
    orgs,
    projects,
    public,
    resource_pools,
    runners,
    schedules,
    device_remote,
    device_remote_ws,
)

auth_router = APIRouter(prefix=API_V1_PREFIX)
router = APIRouter(prefix=API_V1_PREFIX, dependencies=[Depends(require_auth)])

auth_router.include_router(auth.public_router)
auth_router.include_router(public.public_router)
auth_router.include_router(invites.public_router)
auth_router.include_router(device_remote_ws.router)
router.include_router(auth.router)
router.include_router(ops.router)
router.include_router(artifacts.router)
router.include_router(app_builds.router)
router.include_router(orgs.router)
router.include_router(projects.router)
router.include_router(resource_pools.router)
router.include_router(invites.router)
router.include_router(acl.router)
router.include_router(schedules.router)
router.include_router(runners.router)
router.include_router(devices.router)
router.include_router(device_remote.router)
router.include_router(jobs.router)
router.include_router(design.router)

__all__ = ["auth_router", "router"]

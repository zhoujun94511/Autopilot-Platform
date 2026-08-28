"""执行资源池。"""

from .pools import (
    add_device,
    add_runner,
    create_resource_pool,
    delete_resource_pool,
    grant_project,
    list_resource_pools,
    remove_device,
    remove_runner,
    revoke_project,
    update_resource_pool,
)

__all__ = [
    "add_device",
    "add_runner",
    "create_resource_pool",
    "delete_resource_pool",
    "grant_project",
    "list_resource_pools",
    "remove_device",
    "remove_runner",
    "revoke_project",
    "update_resource_pool",
]

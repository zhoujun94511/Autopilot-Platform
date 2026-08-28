"""设备预占与远控服务。"""

from .reservations import (
    active_reservations_for_auth,
    create_reservation,
    release_reservation,
)
from .sessions import (
    close_remote_session,
    create_remote_session,
    get_remote_session,
    join_device_remote_session,
    join_remote_session,
)

__all__ = [
    "active_reservations_for_auth",
    "close_remote_session",
    "create_remote_session",
    "create_reservation",
    "get_remote_session",
    "join_device_remote_session",
    "join_remote_session",
    "release_reservation",
]

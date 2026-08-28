"""远控公共组件：会话协议、坐标映射、帧载荷约定。"""

from .channels import RemoteChannels
from .coords import map_display_to_device
from .frame_bus import (
    build_frame_message,
    build_input_message,
    pack_binary_frame,
    unpack_binary_frame,
)
from .protocol import RemoteMediaSession

__all__ = [
    "RemoteChannels",
    "RemoteMediaSession",
    "map_display_to_device",
    "build_frame_message",
    "build_input_message",
    "pack_binary_frame",
    "unpack_binary_frame",
]

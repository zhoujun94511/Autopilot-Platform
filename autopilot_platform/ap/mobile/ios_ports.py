"""iOS 真机默认端口常量（独立模块，避免 ios_bootstrap ↔ runtime 循环 import）。"""

DEFAULT_TUNNEL_INFO_PORT = 28100
DEFAULT_WDA_PORT = 8100
DEFAULT_MJPEG_PORT = 9100  # WDA 屏幕 MJPEG 流端口（实时镜像用）

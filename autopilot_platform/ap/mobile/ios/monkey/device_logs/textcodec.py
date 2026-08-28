"""设备 syslog 文本解码：go-ios 在 Windows 上进程名常为系统 ANSI(GBK)，消息体多为 UTF-8/ASCII。"""

from __future__ import annotations

import re

# 2026-07-05 19:04:45.822873 爱投屏{CoreFoundation}[1017] <DEBUG>: ...
_LINE_PROC = re.compile(
    rb"^(\d{4}-\d{2}-\d{2} [0-9:.]+\s+)([^{\r\n]+)(\{.+)$",
)

# ANSI / OSC 控制序列（偶发打进管道）
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def decode_syslog_line(data: bytes) -> str:
    """解码单行 syslog；兼容纯 UTF-8 与「GBK 进程名 + UTF-8 正文」混排。"""
    if not data:
        return ""
    line = data.rstrip(b"\r\n")
    try:
        return strip_ansi(line.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    m = _LINE_PROC.match(line)
    if m:
        head, proc, rest = m.group(1), m.group(2), m.group(3)
        proc_s = proc.decode("gb18030", errors="replace")
        try:
            text = head.decode("utf-8") + proc_s + rest.decode("utf-8")
        except UnicodeDecodeError:
            text = (
                head.decode("ascii", errors="replace")
                + proc_s
                + rest.decode("utf-8", errors="replace")
            )
        return strip_ansi(text)
    try:
        return strip_ansi(line.decode("gb18030"))
    except UnicodeDecodeError:
        return strip_ansi(line.decode("utf-8", errors="replace"))


def decode_syslog_text(data: bytes) -> str:
    """整段 syslog（可含多行）解码。"""
    if not data:
        return ""
    # 整段若是合法 UTF-8，直接用（快路径）
    try:
        return strip_ansi(data.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    parts: list[str] = []
    for raw_line in data.splitlines(keepends=True):
        if raw_line.endswith(b"\r\n"):
            body, ending = raw_line[:-2], "\n"
        elif raw_line.endswith(b"\n"):
            body, ending = raw_line[:-1], "\n"
        elif raw_line.endswith(b"\r"):
            body, ending = raw_line[:-1], "\n"
        else:
            body, ending = raw_line, ""
        parts.append(decode_syslog_line(body) + ending)
    return "".join(parts)

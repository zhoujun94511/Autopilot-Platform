"""FTP 关键字。关键字 id 见 keyword_defs 定义（参考 align-data-keywords.md）。用 stdlib ftplib。

注：上传/下载形参名沿用参数 id（localFilePosition/remoteFile 等驼峰），
执行引擎按 param id 绑定 kwargs，不能改小写，故标注 noinspection PyPep8Naming。
"""

from __future__ import annotations

import os
from typing import Any

from ..registry import keyword, KeywordError
from ..context import ExecutionContext


def _manager(ctx: ExecutionContext) -> dict:
    mgr = getattr(ctx, "ftp", None)
    if mgr is None:
        mgr = {}
        ctx.ftp = mgr  # type: ignore[attr-defined]
    return mgr


def default_ftp_factory(host: str, port: int, user: str, pwd: str, path: str):
    from ftplib import FTP
    ftp = FTP()
    ftp.connect(host, port)
    ftp.login(user, pwd)
    if path:
        ftp.cwd(path)
    return ftp


def _factory(ctx: ExecutionContext):
    return getattr(ctx, "ftp_factory", None) or default_ftp_factory


@keyword("ftp_ftpclient_connect", name="连接FTP", category="Public",
         legacy_impl="FtpKeyword:connectFtp")
def connect_ftp(ctx: ExecutionContext, alias="", host="", port="21", user="",
                pwd="", path="", **_kw) -> None:
    _manager(ctx)[alias or ""] = _factory(ctx)(host, int(port), user, pwd, path)


def _client(ctx: ExecutionContext, alias: str):
    c = _manager(ctx).get(alias or "")
    if c is None:
        raise KeywordError(f"FTP 未连接（alias={alias!r}），请先 ftp_ftpclient_connect")
    return c


# noinspection PyPep8Naming
@keyword("ftp_ftpclient_uploadFile", name="上传文件", category="Public",
         legacy_impl="FtpKeyword:uploadFile")
def upload_file(ctx: ExecutionContext, alias="", localFilePosition="", localFile="",
                remoteFile="", **_kw) -> None:
    local = os.path.join(localFilePosition, localFile) if localFilePosition else localFile
    with open(local, "rb") as f:
        _client(ctx, alias).storbinary(f"STOR {remoteFile}", f)


# noinspection PyPep8Naming
@keyword("ftp_ftpclient_downloadFile", name="下载文件", category="Public",
         legacy_impl="FtpKeyword:downloadFile")
def download_file(ctx: ExecutionContext, alias="", remoteFile="", localFilePosition="",
                  localFile="", **_kw) -> None:
    local = os.path.join(localFilePosition, localFile) if localFilePosition else localFile
    with open(local, "wb") as f:
        _client(ctx, alias).retrbinary(f"RETR {remoteFile}", f.write)


@keyword("ftp_ftpclient_closeFtp", name="关闭FTP", category="Public",
         legacy_impl="FtpKeyword:closeFtp")
def close_ftp(ctx: ExecutionContext, alias="", **_kw) -> None:
    c: Any = _manager(ctx).pop(alias or "", None)
    if c is not None:
        # noinspection PyBroadException
        try:
            c.quit()
        except Exception:
            pass

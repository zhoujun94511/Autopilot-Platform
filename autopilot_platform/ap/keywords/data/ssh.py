"""SSH 关键字。关键字 id 见 keyword_defs 定义（参考 align-data-keywords.md）。paramiko 懒加载。

主机信任（AUD-2026-04）：
- 默认 ``RejectPolicy`` + 系统/指定 known_hosts，拒绝未知主机指纹（防 MITM）。
- 未知主机须显式 ``allow_unknown_host=true``，或进程环境
  ``AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST=1``（运维级显式开关，默认关闭）。
- ``exec_command`` / SFTP 仍为产品能力；风险分级见 Intent risk / XML（AUD-2026-09）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from ..registry import keyword, KeywordError
from ..context import ExecutionContext


def _manager(ctx: ExecutionContext) -> dict:
    mgr = getattr(ctx, "ssh", None)
    if mgr is None:
        mgr = {}
        ctx.ssh = mgr  # type: ignore[attr-defined]
    return mgr


def _truthy(raw: Any) -> bool:
    s = str(raw or "").strip().lower()
    return s in ("1", "true", "yes", "on", "y")


def ssh_allow_unknown_host_env() -> bool:
    """运维显式放行未知主机（非默认）。"""
    return _truthy(os.environ.get("AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST", "0"))


def default_ssh_factory(
    ip: str,
    port: int,
    user: str,
    passwd: str,
    *,
    allow_unknown_host: bool = False,
    known_hosts: str = "",
):
    try:
        # noinspection PyUnresolvedReferences,PyPackageRequirements
        import paramiko
    except ImportError as e:  # pragma: no cover
        raise KeywordError("未安装 paramiko。pip install autopilot[data]") from e

    client = paramiko.SSHClient()
    # 系统 known_hosts（~/.ssh/known_hosts 等）
    try:
        client.load_system_host_keys()
    except OSError:
        pass
    kh = (known_hosts or "").strip()
    if kh:
        path = Path(kh).expanduser()
        if not path.is_file():
            raise KeywordError(f"known_hosts 文件不存在：{path}")
        try:
            client.load_host_keys(str(path))
        except OSError as exc:
            raise KeywordError(f"无法加载 known_hosts：{path} ({exc})") from exc

    allow = bool(allow_unknown_host) or ssh_allow_unknown_host_env()
    if allow:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

    try:
        client.connect(ip, port=port, username=user, password=passwd or None)
    except paramiko.BadHostKeyException as exc:
        raise KeywordError(
            f"SSH 主机密钥与 known_hosts 不符（可能遭篡改）：{ip}:{port}。"
            f"请核对指纹或更新 known_hosts。"
        ) from exc
    except paramiko.SSHException as exc:
        # 含未知主机被 RejectPolicy 拒绝
        msg = str(exc).strip() or exc.__class__.__name__
        hint = ""
        if not allow and (
            "not found in known_hosts" in msg.lower()
            or "unknown" in msg.lower()
            or "reject" in msg.lower()
        ):
            hint = (
                " 默认拒绝未知主机指纹；确认已写入 known_hosts，"
                "或显式设置 allow_unknown_host=true"
                " / AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST=1。"
            )
        raise KeywordError(f"SSH 连接失败：{ip}:{port} — {msg}.{hint}") from exc
    return client


def _factory(ctx: ExecutionContext) -> Callable[..., Any]:
    return getattr(ctx, "ssh_factory", None) or default_ssh_factory


def _open_client(
    ctx: ExecutionContext,
    ip: str,
    port: int,
    user: str,
    passwd: str,
    *,
    allow_unknown_host: bool,
    known_hosts: str,
) -> Any:
    factory = _factory(ctx)
    try:
        return factory(
            ip,
            port,
            user,
            passwd,
            allow_unknown_host=allow_unknown_host,
            known_hosts=known_hosts,
        )
    except TypeError:
        # 测试注入的 4 参 factory（lambda ip,port,user,pwd）
        return factory(ip, port, user, passwd)


# noinspection PyPep8Naming
@keyword("linux_ssh_connect", name="连接SSH", category="Public",
         legacy_impl="SshKeyword:connectSSH")
def connect_ssh(
    ctx: ExecutionContext,
    alias="",
    IP="",
    port="22",
    user="",
    passwd="",
    allow_unknown_host="0",
    known_hosts="",
    **_kw,
) -> None:
    allow = _truthy(allow_unknown_host)
    _manager(ctx)[alias or ""] = _open_client(
        ctx,
        IP,
        int(port or "22"),
        user,
        passwd,
        allow_unknown_host=allow,
        known_hosts=str(known_hosts or "").strip(),
    )


def _client(ctx: ExecutionContext, alias: str):
    c = _manager(ctx).get(alias or "")
    if c is None:
        raise KeywordError(f"SSH 未连接（alias={alias!r}），请先 linux_ssh_connect")
    return c


def _run(client, cmd: str) -> str:
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read()
    return out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out)


@keyword("linux_ssh_runCmd_WithResult", name="执行命令(取结果)", category="Public",
         out_params=["result"], legacy_impl="SshKeyword:runCmdWithResult")
def run_cmd_with_result(ctx: ExecutionContext, alias="", cmd="", result="", **_kw) -> dict:
    return {result: _run(_client(ctx, alias), cmd)}


@keyword("linux_ssh_runCmd_WithoutResult", name="执行命令(不取结果)", category="Public",
         legacy_impl="SshKeyword:runCmdWithoutResult")
def run_cmd_without_result(ctx: ExecutionContext, alias="", cmd="", **_kw) -> None:
    _run(_client(ctx, alias), cmd)


@keyword("linux_ssh_close", name="关闭SSH", category="Public",
         legacy_impl="SshKeyword:closeSSH")
def close_ssh(ctx: ExecutionContext, alias="", **_kw) -> None:
    c: Any = _manager(ctx).pop(alias or "", None)
    if c is not None:
        # noinspection PyBroadException
        try:
            c.close()
        except Exception:
            pass


# noinspection PyPep8Naming
@keyword("linux_ssh_sftp_fileUpload", name="SFTP文件上传", category="Public",
         legacy_impl="SshKeyword:fileUpload")
def linux_ssh_sftp_file_upload(ctx: ExecutionContext, alias="", srcPosition="工程",
                               srcFile="", dstFile="", **_kw) -> None:
    local = os.path.join(srcPosition, srcFile)
    sftp = _client(ctx, alias).open_sftp()
    try:
        sftp.put(local, dstFile)
    finally:
        sftp.close()


# noinspection PyPep8Naming
@keyword("linux_ssh_sftp_fileDownload", name="SFTP文件下载", category="Public",
         legacy_impl="SshKeyword:fileDownload")
def linux_ssh_sftp_file_download(ctx: ExecutionContext, alias="", srcFile="",
                                 dstPosition="工程", dstFile="", **_kw) -> None:
    local = os.path.join(dstPosition, dstFile)
    sftp = _client(ctx, alias).open_sftp()
    try:
        sftp.get(srcFile, local)
    finally:
        sftp.close()

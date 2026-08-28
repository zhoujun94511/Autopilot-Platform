#!/usr/bin/env python3
"""使用 keytool 生成 TLS 证书并自动导出 PEM（供 MC_SSL_* / nginx 使用）。
  * 随机 keystore / key 密码（默认 12 位字母数字）
  * ``keytool -genkeypair``，JKS，RSA 2048
  * 别名 ``randomkey_<timestamp>``（可 ``--alias`` 覆盖）

本脚本额外：
  * 可配置 CN / SAN（HTTPS 主机名）
  * JKS → PKCS12 → PEM（``server.crt`` + ``server.key``），依赖 ``cryptography``（已在项目依赖中）
  * 写入 ``*_info.txt`` 与可选 ``platform-tls.env`` / ``dev-local-ide.env`` 片段

**仅用于内网 / 开发 / 联调自签**；公网生产请用 Let's Encrypt 或企业 CA。

用法：
  python tools/gen_tls_cert.py
  python tools/gen_tls_cert.py --cn autopilot.local --san DNS:autopilot.local --san IP:127.0.0.1
  python tools/gen_tls_cert.py --out-dir data/tls/lab --write-env

依赖：JDK ``keytool`` 在 PATH 中（``java -version`` 同目录）。
"""

from __future__ import annotations

import argparse
import random
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_VALIDITY_DAYS = 10_000
DEFAULT_PASSWORD_LEN = 12


def _print(msg: str) -> None:
    print(msg, flush=True)


def generate_random_password(length: int = DEFAULT_PASSWORD_LEN) -> str:
    """与 WebAppForAndroid ``generate_random_password`` 一致：字母 + 数字。"""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(max(8, length)))


def _require_keytool() -> str:
    keytool = shutil.which("keytool")
    if not keytool:
        raise SystemExit(
            "未找到 keytool。请安装 JDK 并将 bin 目录加入 PATH（与 java 同目录）。"
        )
    return keytool


def _run_keytool(args: list[str], *, quiet: bool = True) -> None:
    cmd = args
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.PIPE if quiet else None,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip()
        raise SystemExit(f"keytool 失败：{' '.join(args)}\n{err}") from exc


def _build_san_ext(sans: list[str]) -> str:
    parts: list[str] = []
    for raw in sans:
        item = raw.strip()
        if not item:
            continue
        upper = item.upper()
        if upper.startswith(("DNS:", "IP:", "EMAIL:")):
            parts.append(item if ":" in item else item)
        else:
            parts.append(f"DNS:{item}")
    if not parts:
        return ""
    return "SAN=" + ",".join(parts)


def _jks_to_pem(
    p12_path: Path,
    password: str,
    *,
    cert_pem: Path,
    key_pem: Path,
) -> None:
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            pkcs12,
        )
    except ImportError as exc:
        raise SystemExit(
            "缺少 cryptography，无法导出 PEM：pip install -e \".[core]\""
        ) from exc

    data = p12_path.read_bytes()
    key, cert, chain = pkcs12.load_key_and_certificates(data, password.encode("utf-8"))
    if key is None or cert is None:
        raise SystemExit(f"PKCS12 中缺少私钥或证书：{p12_path}")

    cert_lines = [cert.public_bytes(Encoding.PEM)]
    if chain:
        cert_lines.extend(c.public_bytes(Encoding.PEM) for c in chain if c is not None)
    cert_pem.write_bytes(b"".join(cert_lines))

    key_pem.write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )


def generate_tls_material(
    *,
    out_dir: Path,
    cn: str,
    sans: list[str],
    alias: str | None,
    validity_days: int,
    password_len: int,
    org: str,
    country: str,
) -> dict[str, Path | str]:
    """生成 JKS / P12 / PEM，返回路径与密码元数据。"""
    keytool = _require_keytool()
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d%H%M%S")
    key_alias = (alias or f"randomkey_{timestamp}").strip()
    keystore_password = generate_random_password(password_len)
    key_password = generate_random_password(password_len)

    jks_path = out_dir / f"{key_alias}.jks"
    p12_path = out_dir / f"{key_alias}.p12"
    cert_path = out_dir / "server.crt"
    key_path = out_dir / "server.key"
    info_path = out_dir / f"{key_alias}_info.txt"

    dname = f"CN={cn}, OU=AutoPilot, O={org}, C={country}"
    gen_args = [
        keytool,
        "-genkeypair",
        "-keystore",
        str(jks_path),
        "-storetype",
        "JKS",
        "-keyalg",
        "RSA",
        "-keysize",
        "2048",
        "-validity",
        str(max(1, validity_days)),
        "-storepass",
        keystore_password,
        "-keypass",
        key_password,
        "-alias",
        key_alias,
        "-dname",
        dname,
    ]
    san_ext = _build_san_ext(sans)
    if san_ext:
        gen_args.extend(["-ext", san_ext])

    _run_keytool(gen_args)

    import_args = [
        keytool,
        "-importkeystore",
        "-noprompt",
        "-srckeystore",
        str(jks_path),
        "-destkeystore",
        str(p12_path),
        "-srcstoretype",
        "JKS",
        "-deststoretype",
        "PKCS12",
        "-srcstorepass",
        keystore_password,
        "-deststorepass",
        keystore_password,
        "-srcalias",
        key_alias,
        "-destalias",
        key_alias,
        "-srckeypass",
        key_password,
        "-destkeypass",
        keystore_password,
    ]
    _run_keytool(import_args)

    _jks_to_pem(p12_path, keystore_password, cert_pem=cert_path, key_pem=key_path)

    info_text = "\n".join(
        [
            "AutoPilot Platform TLS 证书（keytool 生成）",
            f"generated_at: {timestamp}",
            f"keystore: {jks_path.name}",
            f"keystore password: {keystore_password}",
            f"key alias: {key_alias}",
            f"key password: {key_password}",
            f"CN: {cn}",
            f"SAN: {san_ext or '(仅 CN)'}",
            f"PEM cert: {cert_path}",
            f"PEM key: {key_path}",
            "",
            "Platform 直连 TLS（复制到 Autopilot-Platform 仓库根 .env）：",
            f"MC_SSL_CERTFILE={cert_path.resolve()}",
            f"MC_SSL_KEYFILE={key_path.resolve()}",
            "",
            "双仓联调（仅开发机，复制 dev-local-ide.env 到 AutoPilot .env）：",
            f"  AUTOPILOT_SSL_CA_FILE={cert_path.resolve()}",
            "  勿将上述 Platform data/tls 路径写入 IDE 企业分发配置。",
            "",
        ]
    )
    info_path.write_text(info_text, encoding="utf-8")

    return {
        "alias": key_alias,
        "jks": jks_path,
        "p12": p12_path,
        "cert_pem": cert_path,
        "key_pem": key_path,
        "info": info_path,
        "keystore_password": keystore_password,
        "key_password": key_password,
        "cn": cn,
    }


def _write_env_snippet(out_dir: Path, cert: Path, key: Path, *, platform_url: str) -> tuple[Path, Path]:
    platform_env = out_dir / "platform-tls.env"
    ide_env = out_dir / "dev-local-ide.env"
    cert_s, key_s = str(cert.resolve()), str(key.resolve())
    platform_env.write_text(
        "\n".join(
            [
                "# Platform 服务端：复制到 Autopilot-Platform 仓库根 .env",
                f"MC_SSL_CERTFILE={cert_s}",
                f"MC_SSL_KEYFILE={key_s}",
                f"MC_PLATFORM_URL={platform_url}",
                "MC_COOKIE_SECURE=1",
                f"MC_CORS_ORIGINS={platform_url},http://127.0.0.1:5173",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ide_env.write_text(
        "\n".join(
            [
                "# 双仓本地联调 ONLY：复制到开发机 AutoPilot 仓库根 .env",
                "# 勿用于 IDE 企业分发；分发用户见 AutoPilot/docs/CONFIGURATION.md",
                f"AUTOPILOT_PLATFORM_URL={platform_url}",
                f"AUTOPILOT_SSL_CA_FILE={cert_s}",
                "AUTOPILOT_SSL_VERIFY=1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return platform_env, ide_env


def _default_platform_url(cn: str, port: int) -> str:
    host = "127.0.0.1" if cn in ("localhost", "127.0.0.1") else cn
    return f"https://{host}:{port}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="keytool 生成 TLS 证书并导出 PEM（内网/联调）"
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="输出目录（默认 data/tls/<timestamp>）",
    )
    ap.add_argument(
        "--cn",
        default="localhost",
        help="证书 CN（Common Name），默认 localhost",
    )
    ap.add_argument(
        "--san",
        action="append",
        default=[],
        help="Subject Alternative Name，可重复。例：--san DNS:autopilot.local --san IP:127.0.0.1",
    )
    ap.add_argument("--alias", default="", help="keytool 别名（默认 randomkey_<timestamp>）")
    ap.add_argument(
        "--validity",
        type=int,
        default=DEFAULT_VALIDITY_DAYS,
        help=f"有效天数（默认 {DEFAULT_VALIDITY_DAYS}，与 WebAppForAndroid 一致）",
    )
    ap.add_argument(
        "--password-len",
        type=int,
        default=DEFAULT_PASSWORD_LEN,
        help="keystore / key 随机密码长度",
    )
    ap.add_argument("--org", default="AutoPilot", help="DNAME 中的 O")
    ap.add_argument("--country", default="CN", help="DNAME 中的 C")
    ap.add_argument(
        "--write-env",
        action="store_true",
        help="额外写入 platform-tls.env（服务端）与 dev-local-ide.env（双仓联调）",
    )
    ap.add_argument(
        "--platform-port",
        type=int,
        default=8443,
        help="--write-env 中 Platform/IDE URL 端口（默认 8443，与 start_dev_https 一致）",
    )
    ap.add_argument(
        "--platform-url",
        default="",
        help="覆盖 --write-env 中的 MC_PLATFORM_URL / AUTOPILOT_PLATFORM_URL",
    )
    ap.add_argument(
        "--keep-p12",
        action="store_true",
        help="保留中间 .p12（默认保留；加 --no-keep-p12 可删）",
    )
    ap.add_argument(
        "--no-keep-p12",
        action="store_true",
        help="PEM 导出成功后删除 .p12",
    )
    args = ap.parse_args(argv)

    ts = time.strftime("%Y%m%d%H%M%S")
    out_dir = args.out_dir or (ROOT / "data" / "tls" / ts)
    out_dir = out_dir.resolve()

    sans = list(args.san)
    if args.cn and not sans:
        sans = [f"DNS:{args.cn}"]
    elif args.cn and not any(args.cn in s for s in sans):
        sans.insert(0, f"DNS:{args.cn}")

    meta = generate_tls_material(
        out_dir=out_dir,
        cn=args.cn,
        sans=sans,
        alias=args.alias or None,
        validity_days=args.validity,
        password_len=args.password_len,
        org=args.org,
        country=args.country,
    )

    if args.no_keep_p12:
        p12 = meta["p12"]
        if isinstance(p12, Path) and p12.is_file():
            p12.unlink()

    _print("")
    _print("TLS 证书已生成（内网/联调自签）：")
    _print(f"  目录:     {out_dir}")
    _print(f"  PEM 证书: {meta['cert_pem']}")
    _print(f"  PEM 私钥: {meta['key_pem']}")
    _print("  （PEM 是编码格式，文件名是 server.crt / server.key，不是 .pem 后缀）")
    _print(f"  JKS:      {meta['jks']}")
    _print(f"  说明文件: {meta['info']}  （含 keystore 密码，勿提交 Git）")
    _print("  提示: data/tls/ 在 .gitignore 中，IDE 文件树可能默认不显示，请用资源管理器或终端 dir 打开上述目录")
    _print("")
    platform_url = (args.platform_url or "").strip() or _default_platform_url(
        args.cn, args.platform_port
    )
    _print("Platform 服务端 .env（复制到 Autopilot-Platform 根 .env）：")
    _print(f"  MC_SSL_CERTFILE={meta['cert_pem']}")
    _print(f"  MC_SSL_KEYFILE={meta['key_pem']}")
    _print(f"  MC_PLATFORM_URL={platform_url}")
    _print("")
    _print("双仓联调 IDE（仅开发机，见 dev-local-ide.env / https.md §2.3）：")
    _print(f"  AUTOPILOT_PLATFORM_URL={platform_url}")
    _print(f"  AUTOPILOT_SSL_CA_FILE={meta['cert_pem']}")

    if args.write_env:
        platform_env, ide_env = _write_env_snippet(
            out_dir,
            cert=meta["cert_pem"],  # type: ignore[arg-type]
            key=meta["key_pem"],  # type: ignore[arg-type]
            platform_url=platform_url,
        )
        _print("")
        _print(f"  Platform 服务端: {platform_env}")
        _print(f"  双仓联调 IDE:   {ide_env}")

    _print("")
    _print("启动示例：")
    _print("  python -m autopilot_platform.platform --host 0.0.0.0 --port 8443")
    _print("")
    _print("文档：docs/setup/https.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

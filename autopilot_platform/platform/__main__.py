"""启动平台：python -m autopilot_platform.platform"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    ap = argparse.ArgumentParser(description="AutoPilot 管理台 Platform")
    ap.add_argument("--host", default=os.environ.get("MC_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MC_PORT", "8000")))
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()
    # 让 create_app → validate_bind_security 看到真实监听地址（含 --host 覆盖）
    os.environ["MC_HOST"] = str(args.host)

    from autopilot_platform.platform.core.tls import (
        production_https_errors,
        uvicorn_proxy_kwargs,
        uvicorn_ssl_kwargs,
        validate_tls_files,
    )

    tls_errors = validate_tls_files() + production_https_errors()
    if tls_errors:
        raise RuntimeError("HTTPS/TLS 配置校验失败：" + "；".join(tls_errors))

    import uvicorn

    uvicorn.run(
        "autopilot_platform.platform.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        **uvicorn_ssl_kwargs(),
        **uvicorn_proxy_kwargs(),
    )


if __name__ == "__main__":
    main()

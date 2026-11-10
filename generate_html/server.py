from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from core.server import DEFAULT_DATA_DIR, DEFAULT_STATE_DIR, create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行订单看板动态服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--web-dir", type=Path, help="已发布的前端目录，默认使用 data-dir")
    parser.add_argument("--allowed-host", action="append", help="额外允许的公共主机名，可重复指定，本机健康检查始终允许 localhost/127.0.0.1")
    parser.add_argument("--allowed-origin", action="append", default=[], help="允许的公共站点完整来源，例如 https://portal.example，可重复指定")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    app = create_app(
        args.data_dir, args.state_dir,
        web_dir=args.web_dir, allowed_hosts=args.allowed_host,
        allowed_origins=args.allowed_origin,
    )
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()

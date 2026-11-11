from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from core.server import DEFAULT_DATA_DIR, DEFAULT_STATE_DIR, PROJECT_ROOT, create_app
from core.data_paths import orders_input_directory


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行订单看板动态服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--web-dir", type=Path, help="已发布的前端目录，默认使用 data-dir")
    parser.add_argument("--allowed-host", action="append", help="额外允许的公共主机名，可重复指定，本机健康检查始终允许 localhost/127.0.0.1")
    parser.add_argument("--allowed-origin", action="append", default=[], help="允许的公共站点完整来源，例如 https://portal.example，可重复指定")
    parser.add_argument("--input", type=Path, default=orders_input_directory(PROJECT_ROOT), help="订单汇总 Excel 目录，默认项目 output_file")
    parser.add_argument("--check-seconds", type=float, default=300)
    parser.add_argument("--stable-seconds", type=float, default=60)
    parser.add_argument("--no-sync", action="store_true", help="只读取已发布数据，不自动处理 Excel")
    parser.add_argument("--open", action="store_true", help="启动或复用后台并打开网页")
    parser.add_argument("--no-open", action="store_true", help="配合 --open 启动后台但不打开浏览器")
    parser.add_argument("--sync-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check_seconds <= 0 or args.stable_seconds <= 0:
        parser.error("检查和稳定等待时间必须大于零")
    return args


def main() -> None:
    args = parse_args()
    if args.sync_worker:
        from core.sync import run_worker
        try:
            run_worker(args.input.resolve(), args.data_dir.resolve(), json.loads(sys.stdin.buffer.read().decode("utf-8")))
        except Exception:
            import traceback
            traceback.print_exc()
            raise SystemExit(1)
        return
    if args.open:
        from main import open_dynamic_dashboard
        open_dynamic_dashboard(args.data_dir, args.port, input_dir=args.input,
                               open_browser=not args.no_open, check_seconds=args.check_seconds,
                               stable_seconds=args.stable_seconds, no_sync=args.no_sync)
        return
    app = create_app(
        args.data_dir, args.state_dir,
        web_dir=args.web_dir, allowed_hosts=args.allowed_host,
        allowed_origins=args.allowed_origin,
        input_dir=None if args.no_sync else args.input,
        check_seconds=args.check_seconds, stable_seconds=args.stable_seconds,
    )
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()

"""Choose an Excel source for the Windows static-export launcher."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from core.data_paths import PROJECT_ROOT, shared_data_root

ROOT = Path(__file__).resolve().parent


def choose_input_directory() -> Path | None:
    shared = (shared_data_root(PROJECT_ROOT) or PROJECT_ROOT.parent / "工作台数据" / "shared") / "订单汇总"
    local = PROJECT_ROOT / "output_file"
    while True:
        print("\n请选择数据来源：")
        print(f"  1. 共享订单汇总：{shared}")
        print(f"  2. 本项目 output_file：{local}")
        print("  3. 自定义目录")
        print("  0. 取消")
        try:
            choice = input("请选择 [1]：").strip() or "1"
            if choice == "0":
                return None
            if choice == "1":
                source = shared
            elif choice == "2":
                source = local
            elif choice == "3":
                value = input("请输入 Excel 所在目录：").strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                if not value:
                    continue
                source = Path(value).expanduser()
            else:
                print("请选择 1、2、3 或 0。")
                continue
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        try:
            source = source.resolve()
            if not source.is_dir():
                print(f"目录不存在：{source}")
                continue
            if not any(p.is_file() and p.suffix.lower() == ".xlsx" and not p.name.startswith("~$")
                       for p in source.iterdir()):
                print(f"目录中没有 Excel 文件：{source}")
                continue
        except OSError as exc:
            print(f"无法读取目录：{exc}")
            continue
        return source


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = [sys.executable, str(ROOT / "main.py"), "--static"]
    if "--help" in argv or "-h" in argv:
        return subprocess.call([*command, *argv])
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--input", type=Path)
    options, remaining = parser.parse_known_args(argv)
    source = options.input.expanduser().resolve() if options.input is not None else choose_input_directory()
    if source is None:
        print("已取消生成。")
        return 0
    print(f"\n数据来源：{source}")
    print("正在读取 Excel 并生成订单分析静态网页...")
    # Pin identity lookups before main imports any business modules.
    environment = dict(os.environ, ORDER_DASHBOARD_INPUT=str(source))
    try:
        return subprocess.call([*command, "--input", str(source), *remaining], env=environment)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

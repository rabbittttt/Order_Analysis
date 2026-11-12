"""Prepare a versioned service payload; never include business data or the annotation DB."""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path

from core.renderer import render_dynamic_shell

ROOT = Path(__file__).resolve().parent


def package(destination: Path, runtime: Path | None = None) -> None:
    """Build from source alone; runtime is accepted only for old callers."""
    destination = destination.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("发布目录必须在程序源码目录之外")
    if destination.exists():
        raise FileExistsError("发布目录已经存在，请使用新版本目录")
    destination.mkdir(parents=True)
    for name in ("server.py", "main.py", "config.json", "requirements.txt", "SERVER.md"):
        shutil.copy2(ROOT / name, destination / name)
    for directory in ("core", "modules", "templates"):
        shutil.copytree(ROOT / directory, destination / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    web = destination / "web"
    # Render the copied templates so the web assets and shipped templates agree.
    # No Excel input, dataset pointer or previously generated report is read.
    render_dynamic_shell(destination / "templates", web)
    (destination / "release-info.json").write_text(json.dumps({
        "application": "order-dashboard", "data_mode": "external",
        "entry": "server.py", "web_dir": "web",
        "required_arguments": ["--input", "--data-dir", "--state-dir", "--web-dir"],
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, help="兼容旧命令；不再读取此目录，始终从当前源码构建")
    args = parser.parse_args()
    if args.runtime is not None:
        print("--runtime 已不再使用；将从当前源码构建，不读取历史报表或业务数据。")
    package(args.output.resolve())
    print(args.output.resolve())

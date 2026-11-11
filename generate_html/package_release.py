"""Prepare a versioned service payload; never include business data or the annotation DB."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent if ROOT.parent.name == "scripts" else ROOT.parent


def package(destination: Path, runtime: Path) -> None:
    if destination.exists():
        raise FileExistsError("发布目录已经存在，请使用新版本目录")
    if not (runtime / "current.json").is_file() or not (runtime / "index.html").is_file():
        raise FileNotFoundError("请先运行 main.py --no-open 完成数据生成")
    recorded = json.loads((runtime / "web-build.json").read_text(encoding="utf-8"))
    expected = {name: hashlib.sha256((ROOT / "templates" / name).read_bytes()).hexdigest()
                for name in ("dashboard.html", "dashboard.css", "dashboard.js", "trend_annotations.js", "brand-logo.png")}
    if recorded != expected:
        raise ValueError("前端源码在生成后发生变化，请先重新运行 main.py --no-open")
    destination.mkdir(parents=True)
    for name in ("server.py", "main.py", "config.json", "requirements.txt", "SERVER.md"):
        shutil.copy2(ROOT / name, destination / name)
    for directory in ("core", "modules", "templates"):
        shutil.copytree(ROOT / directory, destination / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    web = destination / "web"
    web.mkdir()
    shutil.copy2(runtime / "index.html", web / "index.html")
    (web / "assets").mkdir()
    shell = (runtime / "index.html").read_text(encoding="utf-8")
    for filename in set(re.findall(r'assets/([a-f0-9]{64}\.(?:css|js|png))', shell)):
        source = runtime / "assets" / filename
        if hashlib.sha256(source.read_bytes()).hexdigest() != filename.split(".")[0]:
            raise ValueError("前端资源内容校验失败")
        shutil.copy2(source, web / "assets" / filename)
    (destination / "release-info.json").write_text(json.dumps({
        "application": "order-dashboard", "data_mode": "external",
        "entry": "server.py", "web_dir": "web",
        "required_arguments": ["--input", "--data-dir", "--state-dir", "--web-dir"],
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=PROJECT / "output_file" / "runtime")
    args = parser.parse_args()
    package(args.output.resolve(), args.runtime.resolve())
    print(args.output.resolve())

from __future__ import annotations

import base64
import gzip
import json
import logging
import math
from time import perf_counter
from pathlib import Path
from typing import Any


def b64gzip(text: str) -> str:
    """压缩 JSON 文本为 base64,供前端 DecompressionStream 解压。"""
    return base64.b64encode(gzip.compress(text.encode("utf-8"), compresslevel=6, mtime=0)).decode("ascii")


def pack_dashboard(board: dict[str, Any]) -> dict[str, Any]:
    """Encode shared containers once; do not merge distinct equal values."""
    counts, scanned, active = {}, set(), set()
    def count(value):
        if not isinstance(value, (dict, list)):
            return
        identity = id(value)
        if identity in active:
            raise ValueError("Circular dashboard data")
        counts[identity] = counts.get(identity, 0) + 1
        if identity in scanned:
            return
        scanned.add(identity)
        active.add(identity)
        for child in (value.values() if isinstance(value, dict) else value):
            count(child)
        active.remove(identity)
    count(board)
    pool, indexes = [], {}
    def body(value):
        if isinstance(value, list):
            return [encode(child) for child in value]
        if "$shared" in value or "$literal" in value:
            return {"$literal": [[key, encode(child)] for key, child in value.items()]}
        return {key: encode(child) for key, child in value.items()}
    def encode(value):
        if not isinstance(value, (dict, list)):
            # Keep diagnostics on the original board, but never send Python's
            # nonstandard NaN/Infinity tokens to the browser's JSON.parse.
            return None if isinstance(value, float) and not math.isfinite(value) else value
        identity = id(value)
        if counts[identity] > 1:
            if identity not in indexes:
                indexes[identity] = len(pool)
                pool.append(None)
                pool[indexes[identity]] = body(value)
            return {"$shared": indexes[identity]}
        return body(value)
    root = encode(board)
    return {"format": "shared-v1", "root": root, "pool": pool}


def render_dashboard(manifest: dict[str, Any], template_dir: Path, output_file: Path) -> None:
    started = perf_counter()
    html = (template_dir / "dashboard.html").read_text(encoding="utf-8")
    css = (template_dir / "dashboard.css").read_text(encoding="utf-8")
    forecast_math = (template_dir / "forecast-math.js").read_text(encoding="utf-8")
    forecast_import = (template_dir / "forecast-import.js").read_text(encoding="utf-8")
    javascript = f"{forecast_import}\n{forecast_math}\n{(template_dir / 'dashboard.js').read_text(encoding='utf-8')}"
    logo_path = template_dir / "brand-logo.png"
    logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    # 主数据(主体/配置/底表元信息)整体压缩;看板按主体|模块分块压缩、底表行数据按表分块压缩,前端按需解压
    raw_blocks = manifest.get("raw_blocks", {})
    dashboard_blocks, sizes = {}, {}
    pack_seconds = serialize_seconds = compress_seconds = 0.0
    for key, board in manifest.get("dashboards", {}).items():
        tick = perf_counter()
        packed = pack_dashboard(board)
        pack_seconds += perf_counter() - tick
        tick = perf_counter()
        payload = json.dumps(packed, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        sizes[key] = len(payload.encode("utf-8"))
        serialize_seconds += perf_counter() - tick
        tick = perf_counter()
        dashboard_blocks[key] = b64gzip(payload)
        compress_seconds += perf_counter() - tick
    largest_raw = max(raw_blocks.items(), key=lambda item: len(item[1]), default=("-", ""))
    if len(largest_raw[1]) > 5 * 1024**2:
        logging.getLogger(__name__).warning(
            "[性能校验] 单个底表压缩块超过5MB: %s（%.1fMB），建议对该Sheet分页或虚拟滚动",
            largest_raw[0], len(largest_raw[1]) / 1024**2,
        )
    largest = max(sizes.items(), key=lambda item: item[1], default=("-", 0))
    logging.getLogger(__name__).info(
        "HTML载荷: 去重后看板JSON %.1fMB，底表压缩块 %.1fMB；最大看板=%s %.1fMB",
        sum(sizes.values()) / 1024**2,
        sum(len(value) for value in raw_blocks.values()) / 1024**2,
        largest[0], largest[1] / 1024**2,
    )
    main_manifest = {
        key: value for key, value in manifest.items()
        if key not in ("raw_blocks", "dashboards")
    }
    main_payload = b64gzip(json.dumps(main_manifest, ensure_ascii=False, separators=(",", ":")))
    raw_payload = json.dumps(raw_blocks, ensure_ascii=False, separators=(",", ":"))
    board_payload = json.dumps(dashboard_blocks, separators=(",", ":"))
    html = html.replace("__DASHBOARD_CSS__", css)
    html = html.replace("__DASHBOARD_DATA__", main_payload)
    html = html.replace("__DASHBOARD_RAW__", raw_payload)
    html = html.replace("__DASHBOARD_BLOCKS__", board_payload)
    html = html.replace("__DASHBOARD_JS__", javascript)
    html = html.replace("__BRAND_LOGO__", f"data:image/png;base64,{logo_data}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")

    logging.getLogger(__name__).info(
        "HTML输出明细: 公共数据打包 %.2fs | JSON序列化 %.2fs | 看板压缩 %.2fs | 其余输出 %.2fs",
        pack_seconds, serialize_seconds, compress_seconds,
        perf_counter() - started - pack_seconds - serialize_seconds - compress_seconds,
    )

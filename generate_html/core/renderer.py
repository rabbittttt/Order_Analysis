from __future__ import annotations

import base64
import json
import logging
import math
import uuid
from time import perf_counter
from pathlib import Path
from typing import Any

from core.web_shell import _write_text_atomic, b64gzip, gzip_text, render_dynamic_shell, write_static_shell


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
    write_static_shell(main_manifest, raw_blocks, dashboard_blocks, template_dir, output_file)

    logging.getLogger(__name__).info(
        "HTML输出明细: 公共数据打包 %.2fs | JSON序列化 %.2fs | 看板压缩 %.2fs | 其余输出 %.2fs",
        pack_seconds, serialize_seconds, compress_seconds,
        perf_counter() - started - pack_seconds - serialize_seconds - compress_seconds,
    )


def create_dynamic_snapshot(runtime: Path) -> Path:
    # The HTTP service exposes a batch only after its catalog is committed.
    # No populated-directory rename is needed on Windows.
    snapshot = runtime / "datasets" / uuid.uuid4().hex
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.mkdir()
    return snapshot


def render_dynamic_dashboard(manifest: dict[str, Any], template_dir: Path, output_file: Path, *,
                             runtime_dir: Path | None = None, snapshot: Path | None = None) -> None:
    """Publish an immutable dataset, then atomically switch the current pointer.

    Runtime is private: only the HTTP service exposes selected data and assets.
    Older datasets remain available to pages which already pinned their version.
    """
    import hashlib
    from urllib.parse import urlencode

    runtime = runtime_dir or output_file.parent / "runtime"
    entry = runtime / "index.html"
    # Retire only a verified duplicate produced by the previous dynamic build.
    # Keep it until the replacement dataset has been published successfully.
    legacy_duplicate = (output_file.is_file() and not output_file.is_symlink()
                        and entry.is_file() and output_file.read_bytes() == entry.read_bytes())
    assets = runtime / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot if snapshot is not None else create_dynamic_snapshot(runtime)
    dataset_id = snapshot.name

    def json_text(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    for directory in ("boards", "raw", "workbooks", "charts"):
        (snapshot / directory).mkdir(exist_ok=True)
    for key, board in manifest.get("dashboards", {}).items():
        name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json.gz"
        (snapshot / "boards" / name).write_bytes(gzip_text(json_text(pack_dashboard(board))))
    for key, value in manifest.get("raw_blocks", {}).items():
        file_id, sheet_id = key.split("|")
        if not file_id.isdigit() or (sheet_id != "xlsx" and not sheet_id.isdigit()):
            raise ValueError("Invalid raw block key")
        target = (snapshot / "workbooks" / (file_id + ".xlsx") if sheet_id == "xlsx"
                  else snapshot / "raw" / (file_id + "_" + sheet_id + ".json.gz"))
        target.write_bytes(base64.b64decode(value, validate=True))
    catalog = {key: value for key, value in manifest.items() if key not in ("dashboards", "raw_blocks")}
    catalog["dataset_id"] = dataset_id
    catalog["meta"] = {key: value for key, value in catalog.get("meta", {}).items() if key != "input_dir"}
    catalog["chart_assets"] = {}
    for key, value in manifest.get("chart_assets", {}).items():
        if isinstance(value, str) and value.startswith("data:image/") and ";base64," in value:
            header, encoded = value.split(",", 1)
            suffix = {"data:image/png;base64": ".png", "data:image/jpeg;base64": ".jpg", "data:image/svg+xml;base64": ".svg"}.get(header)
            if suffix:
                image_name = hashlib.sha256(key.encode("utf-8")).hexdigest() + suffix
                (snapshot / "charts" / image_name).write_bytes(base64.b64decode(encoded))
                catalog["chart_assets"][key] = "api/chart?" + urlencode({"dataset": dataset_id, "key": key})
                continue
        catalog["chart_assets"][key] = value

    html = render_dynamic_shell(template_dir, runtime)
    # Every data API checks the catalog before serving this batch. Write it
    # only after all batch files are complete, then select the batch last.
    _write_text_atomic(snapshot / "catalog.json", json_text(catalog))
    _write_text_atomic(runtime / "current.json", json_text({"dataset_id": dataset_id}))
    if legacy_duplicate:
        output_file.unlink()
        logging.getLogger(__name__).info("已清理重复页面: %s", output_file)
    logging.getLogger(__name__).info("动态看板已发布：批次 %s，页面 %.1f KB，看板 %d 个；数据目录 %s", dataset_id, len(html.encode("utf-8")) / 1024, len(manifest.get("dashboards", {})), runtime)

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import shutil
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from core.components import add_kpi_comparisons
from core.config import load_config
from core.data_paths import orders_input_directory
from core.discovery import discover_subjects, set_capabilities
from core.excel import WorkbookStore, clean_text, format_excel_cell, reset_conflict_diagnostics
from core.model_identity import STAGE_SOURCE_PATH
from core.renderer import b64gzip, render_dynamic_dashboard as render_dashboard, render_dashboard as render_static_dashboard
from core.validation import validate_manifest
from modules.registry import MODULES


ROOT = Path(__file__).resolve().parent
CODE_ROOT = ROOT.parent
PROJECT_ROOT = CODE_ROOT.parent if CODE_ROOT.name.lower() == "scripts" else CODE_ROOT
AUTO_OPEN_HTML = True
LOGGER = logging.getLogger("order_analysis")
BUILD_DIAGNOSTICS: list[str] = []
DIAGNOSTIC_COUNTS = {"WARNING": 0, "ERROR": 0}


class DuplicateDiagnosticFilter(logging.Filter):
    """Emit the same issue once per build, never hide new issues."""

    def __init__(self):
        super().__init__()
        self.seen = set()

    def filter(self, record):
        cached = getattr(record, "_diagnostic_filter_result", None)
        if cached and cached[0] is self:
            return cached[1]
        message = record.getMessage()
        eligible = ((record.levelno == logging.WARNING and not getattr(record, "diagnostic_continuation", False))
                    or "[Excel格式兼容]" in message)
        result = True
        if eligible:
            key = record.levelno, message
            result = key not in self.seen
            self.seen.add(key)
        record._diagnostic_filter_result = self, result
        return result


class DiagnosticCollector(logging.Handler):
    """Keep every emitted warning/error for the user-facing build report."""

    def __init__(self):
        super().__init__()
        self.seen = set()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING and not getattr(record, "diagnostic_continuation", False):
            DIAGNOSTIC_COUNTS["ERROR" if record.levelno >= logging.ERROR else "WARNING"] += 1
            message = f"{record.levelname} | {record.getMessage()}"
            if message not in self.seen:
                self.seen.add(message)
                BUILD_DIAGNOSTICS.append(message)  # Only the final inventory is unique; console/file output is untouched.


class LevelFormatter(logging.Formatter):
    """Console formatter that colors problem levels; files keep plain text."""

    COLORS = {"WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[35m"}

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        color = self.COLORS.get(record.levelname)
        return f"{color}{message}\033[0m" if color else message


def configure_runtime(output_dir: Path, debug: bool = False) -> Path:
    """Configure UTF-8 console/file logging before any workbook is opened."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    log_dir = output_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"generate_html_{timestamp}.log"
    if sys.platform == "win32":
        os.system("")  # enable ANSI colors in the Windows console
    fmt = "%(asctime)s | %(levelname)s | %(message)s"
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(LevelFormatter(fmt, datefmt="%H:%M:%S"))
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    BUILD_DIAGNOSTICS.clear()
    DIAGNOSTIC_COUNTS.update(WARNING=0, ERROR=0)
    reset_conflict_diagnostics()
    diagnostic_handler = DiagnosticCollector()
    duplicate_filter = DuplicateDiagnosticFilter()
    for handler in (console, file_handler, diagnostic_handler):
        handler.addFilter(duplicate_filter)
    level = logging.DEBUG if debug else logging.INFO
    logging.disable(logging.NOTSET)
    logging.basicConfig(
        level=level,
        handlers=[console, file_handler, diagnostic_handler],
        force=True,
    )
    # force=True resets root handlers, not a named logger's level/disabled flag.
    LOGGER.setLevel(level)
    LOGGER.disabled = False
    LOGGER.propagate = True
    return log_file


def serializable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def split_parallel_blocks(name: str, rows: list[list]) -> list[dict[str, Any]]:
    """Split side-by-side blocks (like SKU's 表格A/B/C) into separate tables."""
    if len(rows) < 2:
        return [{"name": name, "rows": rows}]
    title_cols = [col for col, value in enumerate(rows[0]) if value not in (None, "")]
    # 多区块:第一行有多个标题，且标题列之间至少隔一个空列，第二行在各标题列有表头
    if len(title_cols) < 2:
        return [{"name": name, "rows": rows}]
    if any(right - left < 2 for left, right in zip(title_cols, title_cols[1:])):
        return [{"name": name, "rows": rows}]
    second = rows[1]
    if not all(col < len(second) and second[col] not in (None, "") for col in title_cols):
        return [{"name": name, "rows": rows}]
    width = max(len(row) for row in rows)
    blocks = []
    for index, start in enumerate(title_cols):
        end = title_cols[index + 1] if index + 1 < len(title_cols) else width
        block_rows = []
        for row in rows:
            sliced = row[start:end]
            while sliced and sliced[-1] in (None, ""):
                sliced.pop()
            block_rows.append(sliced)
        if block_rows:
            block_width = max(len(row) for row in block_rows)
            keep = [col for col in range(block_width) if any(col < len(row) and row[col] not in (None, "") for row in block_rows)]
            block_rows = [[row[col] if col < len(row) else None for col in keep] for row in block_rows]
        blocks.append({"name": f"{name} · {rows[0][start]}", "rows": block_rows})
    return blocks


def raw_tables(store: WorkbookStore) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """按需加载的底表行块及原始 XLSX 快照；下载快照保留全部 Sheet 和格式。"""
    files = []
    blocks: dict[str, str] = {}
    for file_index, item in enumerate(store.items):
        sheets = []
        for sheet in item.workbook.worksheets:
            if getattr(sheet, "sheet_state", "visible") != "visible":
                continue
            rows_by_index, occupied = {}, set()
            # Normal Workbook cells already implement merged-cell semantics.
            # Do not materialize every blank cell in a sparse styled rectangle.
            for cell in sheet._cells.values():
                if cell.value is None:
                    continue
                value = format_excel_cell(cell)
                if value not in (None, ""):
                    rows_by_index.setdefault(cell.row, {})[cell.column] = value
                    occupied.add(cell.column)
            columns = sorted(occupied)
            rows = []
            for _, values in sorted(rows_by_index.items()):
                last_column = max(values)
                rows.append([
                    values.get(column, None if column > last_column else "")
                    for column in columns
                ])
            for block in split_parallel_blocks(sheet.title, rows):
                block_rows = block["rows"]
                # 首行是区块大标题（单值）、次行才是列名时，去掉冗余标题行让列名成为表头
                if (
                    len(block_rows) > 1
                    and sum(1 for value in block_rows[0] if value not in (None, "")) <= 1
                    and sum(1 for value in block_rows[1] if value not in (None, "")) > 1
                ):
                    block_rows = block_rows[1:]
                key = f"{file_index}|{len(sheets)}"
                blocks[key] = b64gzip(json.dumps({"rows": block_rows}, ensure_ascii=False, separators=(",", ":")))
                sheets.append({
                    "name": block["name"],
                    "total_rows": len(block_rows),
                    "total_cols": max((len(row) for row in block_rows), default=0),
                    "source_sheet": sheet.title,
                })
        file_info = {"name": item.path.name, "sheets": sheets}
        # Embed the original file once, not a CSV reconstruction of the split
        # display blocks. This also works when the HTML is copied elsewhere or
        # opened offline, and preserves formulas, merged cells and hidden tabs.
        try:
            workbook_bytes = item.path.read_bytes()
        except OSError as exc:
            LOGGER.warning("底表整表导出不可用: %s | %s", item.path.name, exc)
        else:
            workbook_key = f"{file_index}|xlsx"
            blocks[workbook_key] = base64.b64encode(workbook_bytes).decode("ascii")
            file_info["workbook_key"] = workbook_key
        files.append(file_info)
    return files, blocks


def build(input_dir: Path, output_file: Path, *, runtime_dir: Path | None = None, source_signature: dict | None = None, static: bool = False) -> tuple[dict[str, Any], list[str]]:
    runtime_dir = runtime_dir or output_file.parent / "runtime"
    build_started = perf_counter()
    LOGGER.info("开始生成订单分析看板")
    LOGGER.info("输入目录: %s", input_dir)
    LOGGER.info("输出目标: %s", output_file if static else runtime_dir)
    config = load_config(ROOT / "config.json")
    if config.get("chart_render_mode") not in {"original", "generated"}:
        raise ValueError("config.json 的 chart_render_mode 必须是 original 或 generated")
    manifest_mode = config.get("build_manifest_mode", "compact")
    if manifest_mode not in {"compact", "full", "off"}:
        raise ValueError("config.json 的 build_manifest_mode 必须是 compact、full 或 off")
    store = WorkbookStore(input_dir, cache_dir=output_file.parent / ".cache" / "excel")
    stage_started = perf_counter()
    # These workbooks describe stage identities or a separate report, not order sheets.
    excluded_names = {"鸿蒙智行销量数据汇总.xlsx", STAGE_SOURCE_PATH.name}
    store.load(exclude_names=excluded_names, data_only_view=config.get("chart_render_mode") == "generated")
    load_seconds = perf_counter() - stage_started
    if store.load_errors:
        store.close()
        raise RuntimeError("Excel 读取不完整：" + "；".join(store.load_errors))
    if not store.items:
        details = "；".join(store.load_errors) if store.load_errors else "目录中没有xlsx文件"
        raise RuntimeError(f"没有成功读取任何Excel，无法生成看板：{details}")
    try:
        stage_started = perf_counter()
        subjects = discover_subjects(store)
        discovery_seconds = perf_counter() - stage_started
        LOGGER.info("已识别分析主体 %d 个", len(subjects))
        LOGGER.debug("分析主体明细: %s", "、".join(subject.name for subject in subjects))
        dashboards: dict[str, Any] = {}
        capabilities: dict[str, set[str]] = {}
        runtime_warnings = list(store.load_errors)
        module_seconds: dict[str, float] = defaultdict(float)
        module_builds: dict[str, int] = defaultdict(int)
        for module in MODULES:
            set_config = getattr(module, "set_config", None)
            if set_config:
                set_config(config)
        for subject in subjects:
            matched_modules = []
            for module in MODULES:
                if hasattr(module, "set_dashboards"):
                    module.set_dashboards(dashboards)
                module_started = perf_counter()
                try:
                    dashboard = module.build(store, subject)
                except Exception as exc:
                    message = f"模块生成失败: 主体={subject.name}, 模块={module.label}, 错误={exc}"
                    runtime_warnings.append(message)
                    LOGGER.exception(message)
                    continue
                finally:
                    module_seconds[module.label] += perf_counter() - module_started
                    module_builds[module.label] += 1
                if not dashboard:
                    continue
                dashboards[f"{subject.id}|{module.id}"] = store.resolve_dashboard_sources(dashboard).to_dict()
                capabilities.setdefault("".join(subject.name.split()), set()).add(module.id)
                matched_modules.append(module.label)
            LOGGER.debug("主体映射完成: %s -> %s", subject.name, "、".join(matched_modules) if matched_modules else "仅底表")
        configured_order = config.get("module_order") or []
        known_modules = {module.id for module in MODULES} | {"raw"}
        unknown_modules = [module for module in configured_order if module not in known_modules]
        if unknown_modules:
            LOGGER.warning("[\u914d\u7f6e\u6821\u9a8c] module_order \u5305\u542b\u672a\u77e5\u6a21\u5757: %s", "\u3001".join(unknown_modules))
        missing_modules = [module.id for module in MODULES if module.id not in configured_order]
        if missing_modules:
            LOGGER.warning("[\u914d\u7f6e\u6821\u9a8c] module_order \u672a\u914d\u7f6e\u5df2\u6ce8\u518c\u6a21\u5757: %s", "\u3001".join(missing_modules))
        set_capabilities(subjects, capabilities, configured_order)
        add_kpi_comparisons(dashboards)
        if store.multi_source_groups:
            LOGGER.info("多文件来源：%d类，共%d个文件匹配项参与合并；详细文件名可使用 --debug 查看",
                        len(store.multi_source_groups), sum(store.multi_source_groups.values()))
        stage_started = perf_counter()
        raw_files, raw_blocks = raw_tables(store)
        raw_seconds = perf_counter() - stage_started
        manifest = {
            "meta": {
                "title": config["title"],
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "input_dir": str(input_dir),
            },
            "config": config,
            "subjects": [subject.to_dict() for subject in subjects],
            "dashboards": dashboards,
            "chart_assets": store.chart_assets,
            "raw_files": raw_files,
            "raw_blocks": raw_blocks,
        }
        validation_started = perf_counter()
        validation_warnings = validate_manifest(manifest)
        for warning in validation_warnings:
            LOGGER.warning("[生成校验] %s", warning)
        validation_seconds = perf_counter() - validation_started
        LOGGER.info("开始输出%s看板（主体 %d 个，看板 %d 个）", "静态" if static else "动态", len(subjects), len(dashboards))
        stage_started = perf_counter()
        if DIAGNOSTIC_COUNTS["ERROR"]:
            raise RuntimeError("本批次存在生成错误，保留上一批已发布数据")
        if source_signature is not None:
            manifest["source_signature"] = source_signature
        if static:
            render_static_dashboard(manifest, ROOT / "templates", output_file)
        elif runtime_dir == output_file.parent / "runtime":
            render_dashboard(manifest, ROOT / "templates", output_file)
        else:
            render_dashboard(manifest, ROOT / "templates", output_file, runtime_dir=runtime_dir)
        render_seconds = perf_counter() - stage_started
        entry = output_file if static else runtime_dir / "index.html"
        LOGGER.info("入口页面体积: %.1fKB", entry.stat().st_size / 1024)
        emitted_messages = "\n".join(BUILD_DIAGNOSTICS)
        warnings = list(dict.fromkeys([
            *BUILD_DIAGNOSTICS,
            *(f"WARNING | {message}" for message in runtime_warnings if message not in emitted_messages),
        ]))
        stage_started = perf_counter()
        manifest_path = output_file.parent / "build_manifest.json"
        if manifest_mode != "off":
            with manifest_path.open("w", encoding="utf-8") as handle:
                if manifest_mode == "full":
                    json.dump(manifest, handle, ensure_ascii=False, indent=2)
                else:
                    json.dump(manifest, handle, ensure_ascii=False, separators=(",", ":"))
            LOGGER.info(
                "构建清单: %s 模式，%.1fMB",
                manifest_mode,
                manifest_path.stat().st_size / 1024 / 1024,
            )
        else:
            if manifest_path.exists():
                manifest_path.unlink()
            LOGGER.info("构建清单: 已按 config.json 跳过（旧清单已清理，避免误读过期数据）")
        legacy_warning_file = output_file.parent / "build_warnings.log"
        if legacy_warning_file.exists():
            legacy_warning_file.unlink()
        manifest_seconds = perf_counter() - stage_started
        if warnings:
            LOGGER.info("诊断完成：WARNING %d条，ERROR %d条；问题记录%d条；相同问题不重复打印，冲突按完整范围合并",
                        DIAGNOSTIC_COUNTS["WARNING"], DIAGNOSTIC_COUNTS["ERROR"], len(warnings))
        else:
            LOGGER.info("校验完成：没有发现警告")
        module_summary = "；".join(
            f"{label} {seconds:.2f}s/{module_builds[label]}次"
            for label, seconds in sorted(module_seconds.items(), key=lambda item: item[1], reverse=True)
        )
        LOGGER.info("模块耗时: %s", module_summary)
        LOGGER.info(
            "性能汇总: Excel加载 %.2fs | 主体识别 %.2fs | 模块生成 %.2fs | "
            "底表整理 %.2fs | 数据校验 %.2fs | HTML输出 %.2fs | 清单/诊断 %.2fs | 其他编排 %.2fs | 总计 %.2fs",
            load_seconds,
            discovery_seconds,
            sum(module_seconds.values()),
            raw_seconds,
            validation_seconds,
            render_seconds,
            manifest_seconds,
            perf_counter() - build_started - sum((load_seconds, discovery_seconds, sum(module_seconds.values()), raw_seconds, validation_seconds, render_seconds, manifest_seconds)),
            perf_counter() - build_started,
        )
        return manifest, warnings
    finally:
        store.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the HarmonyOS Auto order dashboard.")
    parser.add_argument("--input", type=Path, default=orders_input_directory(PROJECT_ROOT))
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="静态模式为 HTML 文件；动态模式使用其所在目录保存 runtime 和日志。",
    )
    parser.add_argument("--static", action="store_true", help="生成可离线打开的单文件 HTML，不启动后台服务。")
    parser.add_argument("--check", action="store_true", help="Return a non-zero exit code when validation warnings exist.")
    parser.add_argument("--no-open", action="store_true", help="Generate the HTML without opening the default browser.")
    parser.add_argument("--port", type=int, default=8767, help="本地订单服务端口。")
    parser.add_argument("--debug", action="store_true", help="输出调试日志，用于排查数据解析问题。")
    args = parser.parse_args()
    if args.output is None:
        filename = "鸿蒙智行订单分析汇总_静态版.html" if args.static else "鸿蒙智行订单分析汇总.html"
        args.output = PROJECT_ROOT / "output_file" / filename
    return args


def cleanup_input_cache(input_dir: Path) -> None:
    """Remove only the supplied local output directory's real .cache folder."""
    cache_dir = input_dir / ".cache"
    try:
        input_root = input_dir.resolve()
        cache_dir = input_root / ".cache"
        if not cache_dir.exists() and not cache_dir.is_symlink():
            return
        # Do not follow a symlink/junction or remove an unexpected file.
        if cache_dir.is_symlink() or cache_dir.resolve() != cache_dir or not cache_dir.is_dir():
            LOGGER.warning("缓存清理已跳过：不是输入目录内的普通 .cache 文件夹：%s", cache_dir)
            return
        shutil.rmtree(cache_dir)
        LOGGER.info("已清理运行缓存: %s", cache_dir)
    except OSError as exc:
        LOGGER.warning("运行缓存未能清理: %s（%s）；可在文件占用结束后手动删除", cache_dir, exc)


def open_dynamic_dashboard(data_dir: Path, port: int, *, input_dir: Path | None = None, open_browser: bool = True, check_seconds: float = 300, stable_seconds: float = 60, no_sync: bool = False) -> None:
    import subprocess
    import time
    import urllib.error
    import urllib.request

    base = f"http://127.0.0.1:{port}"
    from core.server import SERVICE_FINGERPRINT, data_fingerprint
    expected_service = SERVICE_FINGERPRINT
    expected_directory = data_fingerprint(data_dir)
    input_dir = (input_dir or orders_input_directory(PROJECT_ROOT)).resolve()
    expected_input = None if no_sync else data_fingerprint(input_dir)
    def ready():
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as response:
                health = json.load(response)
            if health.get("application") != "order-dashboard":
                raise RuntimeError(f"端口 {port} 已用于其他服务或数据目录，请使用 --port 指定空闲端口")
            if health.get("data_fingerprint") != expected_directory:
                raise RuntimeError("该端口的订单服务使用不同数据目录，请使用 --port 指定空闲端口")
            if health.get("service_fingerprint") != expected_service:
                raise RuntimeError("订单后台代码已更新，请停止旧订单服务后重新运行；或使用 --port 指定空闲端口")
            if health.get("input_fingerprint") != expected_input:
                raise RuntimeError("该端口订单服务的 Excel 输入目录或同步模式不同，请先停止旧服务或使用其他端口")
            if not no_sync and (health.get("check_seconds") != check_seconds or health.get("stable_seconds") != stable_seconds):
                raise RuntimeError("自动同步间隔已调整，请停止旧订单服务后重新启动")
            return True
        except (urllib.error.URLError, TimeoutError):
            return False
    if not ready():
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        log_path = data_dir.parent / "log" / "order_server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as stream:
            command = [sys.executable, str(ROOT / "server.py"), "--data-dir", str(data_dir.resolve()), "--port", str(port), "--input", str(input_dir), "--check-seconds", str(check_seconds), "--stable-seconds", str(stable_seconds)]
            if no_sync:
                command.append("--no-sync")
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, creationflags=flags)
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError(f"服务启动失败，请查看 {log_path}")
            if ready():
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(f"服务启动超时，请查看 {log_path}")
    if open_browser:
        webbrowser.open(base + "/")
    LOGGER.info("订单看板访问地址: %s/", base)


def main() -> int:
    args = parse_args()
    static_mode = getattr(args, "static", False)
    log_file = configure_runtime(args.output.parent, args.debug)
    try:
        from core.sync import BuildLock
        import core.model_identity as identity
        identity.STAGE_SOURCE_PATH = args.input / "小订及首销数据整理.xlsx"
        with BuildLock(args.output.parent / "runtime"):
            try:
                if static_mode:
                    manifest, warnings = build(args.input, args.output, static=True)
                else:
                    manifest, warnings = build(args.input, args.output)
            finally:
                cleanup_input_cache(args.output.parent)
    except Exception:
        LOGGER.exception("生成失败，请根据上方错误和日志排查")
        LOGGER.error("运行日志: %s", log_file)
        return 1
    target = args.output if static_mode else args.output.parent / "runtime"
    errors = DIAGNOSTIC_COUNTS["ERROR"]
    if errors:
        LOGGER.error("生成不完整：发生%d条错误；输出目标: %s",
                     errors, target, extra={"diagnostic_continuation": True})
    else:
        LOGGER.info("生成成功: %s", target)
    LOGGER.info("汇总: 主体=%d，看板=%d, 问题=%d", len(manifest["subjects"]), len(manifest["dashboards"]), len(warnings))
    LOGGER.info("运行日志: %s", log_file)
    if errors:
        return 1
    if AUTO_OPEN_HTML and not args.no_open:
        try:
            if static_mode:
                webbrowser.open(args.output.resolve().as_uri())
                LOGGER.info("静态网页: %s", args.output.resolve())
            else:
                open_dynamic_dashboard(args.output.parent / "runtime", args.port, input_dir=args.input)
        except Exception:
            if static_mode:
                LOGGER.exception("自动打开失败，请手动打开静态网页: %s", args.output)
            else:
                LOGGER.exception("自动启动失败；请运行 server.py 后通过网址访问看板")
            return 1
    return 1 if args.check and warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())

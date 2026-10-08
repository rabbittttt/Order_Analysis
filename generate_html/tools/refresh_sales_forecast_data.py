from __future__ import annotations

import argparse
import hashlib
import json
from copy import copy
import logging
import os
import re
import sys
import unicodedata
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


LOGGER = logging.getLogger("sales_forecast_refresh")
ROOT = Path(__file__).resolve().parent
GENERATE_HTML_ROOT = ROOT.parent
if str(GENERATE_HTML_ROOT) not in sys.path:
    sys.path.insert(0, str(GENERATE_HTML_ROOT))

from core.model_identity import model_key, usable_attribute, stage_records, stage_name, resolve_stage_identity, generation_records, FORECAST_SOURCE_PATH
from core.forecast_summary import SUMMARY_NAME, INDEX_SHEET, GUIDE_SHEET, DAILY_SHEET, WEEKLY_SHEET, D12_SHEET, D12_HEADERS, public_forecast_tables, summary_scope, summary_quality, table_records
from core.excel import WorkbookItem, _source_date_range, grain_from_sheet, load_data_workbook

CODE_ROOT = GENERATE_HTML_ROOT.parent
PROJECT_ROOT = CODE_ROOT.parent if CODE_ROOT.name.lower() == "scripts" else CODE_ROOT
FORECAST_INPUT_ROOT = PROJECT_ROOT / "input_file" / "销量预测输入文件"
DEFAULT_SOURCE = FORECAST_SOURCE_PATH
DEFAULT_OUTPUT = PROJECT_ROOT / "output_file" / SUMMARY_NAME
DEFAULT_ORDERS = PROJECT_ROOT / "output_file"
DEFAULT_MAPPING = DEFAULT_SOURCE
LEGACY_MAPPINGS = (
    FORECAST_INPUT_ROOT / "传播代际名映射.xlsx",
    FORECAST_INPUT_ROOT / "车型代际映射.xlsx",
)
REFRESH_CODE_DEPENDENCIES = (
    Path(__file__).resolve(),
    GENERATE_HTML_ROOT / "core" / "model_identity.py",
    GENERATE_HTML_ROOT / "core" / "forecast_summary.py",
    GENERATE_HTML_ROOT / "core" / "excel.py",
    GENERATE_HTML_ROOT / "core" / "china_calendar.py",
    GENERATE_HTML_ROOT / "modules" / "sales_forecast.py",
)

BLUE = "1677FF"
BLUE_DARK = "0F4C9A"
BLUE_LIGHT = "EAF4FF"
GRID = "D9E2EC"
TEXT = "243B53"
MUTED = "627D98"
WHITE = "FFFFFF"
PERCENT_FIELDS = {
    "小订转化率", "直接大定占比", "退订率", "字段完整度", "口径一致性", "留存大定率", "大定到锁单率",
    "D1小转大/总小转大", "D2小转大/总小转大", "D1+D2小转大/总小转大", "D1直接大/总直接大",
    "D2直接大/总直接大", "D1+D2直接大/总直接大", "D1直接大/D1大定", "D2直接大/D2大定",
    "D1小转大/D1大定", "D2小转大/D2大定", "D1+D2小转大/D1+D2大定",
    "D2小转大/D1小转大", "D1小转大/D1+D2小转大",
    "D2直接大/D1直接大", "D1直接大/D1+D2直接大",
    "D1+D2直接大/D1+D2大定", "D1退订率", "D2退订率", "D1+D2退订率",
    "D2退订/D1退订", "D1退订/D1+D2退订",
}

# Reuse immutable openpyxl style objects instead of allocating and hashing a
# new Font/Fill/Border/Alignment for every generated cell.
_THIN_SIDE = Side(style="thin", color=GRID)
_HEADER_FILL = PatternFill("solid", fgColor=BLUE)
_HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color=WHITE)
_HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
_HEADER_BORDER = Border(bottom=Side(style="medium", color=BLUE_DARK))
_BODY_FONT = Font(name="微软雅黑", size=10, color=TEXT)
_BODY_ALIGNMENT = Alignment(vertical="center", wrap_text=False)
_WRAPPED_ALIGNMENT = Alignment(vertical="center", wrap_text=True)
_BODY_BORDER = Border(bottom=_THIN_SIDE)
_EVEN_FILL = PatternFill("solid", fgColor="F8FBFF")

SUMMARY_HEADER_ALIASES = {
    "车型": {"传播名", "历史传播名", "车型", "车型名称", "历史车型", "车系车型", "代际名"},
    "留资": {"留资", "留资日期"},
    "小订开始日期": {"小订开始日期", "小订开始", "小订开启日期"},
    "小订结束日期": {"小订结束日期", "小订结束", "小订截止日期"},
    "开始大定日期": {"开始大定日期", "大定开始日期", "首销开始日期", "发布日", "上市日期"},
    "小转大结束日期": {"小转大结束日期", "首销截止", "首销结束日期", "首销期结束日期"},
    "小订天数": {"小订天数", "小订期天数"},
    "首销期天数": {"首销期天数", "首销天数", "首销周期天数"},
    "总小订": {"总小订", "小订总量", "累计小订", "总小订量"},
    "小订转大定量": {"小订转大定量", "小订转大定", "小转大", "总小转大", "小转大总量"},
    "小订转化率": {"小订转化率", "小转大率", "小订转大定率", "小转大转化率"},
    "大定量": {"大定量", "总大定", "大定总量", "首销期大定"},
    "直接大定量": {"直接大定量", "总直接大定", "直接大定", "直接大定总量"},
    "直接大定占比": {"直接大定占比", "大定直接占比", "直接大定比例"},
    "小订后退定": {"小订后退定", "小订后退订", "退订", "退订量", "总退订"},
    "小订后退定占比": {"小订后退定占比", "小订后退订占比", "退订率", "退订占比"},
    "首销期留存大定": {"首销期留存大定", "留存大定", "首销期净大定", "净大定"},
    "留存大定率": {"留存大定率", "首销期留存大定率", "净大定率", "首销期净大定率"},
    "首销期锁单": {"首销期锁单", "锁单量"},
    "锁单率": {"锁单率", "首销期锁单率"},
}

PROGRESS_SPECS = {
    "small": {"preferred": "小转大进度", "title_aliases": ("小转大", "小订转大定"), "forbidden": ()},
    "direct": {"preferred": "直接大定进度", "title_aliases": ("直接大定",), "forbidden": ()},
    "gross": {"preferred": "大定进度", "title_aliases": ("大定进度", "总大定"), "forbidden": ("直接",)},
    "cancel": {"preferred": "退订进度", "title_aliases": ("退订", "退定"), "forbidden": ()},
}


class InputFormatError(ValueError):
    """Raised when a required logical table cannot be recognized from the source workbook."""


def normalize(value: Any) -> str:
    return model_key(value)


def header_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("（", "(").replace("）", ")")
    return re.sub(r"[\s\r\n\t()（）:：/_\-]", "", text)


HEADER_LOOKUP = {
    header_key(alias): canonical
    for canonical, aliases in SUMMARY_HEADER_ALIASES.items()
    for alias in aliases
}


def canonical_header(value: Any) -> str:
    text = str(value or "").strip()
    return HEADER_LOOKUP.get(header_key(text), text)


def day_number(value: Any) -> int | None:
    key = header_key(value).replace("第", "").replace("天", "")
    match = re.fullmatch(r"d?0*(\d+)", key, re.I)
    if not match:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


HeaderScan = list[tuple[int, list[str], list[tuple[int, int]]]]


def scan_header_rows(sheet, max_scan_rows: int = 40) -> HeaderScan:
    """Read a worksheet's header area in one forward XML pass.

    Calling ``iter_rows`` once per candidate row is particularly expensive for
    read-only workbooks because openpyxl restarts the worksheet XML stream each
    time.  This scan is shared by summary/progress sheet discovery.
    """
    limit = min(sheet.max_row or max_scan_rows, max_scan_rows)
    scanned: HeaderScan = []
    for row_number, values in enumerate(
        sheet.iter_rows(min_row=1, max_row=limit, values_only=True),
        1,
    ):
        headers = [canonical_header(value) for value in values]
        day_columns = sorted(
            ((index, number) for index, header in enumerate(headers) if (number := day_number(header)) is not None),
            key=lambda item: item[1],
        )
        scanned.append((row_number, headers, day_columns))
    return scanned


def row_headers(sheet, row_number: int) -> list[str]:
    """Compatibility helper for callers that need one explicit row."""
    for number, headers, _ in scan_header_rows(sheet, row_number):
        if number == row_number:
            return headers
    return []


def find_header_row(
    sheet,
    *,
    require_days: bool = False,
    max_scan_rows: int = 40,
    scanned_rows: HeaderScan | None = None,
) -> tuple[int, list[str], list[tuple[int, int]]]:
    best: tuple[int, int, list[str], list[tuple[int, int]]] | None = None
    rows = scanned_rows if scanned_rows is not None else scan_header_rows(sheet, max_scan_rows)
    for row_number, headers, day_columns in rows:
        score = int("车型" in headers) * 10 + len(set(headers) & set(SUMMARY_HEADER_ALIASES))
        if require_days:
            score += min(len(day_columns), 10) * 2
            if not day_columns:
                continue
        if "车型" not in headers:
            continue
        if require_days:
            # The first block is the raw quantity table. Later percentage
            # blocks may have more day columns while an event is in progress.
            return row_number, headers, day_columns
        candidate = (score, -row_number, headers, day_columns)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        raise InputFormatError(
            f"Sheet“{sheet.title}”前{max_scan_rows}行未找到包含‘车型’"
            + ("和D1/D2…列" if require_days else "")
            + "的表头"
        )
    return -best[1], best[2], best[3]


def workbook_header_index(workbook, max_scan_rows: int = 40) -> dict[str, HeaderScan]:
    return {sheet.title: scan_header_rows(sheet, max_scan_rows) for sheet in workbook.worksheets}


def find_summary_sheet(workbook, header_index: dict[str, HeaderScan] | None = None) -> tuple[Any, int, list[str]]:
    candidates = []
    for sheet in workbook.worksheets:
        try:
            row_number, headers, _ = find_header_row(
                sheet,
                require_days=False,
                scanned_rows=(header_index or {}).get(sheet.title),
            )
        except InputFormatError:
            continue
        recognized = set(headers) & set(SUMMARY_HEADER_ALIASES)
        score = len(recognized) + (8 if "汇总" in sheet.title else 0) + (5 if sheet.title in {"传播名汇总", "车型汇总"} else 0)
        candidates.append((score, sheet, row_number, headers))
    if not candidates:
        raise InputFormatError(f"工作簿没有识别到传播名汇总表；现有Sheet：{'、'.join(workbook.sheetnames)}")
    score, sheet, row_number, headers = max(candidates, key=lambda item: item[0])
    required = {"车型", "总小订", "小订转大定量", "大定量", "直接大定量"}
    missing = sorted(required - set(headers))
    if missing:
        raise InputFormatError(
            f"识别到汇总表“{sheet.title}”第{row_number}行为表头，但缺少必要字段：{'、'.join(missing)}；"
            f"当前表头：{'、'.join(header for header in headers if header)}"
        )
    LOGGER.debug("识别传播名汇总：Sheet=%s，表头行=%d，识别字段=%d个", sheet.title, row_number, len(set(headers) & set(SUMMARY_HEADER_ALIASES)))
    return sheet, row_number, headers


def find_progress_sheet(
    workbook,
    role: str,
    header_index: dict[str, HeaderScan] | None = None,
) -> tuple[Any, int, list[str], list[tuple[int, int]]]:
    spec = PROGRESS_SPECS[role]
    candidates = []
    for sheet in workbook.worksheets:
        try:
            row_number, headers, day_columns = find_header_row(
                sheet,
                require_days=True,
                scanned_rows=(header_index or {}).get(sheet.title),
            )
        except InputFormatError:
            continue
        title_key = header_key(sheet.title)
        name_score = 20 if any(header_key(alias) in title_key for alias in spec["title_aliases"]) else 0
        if any(header_key(term) in title_key for term in spec["forbidden"]):
            name_score -= 30
        if sheet.title == spec["preferred"]:
            name_score += 30
        candidates.append((name_score + min(len(day_columns), 10), sheet, row_number, headers, day_columns))
    if not candidates:
        raise InputFormatError(
            f"未找到{spec['preferred']}对应的当日数量表；允许Sheet轻微改名，但表头必须含车型和D1/D2…列。"
            f"现有Sheet：{'、'.join(workbook.sheetnames)}"
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    score, sheet, row_number, headers, day_columns = candidates[0]
    if score <= 10:
        raise InputFormatError(
            f"无法可靠判断{spec['preferred']}对应哪个Sheet；候选Sheet“{sheet.title}”名称关联度过低。"
        )
    if len(candidates) > 1 and candidates[1][0] == score:
        raise InputFormatError(
            f"{spec['preferred']}识别到两个同分候选Sheet：{sheet.title}、{candidates[1][1].title}；"
            "请在其中一个Sheet名中保留对应指标关键词。"
        )
    return sheet, row_number, headers, day_columns


def as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_div(numerator: Any, denominator: Any) -> float | None:
    if numerator in (None, ""):
        return None
    denominator_value = as_number(denominator)
    if not denominator_value:
        return None
    return as_number(numerator) / denominator_value


def valid_rate(value: Any) -> bool:
    number = as_number(value, float("nan"))
    return number == number and 0 <= number <= 1


def close_count(left: Any, right: Any, relative_tolerance: float = 0.002, absolute_tolerance: float = 5.0) -> bool:
    left_value, right_value = as_number(left), as_number(right)
    return abs(left_value - right_value) <= max(absolute_tolerance, max(abs(left_value), abs(right_value)) * relative_tolerance)


def day_structure_quality(small: Any, direct: Any, gross: Any, label: str) -> tuple[bool, str]:
    small_value, direct_value, gross_value = as_number(small), as_number(direct), as_number(gross)
    if gross_value <= 0:
        return False, f"{label}总大定缺失或为0"
    if small_value < 0 or direct_value < 0:
        return False, f"{label}订单来源出现负数"
    if small_value > gross_value * 1.02 or direct_value > gross_value * 1.02:
        return False, f"{label}单项订单来源高于总大定"
    if not close_count(small_value + direct_value, gross_value):
        return False, f"{label}小转大+直接大定与总大定不一致"
    return True, ""


def weekday_name(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return ("周一", "周二", "周三", "周四", "周五", "周六", "周日")[value.weekday()]
    return "未维护"


def brand_of(model: str) -> str:
    return next((brand for brand in ("问界", "智界", "享界", "尊界", "尚界") if brand in model), "")


def source_models(source: Path) -> list[str]:
    return [str(record["车型"]).strip() for record in cached_summary(source)]


def style_sheet(sheet, percent_headers: set[str] | None = None) -> None:
    percent_headers = percent_headers or set()
    # Register identical style combinations once per sheet, rather than hashing
    # Font/Border/Alignment objects for every cell. Include the original style so
    # custom formats/protection/odd-row fills survive; copy arrays on assignment
    # because later callers may change one cell's format or wrapping independently.
    styles = {}

    def apply_style(cell, *, header=False, number_format=None):
        even = not header and cell.row % 2 == 0
        key = (tuple(cell._style or ()), header, even, number_format)
        if key in styles:
            cell._style = copy(styles[key])
            return
        cell.font = _HEADER_FONT if header else _BODY_FONT
        cell.alignment = _HEADER_ALIGNMENT if header else _BODY_ALIGNMENT
        cell.border = _HEADER_BORDER if header else _BODY_BORDER
        if header or even:
            cell.fill = _HEADER_FILL if header else _EVEN_FILL
        if number_format is not None:
            cell.number_format = number_format
        styles[key] = copy(cell._style)

    for cell in sheet[1]:
        apply_style(cell, header=True)
    sheet.row_dimensions[1].height = 30
    headers = [str(cell.value or "") for cell in sheet[1]]
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            number_format = None
            if headers[cell.column - 1] in percent_headers:
                number_format = "0.0%"
            elif isinstance(cell.value, datetime):
                number_format = "yyyy-mm-dd hh:mm" if any((cell.value.hour, cell.value.minute, cell.value.second)) else "yyyy-mm-dd"
            elif isinstance(cell.value, (int, float)):
                number_format = "#,##0.00" if not float(cell.value).is_integer() else "#,##0"
            apply_style(cell, number_format=number_format)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    for column in range(1, sheet.max_column + 1):
        header = headers[column - 1]
        if column == 1:
            width = 27
        elif header in {"代际名", "映射依据", "来源URL", "人工备注", "参数来源", "数据来源", "读取/计算规则", "内容"}:
            width = 30
        elif re.fullmatch(r"D\d+", header):
            width = 10
        else:
            width = min(max(len(header) * 1.7 + 3, 12), 20)
        sheet.column_dimensions[get_column_letter(column)].width = width


def add_table(sheet, name: str) -> None:
    # Microsoft 365 repairs/removes Table parts generated by the current
    # workbook toolchain. These workbooks do not use structured references, so
    # retain the styled range and worksheet AutoFilter without an Excel Table.
    return


def build_mapping_workbook(path: Path, models: Iterable[str]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "车型基本信息"
    headers = [
        "历史传播名", "订单分析代际名", "品牌", "原始表简称/别名",
        "产品档位", "能源类型", "发布类型", "发布时段",
        "映射状态", "映射依据", "来源URL", "人工备注",
    ]
    sheet.append(headers)
    for model in models:
        sheet.append([
            model, "", brand_of(model), "",
            "待维护", "待维护", "待维护", "待维护",
            "待人工确认", "待人工维护传播名—代际名映射", "", "",
        ])
    style_sheet(sheet)
    add_table(sheet, "VehicleMasterData")
    notes = workbook.create_sheet("使用说明")
    notes.append(["项目", "说明"])
    notes.append(["用途", "连接历史文件中的传播名与订单分析中的代际名；刷新二次处理文件及网页匹配都会读取本文件。"])
    notes.append(["唯一键", "历史传播名必须唯一；多个历史传播名可以映射到同一个订单分析代际名。"])
    notes.append(["别名", "原始表简称/别名用竖线 | 分隔，用于匹配进度表里的简称。"])
    notes.append(["车型属性", "产品档位、能源类型、发布类型、发布时段与映射维护在同一行；发布时段填写上午/下午/晚上，修改后重新运行刷新脚本即可生效。"])
    notes.append(["重名处理", "发现重复历史传播名或同一简称命中多行时，脚本打印警告并拒绝静默覆盖。"])
    notes.append(["初始来源", "仅从原始文件提取历史传播名和品牌；代际映射及车型属性均需人工维护。"])
    style_sheet(notes)
    add_table(notes, "MappingNotes")
    workbook.save(path)
    workbook.close()


def ensure_mapping(path: Path, source: Path) -> None:
    if path.exists():
        return
    LOGGER.warning("映射文件不存在，按原始传播名创建待人工维护版本: %s", path)
    build_mapping_workbook(path, source_models(source))


def load_mapping(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    modern = stage_records(path)
    if modern:
        mapping = {normalize(stage_name(r)): r for r in modern}
        if len(mapping) != len(modern):
            raise InputFormatError("代际名＋二级代际名重复，请核对整理表首个Sheet")
        return mapping, {k: {k} for k in mapping}
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        mapping_sheet = next((name for name in ("车型基本信息", "传播名代际映射", "车型代际映射") if name in workbook.sheetnames), "")
        if not mapping_sheet:
            raise ValueError(f"{path.name} 缺少 Sheet：车型基本信息（也未找到兼容的旧映射 Sheet）")
        sheet = workbook[mapping_sheet]
        headers = [str(cell.value or "").strip() for cell in sheet[1]]
        mapping: dict[str, dict[str, Any]] = {}
        aliases: dict[str, set[str]] = defaultdict(set)
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
            record = dict(zip(headers, values))
            model = str(record.get("历史传播名") or record.get("历史车型名") or "").strip()
            generation = str(record.get("订单分析代际名") or "").strip()
            if not model:
                continue
            key = normalize(model)
            if key in mapping:
                LOGGER.error("映射重名：第%d行历史传播名与已有行重复：%s", row_number, model)
                raise ValueError(f"映射文件存在重复历史传播名：{model}")
            if not generation:
                LOGGER.warning("映射为空：%s 尚未填写订单分析代际名", model)
            record["历史传播名"] = model
            record["订单分析代际名"] = generation
            mapping[key] = record
            aliases[key].add(key)
            for alias in str(record.get("原始表简称/别名") or "").split("|"):
                alias_key = normalize(alias)
                if alias_key:
                    aliases[key].add(alias_key)
        # 兼容旧版双 Sheet：映射主表缺少车型属性列时，从“车型属性”补入同一条记录。
        if "车型属性" in workbook.sheetnames:
            property_sheet = workbook["车型属性"]
            property_headers = [str(cell.value or "").strip() for cell in property_sheet[1]]
            legacy_properties: dict[str, dict[str, Any]] = {}
            for values in property_sheet.iter_rows(min_row=2, values_only=True):
                property_record = dict(zip(property_headers, values))
                property_model = str(
                    property_record.get("历史传播名")
                    or property_record.get("传播名")
                    or property_record.get("车型")
                    or ""
                ).strip()
                if property_model:
                    legacy_properties[normalize(property_model)] = property_record
            for history_key, record in mapping.items():
                property_record = legacy_properties.get(history_key) or legacy_properties.get(normalize(record.get("订单分析代际名"))) or {}
                for field in ("产品档位", "能源类型", "发布类型", "发布时段"):
                    if not str(record.get(field) or "").strip() and str(property_record.get(field) or "").strip():
                        record[field] = property_record[field]
        reverse: dict[str, list[str]] = defaultdict(list)
        for model_key, alias_keys in aliases.items():
            for alias_key in alias_keys:
                reverse[alias_key].append(model_key)
        conflicts = {alias: keys for alias, keys in reverse.items() if len(keys) > 1}
        for alias, keys in conflicts.items():
            LOGGER.warning("别名冲突：%s 同时对应 %s；脚本不会用该别名自动匹配", alias, "、".join(mapping[key]["历史传播名"] for key in keys))
        generation_groups: dict[str, list[str]] = defaultdict(list)
        for history_key, record in mapping.items():
            generation_key = normalize(record.get("订单分析代际名"))
            if generation_key:
                generation_groups[generation_key].append(history_key)
        for generation_key, history_keys in generation_groups.items():
            if len(history_keys) == 1:
                history_key = history_keys[0]
                aliases[history_key].add(generation_key)
                aliases[generation_key].update(aliases[history_key])
        return mapping, aliases
    finally:
        workbook.close()


def read_summary(workbook, header_index: dict[str, HeaderScan]) -> list[dict[str, Any]]:
    sheet, header_row, headers = find_summary_sheet(workbook, header_index)
    result = []
    blank_rows = 0
    seen_models: dict[str, int] = {}
    for row_number, values in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
        record = dict(zip(headers, values))
        primary = str(record.get("车型") or "").strip()
        model = str(record.get("二级代际名") or primary).strip()
        record["代际名"] = primary
        if not model:
            blank_rows += 1
            if result and blank_rows >= 5:
                break
            continue
        blank_rows = 0
        if canonical_header(model) == "车型":
            break
        key = normalize(model)
        if key in seen_models:
            raise InputFormatError(f"汇总表传播名重名：{model} 同时出现在第{seen_models[key]}行和第{row_number}行")
        seen_models[key] = row_number
        record["车型"] = model
        result.append(record)
    if not result:
        raise InputFormatError(f"汇总表“{sheet.title}”第{header_row}行之后没有读取到传播名数据")
    LOGGER.debug("传播名汇总读取完成：%d个传播名", len(result))
    return result


def cached_summary(source: Path) -> list[dict[str, Any]]:
    """Compatibility entry point used when creating a missing mapping file."""
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        header_index = workbook_header_index(workbook)
        return read_summary(workbook, header_index)
    finally:
        workbook.close()


def extract_quantity_table(
    workbook,
    header_index: dict[str, HeaderScan],
    role: str,
) -> tuple[dict[str, list[Any]], int, str, int]:
    sheet, header_row, headers, day_column_pairs = find_progress_sheet(workbook, role, header_index)
    model_column = headers.index("车型")
    # 缺失的中间天数保留空列，防止D1、D3被误当成连续两天。
    day_count = max(number for _, number in day_column_pairs)
    day_columns = {number: index for index, number in day_column_pairs}
    if len(day_columns) != len(day_column_pairs):
        duplicates = sorted(number for number in day_columns if sum(item[1] == number for item in day_column_pairs) > 1)
        raise InputFormatError(f"{sheet.title}第{header_row}行存在重复天数列：{','.join(f'D{n}' for n in duplicates)}")
    missing_days = [number for number in range(1, day_count + 1) if number not in day_columns]
    if missing_days:
        LOGGER.warning("%s缺少%s列，对应日期将在二次处理表留空", sheet.title, "、".join(f"D{n}" for n in missing_days))
    result: dict[str, list[Any]] = {}
    blank_rows = 0
    for row_number, values in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
        model_value = values[model_column] if model_column < len(values) else None
        if canonical_header(model_value) == "车型":
            break  # A repeated quantity/ratio header is not a campaign row.
        record = dict(zip(headers, values))
        model = str(record.get("二级代际名") or model_value or "").strip()
        model = resolve_stage_identity(model, generation_records(), record.get("开始大定日期")) or model
        has_day_value = any(index < len(values) and values[index] not in (None, "") for index in day_columns.values())
        if not model and not has_day_value:
            blank_rows += 1
            continue
        blank_rows = 0
        if canonical_header(model) == "车型":
            break
        if not model:
            LOGGER.warning("%s第%d行有D列数据但传播名为空，已跳过", sheet.title, row_number)
            continue
        key = normalize(model)
        if any(normalize(existing) == key for existing in result):
            raise InputFormatError(f"{sheet.title}首个数量表传播名重名：{model}（第{row_number}行）")
        result[model] = [
            values[day_columns[number]] if number in day_columns and day_columns[number] < len(values) else None
            for number in range(1, day_count + 1)
        ]
    if not result:
        raise InputFormatError(f"{sheet.title}第{header_row}行识别为表头，但首个数量表没有传播名数据")
    return result, day_count, sheet.title, header_row


def extract_first_quantity_table(source: Path, role: str) -> tuple[dict[str, list[Any]], int, str, int]:
    """Compatibility entry point for tests and direct callers."""
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        header_index = workbook_header_index(workbook)
        return extract_quantity_table(workbook, header_index, role)
    finally:
        workbook.close()


def curve_for(
    model: str,
    source_curves: dict[str, list[Any]],
    mapping: dict[str, dict[str, Any]],
    aliases: dict[str, set[str]],
    metric_label: str,
) -> list[Any]:
    model_key = normalize(model)
    exact = [(name, curve) for name, curve in source_curves.items() if normalize(name) == model_key]
    matching_groups = [
        alias_keys for history_key, alias_keys in aliases.items()
        if history_key in mapping and model_key in alias_keys
    ]
    alias_keys = aliases.get(model_key) or (matching_groups[0] if len(matching_groups) == 1 else {model_key})
    matched = exact + [(name, curve) for name, curve in source_curves.items()
                       if normalize(name) in alias_keys and normalize(name) != model_key]
    if len(matched) == 1:
        return matched[0][1]
    if len(matched) > 1:
        # Only explicitly maintained aliases reach this branch. Preserve each
        # known day, keeping source order for conflicting nonblank values.
        result = []
        for index in range(max(len(curve) for _, curve in matched)):
            values = [curve[index] for _, curve in matched if index < len(curve) and curve[index] not in (None, "")]
            result.append(values[0] if values else None)
            if values and any(value != values[0] for value in values[1:]):
                detail = "；".join(f"{name}={curve[index]}" for name, curve in matched
                                  if index < len(curve) and curve[index] not in (None, ""))
                LOGGER.warning("%s别名曲线冲突：%s | D%d | %s | 处理=逐日保留首个非空值",
                               metric_label, model, index + 1, detail)
        return result
    else:
        LOGGER.debug("[初读整理表] %s曲线未匹配：%s；最终缺项在多来源汇总完成后校验", metric_label, model)
    return []


def pad_curve(values: list[Any], day_count: int) -> list[Any]:
    return [values[index] if index < len(values) else None for index in range(day_count)]


def cumulative(values: list[Any], denominator: Any | None = None) -> list[float | None]:
    """Only complete observed prefixes have a known cumulative value.

    A blank is unknown, including future days; explicit zero remains observed.
    After an internal gap, the cumulative total cannot be recovered by summing
    the later values alone.
    """
    running = 0.0
    complete = True
    result: list[float | None] = []
    for value in values:
        if value in (None, ""):
            complete = False
        if complete:
            running += as_number(value)
            result.append(safe_div(running, denominator) if denominator is not None else running)
        else:
            result.append(None)
    return result


def combine_daily(left: list[Any], right: list[Any]) -> list[float | None]:
    result = []
    for left_value, right_value in zip(left, right):
        if left_value in (None, "") or right_value in (None, ""):
            result.append(None)
        else:
            result.append(as_number(left_value) + as_number(right_value))
    return result


def write_rows(workbook: Workbook, name: str, headers: list[str], rows: list[list[Any]], table_name: str, percent_headers: set[str] | None = None) -> None:
    sheet = workbook.create_sheet(name)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    style_sheet(sheet, percent_headers)
    add_table(sheet, table_name)


def mapping_record_for(
    model: str,
    mapping: dict[str, dict[str, Any]],
    aliases: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    model_key = normalize(model)
    exact = mapping.get(model_key)
    if exact:
        return exact
    by_generation = [record for record in mapping.values() if normalize(record.get("订单分析代际名")) == model_key]
    if len(by_generation) == 1:
        return by_generation[0]
    by_alias = [record for key, record in mapping.items() if model_key in (aliases or {}).get(key, set())]
    return by_alias[0] if len(by_alias) == 1 else {}


def build_secondary(source: Path, output: Path, mapping_path: Path, orders_dir: Path | None = None, as_of_date: str = "") -> None:
    started = perf_counter()
    timings = {}
    mapping, aliases = load_mapping(mapping_path)
    for record in mapping.values():
        missing_attributes = [field for field in ("产品档位", "能源类型", "发布类型", "发布时段")
                              if usable_attribute(record.get("首销发布时段") or record.get(field)
                                  if field == "发布时段" else record.get(field)) == "未维护"]
        if missing_attributes:
            LOGGER.warning("[车型属性缺失] 代际=%s | 文件=%s | 缺失字段=%s | 处理=保留未维护标记，影响相应参考匹配；请补齐整理表基本信息",
                           record["历史传播名"], mapping_path.name, "、".join(missing_attributes))
    source_workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        header_index = workbook_header_index(source_workbook)
        summary = read_summary(source_workbook, header_index)

        raw_curves: dict[str, dict[str, list[Any]]] = {}
        day_counts = []
        for target_name in ("small", "direct", "gross", "cancel"):
            curves, count, recognized_sheet, header_row = extract_quantity_table(
                source_workbook,
                header_index,
                target_name,
            )
            raw_curves[target_name] = curves
            day_counts.append(count)
            LOGGER.debug(
                "识别%s：Sheet=%s，表头行=%d，%d条曲线、D1-D%d",
                PROGRESS_SPECS[target_name]["preferred"], recognized_sheet, header_row, len(curves), count,
            )
    finally:
        source_workbook.close()
    day_count = max(day_counts) if day_counts else 0
    day_headers = [f"D{index}" for index in range(1, day_count + 1)]

    models = [str(record["车型"]).strip() for record in summary]
    for model in models:
        if not mapping_record_for(model, mapping, aliases):
            LOGGER.warning("映射未维护：%s；二次处理文件的代际名暂按传播名", model)
    source_keys = {normalize(model) for model in models}
    extra_mappings = [
        record["历史传播名"]
        for key, record in mapping.items()
        if key not in source_keys and normalize(record.get("订单分析代际名")) not in source_keys
    ]
    if extra_mappings:
        LOGGER.info("[来源说明] 基本信息中%d个代际未出现在当前整理表汇总，可由其他订单来源提供数据：%s", len(extra_mappings), "、".join(extra_mappings))

    summary_identity_keys: set[str] = set()
    for model in models:
        key = normalize(model)
        summary_identity_keys.add(key)
        map_record = mapping_record_for(model, mapping, aliases)
        if map_record:
            history_key = normalize(map_record.get("历史传播名"))
            summary_identity_keys.update(aliases.get(history_key, {history_key}))
    for metric, curves in raw_curves.items():
        extras = [name for name in curves if normalize(name) not in summary_identity_keys]
        if extras:
            LOGGER.warning(
                "%s首个数量表有%d个传播名未出现在车型汇总，未写入二次处理文件：%s",
                PROGRESS_SPECS[metric]["preferred"],
                len(extras),
                "、".join(extras),
            )

    base_rows = []
    daily_small_rows, daily_direct_rows, daily_gross_rows, daily_cancel_rows = [], [], [], []
    model_data: list[dict[str, Any]] = []
    for record in summary:
        model = str(record["车型"]).strip()
        map_record = mapping_record_for(model, mapping, aliases)
        mapped = bool(str(map_record.get("订单分析代际名") or "").strip())
        generation = str(map_record.get("订单分析代际名") or model)
        mapping_status = "已映射" if mapped else "未映射·暂按传播名"
        launch_date = record.get("开始大定日期")
        end_date = record.get("小转大结束日期")
        brand = str(map_record.get("品牌") or brand_of(model))
        tier = usable_attribute(map_record.get("产品档位"))
        energy = usable_attribute(map_record.get("能源类型"))
        release_type = usable_attribute(map_record.get("发布类型"))
        release_period = usable_attribute(map_record.get("首销发布时段") or map_record.get("发布时段"))
        total_small = as_number(record.get("总小订"))
        small_to_big = as_number(record.get("小订转大定量"))
        gross = as_number(record.get("大定量"))
        direct = as_number(record.get("直接大定量"))
        cancel = as_number(record.get("小订后退定"))
        raw_conversion = record.get("小订转化率")
        raw_direct_share = record.get("直接大定占比")
        raw_cancel_rate = record.get("小订后退定占比")
        conversion = as_number(raw_conversion) if raw_conversion not in (None, "") else (safe_div(small_to_big, total_small) or 0)
        direct_share = as_number(raw_direct_share) if raw_direct_share not in (None, "") else (safe_div(direct, gross) or 0)
        cancel_rate = as_number(raw_cancel_rate) if raw_cancel_rate not in (None, "") else (safe_div(cancel, total_small) or 0)
        net = as_number(record.get("首销期留存大定"))
        raw_net_rate = record.get("留存大定率")
        net_rate = as_number(raw_net_rate) if raw_net_rate not in (None, "") else (safe_div(net, gross) or 0)
        lock = as_number(record.get("首销期锁单"))
        calculated_lock_rate = safe_div(lock, gross)
        lock_rate = calculated_lock_rate or 0
        if not any((net, lock)):
            LOGGER.debug("[初读整理表] 历史经营结果为空：%s；尚未合并其他订单来源，不要求提前填写终局", model)
        field_completeness, consistency, quality_issues = summary_quality(
            total_small, small_to_big, conversion, gross, direct, direct_share, cancel, cancel_rate,
            net, net_rate, lock, lock_rate,
            tuple(record.get(field) not in (None, "") for field in (
                "总小订", "小订转大定量", "小订转化率", "大定量", "直接大定量", "直接大定占比",
                "小订后退定", "小订后退定占比", "首销期留存大定", "留存大定率", "首销期锁单", "锁单率",
            )),
        )
        quality_status = "需复核" if quality_issues else "通过" if field_completeness >= 0.75 and consistency >= 0.8 else "数据不足"
        base_rows.append([
            model, generation, mapping_status, brand, tier, energy, launch_date, release_type, end_date,
            int(as_number(record.get("首销期天数"), 35)),
            int(total_small) if record.get("总小订") not in (None, "") else None,
            int(small_to_big) if record.get("小订转大定量") not in (None, "") else None, conversion,
            int(gross) if record.get("大定量") not in (None, "") else None,
            int(direct) if record.get("直接大定量") not in (None, "") else None, direct_share,
            int(cancel) if record.get("小订后退定") not in (None, "") else None, cancel_rate,
            field_completeness, consistency, quality_status, "；".join(quality_issues),
            "历史首销参考数量汇总；映射与车型属性来自车型基本信息.xlsx单表", weekday_name(launch_date),
            release_period, int(as_number(net)) if record.get("首销期留存大定") not in (None, "") else None, as_number(net_rate),
            int(as_number(lock)) if record.get("首销期锁单") not in (None, "") else None, as_number(lock_rate),
        ])

        small_curve = pad_curve(curve_for(model, raw_curves["small"], mapping, aliases, "小转大"), day_count)
        direct_curve = pad_curve(curve_for(model, raw_curves["direct"], mapping, aliases, "直接大定"), day_count)
        gross_curve = pad_curve(curve_for(model, raw_curves["gross"], mapping, aliases, "总大定"), day_count)
        cancel_curve = pad_curve(curve_for(model, raw_curves["cancel"], mapping, aliases, "退订"), day_count)
        # Fill by day only when BOTH observed components are present.
        combined = combine_daily(small_curve, direct_curve)
        gross_curve = [value if value not in (None, "") else combined[index]
                       for index, value in enumerate(gross_curve)]
        daily_small_rows.append([model, *small_curve])
        daily_direct_rows.append([model, *direct_curve])
        daily_gross_rows.append([model, *gross_curve])
        daily_cancel_rows.append([model, *cancel_curve])
        model_data.append({
            "model": model, "generation": generation, "mapping_status": mapping_status, "tier": tier, "days": int(as_number(record.get("首销期天数"), 35)),
            "total_small": total_small, "small_to_big": small_to_big, "gross": gross, "direct": direct,
            "cancel": cancel, "small_curve": small_curve, "direct_curve": direct_curve, "gross_curve": gross_curve, "cancel_curve": cancel_curve,
            "quality_status": quality_status, "quality_issues": quality_issues,
        })

    workbook = Workbook()
    workbook.remove(workbook.active)
    field_rows = [
        [
            "车型基本信息",
            "传播名/代际名/品牌/别名/产品档位/能源类型/发布类型/发布时段",
            "统一读取车型基本信息.xlsx的“车型基本信息”Sheet；以历史传播名为唯一键，原始表简称/别名用于进度表匹配，映射和车型属性均取同一行",
            "车型基本信息.xlsx",
        ],
        ["经营结果", "留存大定/锁单", "按表头读取车型汇总；大定到锁单率统一按首销期锁单/总大定计算，任一数量缺失时不输出该比例", source.name],
        ["历史首销数量", "首销逐日参考数量", "生成时读取D1、D2…当日数量；汇总文件只保留预测所需参考结果，不复制原始Sheet", source.name],
        ["小订", "逐日数量", "同车型同日期按可用值逐级读取：小订选配比例分析代际by天→小订退订分析分时汇总→历史小订by天", "小订及退订逐日"],
        ["小转大", "累计完成度", "累计当日小转大数量/总小转大", "小转大当日数量+传播名汇总"],
        ["直接大定", "累计完成度", "累计当日直接大定数量/总直接大定", "直接大定当日数量+传播名汇总"],
        ["总大定", "累计完成度", "累计(当日小转大+当日直接大定)/总大定", "小转大当日数量+直接大定当日数量+预测基准总表"],
        ["小订转化", "累计小订转化率", "Python刷新时逐日累计：累计小转大当日数量/总小订", "小转大当日数量+预测基准总表"],
        ["退订", "累计退订率", "生成时按历史逐日退订累计/总小订计算；汇总文件保留累计参考曲线", "累计退订率+预测基准总表"],
        ["直接大定", "累计直接大定占比", "累计直接大定/累计(小转大+直接大定)", "小转大当日数量+直接大定当日数量"],
        ["直接大定", "每日直接大定占比", "当日直接大定/(当日小转大+当日直接大定)", "小转大当日数量+直接大定当日数量"],
        ["D1/D2", "预测指标", "从历史首销逐日数量提取D1、D2；口径不一致时保留原数量但不生成结构指标", "历史首销参考数量"],
        ["数据质量", "字段完整度/口径一致性", "字段完整度检查必要字段是否有值；口径一致性校验数量勾稽与比例范围，异常指标不参与网页评分", "车型基本信息+首销D1D2预测指标"],
        ["节假日", "法定节假日", "不写入本文件；网页按中国法定节假日与调休工作日自动判断", "core/china_calendar.py"],
    ]
    write_rows(workbook, "字段说明", ["模块", "内容", "读取/计算规则", "来源"], field_rows, "FieldDefinitions")
    field_sheet = workbook["字段说明"]
    field_sheet.column_dimensions["A"].width = 18
    field_sheet.column_dimensions["B"].width = 42
    field_sheet.column_dimensions["C"].width = 68
    field_sheet.column_dimensions["D"].width = 34
    for row in field_sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = _WRAPPED_ALIGNMENT
        field_sheet.row_dimensions[row[0].row].height = 34
    field_sheet.row_dimensions[2].height = 48
    base_headers = ["传播名", "代际名", "映射状态", "品牌", "产品档位", "能源类型", "发布日", "发布类型", "首销截止", "首销天数", "总小订", "总小转大", "小订转化率", "总大定", "总直接大定", "直接大定占比", "总退订", "退订率", "字段完整度", "口径一致性", "质量状态", "质量问题", "数据来源", "发布星期", "发布时段", "首销期留存大定", "留存大定率", "首销期锁单", "大定到锁单率"]
    write_rows(workbook, "预测基准总表", base_headers, base_rows, "ForecastBaseline", PERCENT_FIELDS)

    d12_headers = D12_HEADERS
    d12_rows = []
    for item in model_data:
        s1, s2 = (item["small_curve"] + [None, None])[:2]
        d1, d2 = (item["direct_curve"] + [None, None])[:2]
        g1, g2 = (item["gross_curve"] + [None, None])[:2]
        c1, c2 = (item["cancel_curve"] + [None, None])[:2]
        d1_valid, d1_issue = day_structure_quality(s1, d1, g1, "D1")
        d2_valid, d2_issue = day_structure_quality(s2, d2, g2, "D2")
        s12, d12, g12 = as_number(s1) + as_number(s2), as_number(d1) + as_number(d2), as_number(g1) + as_number(g2)
        d12_valid, d12_issue = day_structure_quality(s12, d12, g12, "D1+D2")
        valid_s1, valid_d1, valid_g1 = (s1, d1, g1) if d1_valid else (None, None, None)
        valid_s2, valid_d2, valid_g2 = (s2, d2, g2) if d2_valid else (None, None, None)
        valid_s12, valid_d12, valid_g12 = (s12, d12, g12) if d12_valid else (None, None, None)
        structure_issues = [issue for issue in (d1_issue, d2_issue, d12_issue) if issue]
        d12_rows.append([
            item["model"], item["generation"], item["mapping_status"], item["tier"], item["days"], int(item["small_to_big"]), int(item["direct"]), int(item["gross"]), int(item["total_small"]),
            s1, safe_div(valid_s1, item["small_to_big"]), s2, safe_div(valid_s2, item["small_to_big"]),
            s12, safe_div(valid_s12, item["small_to_big"]),
            safe_div(valid_s2, valid_s1), safe_div(valid_s1, valid_s12),
            d1, safe_div(valid_d1, item["direct"]), d2, safe_div(valid_d2, item["direct"]),
            d12, safe_div(valid_d12, item["direct"]),
            safe_div(valid_d2, valid_d1), safe_div(valid_d1, valid_d12),
            g1, safe_div(valid_s1, valid_g1), safe_div(valid_d1, valid_g1),
            g2, safe_div(valid_s2, valid_g2), safe_div(valid_d2, valid_g2),
            g12, safe_div(valid_s12, valid_g12), safe_div(valid_d12, valid_g12),
            c1, safe_div(c1, item["total_small"]), c2, safe_div(c2, item["total_small"]),
            as_number(c1)+as_number(c2), safe_div(as_number(c1)+as_number(c2), item["total_small"]),
            safe_div(c2, c1), safe_div(c1, as_number(c1)+as_number(c2)),
            "通过" if d1_valid else "异常", "通过" if d2_valid else "异常", "通过" if d12_valid else "异常", "；".join(structure_issues),
        ])
    write_rows(workbook, D12_SHEET, d12_headers, d12_rows, "D1D2Metrics", PERCENT_FIELDS)

    write_rows(workbook, "小转大当日数量", ["传播名", *day_headers], daily_small_rows, "DailySmallToBig")
    write_rows(workbook, "直接大定当日数量", ["传播名", *day_headers], daily_direct_rows, "DailyDirect")
    write_rows(workbook, "总大定当日数量", ["传播名", *day_headers], daily_gross_rows, "DailyGross")
    write_rows(workbook, "退订当日数量", ["传播名", *day_headers], daily_cancel_rows, "DailyCancel")

    derived_specs = [
        ("小转大累计完成度", "small_curve", "small_to_big", "SmallCompletion"),
        ("直接大定累计完成度", "direct_curve", "direct", "DirectCompletion"),
        ("累计大定完成度", "gross_curve", "gross", "GrossCompletion"),
    ]
    for sheet_name, curve_field, denominator_field, table_name in derived_specs:
        rows = [[item["model"], *cumulative(item[curve_field], item[denominator_field])] for item in model_data]
        write_rows(workbook, sheet_name, ["传播名", *day_headers], rows, table_name, set(day_headers))

    cumulative_conversion_rows = [
        [item["model"], *cumulative(item["small_curve"], item["total_small"])]
        for item in model_data
    ]
    write_rows(
        workbook,
        "累计小订转化率",
        ["传播名", *day_headers],
        cumulative_conversion_rows,
        "CumulativeConversion",
        set(day_headers),
    )

    cumulative_cancel_rows = [
        [item["model"], *cumulative(item["cancel_curve"], item["total_small"])]
        for item in model_data
    ]
    write_rows(
        workbook,
        "累计退订率",
        ["传播名", *day_headers],
        cumulative_cancel_rows,
        "CumulativeCancelRate",
        set(day_headers),
    )
    cumulative_direct_share_rows = []
    daily_direct_share_rows = []
    for item in model_data:
        direct_running = cumulative(item["direct_curve"])
        gross_running = cumulative(item["gross_curve"])
        cumulative_direct_share_rows.append([item["model"], *[safe_div(direct_running[index], gross_running[index]) for index in range(day_count)]])
        daily_direct_share_rows.append([item["model"], *[safe_div(item["direct_curve"][index], item["gross_curve"][index]) for index in range(day_count)]])
    write_rows(workbook, "累计直接大定占比", ["传播名", *day_headers], cumulative_direct_share_rows, "CumulativeDirectShare", set(day_headers))
    write_rows(workbook, "每日直接大定占比", ["传播名", *day_headers], daily_direct_share_rows, "DailyDirectShare", set(day_headers))

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.refreshing{output.suffix}")
    if temporary.exists():
        temporary.unlink()
    workbook.save(temporary)
    timings['历史基准与中间文件'] = perf_counter() - started
    if orders_dir is not None:
        stage_started = perf_counter()
        append_forecast_inputs(workbook, source, mapping_path, orders_dir, as_of_date, preserve_layout=False)
        timings['读取整理订单来源'] = perf_counter() - stage_started
        stage_started = perf_counter()
        append_forecast_views(temporary, as_of_date, workbook=workbook)
        timings['合并计算与结果排版'] = perf_counter() - stage_started
    stage_started = perf_counter()
    reorder_summary_sheets(workbook)
    sheet_count = len(workbook.sheetnames)
    workbook.save(temporary)
    workbook.close()
    try:
        os.replace(temporary, output)
    except PermissionError as exc:
        raise PermissionError(f"无法覆盖 {output}，请确认 Excel 中没有打开该文件") from exc
    timings['最终保存'] = perf_counter() - stage_started
    LOGGER.info('[销量汇总耗时] %s | 总计 %.2fs',
                ' | '.join(f'{name} {seconds:.2f}s' for name, seconds in timings.items()),
                perf_counter() - started)
    LOGGER.info("刷新完成：%s（%d个传播名、%d天、%d个Sheet）", output, len(models), day_count, sheet_count)


def forecast_order_files(directory: Path) -> list[Path]:
    keywords = ("首销期订单节奏", "小订退订分析", "小订选配比例", "锁单选配比例", "大定选配比例")
    return sorted(path for path in directory.glob("*.xlsx") if not path.name.startswith("~$") and any(key in path.name for key in keywords))


def fit_summary_columns(sheet):
    """Fit only new human-readable summary tables; preserve imported source formats."""
    def text_width(value):
        return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in str(value))
    for column in sheet.iter_cols():
        width = min(72, max(13, max((text_width(cell.value) if isinstance(cell.value, str) else 12 for cell in column if cell.value is not None), default=12) + 3))
        sheet.column_dimensions[column[0].column_letter].width = width
        for cell in column[1:]:
            if isinstance(cell.value, str) and text_width(cell.value) > width - 3:
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                sheet.row_dimensions[cell.row].height = max(sheet.row_dimensions[cell.row].height or 18, 18 * math.ceil(text_width(cell.value) / (width - 3)))
            if isinstance(cell.value, bool):
                cell.number_format = "General"


def forecast_signature(source, mapping, directory, as_of_date):
    paths = [source, mapping, *forecast_order_files(directory), *REFRESH_CODE_DEPENDENCIES]
    facts = [(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
    return hashlib.sha256(json.dumps([as_of_date or date.today().isoformat(), facts], ensure_ascii=False).encode()).hexdigest()


def append_forecast_inputs(workbook, source, mapping_path, orders_dir, as_of_date, preserve_layout=True):
    """Consolidate values and formats, never fill blanks or add duplicate orders."""
    directory = []
    source_ranges = {}
    source_counters = {"小订": 0, "首销": 0, "平销": 0, "其他": 0}

    def source_group(kind, filename):
        if kind == "历史":
            return "历史"
        if kind == "映射":
            return "车型"
        if "小订退订分析" in filename or "小订选配比例" in filename:
            return "小订"
        if "首销期订单节奏" in filename:
            return "首销"
        if "锁单选配比例" in filename:
            return "平销"
        return "其他"

    def import_sheet(sheet, kind, filename, preferred=None):
        group = source_group(kind, filename)
        if preferred is None:
            source_counters[group] += 1
            name = f"源_{group}_{source_counters[group]:03d}_{sheet.title}"[:31]
        else:
            name = preferred
        if name in workbook.sheetnames:
            raise ValueError(f"汇总Sheet名冲突：{name}")
        target = workbook.create_sheet(name)
        styles = {}
        # Production removes source tabs after resolving values. Copying blank
        # styled areas and decorative formatting only wastes time/memory there.
        rows = sheet.iter_rows() if preserve_layout else ([cell] for cell in sheet._cells.values() if cell.value is not None)
        for row in rows:
            for cell in row:
                if cell.value is None and not cell.has_style:
                    continue
                dest = target.cell(cell.row, cell.column, cell.value)
                # Cached formula results are imported, with source numeric formats.
                if isinstance(cell.value, str):
                    dest.data_type = "s"
                if not preserve_layout:
                    dest.number_format = cell.number_format
                    continue
                if cell.style_id not in styles:
                    dest.font = copy(cell.font)
                    dest.fill = copy(cell.fill)
                    dest.border = copy(cell.border)
                    dest.alignment = copy(cell.alignment)
                    dest.number_format = cell.number_format
                    styles[cell.style_id] = copy(dest._style)
                else:
                    dest._style = copy(styles[cell.style_id])
        for source_dimensions, target_dimensions in ((
            (sheet.column_dimensions, target.column_dimensions),
            (sheet.row_dimensions, target.row_dimensions),
        ) if preserve_layout else ()):
            for key, dimension in source_dimensions.items():
                dest_dimension = copy(dimension)
                # Dimension.__copy__ retains the source worksheet and style IDs.
                # Rebind before registering each style component in the new book.
                dest_dimension.parent = target
                dest_dimension._style = None
                if dimension.has_style:
                    for attribute in (
                        "font", "fill", "border", "alignment", "protection",
                        "number_format", "quotePrefix", "pivotButton",
                    ):
                        setattr(dest_dimension, attribute, copy(getattr(dimension, attribute)))
                target_dimensions[key] = dest_dimension
        for area in (sheet.merged_cells.ranges if preserve_layout else ()):
            target.merge_cells(str(area))
        target.freeze_panes = sheet.freeze_panes
        target.auto_filter = copy(sheet.auto_filter)
        target.sheet_view.showGridLines = False
        if not any(row[1] == filename and row[2] == sheet.title for row in directory):
            directory.append([kind, filename, sheet.title, name, sheet.max_row, sheet.max_column])

    for path, kind in [(source, "历史"), (mapping_path, "映射"), *[(path, "订单") for path in forecast_order_files(orders_dir)]]:
        file_started = perf_counter()
        book = (load_workbook(path, read_only=False, data_only=True) if preserve_layout
                else load_data_workbook(path, orders_dir / ".cache" / "excel"))
        loaded = perf_counter()
        try:
            if kind == "订单":
                source_ranges[path.name] = _source_date_range(WorkbookItem(path, book))
            for sheet in book.worksheets:
                if kind == "历史" and sheet.title not in {"车型汇总", "小订by天", "小订进度"} and not (sheet is book.worksheets[0] and stage_records(path)):
                    continue
                if kind == "映射" and stage_records(path):
                    if sheet is book.worksheets[0]:
                        import_sheet(sheet, kind, path.name, "车型基本信息")
                    continue
                if kind == "映射" and sheet.title not in {"车型基本信息", "传播名代际映射", "车型代际映射"}:
                    continue
                if kind == "订单":
                    if "图表" in sheet.title:
                        continue
                    if "锁单选配比例" in path.name and grain_from_sheet(sheet.title) not in {"day", "week"}:
                        continue
                    if "首销期订单节奏" in path.name and grain_from_sheet(sheet.title) not in {"day", "hour"}:
                        continue
                    if "小订选配比例" in path.name and grain_from_sheet(sheet.title) != "day":
                        continue
                import_sheet(sheet, kind, path.name, sheet.title if kind != "订单" else None)
        finally:
            book.close()
        LOGGER.debug('[销量汇总来源耗时] 文件=%s | 类别=%s | 解析 %.2fs | 来源整理 %.2fs',
                     path.name, kind, loaded - file_started, perf_counter() - loaded)
    write_rows(workbook, INDEX_SHEET, ["类别", "原始文件", "原始Sheet", "汇总Sheet", "行数", "列数", "阅读用途", "文件数据开始日期", "文件数据结束日期"], [
        [*row, {
            "历史": "历史参考与预测基准",
            "映射": "车型名称与属性映射",
            "订单": "当前真实订单候选来源",
        }.get(row[0], "来源明细"), *[day.isoformat() if day else None for day in (source_ranges.get(row[1]) or (None, None))]]
        for row in directory
    ], "ForecastSources")
    fit_summary_columns(workbook[INDEX_SHEET])
    write_rows(workbook, "汇总说明", ["项目", "内容"], [
        ["文件用途", "统一保存小订、首销、平销历史参考及当前真实订单，网页从本文件读取。"],
        ["更新方式", "更新原始文件后运行main.py。汇总明细由脚本刷新，手工修改会被覆盖。"],
        ["数据边界", "缺失保持空白，真实0保留为0。历史合成曲线、当日快照和未来日期单独标识，不作为已结束日期真实值。"],
        ["退订口径", "累计小订退订统一放在小订及退订逐日，不与当日大定退订混用。当前订单逐日只放大定、留存大定、小转大、直接大定和交车锁单。"],
        ["阅读顺序", "先看字段说明、车型基本信息和数据来源目录；再看小订及退订逐日、当前小订分时、当前订单逐日和当前首销分时；最后核对预测参考。"],
        ["当前结果区", "车型基本信息已合并当前车型阶段；小订及退订逐日合并三类来源，同车型同日期按《小订选配比例分析》代际by天→《小订退订分析》分时汇总→历史小订by天读取可用值。"],
        ["预测参考区", "车型基本信息、首销D1D2预测指标及首销参考曲线：保留首销预测现有参考数据和计算结果，首销预测继续读取这些既有口径。"],
        ["历史与资料区", "车型基本信息、小订及退订逐日和预测基准总表：用于名称映射、车型属性、当前阶段及历史小订/首销基准核对。"],
        ["来源说明", "本文件只保留预测所需的汇总结果，不复制原始订单Sheet，也不重复展示可由统一逐日表表达的明细；数据来源目录记录对应汇总位置。"],
        ["取数规则", "按原有阶段优先级逐字段回退；同类文件全部纳入，普通重叠保留排序后首个非空值，同值去重。边界周仅在两个原始文件日期范围分别截止6月30日/12月31日、从次日开始且互不重叠时累加不同有效数量；单文件已跨界、范围重叠或无法确认衔接时不累加。日期范围由真实逐日数量或明确导出起止日期确定，来源目录保留该证据；占比重算或加权，不直接相加。"],
        ["首销数据说明", "首销逐日数据与首销参考曲线承担不同预测用途，虽然部分车型数值可能相同，本次不合并、不改取数来源。"],
        ["汇总日期", as_of_date or date.today().isoformat()],
        ["刷新签名", forecast_signature(source, mapping_path, orders_dir, as_of_date)],
    ], "ForecastSummaryGuide")
    workbook.move_sheet("汇总说明", offset=-workbook.index(workbook["汇总说明"]))
    workbook["汇总说明"].column_dimensions["B"].width = 105


def forecast_weekly_orders(store, dashboard, today, daily_output=None):
    """Collect quantities after file-boundary merging, split stage-boundary weeks by day."""
    from modules.sales_forecast import (_iso_week_bounds, _as_date, _canonical_model,
        _read_model_mapping, _fill_sparse_dates)
    from core.excel import sheet_subject, display_period, _source_date_ranges
    data = dashboard.views["week"]["pages"]["预测方案"]["workspace"]["data"]
    targets = {r["name"]: r for r in [*data.get("targets", []), *data.get("steady_targets", [])]}
    mapping = _read_model_mapping()
    daily, weekly = {}, {}
    labels = {"大定": "gross", "总大定": "gross", "留存大定": "net", "净大定": "net", "交车锁单": "lock"}
    for keyword in ("大定选配比例", "锁单选配比例"):
        item = store.find(keyword)
        if item is None:
            continue
        coverage = _source_date_ranges(item)
        for sheet in item.workbook.worksheets:
            grain = grain_from_sheet(sheet.title)
            if "图表" in sheet.title or grain not in {"day", "week"}:
                continue
            model = _canonical_model(sheet_subject(sheet.title), mapping)
            if model not in targets:
                continue
            metric = ""
            for row in sheet.iter_rows(min_row=2):
                metric = str(row[0].value or metric).strip()
                field = labels.get(metric)
                if field is None or row[1].value != "数量" or row[2].value != "数量":
                    continue
                source = f"{item.path.name}｜{sheet.title}"
                observed = []
                for cell in row[3:]:
                    header = sheet.cell(1, cell.column)
                    value = cell.value
                    value = value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
                    if grain == "day":
                        day = _as_date(header.value)
                        if day:
                            observed.append({"date": day.isoformat(), field: value})
                    else:
                        period = display_period(header.value, header.number_format)
                        if _iso_week_bounds(period):
                            weekly[(model, period, field)] = (value, source)
                if grain == "day":
                    filled = _fill_sparse_dates(observed, (field,), coverage, end=today)
                    for entry in filled:
                        daily[(model, entry["date"], field)] = (entry.get(field), source)
    if daily_output is not None:
        daily_output.update(daily)
    # Launch/day selections already carry the shared stage priority. For steady
    # sales the mix sheets remain primary; do not extend launch data over them.
    resolved = {}
    for profile in data.get("actuals", []):
        for row in profile.get("days", []):
            if row.get("date"):
                for field in ("gross", "net", "lock"):
                    resolved[(profile["model"], row["date"], field)] = (row.get(field), DAILY_SHEET + "｜字段来源")
    periods = {(model, period) for model, period, _ in weekly}
    for model, day, _ in {*daily, *resolved}:
        parsed = date.fromisoformat(day)
        year, week, _ = parsed.isocalendar()
        periods.add((model, f"{year % 100:02d}WK{week:02d}"))
    rows, missing_split = [], []
    current_week_start = (today - timedelta(days=today.weekday())).isoformat()
    current_updated = {}
    for entries in (daily, resolved):
        for (model, day, _), entry in entries.items():
            if entry[0] is not None and current_week_start <= day <= today.isoformat():
                current_updated.setdefault(model, set()).add(day)
    for model, period in sorted(periods):
        target = targets[model]
        launch, finish = _as_date(target.get("launch_date")), _as_date(target.get("end_date"))
        bounds = _iso_week_bounds(period)
        if not bounds or not launch or not finish:
            continue
        for stage, first, last in (("首销", launch, finish), ("平销", finish + timedelta(days=1), today)):
            start, end = max(bounds[0], first), min(bounds[1], last, today)
            # A current partial week is not a stage-boundary split. Keep only
            # the dates actually updated; omitted covered dates were filled at
            # the physical-file merge, future/unupdated dates remain unknown.
            stage_split = first > bounds[0] or (stage == "首销" and last < bounds[1])
            if bounds[0] <= today <= bounds[1]:
                observed = [date.fromisoformat(day) for day in current_updated.get(model, ())
                            if start.isoformat() <= day <= end.isoformat()]
                if observed:
                    end = min(end, max(observed))
            if start > end:
                continue
            whole = start == bounds[0] and end == bounds[1]
            values, sources = [], []
            for field in ("gross", "net", "lock"):
                values_by_day = []
                current = start
                while current <= end:
                    key = (model, current.isoformat(), field)
                    candidates = [resolved.get(key), daily.get(key)] if stage == "首销" else [daily.get(key)]
                    values_by_day.append(next((c for c in candidates if c is not None and c[0] is not None), None))
                    current += timedelta(days=1)
                valid_days = all(c is not None for c in values_by_day)
                raw_week = weekly.get((model, period, field)) if whole else None
                if stage == "平销" and raw_week is not None and raw_week[0] is not None:
                    value, source = raw_week
                elif valid_days:
                    value = sum(c[0] for c in values_by_day)
                    source = "、".join(dict.fromkeys(str(c[1] or "") for c in values_by_day)) + "（by天汇总）"
                elif raw_week is not None:
                    value, source = raw_week
                else:
                    value, source = None, "by天不完整，未补估"
                    if stage_split and (model, period, field) in weekly:
                        missing_split.append((model, period, stage, field))
                values.append(value)
                sources.append(source)
            if any(value is not None for value in values) or any((model, period, field) in weekly for field in ("gross", "net", "lock")):
                rows.append([model, period, stage, datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time()), *values, *sources, False])
    if missing_split:
        for model, period, stage, field in missing_split:
            label = {"gross": "大定", "net": "留存大定", "lock": "交车锁单"}.get(field, field)
            LOGGER.warning("[周阶段切分] 代际=%s | 周期=%s | 阶段=%s | 字段=%s | 原因=缺少拆分所需完整日数据 | 处理=相关字段留空，不补估",
                           model, period, stage, label)
    return rows


def audit_final_forecast(workbook, today, data=None):
    """Diagnose the selected visible values, not gaps in one preliminary source."""
    from core.forecast_summary import MASTER_SHEET, ORDER_FIELDS, iso_day
    from core.model_identity import has_reservation
    from modules.sales_forecast import _profile_hard_errors, _forecast_stage, _as_date
    masters = table_records(workbook, MASTER_SHEET)
    lookup = {(row.get("订单分析代际名"), iso_day(row.get("日期"))): row
              for row in table_records(workbook, DAILY_SHEET) if row.get("订单分析代际名") and row.get("日期")}
    by_model = {}
    for (name, day), row in lookup.items():
        by_model.setdefault(name, []).append((day, row))
    for rows in by_model.values():
        rows.sort(key=lambda pair: pair[0])
    maintained = {target["name"]: target for target in (data or {}).get("targets", [])}
    messages = []
    valid = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
    for master in masters:
        model = master.get("订单分析代际名") or master.get("历史传播名")
        if not model:
            continue
        start, end = _as_date(master.get("首销开始")), _as_date(master.get("首销结束"))
        stage = _forecast_stage(start, end, master.get("首销天数"), today)
        target = {**maintained.get(model, {}), "name": model, "stage": stage["key"],
                  "launch_date": stage["launch_date"], "end_date": stage["end_date"], "days": stage["days"],
                  "has_small": has_reservation(master),
                  "small_start_date": iso_day(master.get("小订开始")), "small_end_date": iso_day(master.get("小订结束"))}
        days = [{"date": day, **{field: row.get(column) for field, column in ORDER_FIELDS.items()}}
                for day, row in by_model.get(model, [])
                if start and day >= start.isoformat() and (not end or day <= end.isoformat())]
        errors = _profile_hard_errors(target, {"model": model, "days": days}, today)
        if errors:
            messages.append(f"[销量预测条件不足] 预测对象={model} | 阶段={stage['label']} | 原因={'；'.join(errors)} | 影响=首销预测条件受限，保留已知实际；请核对原始来源")
        if target["has_small"]:
            small_start, small_end = _as_date(master.get("小订开始")), _as_date(master.get("小订结束"))
            if small_start and small_end and small_end >= small_start and small_start < today:
                finish = min(small_end, today-timedelta(days=1))
                values, missing = [], []
                for index in range((finish-small_start).days+1):
                    day = (small_start+timedelta(days=index)).isoformat()
                    value = lookup.get((model, day), {}).get("小订数量")
                    values.append(value)
                    if not valid(value):
                        missing.append(index+1)
                if missing:
                    labels = '、'.join(f'D{i}' for i in missing)
                    messages.append(f"[销量预测条件不足] 预测对象={model} | 阶段=小订 | 原因=已结束日小订数量缺失或无效：{labels}（共{len(missing)}天） | 影响=小订预测条件受限，其他阶段独立检查；请核对原始来源")
                elif small_end < today and values and valid(master.get("总小订")) and abs(sum(values)-master["总小订"]) > 1:
                    messages.append(f"[销量预测口径差异] 代际={model} | 范围={small_start}~{small_end} | 最终总小订={master['总小订']}，多来源逐日合计={sum(values)} | 处理=保留既有优先级，请核对原始来源的统计口径")
        if end and end < today:
            missing = [field for field in ("首销期留存大定", "首销期锁单") if not valid(master.get(field))]
            if missing:
                messages.append(f"[预测历史参考缺项] 代际={model} | 阶段=首销已结束 | 缺失字段={'、'.join(missing)} | 影响=对应历史留存或锁单率参考不可用，不停止其他有效预测")
    for message in messages:
        LOGGER.warning("%s", message)
    return messages


def append_forecast_views(path, as_of_date, workbook=None):
    """Resolve sources once, then write only the visible forecast domain tables."""
    from modules.sales_forecast import SalesForecastModule
    from core.models import Subject

    module = SalesForecastModule()
    module.summary_path = path
    module.as_of_date = date.fromisoformat(as_of_date) if as_of_date else None
    owns_workbook = workbook is None
    book = load_workbook(path) if owns_workbook else workbook
    with summary_scope(path, workbook=book) as summary:
        dashboard = module._build_from_sources(summary["store"], Subject("summary", "鸿蒙智行", "group"))
        if dashboard is None:
            raise ValueError("汇总未生成有效销量预测数据，请检查原始历史基准")
        mix_daily = {}
        weekly_rows = forecast_weekly_orders(summary["store"], dashboard, module.as_of_date or date.today(), mix_daily)
    data = dashboard.views["week"]["pages"]["预测方案"]["workspace"]["data"]
    data["mix_daily"] = mix_daily
    data["reference_daily"] = {
        name: {row[0]: list(row[1:]) for row in book[name].iter_rows(min_row=2, values_only=True) if row[0]}
        for name in ("小转大当日数量", "直接大定当日数量", "总大定当日数量", "退订当日数量") if name in book.sheetnames
    }

    def emit(name, headers, rows, percent_headers=None):
        if name in book.sheetnames:
            del book[name]
        write_rows(book, name, headers, rows, "ForecastDetail", percent_headers)
        fit_summary_columns(book[name])
        book[name].freeze_panes = "C2"

    compact_source_sheets(book)
    public_forecast_tables(book, data, emit, weekly_rows, module.as_of_date or date.today(), getattr(module, "summary_raw_profiles", None))
    normalize_public_names(book, data, emit)
    audit_final_forecast(book, module.as_of_date or date.today(), data)
    sheet_count = len(book.sheetnames)
    if owns_workbook:
        book.save(path)
        book.close()
    return sheet_count



def normalize_public_names(book, data, emit):
    """Persist only generation/campaign identities; old labels are read adapters."""
    parents = {r["name"]: (r.get("primary_generation") or r["name"], r.get("secondary_generation") or "")
               for r in data.get("targets", [])}
    for record in table_records(book, "车型基本信息"):
        if record.get("primary_generation"):
            parents[stage_name(record)] = (record["primary_generation"], record.get("secondary_generation") or "")
    identity_headers = {"传播名", "历史传播名", "订单分析代际名", "代际名", "二级代际名", "映射状态", "原始表简称/别名"}
    for sheet in list(book.worksheets):
        values = list(sheet.iter_rows(values_only=True))
        if not values:
            continue
        headers = [str(v or "") for v in values[0]]
        if not set(headers) & {"传播名", "历史传播名", "订单分析代际名"}:
            continue
        remaining = [(i, h) for i, h in enumerate(headers) if h not in identity_headers]
        output = []
        for values in values[1:]:
            row = dict(zip(headers, values))
            event = str(row.get("历史传播名") or row.get("传播名") or row.get("订单分析代际名") or "")
            fallback = str(row.get("订单分析代际名") or row.get("代际名") or event)
            primary, secondary = parents.get(event, parents.get(fallback, (fallback, "")))
            if not primary:
                continue  # Formatting-only rows are not forecast identities.
            output.append([primary, secondary or None, *[values[i] if i < len(values) else None for i, _ in remaining]])
        emit(sheet.title, ["代际名", "二级代际名", *[h for _, h in remaining]], output,
             {h for _, h in remaining if h in PERCENT_FIELDS or h.endswith("率") or "占比" in h})


def compact_source_sheets(workbook):
    """Replace copied source worksheets with a concise source-to-summary index."""
    source_records = list(workbook[INDEX_SHEET].iter_rows(min_row=2, values_only=True))
    grouped = defaultdict(list)
    headers = [cell.value for cell in workbook[INDEX_SHEET][1]]
    range_columns = [headers.index(label) if label in headers else None
                     for label in ("文件数据开始日期", "文件数据结束日期")]
    source_ranges = {}
    for record in source_records:
        source_ranges.setdefault((record[0], record[1]),
                                 [record[column] if column is not None and column < len(record) else None
                                  for column in range_columns])
    for kind, filename, original, *_ in source_records:
        grouped[(kind, filename)].append(original)
    for sheet in list(workbook.worksheets):
        if sheet.title.startswith("源_") or sheet.title in {
            "车型汇总", "小订by天", "小订进度", "总大定当日数量", "退订当日数量",
        }:
            workbook.remove(sheet)
    workbook.remove(workbook[INDEX_SHEET])

    def destinations(kind, filename):
        if kind == "历史":
            return "预测基准总表、首销参考曲线、小订及退订逐日"
        if kind == "映射":
            return "车型基本信息（含当前阶段）"
        if "小订退订分析" in filename:
            return "车型基本信息、小订及退订逐日、当前小订分时、当前订单逐日"
        if "小订选配比例" in filename:
            return "车型基本信息、小订及退订逐日"
        if "首销期订单节奏" in filename:
            return "当前订单逐日、当前首销分时"
        if "锁单选配比例" in filename:
            return "当前订单逐日"
        return "当前订单汇总"

    def content_summary(kind, filename):
        if kind == "历史":
            return "车型阶段汇总、小订逐日和小订进度"
        if kind == "映射":
            return "车型名称、别名和车型属性"
        if "小订退订分析" in filename:
            return "日度退订、选配退订和小订分时"
        if "小订选配比例" in filename:
            return "代际小订逐日数量"
        if "首销期订单节奏" in filename:
            return "首销逐日和首销分时订单节奏"
        if "锁单选配比例" in filename:
            return "平销交车锁单逐日和逐周数据"
        return "当前订单数据"

    rows = [
        [kind, filename, len(names), content_summary(kind, filename), destinations(kind, filename),
         *source_ranges[(kind, filename)]]
        for (kind, filename), names in grouped.items()
    ]
    write_rows(
        workbook,
        INDEX_SHEET,
        ["来源类型", "原始文件", "原始Sheet数", "包含内容", "汇总位置", "文件数据开始日期", "文件数据结束日期"],
        rows,
        "ForecastSources",
    )
    fit_summary_columns(workbook[INDEX_SHEET])


def reorder_summary_sheets(workbook):
    """Keep a stable, readable progression without changing any source values."""
    first = [
        GUIDE_SHEET, "车型基本信息", "小订by时", "首销by时", DAILY_SHEET, WEEKLY_SHEET,
        "小订当日数量", "小订累计完成度", D12_SHEET,
        "汇总说明", "字段说明", "车型基本信息", "数据来源目录",
        "小订及退订逐日", "当前小订分时", "当前订单逐日", "当前首销分时",
        "预测基准总表",
        "小转大当日数量", "直接大定当日数量",
        "小转大累计完成度", "直接大定累计完成度", "累计大定完成度", "累计小订转化率", "累计退订率",
        "累计直接大定占比", "每日直接大定占比",
        "车型汇总", "小订by天", "小订进度",
    ]
    existing = {sheet.title: sheet for sheet in workbook.worksheets}
    ordered = [existing[name] for name in dict.fromkeys(first) if name in existing]
    group_order = {"源_小订": 0, "源_首销": 1, "源_平销": 2, "源_其他": 3}
    raw_sheets = [sheet for sheet in workbook.worksheets if sheet.title.startswith("源_")]
    raw_sheets.sort(key=lambda sheet: (
        next((rank for prefix, rank in group_order.items() if sheet.title.startswith(prefix)), 9),
        sheet.title,
    ))
    ordered.extend(raw_sheets)
    if INDEX_SHEET in existing and existing[INDEX_SHEET] not in ordered:
        ordered.append(existing[INDEX_SHEET])
    remaining = [sheet for sheet in workbook.worksheets if sheet not in ordered]
    workbook._sheets = ordered + remaining


def summary_is_current(source, output, mapping, orders_dir, as_of_date):
    if not output_is_current(source, output, mapping):
        return False
    book = load_workbook(output, read_only=True, data_only=True)
    try:
        if GUIDE_SHEET not in book.sheetnames or DAILY_SHEET not in book.sheetnames:
            return False
        return book.properties.identifier == forecast_signature(source, mapping, orders_dir, as_of_date)
    finally:
        book.close()


def resolve_source_path(requested: Path) -> Path:
    if requested.exists():
        return requested
    candidates = [
        path for path in requested.parent.glob("*.xlsx")
        if not path.name.startswith("~$")
        and "二次处理" not in path.name
        and "映射" not in path.name
        and ("小订" in path.name or "首销" in path.name)
    ]
    preferred = [path for path in candidates if "数据整理" in path.name and "副本" not in path.name and "修正前" not in path.name]
    pool = preferred or candidates
    if len(pool) == 1:
        LOGGER.info("[来源选择] 默认原始文件名不存在，使用同目录唯一候选：%s", pool[0].name)
        return pool[0]
    raise FileNotFoundError(
        f"找不到原始历史文件：{requested}；同目录候选："
        + ("、".join(path.name for path in pool) if pool else "无")
    )


def output_is_current(source: Path, output: Path, mapping: Path) -> bool:
    """Return true when the generated workbook is newer than every dependency."""
    if not output.exists() or output.stat().st_size < 4:
        return False
    try:
        with output.open("rb") as handle:
            if handle.read(4) != b"PK\x03\x04":
                return False
        output_time = output.stat().st_mtime_ns
        dependencies = (source, mapping, *REFRESH_CODE_DEPENDENCIES)
        return all(path.exists() and path.stat().st_mtime_ns <= output_time for path in dependencies)
    except OSError:
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="汇总小订、首销、平销历史及当前真实订单")
    parser.add_argument("--orders", type=Path, default=DEFAULT_ORDERS, help="当前订单Excel目录")
    parser.add_argument("--as-of-date", default="", help="复盘日期YYYY-MM-DD，默认运行当天")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="原始历史数据文件")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="二次处理输出文件")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="默认从整理表第一个Sheet读取代际名、二级代际名和属性；显式指定时兼容旧映射文件")
    parser.add_argument("--force", action="store_true", help="忽略文件时间，强制重新生成二次处理文件")
    parser.add_argument("--debug", action="store_true", help="显示全部来源、冲突位置和诊断明细")
    return parser.parse_args()


def resolve_mapping_path(requested: Path) -> Path:
    if requested.exists():
        return requested
    if requested == DEFAULT_MAPPING:
        legacy = next((path for path in LEGACY_MAPPINGS if path.exists()), None)
        if legacy:
            LOGGER.info("[来源选择] 默认车型基本信息文件不存在，兼容使用旧文件名：%s", legacy.name)
            return legacy
    return requested


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="[%(levelname)s] %(message)s", stream=sys.stdout)
    try:
        args.source = resolve_source_path(args.source)
        if args.mapping == DEFAULT_MAPPING:
            args.mapping = args.source  # One integrated source, including custom --source.
        args.mapping = resolve_mapping_path(args.mapping)
        LOGGER.debug("原始历史文件: %s", args.source)
        LOGGER.debug("车型基本信息: %s", args.mapping)
        LOGGER.debug("二次处理输出: %s", args.output)
        ensure_mapping(args.mapping, args.source)
        if not args.force and summary_is_current(args.source, args.output, args.mapping, args.orders, args.as_of_date):
            LOGGER.info("销量数据汇总已是最新，跳过刷新：%s", args.output)
            book = load_workbook(args.output, read_only=True, data_only=True)
            try:
                audit_final_forecast(book, date.fromisoformat(args.as_of_date) if args.as_of_date else date.today())
            finally:
                book.close()
            return 0
        build_secondary(args.source, args.output, args.mapping, args.orders, args.as_of_date)
        return 0
    except Exception:
        LOGGER.exception("刷新失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

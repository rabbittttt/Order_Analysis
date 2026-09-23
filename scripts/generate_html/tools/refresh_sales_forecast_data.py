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
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


LOGGER = logging.getLogger("sales_forecast_refresh")
ROOT = Path(__file__).resolve().parent
GENERATE_HTML_ROOT = ROOT.parent
if str(GENERATE_HTML_ROOT) not in sys.path:
    sys.path.insert(0, str(GENERATE_HTML_ROOT))

from core.model_identity import model_key, usable_attribute
from core.forecast_summary import SUMMARY_NAME, INDEX_SHEET, write_summary_snapshot, summary_scope
from core.excel import grain_from_sheet

PROJECT_ROOT = ROOT.parents[2]
FORECAST_INPUT_ROOT = PROJECT_ROOT / "input_file" / "销量预测输入文件"
DEFAULT_SOURCE = FORECAST_INPUT_ROOT / "小订及首销数据整理.xlsx"
DEFAULT_OUTPUT = PROJECT_ROOT / "output_file" / SUMMARY_NAME
DEFAULT_ORDERS = PROJECT_ROOT / "output_file"
DEFAULT_MAPPING = FORECAST_INPUT_ROOT / "车型基本信息.xlsx"
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
    "车型": {"传播名", "历史传播名", "车型", "车型名称", "历史车型", "车系车型"},
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
            if len(day_columns) < 2:
                continue
        if "车型" not in headers:
            continue
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


def summary_quality(
    total_small: float,
    small_to_big: float,
    conversion: float,
    gross: float,
    direct: float,
    direct_share: float,
    cancel: float,
    cancel_rate: float,
    net: float,
    net_rate: float,
    lock: float,
    lock_rate: float,
    provided_fields: tuple[bool, ...] | None = None,
) -> tuple[float, float, list[str]]:
    fields = (total_small, small_to_big, conversion, gross, direct, direct_share, cancel, cancel_rate, net, net_rate, lock, lock_rate)
    presence = provided_fields or tuple(value not in (None, "") for value in fields)
    field_completeness = sum(bool(value) for value in presence) / len(fields)
    checks: list[tuple[bool, str]] = []
    if gross > 0 and (small_to_big > 0 or direct > 0):
        checks.append((close_count(small_to_big + direct, gross), "总小转大+总直接大定与总大定不一致"))
    for label, value in (("小订转化率", conversion), ("直接大定占比", direct_share), ("退订率", cancel_rate), ("留存大定率", net_rate), ("大定到锁单率", lock_rate)):
        if value not in (None, 0):
            checks.append((valid_rate(value), f"{label}超出0%～100%"))
    if gross > 0 and direct > 0 and direct_share > 0:
        checks.append((abs(direct_share - direct / gross) <= 0.02, "直接大定占比与数量不一致"))
    if gross > 0 and net > 0:
        checks.append((net <= gross * 1.02, "首销期留存大定高于总大定"))
    if gross > 0 and lock > 0:
        checks.append((lock <= gross * 1.02, "首销期锁单高于总大定"))
    issues = [message for passed, message in checks if not passed]
    consistency = sum(passed for passed, _ in checks) / len(checks) if checks else 0.0
    return field_completeness, consistency, issues


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
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGNMENT
        cell.border = _HEADER_BORDER
    sheet.row_dimensions[1].height = 30
    headers = [str(cell.value or "") for cell in sheet[1]]
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = _BODY_FONT
            cell.alignment = _BODY_ALIGNMENT
            cell.border = _BODY_BORDER
            if cell.row % 2 == 0:
                cell.fill = _EVEN_FILL
            if headers[cell.column - 1] in percent_headers:
                cell.number_format = "0.0%"
            elif isinstance(cell.value, datetime):
                cell.number_format = "yyyy-mm-dd"
            elif isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.00" if not float(cell.value).is_integer() else "#,##0"
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
        model = str(record.get("车型") or "").strip()
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
        model = str(model_value or "").strip()
        has_day_value = any(index < len(values) and values[index] not in (None, "") for index in day_columns.values())
        if not model and not has_day_value:
            blank_rows += 1
            if result and blank_rows >= 2:
                break
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
    if len(exact) == 1:
        return exact[0][1]
    matching_groups = [
        alias_keys for history_key, alias_keys in aliases.items()
        if history_key in mapping and model_key in alias_keys
    ]
    alias_keys = aliases.get(model_key) or (matching_groups[0] if len(matching_groups) == 1 else {model_key})
    matched = [(name, curve) for name, curve in source_curves.items() if normalize(name) in alias_keys]
    if len(matched) == 1:
        return matched[0][1]
    if len(matched) > 1:
        LOGGER.warning("%s曲线匹配不唯一：%s -> %s；该车型曲线留空", metric_label, model, "、".join(name for name, _ in matched))
    else:
        LOGGER.warning("%s曲线未匹配：%s", metric_label, model)
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
        if left_value in (None, "") and right_value in (None, ""):
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
    mapping, aliases = load_mapping(mapping_path)
    missing_attributes = [
        record["历史传播名"]
        for record in mapping.values()
        if not all(usable_attribute(record.get(field)) != "未维护" for field in ("产品档位", "能源类型", "发布类型", "发布时段"))
    ]
    if missing_attributes:
        LOGGER.warning(
            "%s 的“车型基本信息”Sheet有%d行车型属性未填完整，将对缺失字段使用默认值：%s",
            mapping_path.name, len(missing_attributes), "、".join(missing_attributes),
        )
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
        LOGGER.warning("映射文件中有%d个传播名未出现在当前原始汇总：%s", len(extra_mappings), "、".join(extra_mappings))

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
        release_period = usable_attribute(map_record.get("发布时段"))
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
            LOGGER.warning("历史经营结果为空：%s；请在车型汇总对应表头下维护留存大定和锁单", model)
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
            int(as_number(record.get("首销期天数"), 35)), int(total_small), int(small_to_big), conversion,
            int(gross), int(direct), direct_share, int(cancel), cancel_rate,
            field_completeness, consistency, quality_status, "；".join(quality_issues),
            "历史首销参考数量汇总；映射与车型属性来自车型基本信息.xlsx单表", weekday_name(launch_date),
            release_period, int(as_number(net)), as_number(net_rate),
            int(as_number(lock)), as_number(lock_rate),
        ])

        small_curve = pad_curve(curve_for(model, raw_curves["small"], mapping, aliases, "小转大"), day_count)
        direct_curve = pad_curve(curve_for(model, raw_curves["direct"], mapping, aliases, "直接大定"), day_count)
        gross_curve = pad_curve(curve_for(model, raw_curves["gross"], mapping, aliases, "总大定"), day_count)
        cancel_curve = pad_curve(curve_for(model, raw_curves["cancel"], mapping, aliases, "退订"), day_count)
        # 总大定首表若某行缺失，用小转大+直接大定补齐；两者也无数据时保持空白。
        if not any(value not in (None, "") for value in gross_curve):
            gross_curve = combine_daily(small_curve, direct_curve)
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
        ["数据质量", "字段完整度/口径一致性", "字段完整度检查必要字段是否有值；口径一致性校验数量勾稽与比例范围，异常指标不参与网页评分", "预测基准总表+D1_D2预测指标"],
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

    d12_headers = [
        "传播名", "代际名", "映射状态", "产品档位", "首销天数", "总小转大", "总直接大定", "总大定", "总小订",
        "D1小转大", "D1小转大/总小转大", "D2小转大", "D2小转大/总小转大",
        "D1+D2小转大", "D1+D2小转大/总小转大", "D2小转大/D1小转大", "D1小转大/D1+D2小转大",
        "D1直接大", "D1直接大/总直接大", "D2直接大", "D2直接大/总直接大",
        "D1+D2直接大", "D1+D2直接大/总直接大", "D2直接大/D1直接大", "D1直接大/D1+D2直接大",
        "D1大定", "D1小转大/D1大定", "D1直接大/D1大定",
        "D2大定", "D2小转大/D2大定", "D2直接大/D2大定",
        "D1+D2大定", "D1+D2小转大/D1+D2大定", "D1+D2直接大/D1+D2大定",
        "D1退订", "D1退订率", "D2退订", "D2退订率", "D1+D2退订", "D1+D2退订率",
        "D2退订/D1退订", "D1退订/D1+D2退订",
        "D1口径状态", "D2口径状态", "D1+D2口径状态", "结构异常说明",
    ]
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
    write_rows(workbook, "D1_D2预测指标", d12_headers, d12_rows, "D1D2Metrics", PERCENT_FIELDS)

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
    if orders_dir is not None:
        append_forecast_inputs(workbook, source, mapping_path, orders_dir, as_of_date, preserve_layout=False)
        append_forecast_views(temporary, as_of_date, workbook=workbook)
    reorder_summary_sheets(workbook)
    sheet_count = len(workbook.sheetnames)
    workbook.save(temporary)
    workbook.close()
    try:
        os.replace(temporary, output)
    except PermissionError as exc:
        raise PermissionError(f"无法覆盖 {output}，请确认 Excel 中没有打开该文件") from exc
    LOGGER.info("刷新完成：%s（%d个传播名、%d天、%d个Sheet）", output, len(models), day_count, sheet_count)


def forecast_order_files(directory: Path) -> list[Path]:
    keywords = ("首销期订单节奏", "小订退订分析", "小订选配比例", "锁单选配比例")
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
        directory.append([kind, filename, sheet.title, name, sheet.max_row, sheet.max_column])

    for path, kind in [(source, "历史"), (mapping_path, "映射"), *[(path, "订单") for path in forecast_order_files(orders_dir)]]:
        book = load_workbook(path, read_only=False, data_only=True)
        try:
            for sheet in book.worksheets:
                if kind == "历史" and sheet.title not in {"车型汇总", "小订by天", "小订进度"}:
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
    write_rows(workbook, INDEX_SHEET, ["类别", "原始文件", "原始Sheet", "汇总Sheet", "行数", "列数", "阅读用途"], [
        [*row, {
            "历史": "历史参考与预测基准",
            "映射": "车型名称与属性映射",
            "订单": "当前真实订单候选来源",
        }.get(row[0], "来源明细")]
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
        ["预测参考区", "预测基准总表、D1_D2预测指标及首销参考曲线：保留首销预测现有参考数据和计算结果，首销预测继续读取这些既有口径。"],
        ["历史与资料区", "车型基本信息、小订及退订逐日和预测基准总表：用于名称映射、车型属性、当前阶段及历史小订/首销基准核对。"],
        ["来源说明", "本文件只保留预测所需的汇总结果，不复制原始订单Sheet，也不重复展示可由统一逐日表表达的明细；数据来源目录记录对应汇总位置。"],
        ["取数规则", "按原有阶段优先级逐字段回退；只要后续优先级存在可用数据就继续取数，不因第一优先级缺失直接报错。"],
        ["首销数据说明", "首销逐日数据与首销参考曲线承担不同预测用途，虽然部分车型数值可能相同，本次不合并、不改取数来源。"],
        ["汇总日期", as_of_date or date.today().isoformat()],
        ["刷新签名", forecast_signature(source, mapping_path, orders_dir, as_of_date)],
    ], "ForecastSummaryGuide")
    workbook.move_sheet("汇总说明", offset=-workbook.index(workbook["汇总说明"]))
    workbook["汇总说明"].column_dimensions["B"].width = 105


def append_forecast_views(path, as_of_date, workbook=None):
    """Materialize auditable detail using exactly the same readers as the webpage."""
    from modules.sales_forecast import SalesForecastModule, SOURCE_LABELS
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
    data = dashboard.views["week"]["pages"]["预测方案"]["workspace"]["data"]

    def emit(name, headers, rows, percent_headers=None):
        write_rows(book, name, headers, rows, "ForecastDetail", percent_headers)
        fit_summary_columns(book[name])
        book[name].freeze_panes = "C2"

    def excel_date(value):
        try:
            return datetime.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return value

    effective_date = as_of_date or date.today().isoformat()

    def row_status(value, actual=True):
        if not actual:
            return "参考曲线（非真实日）"
        if not value:
            return "日期缺失"
        return "已结束日" if value < effective_date else "当日快照（未结束）" if value == effective_date else "未来日期（不作真实值）"

    target_by_model = {row.get("name"): row for row in data["targets"]}
    master_sheet = book["车型基本信息"]
    raw_master_headers = [cell.value for cell in master_sheet[1]]
    master_width = max((index for index, value in enumerate(raw_master_headers, 1) if value not in (None, "")), default=0)
    master_headers = raw_master_headers[:master_width]
    model_column = master_headers.index("订单分析代际名")
    history_column = master_headers.index("历史传播名")
    stage_headers = ["首销阶段", "小订阶段", "小订开始", "小订结束", "首销开始", "首销结束", "总小订", "取数来源", "数据问题"]

    def stage_values(target):
        if not target:
            return [None] * len(stage_headers)
        return [
            target.get("stage_label"), target.get("small_stage_label"),
            *[excel_date(target.get(key)) for key in ("small_start_date", "small_end_date", "launch_date", "end_date")],
            target.get("small"), target.get("selected_source_label"), "；".join(target.get("hard_errors", [])),
        ]

    model_rows = []
    matched_targets = set()
    for values in master_sheet.iter_rows(min_row=2, values_only=True):
        row = list(values[:master_width])
        if not any(value not in (None, "") for value in row):
            continue
        model = row[model_column]
        target = target_by_model.get(model)
        if target:
            matched_targets.add(model)
        model_rows.append([*row, *stage_values(target)])
    for model, target in sorted(target_by_model.items()):
        if model in matched_targets:
            continue
        row = [None] * master_width
        row[model_column] = model
        row[history_column] = target.get("history_model")
        model_rows.append([*row, *stage_values(target)])
    book.remove(master_sheet)
    emit("车型基本信息", [*master_headers, *stage_headers], model_rows)

    def source_text(reference, fallback):
        if not isinstance(reference, dict):
            return fallback
        parts = [reference.get("file"), reference.get("sheet")]
        return "｜".join(str(part) for part in parts if part) or fallback

    small_cancel = {}
    for profile in data["small_order_history"]:
        generation = profile.get("generation") or profile.get("model")
        dates = profile.get("dates") or []
        for index, value in enumerate(profile.get("daily_orders", [])):
            date_value = dates[index] if index < len(dates) else None
            key = (generation, date_value)
            small_cancel[key] = {
                "history_model": profile.get("model"), "model": generation,
                "small_start": profile.get("small_start_date"), "date": date_value,
                "day": f"D{index + 1}", "orders": value, "daily_actual": profile.get("daily_actual"),
                "source_model": profile.get("source_model"), "small_source_type": "历史小订逐日",
                "small_source": profile.get("source_sheet"),
            }

    def current_small_defaults(model, date_value):
        target = target_by_model.get(model, {})
        small_start = target.get("small_start_date")
        day = None
        if small_start and date_value:
            day_number = (date.fromisoformat(date_value) - date.fromisoformat(small_start)).days + 1
            day = f"D{day_number}" if day_number > 0 else None
        return {
            "history_model": target.get("history_model"), "model": model,
            "small_start": small_start, "date": date_value, "day": day,
            "source_model": model,
        }

    for profile in data["actuals"]:
        model = profile["model"]
        for day in profile.get("small_daily_days", []):
            date_value = day.get("date")
            row = small_cancel.setdefault((model, date_value), current_small_defaults(model, date_value))
            if day.get("orders") is not None:
                daily_source = profile.get("small_daily_sources", {}).get(date_value) or profile.get("small_hour_source")
                source_file = daily_source.get("file", "") if isinstance(daily_source, dict) else ""
                row["orders"] = day.get("orders")
                row["daily_actual"] = True
                row["small_source_type"] = "小订选配比例分析" if "小订选配比例" in source_file else "小订退订分析" if "小订退订分析" in source_file else "历史小订逐日" if isinstance(daily_source, dict) and daily_source.get("sheet") == "小订by天" else "当前小订"
                row["small_source"] = source_text(daily_source, row["small_source_type"])
        for day in profile.get("cancel_days", []):
            date_value = day.get("date")
            row = small_cancel.setdefault((model, date_value), current_small_defaults(model, date_value))
            row["cancel"] = day.get("cancel")
            row["cancel_rate"] = day.get("cancel_rate")
            row["cancel_source"] = source_text(profile.get("cancel_source"), "小订退订分析")
        # Resolved launch/ended-stage fields use the same priority as the webpage.
        # Cancellation is cumulative SMALL-order cancellation, never daily big orders.
        for day in profile.get("days", []):
            if day.get("cancel") is None or not day.get("date"):
                continue
            date_value = day["date"]
            row = small_cancel.setdefault((model, date_value), current_small_defaults(model, date_value))
            row["cancel"] = day["cancel"]
            total_small = profile.get("total_small")
            row["cancel_rate"] = day["cancel"] / total_small if total_small else None
            row["cancel_source"] = SOURCE_LABELS.get(day.get("_field_sources", {}).get("cancel"), "数据缺失")
    small_cancel_rows = sorted(small_cancel.values(), key=lambda row: (row["model"], row.get("date") or ""))
    emit("小订及退订逐日", ["历史传播名", "订单分析代际名", "小订开始", "日期", "生命周期", "小订数量", "累计退订", "累计退订率", "真实逐日", "原始名称", "小订来源类型", "小订来源", "退订来源", "数据状态"], [
        [row.get("history_model"), row["model"], excel_date(row.get("small_start")), excel_date(row.get("date")), row.get("day"), row.get("orders"), row.get("cancel"), row.get("cancel_rate"), row.get("daily_actual"), row.get("source_model"), row.get("small_source_type"), row.get("small_source"), row.get("cancel_source"), row_status(row.get("date"), row.get("daily_actual") is not False)]
        for row in small_cancel_rows
    ], {"累计退订率"})
    emit("当前小订分时", ["订单分析代际名", "日期", "小时", "小时小订"], [
        [p["model"], excel_date(day.get("date")), hour.get("hour"), hour.get("orders")]
        for p in data["actuals"] for day in p.get("small_hourly_days", []) for hour in day.get("hours", [])
    ])

    def order_stage(model, value):
        target = target_by_model.get(model, {})
        end_date = target.get("end_date")
        return "平销" if value and end_date and value > end_date else "首销"

    fields = ("gross", "net", "small_to_big", "direct", "lock")
    order_rows = {}
    for profile in data["actuals"]:
        for row in profile.get("days", []):
            key = (profile["model"], row.get("date"))
            order_rows[key] = {
                "model": profile["model"], "date": row.get("date"), "day": row.get("day"),
                "stage": order_stage(profile["model"], row.get("date")),
                **{field: row.get(field) for field in fields},
                **{f"{field}_source": SOURCE_LABELS.get(row.get("_field_sources", {}).get(field), "数据缺失") for field in fields},
            }
    for profile in data["steady_history"]:
        steady_start = date.fromisoformat(profile["steady_start_date"]) if profile.get("steady_start_date") else None
        for row in profile.get("daily", []):
            key = (profile["model"], row.get("date"))
            current = order_rows.setdefault(key, {
                "model": profile["model"], "date": row.get("date"), "stage": "平销",
                **{field: None for field in fields},
                **{f"{field}_source": "数据缺失" for field in fields},
            })
            current["stage"] = "平销"
            current_date = date.fromisoformat(row["date"]) if row.get("date") else None
            if not current.get("day") and steady_start and current_date:
                current["day"] = f"P{(current_date - steady_start).days + 1}"
            current["lock"] = row.get("lock")
            current["lock_source"] = source_text({"file": profile.get("source_file"), "sheet": "、".join(profile.get("daily_source_sheets", []))}, "锁单选配比例分析")
    current_order_rows = sorted(order_rows.values(), key=lambda row: (row["model"], row.get("date") or ""))
    emit("当前订单逐日", ["订单分析代际名", "日期", "生命周期", "订单阶段", "大定", "留存大定", "小转大", "直接大定", "交车锁单", "大定来源", "留存大定来源", "小转大来源", "直接大定来源", "锁单来源", "数据状态"], [
        [row["model"], excel_date(row.get("date")), row.get("day"), row.get("stage"), *[row.get(field) for field in fields], *[row.get(f"{field}_source") for field in fields], row_status(row.get("date"))]
        for row in current_order_rows
    ])
    emit("当前首销分时", ["订单分析代际名", "日期", "小时", "小时大定"], [
        [p["model"], excel_date(day.get("date")), hour.get("hour"), hour.get("gross")]
        for p in data["actuals"] for day in p.get("hourly_days", []) for hour in day.get("hours", [])
    ])
    for position, name in enumerate([
        "字段说明", "车型基本信息", INDEX_SHEET, "小订及退订逐日", "当前小订分时", "当前订单逐日", "当前首销分时",
    ], 1):
        book.move_sheet(name, offset=position - book.index(book[name]))
    def snapshot_value(value):
        if isinstance(value, dict):
            return {
                key: (SUMMARY_NAME if key == "file" and item == path.name else snapshot_value(item))
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [snapshot_value(item) for item in value]
        return value

    write_summary_snapshot(book, snapshot_value(dashboard.to_dict()))
    compact_source_sheets(book)
    sheet_count = len(book.sheetnames)
    if owns_workbook:
        book.save(path)
        book.close()
    return sheet_count


def compact_source_sheets(workbook):
    """Replace copied source worksheets with a concise source-to-summary index."""
    source_records = list(workbook[INDEX_SHEET].iter_rows(min_row=2, values_only=True))
    grouped = defaultdict(list)
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
        [kind, filename, len(names), content_summary(kind, filename), destinations(kind, filename)]
        for (kind, filename), names in grouped.items()
    ]
    write_rows(
        workbook,
        INDEX_SHEET,
        ["来源类型", "原始文件", "原始Sheet数", "包含内容", "汇总位置"],
        rows,
        "ForecastSources",
    )
    fit_summary_columns(workbook[INDEX_SHEET])


def reorder_summary_sheets(workbook):
    """Keep a stable, readable progression without changing any source values."""
    first = [
        "汇总说明", "字段说明", "车型基本信息", "数据来源目录",
        "小订及退订逐日", "当前小订分时", "当前订单逐日", "当前首销分时",
        "预测基准总表", "D1_D2预测指标",
        "小转大当日数量", "直接大定当日数量",
        "小转大累计完成度", "直接大定累计完成度", "累计大定完成度", "累计小订转化率", "累计退订率",
        "累计直接大定占比", "每日直接大定占比",
        "车型汇总", "小订by天", "小订进度",
    ]
    existing = {sheet.title: sheet for sheet in workbook.worksheets}
    ordered = [existing[name] for name in first if name in existing]
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
        if "汇总说明" not in book.sheetnames or INDEX_SHEET not in book.sheetnames:
            return False
        info = dict(book["汇总说明"].iter_rows(min_row=2, values_only=True))
        return info.get("刷新签名") == forecast_signature(source, mapping, orders_dir, as_of_date)
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
        LOGGER.warning("默认原始文件名不存在，自动使用同目录唯一候选：%s", pool[0].name)
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
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="车型基本信息文件（单表维护映射和车型属性）")
    parser.add_argument("--force", action="store_true", help="忽略文件时间，强制重新生成二次处理文件")
    return parser.parse_args()


def resolve_mapping_path(requested: Path) -> Path:
    if requested.exists():
        return requested
    if requested == DEFAULT_MAPPING:
        legacy = next((path for path in LEGACY_MAPPINGS if path.exists()), None)
        if legacy:
            LOGGER.warning("默认车型基本信息文件不存在，兼容使用旧文件名：%s", legacy.name)
            return legacy
    return requested


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s", stream=sys.stdout)
    args = parse_args()
    try:
        args.source = resolve_source_path(args.source)
        args.mapping = resolve_mapping_path(args.mapping)
        LOGGER.debug("原始历史文件: %s", args.source)
        LOGGER.debug("车型基本信息: %s", args.mapping)
        LOGGER.debug("二次处理输出: %s", args.output)
        ensure_mapping(args.mapping, args.source)
        if not args.force and summary_is_current(args.source, args.output, args.mapping, args.orders, args.as_of_date):
            LOGGER.info("销量数据汇总已是最新，跳过刷新：%s", args.output)
            return 0
        build_secondary(args.source, args.output, args.mapping, args.orders, args.as_of_date)
        return 0
    except Exception:
        LOGGER.exception("刷新失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

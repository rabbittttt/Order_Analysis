from __future__ import annotations

import base64
import logging
import gzip
import hashlib
import json
import math
import os
import tempfile
from itertools import groupby
import re
import weakref
from statistics import median
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from types import SimpleNamespace

from openpyxl import Workbook, load_workbook
from openpyxl.styles.numbers import is_date_format
from openpyxl.utils.cell import get_column_letter, coordinate_to_tuple


GRAIN_MAP = {"时": "hour", "天": "day", "周": "week", "月": "month"}
GRAIN_LABELS = {value: key for key, value in GRAIN_MAP.items()}
LOGGER = logging.getLogger(__name__)
_CONFLICT_CHECKS = None


def reset_conflict_diagnostics(enabled=True):
    """Scope physical-cell diagnostic deduplication to one generation run."""
    global _CONFLICT_CHECKS
    _CONFLICT_CHECKS = set() if enabled else None


def compact_diagnostic_ranges(labels):
    """Render all consecutive dates/day numbers/ranks without hiding gaps."""
    groups, other = {}, []
    for value in sorted({str(label).strip('/') for label in labels if str(label).strip('/')}):
        if match := re.fullmatch(r"(\d{2}|\d{4})[/-](\d{1,2})[/-](\d{1,2})", value):
            try:
                year, month, day = map(int, match.groups())
                parsed = date(year + 2000 if year < 100 else year, month, day)
                number = parsed.toordinal()
            except ValueError:
                other.append(value)
                continue
            groups.setdefault("date", {})[number] = parsed.isoformat()
        elif week := _week_period(value):
            groups.setdefault("week", {})[week[1].toordinal() // 7] = week[0]
        elif match := re.fullmatch(r"(D|TOP)(\d+)", value, re.I):
            groups.setdefault(match[1].upper(), {})[int(match[2])] = value
        else:
            other.append(value)
    result = []
    for values in groups.values():
        for _, run in groupby(enumerate(sorted(values)), lambda pair: pair[1] - pair[0]):
            numbers = [number for _, number in run]
            first, last = values[numbers[0]], values[numbers[-1]]
            result.append(first if first == last else f"{first}～{last}")
    return "、".join(result + sorted(other, key=_period_sort))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u2011", "-")).strip()


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", clean_text(value))


def compact_identifier(value: Any) -> str:
    """Normalize separators used inconsistently in workbook and Sheet names."""
    return re.sub(r"[\s_\-—–:：/\\（）()【】\[\]]+", "", clean_text(value)).lower()


def display_period(value: Any, number_format: str = "") -> str:
    if isinstance(value, (datetime, date)):
        return format_excel_value(value, number_format or "yyyy-mm-dd")
    return _source_key(value)


def safe_number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        text = clean_text(value)
        negative = text.startswith("(") and text.endswith(")")
        percent = "%" in text or "％" in text
        text = text.replace(",", "").replace("，", "").replace("%", "").replace("％", "")
        text = re.sub(r"(?:人民币|RMB|CNY|元|万元|亿元|￥|¥|\$)", "", text, flags=re.IGNORECASE).strip(" ()")
        try:
            number = float(text)
            if negative:
                number = -number
            return number / 100 if percent else number
        except ValueError:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def cell_number(cell: Any, rate: bool = False, default: float = 0.0) -> float:
    """Read a number while respecting percent-like strings and cell formats."""
    value = safe_number(cell.value, default)
    if not rate or cell.value in (None, ""):
        return value
    if isinstance(cell.value, str):
        text = clean_text(cell.value)
        return value / 100 if "%" not in text and "％" not in text and abs(value) > 1.5 else value
    number_format = clean_text(getattr(cell, "number_format", ""))
    if "%" not in number_format and abs(value) > 1.5:
        return value / 100
    return value


def _format_precision(number_format: str, marker: str = "") -> int:
    section = number_format.split(";", 1)[0]
    if marker and marker in section:
        section = section.split(marker, 1)[0]
    match = re.search(r"[0#](?:\.([0#]+))?[^0#]*$", section)
    return len(match.group(1) or "") if match else 0


def _format_date(value: date | datetime, number_format: str) -> str:
    fmt = number_format.lower().replace("\\", "")
    has_time = any(token in fmt for token in ("h", "s", "am/pm"))
    has_day = "d" in fmt
    has_month = "m" in fmt
    has_year = "y" in fmt
    separator = "/" if "/" in fmt else "." if "." in fmt else "-"
    if has_year and has_month and has_day:
        result = value.strftime(f"%Y{separator}%m{separator}%d")
    elif has_year and has_month:
        result = value.strftime(f"%Y{separator}%m")
    elif has_month and has_day:
        result = value.strftime(f"%m{separator}%d")
    else:
        result = value.isoformat()
    if has_time and isinstance(value, datetime):
        time_text = value.strftime("%H:%M:%S" if "s" in fmt else "%H:%M")
        result = f"{result} {time_text}" if has_year or has_month or has_day else time_text
    return result


def format_excel_value(value: Any, number_format: str = "General") -> str:
    """Render common Excel formats without assuming fixed precision or date syntax."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return _format_date(value, number_format)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if not isinstance(value, (int, float)):
        return clean_text(value)
    fmt = clean_text(number_format or "General")
    if fmt.lower() == "general" or fmt == "@":
        return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    if is_date_format(fmt):
        return str(value)
    if "%" in fmt:
        precision = _format_precision(fmt, "%")
        return f"{value * 100:,.{precision}f}%"
    precision = _format_precision(fmt)
    grouping = "," in fmt.split(";", 1)[0]
    rendered = f"{value:,.{precision}f}" if grouping else f"{value:.{precision}f}"
    currency = next((symbol for symbol in ("￥", "¥", "$", "€", "£") if symbol in fmt), "")
    return f"{currency}{rendered}"


def format_excel_cell(cell: Any) -> str:
    return format_excel_value(cell.value, getattr(cell, "number_format", "General"))


def safe_rate(numerator: Any, denominator: Any) -> float:
    den = safe_number(denominator)
    return safe_number(numerator) / den if den else 0.0


def sheet_subject(name: str) -> str:
    value = clean_text(name)
    patterns = [
        r"净(?:大定|小订)by[时天周月](?:第\s*\d+\s*期)?图表$",
        r"by[时天周月](?:第\s*\d+\s*期)?图表$",
        r"by[时天周月](?:第\s*\d+\s*期)?$",
        r"_(SKU|组合|日度退订|选配退订|小订分时退订|选配渗透率排名|付费选配占比|选配渗透率)$",
    ]
    for pattern in patterns:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    # Generic analysis sheets may append a free-form suffix. Keep the suffix as
    # the analysis name while resolving the sheet back to its known group,
    # brand, or generation subject.
    subject_prefixes = [
        # “总计/汇总”可以是代际名称本身的一部分，例如“问界 M9 2026款总计”。
        # 只清理它后面的分析后缀，不要把它误当作汇总周期截掉。
        r"^(.+?20\d{2}\s*款(?:\s*(?:总计|汇总))?)\s*[_\-—]\s*.+$",
        # 代号型代际（无款号），例如“问界 F2N”。
        r"^([\u4e00-\u9fff]{1,3}界\s*[A-Za-z0-9]+(?:\s*20\d{2}\s*款)?(?:\s*(?:总计|汇总))?)\s*[_\-—]\s*.+$",
        r"^(鸿蒙智行)\s*[_\-—]\s*.+$",
        r"^([\u4e00-\u9fff]{1,3}界)\s*[_\-—]\s*.+$",
    ]
    for pattern in subject_prefixes:
        match = re.match(pattern, value, flags=re.IGNORECASE)
        if match:
            value = match.group(1)
            break
    return clean_text(value.rstrip("_"))


def is_aggregate_generation(name: str) -> bool:
    """以“总计/汇总”结尾的代际是多个代际的聚合视图，品牌级统计时须排除以免重复。"""
    return clean_text(name).endswith(("总计", "汇总"))


def subject_type(name: str) -> str:
    if compact_text(name) == "鸿蒙智行":
        return "group"
    if re.search(r"20\d{2}\s*款", name):
        return "generation"
    if re.fullmatch(r"[\u4e00-\u9fff]{1,3}界[A-Za-z0-9]+(?:[&+/][A-Za-z0-9]+)*(?:[\u4e00-\u9fff]{1,8})?", compact_text(name)):
        return "generation"
    return "brand"


def subject_parent(name: str, kind: str) -> str | None:
    if kind == "brand":
        return "鸿蒙智行"
    if kind != "generation":
        return None
    match = re.match(r"^([\u4e00-\u9fff]{1,3}界)", compact_text(name))
    return match.group(1) if match else None


def grain_from_sheet(name: str) -> str | None:
    match = re.search(r"by([时天周月])", name)
    return GRAIN_MAP.get(match.group(1)) if match else None



_DATA_CACHE_VERSION = 3


def load_data_workbook(path: Path, cache_dir: Path | None = None):
    """Return cached values/formats without retaining drawings/decorative styles.

    Cache is derived JSON (not executable pickle), keyed by the exact source
    identity, nanosecond timestamps and size. A failed cache is always optional.
    """
    path = Path(path)
    stat = path.stat()
    signature = [_DATA_CACHE_VERSION, str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    cache = None
    if cache_dir is not None:
        cache = Path(cache_dir) / (hashlib.sha256(str(path.resolve()).encode()).hexdigest() + ".jsonl.gz")

    def decode(value, kind):
        if kind == "datetime":
            return datetime.fromisoformat(value)
        if kind == "date":
            return date.fromisoformat(value)
        if kind == "time":
            from datetime import time
            return time.fromisoformat(value)
        if kind == "timedelta":
            from datetime import timedelta
            return timedelta(seconds=value)
        return value

    def restore(stream):
        if json.loads(stream.readline()) != signature:
            raise ValueError("stale workbook cache")
        result = Workbook()
        result.remove(result.active)
        sheet = None
        complete = False
        for line in stream:
            row = json.loads(line)
            if row == ["end"]:
                complete = True
                break
            if row[0] == "sheet":
                sheet = result.create_sheet(row[1])
                sheet.sheet_state = row[2]
            elif row[0] == "row" and sheet is not None:
                for col, value, kind, data_type, number_format in row[2]:
                    cell = sheet.cell(row[1], col, decode(value, kind))
                    cell.data_type = data_type
                    cell.number_format = number_format
            else:
                raise ValueError("invalid workbook cache")
        if not result.worksheets or not complete:
            raise ValueError("incomplete workbook cache")
        return result

    if cache is not None and cache.exists():
        try:
            with gzip.open(cache, "rt", encoding="utf-8") as stream:
                result = restore(stream)
            LOGGER.debug("Excel解析缓存命中: %s", path.name)
            return result
        except (OSError, EOFError, ValueError, TypeError, IndexError, KeyError):
            LOGGER.debug("Excel解析缓存失效，重新读取: %s", path.name)

    # The normal reader applies Excel merged-cell semantics. Read-only mode
    # exposes hidden XML values inside merged ranges and can change real orders.
    # Only cache misses pay this cost; the returned view and cache stay compact.
    source = load_workbook(path, data_only=True, read_only=False, keep_links=False)
    result = Workbook()
    result.remove(result.active)
    pending = None
    writer = None
    try:
        if cache is not None:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix=cache.stem + ".", suffix=".tmp", dir=cache.parent)
                os.close(fd)
                pending = Path(name)
                writer = gzip.open(pending, "wt", encoding="utf-8", compresslevel=1)
                writer.write(json.dumps(signature) + "\n")
            except OSError:
                LOGGER.debug("Excel解析缓存不可写，将直接读取: %s", path.name)

        def write(record):
            nonlocal writer
            if writer is not None:
                try:
                    writer.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                except OSError:
                    writer.close()
                    writer = None

        from datetime import time, timedelta
        for raw in source.worksheets:
            sheet = result.create_sheet(raw.title)
            sheet.sheet_state = raw.sheet_state
            write(["sheet", sheet.title, sheet.sheet_state])
            # Iterate stored cells, never materialize a huge styled blank grid.
            for row_number, cells in groupby(raw._cells.values(), key=lambda cell: cell.row):
                entries = []
                for cell in cells:
                    column, value = cell.column, cell.value
                    if value is None:
                        continue
                    dest = sheet.cell(row_number, column, value)
                    dest.data_type = cell.data_type
                    dest.number_format = cell.number_format
                    kind = ""
                    if isinstance(value, datetime):
                        value, kind = value.isoformat(), "datetime"
                    elif isinstance(value, date):
                        value, kind = value.isoformat(), "date"
                    elif isinstance(value, time):
                        value, kind = value.isoformat(), "time"
                    elif isinstance(value, timedelta):
                        value, kind = value.total_seconds(), "timedelta"
                    entries.append([column, value, kind, cell.data_type, cell.number_format])
                if entries:
                    write(["row", row_number, entries])
        write(["end"])
        if writer is not None:
            writer.close()
            writer = None
            # Never commit a cache for a source edited while it was being read.
            after = path.stat()
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                try:
                    os.replace(pending, cache)
                    pending = None
                except OSError:
                    LOGGER.debug("Excel解析缓存提交失败，当前读取结果仍有效: %s", path.name)
        return result
    finally:
        source.close()
        if writer is not None:
            writer.close()
        if pending is not None:
            pending.unlink(missing_ok=True)


@lru_cache(maxsize=4096)
def _week_period(text):
    match = re.fullmatch(r"(\d{2}|\d{4})WK(\d{1,2})", text.upper())
    if not match:
        return None
    year = int(match[1])
    year = year + 2000 if year < 100 else year
    try:
        start = date.fromisocalendar(year, int(match[2]), 1)
    except ValueError:
        return None
    end = start + timedelta(days=6)
    reason = "跨年" if start.year != end.year else (
        "跨半年" if start <= date(start.year, 6, 30) < end else "")
    return f"{year % 100:02d}WK{int(match[2]):02d}", start, end, reason


def _source_key(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat().replace("T00:00:00", "")
    text = clean_text(value)
    week = _week_period(text)
    return week[0] if week else text


@lru_cache(maxsize=4096)
def _quantity_field(labels, number_format):
    text = "|".join(map(str, labels))
    return ("%" not in number_format and "％" not in number_format
            and not re.search(r"占比|比例|率|平均|均价|时长|天数|（天）|\(天\)", text)
            and any(label in {"数量", "订单量", "订单数", "单量", "累计锁单"} for label in labels))


def _quantity_value(value):
    if isinstance(value, str) and ("%" in value or "％" in value):
        return None
    number = safe_number(value, float("nan"))
    return number if not isinstance(value, bool) and math.isfinite(number) and number >= 0 else None


def _coverage_date(cell, *, day_header=False):
    value = cell.value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = clean_text(value).replace("年", "-").replace("月", "-").replace("日", "")
        match = re.fullmatch(r"(\d{2}|\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T]00:00:00)?", text)
        if match:
            try:
                year, month, day = map(int, match.groups())
                return date(year + 2000 if year < 100 else year, month, day)
            except ValueError:
                pass
    if isinstance(value, (int, float)) and not isinstance(value, bool) and (
        is_date_format(cell.number_format) or (day_header and 20000 < value < 100000)
    ):
        from openpyxl.utils.datetime import from_excel
        try:
            converted = from_excel(value)
            return converted.date() if isinstance(converted, datetime) else None
        except (ValueError, OverflowError):
            pass
    return None


def _daily_period(value, number_format=""):
    """Use one calendar key for daily joins, without changing raw Excel display."""
    day = _coverage_date(SimpleNamespace(value=value, number_format=number_format), day_header=True)
    return day.isoformat() if day is not None else display_period(value, number_format)


def _source_date_range(item):
    """Infer the physical file's coverage from real daily quantities/explicit export dates.

    A week label alone never proves which side of a boundary a file contains.
    File names and other source files are deliberately not used as evidence.
    """
    if hasattr(item, "_boundary_date_range"):
        return item._boundary_date_range
    dates, chart_sheets = [], []
    starts = {"数据开始日期", "统计开始日期", "导出开始日期", "数据起始日期", "统计起始日期"}
    ends = {"数据结束日期", "数据截止日期", "统计结束日期", "统计截止日期", "导出结束日期", "导出截止日期"}
    for sheet in item.workbook.worksheets:
        declared = {}
        for row in range(1, min(sheet.max_row, 10) + 1):
            label = compact_text(sheet.cell(row, 1).value)
            if label in starts | ends:
                day = _coverage_date(sheet.cell(row, 2))
                if day:
                    declared["start" if label in starts else "end"] = day
        if "start" in declared and "end" in declared and declared["start"] <= declared["end"]:
            dates.extend(declared.values())
        if grain_from_sheet(sheet.title) != "day":
            continue
        if "图表" in sheet.title:
            chart_sheets.append(sheet)
            continue
        count_rows = [row for row in range(2, sheet.max_row + 1)
                      if clean_text(sheet.cell(row, 2).value) == "数量"
                      and clean_text(sheet.cell(row, 3).value) == "数量"]
        if not count_rows:
            continue
        for column in range(4, sheet.max_column + 1):
            day = _coverage_date(sheet.cell(1, column), day_header=True)
            if day and any(_quantity_value(sheet.cell(row, column).value) is not None for row in count_rows):
                dates.append(day)
    # Full by-day detail is export evidence; rolling chart windows are not.
    # Only chart-only workbooks fall back to all blocks' own date headers.
    if not dates:
        for sheet in chart_sheets:
            block_starts = [row for row in range(1, sheet.max_row + 1) if clean_text(sheet.cell(row, 1).value)]
            for start, end in zip(block_starts, [*block_starts[1:], sheet.max_row + 1]):
                count_rows = [row for row in range(start + 2, end)
                              if clean_text(sheet.cell(row, 2).value) == "总计"]
                if not count_rows:
                    continue
                for column in range(3, sheet.max_column + 1):
                    day = _coverage_date(sheet.cell(start + 1, column), day_header=True)
                    if day and any(_quantity_value(sheet.cell(row, column).value) is not None for row in count_rows):
                        dates.append(day)
    item._boundary_date_range = (min(dates), max(dates)) if dates else None
    return item._boundary_date_range


def _boundary_side(coverage, week):
    if not coverage:
        return None
    start, end = coverage
    cutoff = date(week[1].year, 12, 31) if week[3] == "跨年" else date(week[1].year, 6, 30)
    if start <= cutoff and end == cutoff:
        return "left"
    if start == cutoff + timedelta(days=1) and end >= start:
        return "right"
    return None  # Already crosses the cut, overlaps it, has a gap, or is unrelated.


def _source_date_ranges(item):
    """Keep each physical export interval; a merged view must not invent gap days."""
    origins = getattr(item, "_source_items", (item,))
    return list(dict.fromkeys(span for origin in origins if (span := _source_date_range(origin))))


def _add_boundary_week(previous, current, key, period, parts, reports, coverage):
    """Add only two confirmed adjoining file pieces, never an already complete week."""
    week = _week_period(period)
    if not week or not week[3]:
        return None
    old, new = _quantity_value(previous[0]), _quantity_value(current[0])
    if old is None or new is None:
        return None
    pieces = parts.get(key, [(previous[3], old)])
    if any(value == new for _, value in pieces):
        return previous  # Preserve the established identical-value deduplication.
    if any(source == current[3] for source, _ in pieces):
        return None  # Duplicate keys within one physical file are not shards.
    sides = [_boundary_side(coverage.get(source), week) for source, _ in pieces]
    new_side = _boundary_side(coverage.get(current[3]), week)
    if len(pieces) != 1 or sides[0] is None or new_side is None or sides[0] == new_side:
        return None
    parts[key] = pieces
    pieces.append((current[3], new))
    total = sum(value for _, value in pieces)
    report = reports.setdefault(week[0], {"week": week, "fields": set(), "sources": set(), "ranges": {}, "examples": []})
    report["fields"].add(key)
    report["sources"].update(source for source, _ in pieces)
    report["ranges"].update({source: coverage[source] for source, _ in pieces})
    if len(report["examples"]) < 3:
        report["examples"].append(f"{'/'.join(map(str, key))}: "
                                  + "+".join(f"{source}={value:g}" for source, value in pieces)
                                  + f" → {total:g}")
    return (total, previous[1], "n", previous[3], *previous[4:])


def _log_boundary_weeks(label, reports):
    if not reports:
        return
    weeks, sources, examples, ranges = {}, set(), [], {}
    for report in reports:
        week = report["week"]
        weeks[week[0]] = f"{week[0]} {week[1]}~{week[2]}（{week[3]}）"
        sources.update(report["sources"])
        ranges.update(report["ranges"])
        examples.extend(report["examples"][:max(0, 3 - len(examples))])
    LOGGER.info("[边界周累加] %s | 周期=%s | 累加数量字段=%d | 来源=%s | 文件日期范围=%s | 示例=%s",
                label, "、".join(weeks[key] for key in sorted(weeks)),
                sum(len(report["fields"]) for report in reports), "、".join(sorted(sources)),
                "、".join(f"{source}:{start}~{end}" for source, (start, end) in sorted(ranges.items())), "；".join(examples))


def _period_sort(value, *, keep_aggregate_order=False):
    text = str(value)
    aggregate = any(word in text for word in ("总计", "汇总", "累计", "近"))
    if aggregate and keep_aggregate_order:
        return (True, ())  # Stable sort retains source ordering among summary columns.
    return (aggregate, tuple((0, int(part)) if part.isdigit() else (1, part)
                             for part in re.split(r"(\d+)", text)))


def _aggregate_period(labels):
    return any(re.fullmatch(r"(?:总计|合计|汇总|累计)(?:占比|比例|数量)?|近\d+(?:天|日|周|月)", clean_text(v))
               for v in labels)


def _diagnostic_equal(a, b):
    # Logging tolerance only: never round or replace the underlying selected value.
    if a == b:
        return True
    return (all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (a, b))
            and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12))


def _cell_location(value):
    cell = value[4] if len(value) > 4 else None
    parent = getattr(cell, "parent", None)
    original = getattr(parent, "_log_origin", None)
    if original:
        title, row_offset, col_offset = original
        return title, f"{get_column_letter(cell.column + col_offset)}{cell.row + row_offset}"
    return (getattr(parent, "title", getattr(cell, "sheet_title", "位置未记录")),
            getattr(cell, "coordinate", ""))


def _coordinate_ranges(coordinates):
    columns, other, omitted = {}, [], {}
    for coordinate in sorted(coordinates):
        if re.fullmatch(r"[A-Z]+[1-9]\d*", coordinate):
            row, col = coordinate_to_tuple(coordinate)
            columns.setdefault(col, []).append(row)
        elif match := re.fullmatch(r"省略日期(\d{4}-\d{2}-\d{2})，行(\d+)", coordinate):
            omitted.setdefault(int(match[2]), set()).add(match[1])
        else:
            other.append(coordinate)
    intervals = {}
    for col, rows in sorted(columns.items()):
        for _, group in groupby(enumerate(sorted(set(rows))), lambda item: item[1] - item[0]):
            run = [row for _, row in group]
            intervals.setdefault((run[0], run[-1]), []).append(col)
    result = []
    for (start, end), cols in sorted(intervals.items()):
        for _, group in groupby(enumerate(cols), lambda item: item[1] - item[0]):
            run = [col for _, col in group]
            first, last = f"{get_column_letter(run[0])}{start}", f"{get_column_letter(run[-1])}{end}"
            result.append(first if first == last else f"{first}:{last}")
    for row, days in sorted(omitted.items()):
        result.append(f"省略日期按0：{compact_diagnostic_ranges(days)}（行{row}）")
    return "、".join(result + other)


def _diagnostic_location(coordinates):
    """Use a search area for heavily fragmented cells, never claim a solid conflict rectangle."""
    rendered = _coordinate_ranges(coordinates)
    if len(rendered) <= 240:
        return f"单元格={rendered}"
    cells, omitted, other = [], {}, []
    for coordinate in coordinates:
        if re.fullmatch(r"[A-Z]+[1-9]\d*", coordinate):
            cells.append(coordinate_to_tuple(coordinate))
        elif match := re.fullmatch(r"省略日期(\d{4}-\d{2}-\d{2})，行(\d+)", coordinate):
            omitted.setdefault(match[1], set()).add(int(match[2]))
        else:
            other.append(coordinate)
    parts = []
    if cells:
        rows, cols = zip(*cells)
        parts.append(f"单元格定位区间={get_column_letter(min(cols))}{min(rows)}:{get_column_letter(max(cols))}{max(rows)}（{len(cells)}处，区间含非冲突单元格）")
    if omitted:
        rows = set().union(*omitted.values())
        count = sum(map(len, omitted.values()))
        parts.append(f"省略日期按0={compact_diagnostic_ranges(omitted)}（行定位区间{min(rows)}～{max(rows)}，{count}处，非逐格明细）")
    return "、".join(parts + sorted(other))


class _OverlapDiagnostics:
    """Compare only compatible scopes; report unresolved scope once with every affected cell."""

    def __init__(self, coverage):
        self.coverage = coverage
        self.notes = {}
        self.conflicts = {}

    def conflict(self, previous, current, rows, columns, *, nonadditive=False, metric=None):
        if _diagnostic_equal(previous[0], current[0]):
            return None
        cross_file = previous[3] != current[3]
        period = next((value for value in columns if _week_period(value)), "")
        week = _week_period(period)
        reason, level = "", logging.INFO
        if cross_file and _aggregate_period(columns):
            reason = "文件汇总列没有共同统计范围，不作为同周期数值冲突"
        elif cross_file and nonadditive and week and week[3]:
            spans = [self.coverage.get(previous[3]), self.coverage.get(current[3])]
            sides = [_boundary_side(span, week) for span in spans]
            if set(sides) == {"left", "right"}:
                reason = "已确认边界周前后分段；比例或排名不能直接累加，当前保留来源值不代表合并全周指标"
            elif any(span is None for span in spans):
                reason, level = "缺少文件实际日期范围，无法确认边界周是否分段；请核对来源范围，不能据文件名判断", logging.WARNING
        if reason:
            titles = tuple(_cell_location(value)[0] for value in (previous, current))
            key = (reason, previous[3], current[3], titles)
            note = self.notes.setdefault(key, {"level": level, "keys": set(), "periods": set(), "cells": {}})
            note["keys"].add(tuple((value[3], *_cell_location(value), repr(value[0])) for value in (previous, current)))
            note["periods"].add(period or "文件汇总")
            for value in (previous, current):
                title, coordinate = _cell_location(value)
                note["cells"].setdefault((value[3], title), set()).add(coordinate)
            return None
        kind, example = _conflict_location(previous, current, f"{'/'.join(map(str, rows))} @ {'/'.join(map(str, columns))}")
        if week and week[3]:
            spans = [self.coverage.get(value[3]) for value in (previous, current)]
            reason = ("缺少完整逐日日期范围" if any(span is None for span in spans)
                      else "未在边界日衔接（范围跨界、重叠或缺口），或存在额外来源")
            ranges = "；".join(f"{value[3]}:{span[0]}~{span[1]}" if span else f"{value[3]}:未识别"
                              for value, span in zip((previous, current), spans))
            example += f" | 文件日期范围={ranges} | 未累加说明={reason}"
        physical = tuple((value[3], *_cell_location(value), repr(value[0])) for value in (previous, current))
        identity = physical, tuple(rows), tuple(columns)
        if _CONFLICT_CHECKS is not None:
            if identity in _CONFLICT_CHECKS:
                return kind, example
            _CONFLICT_CHECKS.add(identity)
        # TOP ranks share one metric; keep all affected ranks in the range, not
        # one warning per SKU row. Other business dimensions remain independent.
        metric = metric or tuple(re.sub(r"^TOP\d+$", "TOP排名", str(label), flags=re.I) for label in rows)
        titles = tuple(_cell_location(value)[0] for value in (previous, current))
        key = kind, previous[3], current[3], titles, metric
        note = self.conflicts.setdefault(key, {"keys": set(), "periods": set(), "rows": set(),
                                               "cells": {}, "sample": (previous, current),
                                               "boundary": set()})
        note["keys"].add(identity)
        note["periods"].add("/".join(map(str, columns)))
        note["rows"].add("/".join(map(str, rows)))
        if week and week[3]:
            note["boundary"].add(reason)
        for value in (previous, current):
            title, coordinate = _cell_location(value)
            note["cells"].setdefault((value[3], title), set()).add(coordinate)
        return kind, example

    def flush(self):
        for (kind, _, _, _, metric), note in self.conflicts.items():
            locations = "；".join(f"{file} / Sheet={sheet} / {_diagnostic_location(cells)}"
                                  for (file, sheet), cells in note["cells"].items())
            label = "多文件数值冲突" if kind == "跨文件冲突" else "同文件重复键冲突"
            rows = (compact_diagnostic_ranges(note["rows"]) if all(re.fullmatch(r"TOP\d+", row, re.I) for row in note["rows"])
                    else f"{len(note['rows'])}个业务行")
            sample = " / ".join(f"单元格={_cell_location(value)[1]}: {value[0]}" for value in note["sample"])
            boundary = ""
            if note["boundary"]:
                spans = "；".join(f"{file}:{span[0]}~{span[1]}" if (span := self.coverage.get(file)) else f"{file}:未识别"
                                  for file in dict.fromkeys(value[3] for value in note["sample"]))
                boundary = f" | 文件日期范围={spans} | 未累加说明={'；'.join(sorted(note['boundary']))}"
            LOGGER.warning("[%s] 指标=%s | 冲突%d项 | 全部周期=%s | 涉及业务行=%s | 定位=%s | 首处数值=%s%s | 处理=保留原文件顺序中首个非空值，不累加",
                           label, "/".join(metric), len(note["keys"]), compact_diagnostic_ranges(note["periods"]),
                           rows, locations, sample, boundary)
        self.conflicts.clear()
        for (reason, first, second, _), note in self.notes.items():
            locations = "；".join(f"{file} / Sheet={sheet} / {_diagnostic_location(cells)}"
                                  for (file, sheet), cells in note["cells"].items())
            spans = "；".join(f"{file}:{span[0]}~{span[1]}" if (span := self.coverage.get(file)) else f"{file}:未识别"
                              for file in (first, second))
            label = "统计范围待核对" if note["level"] == logging.WARNING else "统计口径说明"
            LOGGER.log(note["level"], "[%s] 周期=%s | 原因=%s | 涉及%d处差异 | 定位=%s | 文件日期范围=%s | 处理=保留原优先值，不强行合并",
                       label, compact_diagnostic_ranges(note["periods"]), reason, len(note["keys"]), locations, spans)
        self.notes.clear()


def _merge_matrix(matches, header_rows, key_columns, *, forward_rows=(), forward_headers=(), time_row=None,
                  column_group_row=None, sparse_headers=(), quantity_columns=False,
                  diagnostics=None, diagnostic_metric=None):
    """Union an identified table by business labels; first nonblank value wins.

    Boundary-week quantities may add distinct yearly/half-year pieces. Summary
    columns and different launch phases never enter that exception.
    Physical originals stay untouched and remain available in the raw-table centre.
    """
    rows, columns, values = {}, {}, {}
    conflicts = []
    conflict_count = 0
    conflict_kinds = {"同文件重复键": 0, "跨文件冲突": 0}
    boundary_parts, boundary_reports, ratio_sources, ratio_conflicts = {}, {}, {}, []
    coverage = {item.path.name: _source_date_range(item) for item, _ in matches}
    owns_diagnostics = diagnostics is None
    diagnostics = diagnostics if diagnostics is not None else _OverlapDiagnostics(coverage)
    sku = all("SKU" in item.path.name for item, _ in matches)
    if sku and diagnostic_metric is None:
        diagnostic_metric = (clean_text(matches[0][1].cell(1, 1).value) or "SKU数据",)
    mix = header_rows == 1 and key_columns == 3 and all("选配比例" in item.path.name for item, _ in matches)
    mix_days = set()
    if header_rows == 1 and key_columns == 3:
        for item, sheet in matches:
            if "选配比例" in item.path.name and grain_from_sheet(sheet.title) == "day" and "图表" not in sheet.title:
                mix_days.update(day for cell in sheet[1][3:] if (day := _coverage_date(cell)))
    for item, sheet in matches:
        row_keys, col_keys = {}, {}
        inherited = {}
        for row in range(header_rows + 1, sheet.max_row + 1):
            labels = []
            for col in range(1, key_columns + 1):
                cell = sheet.cell(row, col)
                value = cell.value
                if col in forward_rows:
                    if value not in (None, ""):
                        inherited[col] = value
                    value = inherited.get(col) if value in (None, "") else value
                labels.append(value)
            if not any(value not in (None, "") for value in labels):
                continue
            # Overview already treats these as legacy/current aliases. Apply
            # that same identity only to the metric label of known mix tables.
            if header_rows == 1 and key_columns == 3 and 1 in forward_rows and clean_text(labels[0]) == "净大定":
                labels[0] = "留存大定"
            key = tuple(_source_key(value) for value in labels)
            row_keys[row] = key
            rows.setdefault(key, labels)
        inherited = {}
        for col in range(key_columns + 1, sheet.max_column + 1):
            labels = []
            for row in range(1, header_rows + 1):
                cell = sheet.cell(row, col)
                value = cell.value
                if row in forward_headers:
                    if value not in (None, ""):
                        inherited[row] = value
                    value = inherited.get(row) if value in (None, "") else value
                if isinstance(value, str) and _week_period(clean_text(value)):
                    value = _source_key(value)
                labels.append((value, cell.number_format))
            if not any(value not in (None, "") for value, _ in labels):
                continue
            if header_rows == 1 and key_columns == 3 and grain_from_sheet(sheet.title) == "day":
                # Text dates and Excel dates must match before sparse-day zeros
                # are inserted; otherwise a real day gets a second zero column.
                key = (_daily_period(*labels[0]),)
            elif time_row and labels[time_row - 1][0] not in (None, ""):
                value = labels[time_row - 1][0]
                if isinstance(value, (int, float)) and 20000 < value < 100000:
                    from openpyxl.utils.datetime import from_excel
                    value = from_excel(value)
                key = (_source_key(value),)
            else:
                key = tuple(_source_key(value) for value, _ in labels)
            # Rolling/file aggregates are not a shared calendar period. Do not
            # merge or diagnose them as duplicate quantities in order mix files.
            if header_rows == 1 and key_columns == 3 and 1 in forward_rows and any(
                re.fullmatch(r"(?:总计|合计|汇总|累计|近\d+(?:天|日|周|月))", clean_text(part))
                for part in key
            ):
                continue
            col_keys[col] = key
            columns.setdefault(key, labels)
        span = coverage.get(item.path.name)
        if mix_days and span:
            present = set(col_keys.values())
            for day in sorted(mix_days):
                key = (_source_key(day),)
                if span[0] <= day <= span[1] and key not in present:
                    # A missing date column means zero for this physical export;
                    # an existing blank cell remains unknown. Do this before
                    # merging so another file's columns cannot erase that fact.
                    col_keys[-len(col_keys)-1] = key
                    columns.setdefault(key, [(day, "yyyy-mm-dd")])
        column_periods = {col: next((part for part in key if _week_period(part)), "") for col, key in col_keys.items()}
        for row, row_key in row_keys.items():
            for col, col_key in col_keys.items():
                if col < 0:
                    if not _quantity_field(row_key, "0"):
                        continue
                    cell = SimpleNamespace(value=0, number_format="0", data_type="n",
                                           sheet_title=sheet.title, coordinate=f"省略日期{'/'.join(col_key)}，行{row}")
                else:
                    cell = sheet.cell(row, col)
                if cell.value in (None, ""):
                    continue
                key = row_key, col_key
                period = column_periods[col]
                if len(row_key) == 3 and row_key[1] == "占比" and period and _week_period(period)[3]:
                    ratio_sources.setdefault(key, {}).setdefault(item.path.name, cell_number(cell, rate=True, default=float("nan")))
                previous = values.get(key)
                current = (cell.value, cell.number_format, cell.data_type, item.path.name, cell)
                if previous is None:
                    values[key] = current
                else:
                    merged = (_add_boundary_week(previous, current,
                                                 key, period, boundary_parts, boundary_reports, coverage)
                              if _quantity_field(row_key, cell.number_format)
                              or (quantity_columns and _quantity_field(("数量",), cell.number_format)) else None)
                    if merged is not None:
                        values[key] = merged
                    elif previous[0] != cell.value:
                        if key in ratio_sources:
                            ratio_conflicts.append((key, previous, current))
                        else:
                            issue = diagnostics.conflict(previous, current, row_key, col_key,
                                metric=diagnostic_metric or (row_key[:2] if mix else None),
                                nonadditive=sku and (not quantity_columns or '%' in cell.number_format
                                    or any(re.fullmatch(r'TOP\d+', label, re.I) for label in row_key)))
                            if issue:
                                kind, example = issue
                                conflict_count += 1
                                conflict_kinds[kind] += 1
                                if len(conflicts) < 3:
                                    conflicts.append(example)
    # Counts are additive; percentages are not. Rebuild dimension shares from
    # merged category counts, or weight source shares by the primary order count.
    primary = next((metric for marker, metric in (("锁单", "交车锁单"), ("小订", "小订"), ("大定", "大定"))
                    if marker in matches[0][0].path.name), "")
    category_totals, resolved_ratios = {}, set()
    ratio_columns = {column for _, column in ratio_sources}
    for labels in rows:
        if len(labels) != 3 or labels[1] != "数量" or labels[2] == "数量":
            continue
        for column in ratio_columns:
            entry = values.get((labels, column))
            number = _quantity_value(entry[0]) if entry else None
            if number is not None:
                group = labels[0], column
                category_totals[group] = category_totals.get(group, 0) + number
    for (row_key, col_key), source_rates in ratio_sources.items():
        period = next((part for part in col_key if _week_period(part)), "")
        if period not in boundary_reports:
            continue
        count = values.get(((row_key[0], "数量", row_key[2]), col_key))
        denominator = category_totals.get((row_key[0], col_key), 0)
        ratio = None
        if count is not None and denominator > 0 and _quantity_value(count[0]) is not None:
            ratio = _quantity_value(count[0]) / denominator
        else:
            weights = boundary_parts.get(((primary, "数量", "数量"), col_key), [])
            if len(weights) > 1 and sum(weight for _, weight in weights) > 0 and all(
                weight == 0 or math.isfinite(source_rates.get(source, float("nan"))) for source, weight in weights
            ):
                ratio = sum(source_rates.get(source, 0) * weight for source, weight in weights if weight > 0) / sum(weight for _, weight in weights)
        if ratio is not None:
            old = values[(row_key, col_key)]
            values[(row_key, col_key)] = (ratio, old[1], "n", old[3], *old[4:])
            resolved_ratios.add((row_key, col_key))
    for key, previous, current in ratio_conflicts:
        if key not in resolved_ratios:
            issue = diagnostics.conflict(previous, current, key[0], key[1], nonadditive=True,
                                         metric=diagnostic_metric or (key[0][:2] if mix else None))
            if issue:
                kind, example = issue
                conflict_count += 1
                conflict_kinds[kind] += 1
                if len(conflicts) < 3:
                    conflicts.append(example)
    if owns_diagnostics:
        diagnostics.flush()
    book = Workbook()
    target = book.active
    target.title = matches[0][1].title
    first = matches[0][1]
    for row in range(1, header_rows + 1):
        for col in range(1, key_columns + 1):
            cell = first.cell(row, col)
            target.cell(row, col, cell.value).number_format = cell.number_format
    if column_group_row is None:
        column_order = sorted(columns, key=lambda key: _period_sort("|".join(key), keep_aggregate_order=True))
    else:
        # Keep a month's bands and subtotal together, in source band order.
        column_order = sorted(columns, key=lambda key: (
            _period_sort(key[column_group_row - 1]),
            any(word in "|".join(key) for word in ("总计", "汇总", "合计")),
        ))
    previous_headers = {}
    for index, key in enumerate(column_order, key_columns + 1):
        for row, (value, fmt) in enumerate(columns[key], 1):
            repeated = row in sparse_headers and previous_headers.get(row) == value
            target.cell(row, index, None if repeated else value).number_format = fmt
            previous_headers[row] = value
    for row, (row_key, labels) in enumerate(rows.items(), header_rows + 1):
        for col, value in enumerate(labels, 1):
            target.cell(row, col, value)
        for col, col_key in enumerate(column_order, key_columns + 1):
            value = values.get((row_key, col_key))
            if value is not None:
                cell = target.cell(row, col, value[0])
                cell.number_format, cell.data_type = value[1:3]
    target._source_matches = matches
    target._merge_conflict_count = conflict_count
    target._merge_conflict_examples = conflicts
    target._merge_conflict_kinds = conflict_kinds
    target._boundary_week_merges = list(boundary_reports.values())
    return target


def _conflict_location(previous, current, key):
    """Locate both physical cells without copying source metadata per value."""
    kind = "同文件重复键" if previous[3] == current[3] else "跨文件冲突"
    def point(value):
        cell = value[4] if len(value) > 4 else None
        title, coordinate = _cell_location(value)
        raw = getattr(cell, "value", value[0])
        rendered = str(value[0]) if raw == value[0] else f"{raw}（当前合并值={value[0]}）"
        return f"{value[3]} / Sheet={title} / 单元格={coordinate}: {rendered}"
    example = f"[{kind}] {key}: {point(previous)} / {point(current)}"
    LOGGER.debug("[数值重叠定位] %s", example)
    return kind, example


def _merge_records(matches, key_aliases, *, header_depth=1):
    """Union records by named date/hour/period fields, not physical positions."""
    aliases = [{compact_identifier(value) for value in group} for group in key_aliases]
    columns, records = {}, {}
    first_header = None
    conflict_count, conflicts = 0, []
    conflict_kinds = {"同文件重复键": 0, "跨文件冲突": 0}
    boundary_parts, boundary_reports = {}, {}
    coverage = {item.path.name: _source_date_range(item) for item, _ in matches}
    diagnostics = _OverlapDiagnostics(coverage)
    for item, sheet in matches:
        header_row = None
        for row in range(1, min(sheet.max_row, 15) + 1):
            found = {}
            for col in range(1, sheet.max_column + 1):
                label = compact_identifier(sheet.cell(row, col).value)
                for field, names in enumerate(aliases):
                    if label in names:
                        found.setdefault(field, col)
            if len(found) == len(aliases):
                header_row, key_cols = row, [found[i] for i in range(len(aliases))]
                break
        if header_row is None:
            raise ValueError(f"多文件合并无法识别业务键表头: {item.path.name} / {sheet.title}")
        if first_header is None:
            first_header = header_row
        by_column, inherited = {}, ""
        for col in range(1, sheet.max_column + 1):
            labels = []
            for offset in range(header_depth):
                cell = sheet.cell(header_row + offset, col)
                value = cell.value
                if header_depth > 1 and offset == 0:
                    if value not in (None, ""):
                        inherited = value
                    value = inherited
                labels.append((value, cell.number_format))
            if not any(value not in (None, "") for value, _ in labels):
                continue
            # Key aliases describe the same field even if the header wording differs.
            key = (f"__key_{key_cols.index(col)}",) if col in key_cols else tuple(
                compact_identifier(value) for value, _ in labels)
            by_column[col] = key
            columns.setdefault(key, labels)
        for row in range(header_row + header_depth, sheet.max_row + 1):
            keys = [sheet.cell(row, col).value for col in key_cols]
            if any(value in (None, "") for value in keys):
                continue
            row_key = tuple(_source_key(value) for value in keys)
            record = records.setdefault(row_key, {})
            for col, field in by_column.items():
                cell = sheet.cell(row, col)
                if cell.value in (None, ""):
                    continue
                previous = record.get(field)
                value = (_source_key(cell.value) if col in key_cols and isinstance(cell.value, str)
                         and _week_period(clean_text(cell.value)) else cell.value)
                if previous is None:
                    record[field] = (value, cell.number_format, cell.data_type, item.path.name, cell)
                else:
                    period = next((part for part in row_key if _week_period(part)), "")
                    labels = tuple(_source_key(label) for label, _ in columns[field])
                    current = (value, cell.number_format, cell.data_type, item.path.name, cell)
                    merged = (_add_boundary_week(previous, current,
                                                 (row_key, field), period, boundary_parts, boundary_reports, coverage)
                              if _quantity_field(labels, cell.number_format) else None)
                    if merged is not None:
                        record[field] = merged
                    elif previous[0] != value:
                        issue = diagnostics.conflict(previous, current, field, row_key)
                        if issue:
                            kind, example = issue
                            conflict_count += 1
                            conflict_kinds[kind] += 1
                            if len(conflicts) < 3:
                                conflicts.append(example)
    diagnostics.flush()
    target = Workbook().active
    target.title = matches[0][1].title
    if first_header > 1:
        _copy_cells(matches[0][1], target, row_end=first_header - 1)
    for col, labels in enumerate(columns.values(), 1):
        for offset, (value, fmt) in enumerate(labels):
            target.cell(first_header + offset, col, value).number_format = fmt
    for row, key in enumerate(sorted(records, key=lambda key: _period_sort("|".join(key))),
                              first_header + header_depth):
        for col, field in enumerate(columns, 1):
            value = records[key].get(field)
            if value is not None:
                cell = target.cell(row, col, value[0])
                cell.number_format, cell.data_type = value[1:3]
    target._source_matches = matches
    target._merge_conflict_count = conflict_count
    target._merge_conflict_examples = conflicts
    target._merge_conflict_kinds = conflict_kinds
    target._boundary_week_merges = list(boundary_reports.values())
    return target


def _merge_option_fee(matches):
    """Align dynamic period/band headers, retaining sparse grouped headers."""
    parts, first_period_row = [], None
    for item, sheet in matches:
        # An amount-band header is not a month such as 26-03.
        def is_band(value):
            text = compact_text(value).replace("元", "")
            if "免费" in text:
                return True
            numbers = re.findall(r"\d+", text)
            return bool(numbers and max(map(int, numbers)) >= 100
                        and re.search(r"[-—–~～至到]|以上|以下", text))
        scored = [(sum(is_band(sheet.cell(row, col).value)
                       for col in range(3, sheet.max_column + 1)), row)
                  for row in range(2, min(sheet.max_row, 15) + 1)]
        score, band_row = max(scored, default=(0, 0))
        if not score:
            raise ValueError(f"多文件合并无法识别金额段表头: {item.path.name} / {sheet.title}")
        period_row = band_row - 1
        if first_period_row is None:
            first_period_row = period_row
        part = Workbook().active
        part.title = sheet.title
        _copy_cells(sheet, part, row_start=period_row)
        part._log_origin = (sheet.title, period_row - 1, 0)
        parts.append((item, part))
    merged = _merge_matrix(parts, 2, 2, forward_rows=(1,), forward_headers=(1,),
                           column_group_row=1, sparse_headers=(1,))
    target = Workbook().active
    target.title = matches[0][1].title
    if first_period_row > 1:
        _copy_cells(matches[0][1], target, row_end=first_period_row - 1)
    _copy_cells(merged, target, row_offset=first_period_row - 1)
    target._source_matches = matches
    target._merge_conflict_count = merged._merge_conflict_count
    target._merge_conflict_examples = merged._merge_conflict_examples
    target._merge_conflict_kinds = getattr(merged, "_merge_conflict_kinds", {})
    target._boundary_week_merges = getattr(merged, "_boundary_week_merges", [])
    return target


def _copy_cells(source, target, row_start=1, row_end=None, col_start=1, col_end=None, row_offset=0, col_offset=0):
    for cells in source.iter_rows(min_row=row_start, max_row=row_end or source.max_row,
                                  min_col=col_start, max_col=col_end or source.max_column):
        for cell in cells:
            if cell.value is not None:
                dest = target.cell(cell.row - row_start + 1 + row_offset,
                                   cell.column - col_start + 1 + col_offset, cell.value)
                dest.number_format, dest.data_type = cell.number_format, cell.data_type


def _merge_partitioned(matches, *, horizontal):
    groups = {}
    for item, sheet in matches:
        if horizontal:
            starts = [col for col in range(1, sheet.max_column + 1) if sheet.cell(1, col).value not in (None, "")]
            limit = sheet.max_column + 1
        else:
            starts = [row for row in range(1, sheet.max_row + 1)
                      if clean_text(sheet.cell(row, 1).value).endswith("退订比例")
                      and all(sheet.cell(row, col).value in (None, "") for col in range(2, sheet.max_column + 1))]
            limit = sheet.max_row + 1
        for start, end in zip(starts, starts[1:] + [limit]):
            title = clean_text(sheet.cell(1, start).value if horizontal else sheet.cell(start, 1).value)
            book = Workbook()
            part = book.active
            part.title = sheet.title
            if horizontal:
                _copy_cells(sheet, part, col_start=start, col_end=end - 1)
                part._log_origin = (sheet.title, 0, start - 1)
            else:
                _copy_cells(sheet, part, row_start=start, row_end=end - 1)
                part._log_origin = (sheet.title, start - 1, 0)
            groups.setdefault(title, []).append((item, part))
    if not groups:
        return None
    book = Workbook()
    target = book.active
    target.title = matches[0][1].title
    offset = 0
    conflict_count, conflict_examples = 0, []
    conflict_kinds = {"同文件重复键": 0, "跨文件冲突": 0}
    boundary_reports = []
    diagnostics = _OverlapDiagnostics({item.path.name: _source_date_range(item) for item, _ in matches})
    for title, parts in groups.items():
        if horizontal:
            first = parts[0][1]
            period_column = next((col for col in range(2, first.max_column + 1)
                                  if re.match(r"^(?:20)?\d{2}(?:WK|[-/.])", clean_text(first.cell(2, col).value), re.I)), None)
            if period_column is None:
                diagnostics.flush()
                return None
            merged = _merge_matrix(parts, 2, period_column - 1,
                                   quantity_columns=title in {"累计锁单", "锁单数量", "订单数量"},
                                   diagnostics=diagnostics, diagnostic_metric=(title,))
            conflict_count += merged._merge_conflict_count
            conflict_examples.extend(merged._merge_conflict_examples[:max(0, 3 - len(conflict_examples))])
            _copy_cells(merged, target, col_offset=offset)
            offset += merged.max_column + 1
        else:
            merged = _merge_matrix(parts, 2, 1, diagnostics=diagnostics, diagnostic_metric=(title,))
            conflict_count += merged._merge_conflict_count
            conflict_examples.extend(merged._merge_conflict_examples[:max(0, 3 - len(conflict_examples))])
            _copy_cells(merged, target, row_offset=offset)
            offset += merged.max_row + 1
        boundary_reports.extend(getattr(merged, "_boundary_week_merges", []))
        for kind, count in getattr(merged, "_merge_conflict_kinds", {}).items():
            conflict_kinds[kind] += count
    target._source_matches = matches
    target._merge_conflict_count = conflict_count
    target._merge_conflict_examples = conflict_examples
    target._merge_conflict_kinds = conflict_kinds
    target._boundary_week_merges = boundary_reports
    diagnostics.flush()
    return target

def merge_source_sheets(matches):
    """Known source layouts share one merged read view, not a copied source file."""
    if len(matches) == 1:
        return matches[0]
    first, sheet = matches[0]
    if "图表" not in sheet.title and all("选配比例" in item.path.name for item, _ in matches):
        return first, _merge_matrix(matches, 1, 3, forward_rows=(1, 2))
    if all("首销期订单节奏" in item.path.name for item, _ in matches):
        return first, _merge_matrix(matches, 2, 1, time_row=2)
    if "小订分时退订" in sheet.title:
        return first, _merge_records(matches, ({"小订日期", "下单日期", "日期"}, {"小订小时", "小时", "时段"}))
    if "日度退订" in sheet.title:
        return first, _merge_records(matches, ({"取消日期", "退订日期", "日期"},))
    if all("订单7级转化" in item.path.name for item, _ in matches):
        return first, _merge_records(matches, ({"周", "月", "周期", "统计周期"},), header_depth=2)
    if all("选配金统计" in item.path.name for item, _ in matches):
        if "排名" in sheet.title:
            return first, _merge_matrix(matches, 2, 2, forward_rows=(1,))
        return first, _merge_option_fee(matches)
    if "选配退订" in sheet.title:
        merged = _merge_partitioned(matches, horizontal=False)
        return (first, merged) if merged is not None else None
    if all("SKU" in item.path.name for item, _ in matches):
        merged = _merge_partitioned(matches, horizontal=True)
        return (first, merged) if merged is not None else None
    return None


class WorkbookView:
    def __init__(self, sheets):
        self.worksheets = list(sheets)
        self.sheetnames = [sheet.title for sheet in self.worksheets]

    def __getitem__(self, name):
        return next(sheet for sheet in self.worksheets if sheet.title == name)

    def close(self):
        pass  # The enclosing store/context owns the physical workbooks.


@dataclass
class WorkbookItem:
    path: Path
    workbook: Any


class WorkbookStore:
    def __init__(self, input_dir: Path):
        self.input_dir = input_dir
        self.items: list[WorkbookItem] = []
        self.chart_assets: dict[str, str] = {}
        self.load_errors: list[str] = []
        self._find_all_cache: dict[str, list[WorkbookItem]] = {}
        self._combined_cache: dict[str, WorkbookItem] = {}
        self._source_aliases: dict[tuple[str, str], list[tuple[WorkbookItem, Any]]] = {}
        self._subject_sheets_cache: dict[tuple[Any, ...], list[tuple[WorkbookItem, Any]]] = {}
        self.multi_source_groups: dict[str, int] = {}
        self._boundary_chart_logs: set[tuple] = set()
        self._chart_conflict_logs: set[tuple] = set()

    def load(self, exclude_names: Iterable[str] = (), *, data_only_view: bool = False) -> None:
        if not self.input_dir.exists():
            raise FileNotFoundError(f"输入目录不存在: {self.input_dir}")
        self._find_all_cache.clear()
        self._combined_cache.clear()
        self._source_aliases.clear()
        self._subject_sheets_cache.clear()
        self.multi_source_groups.clear()
        self._boundary_chart_logs.clear()
        self._chart_conflict_logs.clear()
        excluded = set(exclude_names)
        paths = sorted(path for path in self.input_dir.glob("*.xlsx") if not path.name.startswith("~$") and path.name not in excluded)
        if not paths:
            LOGGER.warning("输入目录中没有找到 .xlsx 文件: %s", self.input_dir)
        for path in paths:
            try:
                workbook = (load_data_workbook(path, self.input_dir / ".cache" / "excel")
                            if data_only_view else load_workbook(path, data_only=True, read_only=False))
                self.items.append(WorkbookItem(path=path, workbook=workbook))
                LOGGER.debug("已读取 Excel: %s（%d 个 Sheet）", path.name, len(workbook.sheetnames))
            except Exception as exc:
                message = f"Excel读取失败: {path.name}: {exc}"
                self.load_errors.append(message)
                LOGGER.exception(message)

    def close(self) -> None:
        for item in self.items:
            item.workbook.close()

    def find(self, keyword: str) -> WorkbookItem | None:
        items = self.find_all(keyword)
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        if keyword in self._combined_cache:
            return self._combined_cache[keyword]
        groups = {}
        for item in items:
            for sheet in item.workbook.worksheets:
                groups.setdefault(compact_text(sheet.title), []).append((item, sheet))
        sheets = []
        conflict_count, conflict_sheets, conflict_examples = 0, 0, []
        conflict_kinds = {"同文件重复键": 0, "跨文件冲突": 0}
        boundary_reports = []
        for matches in groups.values():
            title = matches[0][1].title
            combined = merge_source_sheets(matches)
            if combined is not None:
                sheets.append(combined[1])
                merged = combined[1]
                boundary_reports.extend(getattr(merged, "_boundary_week_merges", []))
                count = getattr(merged, "_merge_conflict_count", 0)
                if count:
                    conflict_count += count
                    for kind, subtotal in getattr(merged, "_merge_conflict_kinds", {}).items():
                        conflict_kinds[kind] += subtotal
                    conflict_sheets += 1
                    for example in getattr(merged, "_merge_conflict_examples", []):
                        if len(conflict_examples) < 3:
                            conflict_examples.append(f"{title}: {example}")
            else:
                # Unknown layouts remain separate; consumers using all matching
                # sheets or the raw centre still see every original.
                sheets.extend(sheet for _, sheet in matches)
            self._source_aliases[(items[0].path.name, title)] = matches
            for source_item, source_sheet in matches:
                self._source_aliases[(source_item.path.name, source_sheet.title)] = matches
                self._source_aliases[(items[0].path.name, source_sheet.title)] = matches
        result = WorkbookItem(items[0].path, WorkbookView(sheets))
        result._source_items = items
        self._combined_cache[keyword] = result
        self.multi_source_groups[keyword] = len(items)
        LOGGER.debug("多文件来源: %s | 共%d个文件全部纳入: %s", keyword, len(items), "、".join(item.path.name for item in items))
        _log_boundary_weeks(f"类别={keyword}", boundary_reports)
        if conflict_count:
            label = "多文件数值冲突" if conflict_kinds["跨文件冲突"] else "同文件重复键冲突"
            LOGGER.debug("[%s汇总] 类别=%s | %d个Sheet共%d项（同文件重复键%d项，跨文件冲突%d项） | 冲突按来源Sheet和指标合并打印 | 示例=%s",
                           label, keyword, conflict_sheets, conflict_count, conflict_kinds["同文件重复键"],
                           conflict_kinds["跨文件冲突"], "；".join(conflict_examples))
        return result

    def expand_sources(self, sources):
        from core.models import SourceRef
        result, seen = [], set()
        for source in sources:
            matches = self._source_aliases.get((source.file, source.sheet))
            candidates = [SourceRef(item.path.name, sheet.title, source.note) for item, sheet in matches] if matches else [source]
            for candidate in candidates:
                key = candidate.file, candidate.sheet, candidate.note
                if key not in seen:
                    seen.add(key)
                    result.append(candidate)
        return result

    def resolve_dashboard_sources(self, dashboard):
        """Keep physical source links valid for merged/secondary-file sheets."""
        seen = set()
        def visit(value):
            if isinstance(value, (dict, list)):
                if id(value) in seen:
                    return
                seen.add(id(value))
            if isinstance(value, dict):
                matches = self._source_aliases.get((value.get("file"), value.get("sheet")))
                if matches:
                    value["file"], value["sheet"] = matches[0][0].path.name, matches[0][1].title
                    if len(matches) > 1:
                        value["source_files"] = list(dict.fromkeys(item.path.name for item, _ in matches))
                matches = self._source_aliases.get((value.get("source_file"), value.get("source_sheet")))
                if matches:
                    value["source_file"] = matches[0][0].path.name
                    if len(matches) > 1:
                        value["source_files"] = list(dict.fromkeys(item.path.name for item, _ in matches))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        dashboard.sources = self.expand_sources(dashboard.sources)
        visit(dashboard.views)
        return dashboard

    def find_all(self, keyword: str) -> list[WorkbookItem]:
        cached = self._find_all_cache.get(keyword)
        if cached is None:
            cached = [item for item in self.items if keyword in item.path.name]
            self._find_all_cache[keyword] = cached
        return cached

    def find_subject_sheet(
        self,
        keyword: str,
        subject: str,
        grain: str | None = None,
        suffix: str | tuple[str, ...] | list[str] | None = None,
        include_charts: bool = False,
    ) -> tuple[WorkbookItem, Any] | None:
        matches = self.find_subject_sheets(keyword, subject, grain, suffix, include_charts)
        return matches[0] if matches else None

    def find_subject_sheets(
        self,
        keyword: str,
        subject: str,
        grain: str | None = None,
        suffix: str | tuple[str, ...] | list[str] | None = None,
        include_charts: bool = False,
    ) -> list[tuple[WorkbookItem, Any]]:
        """Return every matching sheet; callers can retain multiple launch phases."""
        suffixes = () if suffix is None else ((suffix,) if isinstance(suffix, str) else tuple(suffix))
        cache_key = (keyword, compact_text(subject), grain, suffixes, include_charts)
        cached = self._subject_sheets_cache.get(cache_key)
        if cached is not None:
            return cached
        combined = self.find(keyword)
        items = [combined] if combined else []
        if not items:
            return []
        result: list[tuple[WorkbookItem, Any]] = []
        for item in items:
            for sheet in item.workbook.worksheets:
                if not include_charts and "图表" in sheet.title:
                    continue
                sheet_name = sheet_subject(sheet.title)
                if any(marker in keyword for marker in ("首销期订单节奏", "小订退订")):
                    from core.model_identity import generation_records, parent_generation
                    sheet_name = parent_generation(sheet_name, generation_records()) if parent_generation(subject, generation_records()) == subject else sheet_name
                if compact_text(sheet_name) != compact_text(subject):
                    continue
                if grain and grain_from_sheet(sheet.title) != grain:
                    continue
                if suffixes:
                    normalized_title = compact_identifier(sheet.title)
                    if not any(compact_identifier(candidate) in normalized_title for candidate in suffixes):
                        continue
                origins = self._source_aliases.get((item.path.name, sheet.title))
                owner = WorkbookItem(origins[0][0].path, item.workbook) if origins else item
                result.append((owner, sheet))
                LOGGER.debug("Sheet映射: 关键词=%s, 主体=%s -> %s / %s", keyword, subject, item.path.name, sheet.title)
        self._subject_sheets_cache[cache_key] = result
        return result

    def matching_sheet_names(self, keyword: str, subject: str) -> list[str]:
        """Return candidate Sheet names for diagnostics when a module mapping fails."""
        items = self.find_all(keyword)
        target = compact_text(subject)
        return [
            f"{item.path.name} / {sheet.title}"
            for item in items
            for sheet in item.workbook.worksheets
            if compact_text(sheet_subject(sheet.title)) == target
        ]

    def all_sheet_names(self) -> Iterable[tuple[str, str]]:
        for item in self.items:
            for name in item.workbook.sheetnames:
                yield item.path.name, name

    def find_chart_data(
        self, keyword: str, subject: str, grain: str
    ) -> tuple[WorkbookItem, Any, dict[str, Any]] | None:
        """Read the preferred subject block from EVERY matching workbook."""
        self.find(keyword)  # register source aliases and reuse merged read views
        target = compact_text(subject)
        kind = subject_type(subject)
        owner = subject_parent(subject, kind) if kind == "generation" else subject
        found = []
        for item in self.find_all(keyword):
            sheets = [sheet for sheet in item.workbook.worksheets
                      if "图表" in sheet.title and grain_from_sheet(sheet.title) == grain]
            sheets.sort(key=lambda sheet: compact_text(sheet_subject(sheet.title)) != compact_text(owner))
            match = None
            for sheet in sheets:
                for row in range(1, sheet.max_row + 1):
                    if compact_text(sheet.cell(row, 1).value) == target:
                        data = self._parse_chart_block(item, sheet, row, target)
                        if data:
                            match = (item, sheet, data)
                            break
                if match:
                    break
            if match:
                found.append(match)
        if not found:
            return None
        return found[0][0], found[0][1], self._merge_chart_data(found)

    def find_chart_blocks(
        self, keyword: str, subject: str, grain: str
    ) -> tuple[WorkbookItem, Any, list[dict[str, Any]]] | None:
        """Union owner/subject chart blocks and periods across source files."""
        self.find(keyword)
        kind = subject_type(subject)
        owner = subject_parent(subject, kind) if kind == "generation" else subject
        grouped = {}
        for item in self.find_all(keyword):
            for sheet in item.workbook.worksheets:
                if "图表" not in sheet.title or grain_from_sheet(sheet.title) != grain:
                    continue
                if compact_text(sheet_subject(sheet.title)) != compact_text(owner):
                    continue
                for row in range(1, sheet.max_row + 1):
                    name = clean_text(sheet.cell(row, 1).value)
                    if not name or (kind == "generation" and compact_text(name) != compact_text(subject)):
                        continue
                    data = self._parse_chart_block(item, sheet, row, compact_text(name))
                    if data:
                        grouped.setdefault(compact_text(name), []).append((item, sheet, data))
        if grouped:
            first = next(iter(grouped.values()))[0]
            return first[0], first[1], [self._merge_chart_data(matches) for matches in grouped.values()]
        exact = self.find_chart_data(keyword, subject, grain)
        return (exact[0], exact[1], [exact[2]]) if exact else None

    def _merge_chart_data(self, matches):
        public = {key: value for key, value in matches[0][2].items() if not key.startswith("_log_")}
        if len(matches) == 1:
            data = matches[0][2]
            return {**public, "totals": [0 if value is None else value for value in data["totals"]],
                    "series": [{**entry, "values": [0 if value is None else value for value in entry["values"]]}
                               for entry in data["series"]]}
        periods, series, totals = set(), {}, {}
        boundary_parts, boundary_reports, observations, total_sources = {}, {}, {}, {}
        coverage = {item.path.name: _source_date_range(item) for item, _, _ in matches}
        diagnostics = _OverlapDiagnostics(coverage)
        total_points, series_points = {}, {}
        log_key = tuple((str(item.path), sheet.title, data["subject"], data.get("headline", "")) for item, sheet, data in matches)
        emit = log_key not in self._chart_conflict_logs
        rate_conflicts, resolved_rates = [], set()
        for item, sheet, data in matches:
            def point(value, index, name):
                source_row = data.get("_log_rows", {}).get(name)
                source_cols = data.get("_log_columns", [])
                coordinate = f"{get_column_letter(source_cols[index])}{source_row}" if source_row and index < len(source_cols) else "位置未记录"
                cell = SimpleNamespace(value=value, sheet_title=sheet.title, coordinate=coordinate)
                return (value, "", "n", item.path.name, cell)
            for index, raw_period in enumerate(data["periods"]):
                period = _source_key(raw_period)
                periods.add(period)
                value = data["totals"][index]
                boundary = bool(_week_period(period) and _week_period(period)[3])
                if boundary:
                    observations.setdefault(period, {}).setdefault(item.path.name, {
                        "rates": {entry["name"]: entry["values"][index] for entry in data["series"]},
                    })
                if value is not None and period not in totals:
                    totals[period] = value
                    total_sources[period] = item.path.name
                    total_points[period] = point(value, index, "总计")
                elif value is not None:
                    merged = _add_boundary_week((totals[period], "", "n", total_sources[period]),
                                                (value, "", "n", item.path.name), (period, "总量"), period,
                                                boundary_parts, boundary_reports, coverage)
                    if merged is not None:
                        totals[period] = merged[0]
                    elif totals[period] != value and emit:
                        previous = (totals[period], *total_points[period][1:])
                        diagnostics.conflict(previous, point(value, index, "总计"), (data["subject"], "图表总量"), (period,))
                for entry in data["series"]:
                    values = series.setdefault(entry["name"], {})
                    value = entry["values"][index]
                    if value is not None and period not in values:
                        values[period] = value
                        series_points[(entry["name"], period)] = point(value, index, entry["name"])
                    elif value is not None and values[period] != value:
                        if emit:
                            rate_conflicts.append((entry["name"], period, series_points[(entry["name"], period)],
                                                   point(value, index, entry["name"])))
        for (period, _), weights in boundary_parts.items():
            denominator = sum(weight for _, weight in weights)
            if len(weights) < 2 or denominator <= 0:
                continue
            names = {name for source, _ in weights for name in observations[period][source]["rates"]}
            for name in names:
                pieces = [(observations[period][source]["rates"].get(name, 0), weight) for source, weight in weights]
                if any(weight > 0 and (rate is None or not math.isfinite(rate)) for rate, weight in pieces):
                    continue
                series.setdefault(name, {})[period] = sum(rate * weight for rate, weight in pieces if weight > 0) / denominator
                resolved_rates.add((name, period))
        for name, period, previous, current in rate_conflicts:
            accepted_sources = {source for source, _ in boundary_parts.get((period, "总量"), [])}
            if (name, period) not in resolved_rates or not {previous[3], current[3]} <= accepted_sources:
                diagnostics.conflict(previous, current, (matches[0][2]["subject"], name, "图表占比"), (period,),
                                     nonadditive=True, metric=(matches[0][2]["subject"], "图表占比"))
        diagnostics.flush()
        if boundary_reports and log_key not in self._boundary_chart_logs:
            _log_boundary_weeks(f"图表主体={matches[0][2]['subject']}", list(boundary_reports.values()))
            self._boundary_chart_logs.add(log_key)
        order = sorted(periods, key=_period_sort)
        self._chart_conflict_logs.add(log_key)
        return {**public, "periods": order,
                "totals": [totals.get(period, 0) for period in order],
                "series": [{"name": name, "values": [values.get(period, 0) for period in order]}
                           for name, values in series.items()],
                "image_key": None}

    def _parse_chart_block(
        self, item: WorkbookItem, sheet: Any, row: int, target: str
    ) -> dict[str, Any] | None:
        header_row = row + 1
        columns: list[int] = []
        periods: list[str] = []
        period_label = _daily_period if grain_from_sheet(sheet.title) == "day" else display_period
        for col in range(3, sheet.max_column + 1):
            cell = sheet.cell(header_row, col)
            value = period_label(cell.value, cell.number_format)
            if _week_period(value):
                value = _source_key(value)
            if not value or value == "总计":
                continue
            columns.append(col)
            periods.append(value)
        if not columns:
            return None
        series = []
        log_rows = {}
        # Missing cells must remain missing until cross-file fallback finishes.
        totals = [None] * len(columns)
        for data_row in range(header_row + 1, sheet.max_row + 1):
            label = clean_text(sheet.cell(data_row, 2).value)
            next_subject = clean_text(sheet.cell(data_row, 1).value)
            if next_subject:
                break
            if not label:
                if series:
                    break
                continue
            if label == "总计":
                log_rows[label] = data_row
                totals = [cell_number(sheet.cell(data_row, col))
                          if sheet.cell(data_row, col).value not in (None, "") else None for col in columns]
                break
            values = [cell_number(sheet.cell(data_row, col), rate=True)
                      if sheet.cell(data_row, col).value not in (None, "") else None for col in columns]
            series.append({"name": label, "values": values})
            log_rows[label] = data_row
        if not series:
            return None
        block_subject = clean_text(sheet.cell(row, 1).value)
        image_key = self._extract_chart_image(item, sheet, row, compact_text(target))
        return {
            "subject": block_subject,
            "headline": clean_text(sheet.cell(header_row, 2).value),
            "periods": periods,
            "series": series,
            "totals": totals,
            "image_key": image_key,
            "_log_rows": log_rows,
            "_log_columns": columns,
        }

    def _extract_chart_image(self, item: WorkbookItem, sheet: Any, subject_row: int, target: str) -> str | None:
        """Extract the image embedded in a subject block once and keep it as a shared HTML asset."""
        asset_key = f"{item.path.name}|{sheet.title}|{target}"
        if asset_key in self.chart_assets:
            return asset_key
        next_subject_row = None
        for row in range(subject_row + 1, sheet.max_row + 1):
            if clean_text(sheet.cell(row, 1).value):
                next_subject_row = row
                break

        if next_subject_row is None:
            # The final subject has no real lower boundary. Infer one from the
            # preceding block spacing instead of relying on sheet.max_row: Excel
            # images may be anchored one or more rows below the last data cell.
            subject_rows = [
                row for row in range(1, subject_row + 1)
                if clean_text(sheet.cell(row, 1).value)
            ]
            spacings = [
                later - earlier
                for earlier, later in zip(subject_rows, subject_rows[1:])
                if later > earlier
            ]
            if spacings:
                block_span = max(1, int(round(median(spacings))))
            else:
                # A single-block sheet still gets a finite search window. Cover
                # its existing cells plus the immediately following anchor row.
                block_span = max(30, sheet.max_row - subject_row + 2)
            next_subject_row = subject_row + block_span

        images = sorted(
            getattr(sheet, "_images", []),
            key=lambda image: getattr(getattr(getattr(image, "anchor", None), "_from", None), "row", -1),
        )
        for image in images:
            anchor = getattr(image, "anchor", None)
            marker = getattr(anchor, "_from", None)
            image_row = getattr(marker, "row", -1) + 1
            if not subject_row <= image_row < next_subject_row:
                continue
            try:
                image_format = clean_text(getattr(image, "format", "png")).lower() or "png"
                mime = "jpeg" if image_format in {"jpg", "jpeg"} else image_format
                encoded = base64.b64encode(image._data()).decode("ascii")
                self.chart_assets[asset_key] = f"data:image/{mime};base64,{encoded}"
                return asset_key
            except (OSError, ValueError, AttributeError):
                return None
        return None


_METRIC_SHEET_CACHE: "weakref.WeakKeyDictionary[Any, dict[str, dict[str, Any]]]" = weakref.WeakKeyDictionary()


def parse_metric_sheet(sheet: Any) -> dict[str, dict[str, Any]]:
    """Parse one metric sheet once per build.

    Dashboard modules only read the returned structure.  Caching by Worksheet
    identity avoids reparsing the same order/lock sheet for every subject and
    every period while allowing closed workbooks to be garbage-collected.
    """
    cached = _METRIC_SHEET_CACHE.get(sheet)
    if cached is not None:
        return cached
    period_label = _daily_period if grain_from_sheet(sheet.title) == "day" else display_period
    headers = [period_label(sheet.cell(1, col).value, sheet.cell(1, col).number_format) for col in range(4, sheet.max_column + 1)]
    # File-level total/rolling aggregates are not shared calendar observations.
    # Keep originals in the raw-table center, but never use these for forecasts,
    # dashboard metrics, or multi-file duplicate conflicts.
    headers = ["" if re.fullmatch(r"(?:总计|合计|汇总|累计|近\d+(?:天|日|周|月))", clean_text(header))
               else header for header in headers]
    periods = [header for header in headers if header]
    result = {period: {"metrics": {}, "structures": {}} for period in periods}
    current_metric = ""
    current_stat = ""
    for row in range(2, sheet.max_row + 1):
        metric = clean_text(sheet.cell(row, 1).value)
        stat = clean_text(sheet.cell(row, 2).value)
        category = clean_text(sheet.cell(row, 3).value)
        if metric:
            current_metric = metric
        if stat:
            current_stat = stat
        if not current_metric or not category:
            continue
        for offset, period in enumerate(headers, start=4):
            if period not in result:
                continue
            cell = sheet.cell(row, offset)
            if current_stat == "数量" and category == "数量":
                result[period]["metrics"][current_metric] = cell_number(cell)
            elif current_stat == "占比":
                result[period]["structures"].setdefault(current_metric, []).append(
                    {"label": category, "share": cell_number(cell, rate=True), "count": None}
                )
            elif current_stat == "数量":
                rows = result[period]["structures"].setdefault(current_metric, [])
                target = next((entry for entry in rows if entry["label"] == category), None)
                if target:
                    target["count"] = cell_number(cell)
    _METRIC_SHEET_CACHE[sheet] = result
    return result

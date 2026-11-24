"""Display source-cell text, dates and number formats for order workbooks."""
import re
from datetime import date, datetime
from typing import Any

from openpyxl.styles.numbers import is_date_format


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u2011", "-")).strip()


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

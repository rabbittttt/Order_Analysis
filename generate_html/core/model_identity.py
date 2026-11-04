from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.data_paths import orders_input_directory


CODE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = CODE_ROOT.parent if CODE_ROOT.name.lower() == "scripts" else CODE_ROOT
STAGE_SOURCE_PATH = orders_input_directory(PROJECT_ROOT) / "小订及首销数据整理.xlsx"


_REMOVABLE_WORDS = re.compile(r"鸿蒙智行|车型|款|总计|汇总|合计", re.I)
_SEPARATORS = re.compile(r"[\s()（）/\\_\-&]+")


def model_key(value: Any) -> str:
    """Return a brand-preserving identity key for propagation and generation names.

    Brand names are deliberately retained.  Removing them makes similarly named
    vehicles from different brands indistinguishable and can bind the wrong data.
    """

    text = str(value or "").strip().lower().replace("（", "(").replace("）", ")")
    text = _REMOVABLE_WORDS.sub("", text)
    return _SEPARATORS.sub("", text)


def stage_name(record: dict) -> str:
    """Identity of a reservation/launch campaign; the parent is never its alias."""
    return str(record.get("二级代际名") or record.get("代际名") or record.get("车型") or record.get("历史传播名") or "").strip()


def stage_records(path) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    stat = source.stat()
    return _stage_records(str(source.resolve()), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _stage_records(path, stamp, size):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        headers = [str(v or "").strip() for v in next(rows, ())]
        if "代际名" not in headers:
            return []  # Legacy mappings have a separate compatibility reader.
        records = []
        for values in rows:
            record = dict(zip(headers, values))
            # Explicit small-order synonym only; never borrow a launch period.
            if "小订发布时段" not in headers and "小订发布时间" in headers:
                record["小订发布时段"] = record.get("小订发布时间")
            primary = str(record.get("代际名") or "").strip()
            if not primary:
                continue
            secondary = str(record.get("二级代际名") or "").strip()
            record.update({"代际名": primary, "二级代际名": secondary,
                           "历史传播名": secondary or primary,
                           "订单分析代际名": secondary or primary,
                           "primary_generation": primary, "secondary_generation": secondary})
            record.setdefault("品牌", primary.split(" ", 1)[0])
            records.append(record)
        return records
    finally:
        book.close()


def parent_generation(name, records) -> str:
    key = model_key(name)
    found = next((r for r in records if r.get("二级代际名") and model_key(r["二级代际名"]) == key), None)
    return str(found["代际名"]) if found else str(name or "")


def stage_label(name, parent) -> str:
    text = str(name or "").strip()
    if text.startswith(str(parent)):
        return text[len(str(parent)):].strip() or ""
    return text


def generation_records() -> list[dict]:
    return stage_records(STAGE_SOURCE_PATH)

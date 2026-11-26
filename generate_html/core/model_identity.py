from __future__ import annotations

import re
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.data_paths import PROJECT_ROOT, orders_input_directory, workbench_root, shared_data_root


STAGE_SOURCE_NAME = "小订及首销数据整理.xlsx"
STAGE_SOURCE_PATH = orders_input_directory(PROJECT_ROOT) / STAGE_SOURCE_NAME


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
    if Path(path).suffix.lower() == ".json":
        edition = json.loads(Path(path).read_text(encoding="utf-8"))
        if edition.get("schemaVersion") != 1 or not edition.get("revision"):
            raise ValueError("小订与首销发布数据的版本无效")
        summary = next((s for s in edition["sheets"] if s["name"] == "车型汇总"), None)
        if not summary or not summary["rows"] or "代际名" not in summary["rows"][0]:
            raise ValueError("小订与首销发布数据缺少车型汇总")
        records = _campaign_rows(iter(summary["rows"]))
        for record in records:
            for field in ("留资", "小订开始日期", "小订结束日期", "开始大定日期", "首销结束日期"):
                value = record.get(field)
                if isinstance(value, str) and value:
                    record[field] = datetime.fromisoformat(value)
        return records
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        return _campaign_rows(book.worksheets[0].iter_rows(values_only=True))
    finally:
        book.close()


def _campaign_rows(rows):
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


def aggregate_members(name: str) -> list[str]:
    clean = re.sub(r"(?:汇总|总计)$", "", name.strip()).strip()
    match = re.fullmatch(r"(\S+?界)\s*(.+?)(?:\s*(20\d{2}\s*款))?", clean)
    if not match:
        return []
    brand, models, year = match.groups()
    # Older exports used project codes for the same pairs.
    legacy = {("问界", "F2N"): "M9&M9U", ("尊界", "X6M"): "V680&V800",
              ("尚界", "SHB"): "Z7&Z7T", ("享界", "X4"): "S9&S9T"}
    pair = legacy.get((brand, models), models).split("&")
    if len(pair) != 2 or not all(part.strip() for part in pair):
        return []
    members = []
    for part in pair:
        model = part.strip()
        if brand == "问界" and model == "M9U":
            model = "M9 Ultimate"
        members.append(" ".join(filter(None, (brand, model, year))))
    return members


def parent_generation(name, records) -> str:
    key = model_key(name)
    found = next((r for r in records if r.get("二级代际名") and model_key(r["二级代际名"]) == key), None)
    return str(found["代际名"]) if found else str(name or "")


def stage_label(name, parent) -> str:
    text = str(name or "").strip()
    if text.startswith(str(parent)):
        return text[len(str(parent)):].strip() or ""
    return text


PINNED_CAMPAIGN = "小订首销发布.json"


def campaign_snapshot(input_dir: Path) -> Path | None:
    directory = Path(input_dir).resolve()
    if directory == (shared_data_root(PROJECT_ROOT) / "订单汇总").resolve():
        override = os.environ.get("VEHICLE_CONFIG_CAMPAIGN_SNAPSHOT", "").strip()
        if override:
            current = (PROJECT_ROOT / override).resolve()
            if not current.is_file():
                raise FileNotFoundError(f"指定的小订与首销发布数据不存在：{current}")
            return current
        folder = workbench_root(PROJECT_ROOT) / "database/vehicle-config/campaigns"
        current = folder / "published.json"
        if current.is_file():
            return current
        database = folder / "campaigns.sqlite3"
        if database.is_file():
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                latest = db.execute("SELECT MAX(revision) FROM publications").fetchone()[0]
            if latest:
                raise FileNotFoundError("已切换到网页发布数据，请恢复缺失的 published.json")
        return None
    pinned = directory / PINNED_CAMPAIGN
    return pinned if pinned.is_file() else None


def generation_records(input_dir: Path | None = None) -> list[dict]:
    path = STAGE_SOURCE_PATH if input_dir is None else input_dir / STAGE_SOURCE_NAME
    return stage_records(campaign_snapshot(path.parent) or path)

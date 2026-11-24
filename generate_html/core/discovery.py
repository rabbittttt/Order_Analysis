from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Iterable

from core.excel import WorkbookStore, clean_text, compact_text, sheet_subject, subject_parent, subject_type
from core.models import Subject
from core.model_identity import aggregate_members, generation_records, model_key, parent_generation, stage_name
from core.excel import parse_metric_sheet, is_aggregate_generation


DEFAULT_MODULE_ORDER = [
    "overview", "channel_analysis", "cancellation", "launch_rhythm", "conversion", "order_mix",
    "lock_mix", "small_order_mix", "option_fee", "sku", "generic", "raw",
]
# 保留旧导入名作为只读兼容别名；运行时排序仍以 config.json 为唯一来源。
MODULE_ORDER = DEFAULT_MODULE_ORDER

# 品牌业务优先级顺序；未列入的新品牌自动排到最后
BRAND_ORDER = ["问界", "智界", "享界", "尊界", "尚界"]


def subject_id(name: str, kind: str) -> str:
    digest = hashlib.sha1(compact_text(name).encode("utf-8")).hexdigest()[:10]
    return f"{kind}_{digest}"


def is_valid_subject_name(name: str) -> bool:
    """Keep metric labels such as '尊界交车锁单' out of the subject selector."""
    value = compact_text(name)
    if value == "鸿蒙智行":
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{1,3}界", value):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff]{1,3}界.+20\d{2}款(?:总计|汇总|合计)?", value, flags=re.IGNORECASE):
        return True
    # 代号型代际（无款号），含组合代号或版本名；中文指标名仍须排除。
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{1,3}界[A-Za-z0-9]+(?:[&+/][A-Za-z0-9]+)*(?:[\u4e00-\u9fff]{1,8})?", value))


def _has_lock_orders(store, name):
    for grain in ("day", "week", "month"):
        found = store.find_subject_sheet("锁单选配比例", name, grain)
        if found and any(row["metrics"].get("交车锁单", 0) > 0 for row in parse_metric_sheet(found[1]).values()):
            return True
    return False


def catalog_subjects(store, subjects):
    records = generation_records(store.input_dir)
    result = []
    for subject in subjects:
        item = subject.to_dict()
        if subject.type == "generation":
            item["is_aggregate"] = is_aggregate_generation(subject.name)
            item["has_lock_orders"] = _has_lock_orders(store, subject.name)
        names = {model_key(name) for name in [subject.name, *aggregate_members(subject.name)]}
        events = set()
        for row in records:
            if subject.type == "brand" and subject.name != row.get("品牌"):
                continue
            if subject.type == "generation" and model_key(row["代际名"]) not in names:
                continue
            for field, label in (("小订开始日期", "小订开始"), ("开始大定日期", "大定开始")):
                value = row.get(field)
                if isinstance(value, datetime):
                    value = value.date()
                elif not isinstance(value, date):
                    try:
                        value = date.fromisoformat(str(value).strip().split(" ")[0].replace("/", "-"))
                    except ValueError:
                        continue
                events.add((value.isoformat(), f"{stage_name(row)} {label}"))
        item["stage_annotations"] = [{"date": day, "text": text} for day, text in sorted(events)]
        result.append(item)
    return result


def discover_subjects(store: WorkbookStore) -> list[Subject]:
    names: dict[str, str] = {"鸿蒙智行": "鸿蒙智行"}
    records = generation_records(store.input_dir)
    for _, sheet_name in store.all_sheet_names():
        subject = parent_generation(sheet_subject(sheet_name), records)
        if subject and "图表" not in subject and subject not in {"Sheet1", "汇总"} and is_valid_subject_name(subject):
            clean = clean_text(subject)
            key = compact_text(clean)
            if key not in names or (" " in clean and " " not in names[key]):
                names[key] = clean
    for item in store.items:
        for sheet in item.workbook.worksheets:
            if "图表" not in sheet.title:
                continue
            for row in range(1, sheet.max_row + 1):
                value = clean_text(parent_generation(sheet.cell(row, 1).value, records))
                if value and is_valid_subject_name(value):
                    key = compact_text(value)
                    if key not in names or (" " in value and " " not in names[key]):
                        names[key] = value

    subjects = []
    for name in names.values():
        kind = subject_type(name)
        subjects.append(Subject(subject_id(name, kind), name, kind, subject_parent(name, kind)))
    rank = {"group": 0, "brand": 1, "generation": 2}

    def sort_key(item: Subject) -> tuple:
        brand = item.name if item.type == "brand" else (item.parent or "")
        brand_index = BRAND_ORDER.index(brand) if brand in BRAND_ORDER else len(BRAND_ORDER)
        return (rank[item.type], brand_index, compact_text(item.name))

    return sorted(subjects, key=sort_key)


def set_capabilities(
    subjects: Iterable[Subject],
    available: dict[str, set[str]],
    module_order: Iterable[str] | None = None,
) -> None:
    order = list(module_order or DEFAULT_MODULE_ORDER)
    if "raw" not in order:
        order.append("raw")
    for subject in subjects:
        modules = available.get(compact_text(subject.name), set())
        subject.modules = [module for module in order if module in modules or module == "raw"]

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any


from core.excel import WorkbookStore, compact_text, sheet_subject
from core.models import Subject


LOGGER = logging.getLogger(__name__)
KNOWN_FILES = (
    ("SKU收敛度", "SKU收敛"),
    ("大定选配比例", "大定选配"),
    ("小订选配比例", "小订选配"),
    ("小订退订", "小订节奏"),
    ("订单7级转化", "订单7级转化"),
    ("选配金统计", "选配金"),
    ("锁单选配比例", "锁单选配"),
    ("首销期订单节奏", "首销节奏"),
)


def log_import_issues(store: WorkbookStore, subjects: list[Subject], dashboards: dict) -> None:
    """Log unmapped source sheets after every business board has declared its sources."""
    subjects_by_name = {compact_text(subject.name): subject for subject in subjects}
    used = {
        (board["subject_id"], source.get("file"), source.get("sheet"))
        for board in dashboards.values()
        for source in board.get("sources", [])
    }
    for item in store.items:
        filename = item.path.name
        module = next((label for keyword, label in KNOWN_FILES if keyword in filename), None)
        issues = defaultdict(list)
        for sheet in item.workbook.worksheets:
            subject = subjects_by_name.get(compact_text(sheet_subject(sheet.title)))
            if subject is None or (subject.id, filename, sheet.title) in used:
                continue
            if module is None:
                LOGGER.warning("[映射诊断] 主体=%s | 文件=%s | Sheet=%s | 状态=未识别到专属看板映射",
                               subject.name, filename, sheet.title)
                continue
            if "图表" in sheet.title:
                continue
            # Inspect populated cells only, preserving the previous 80-row diagnostic window.
            numeric = sum(1 for cell in sheet._cells.values() if cell.row <= 80
                          and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool))
            rows, cols = sheet.max_row, sheet.max_column
            if numeric == 0:
                status = "无数值数据"
            elif rows <= 2:
                status = "疑似仅包含表头"
            else:
                status = "尚未被看板使用"
            issues[subject.name, status, rows, cols, numeric].append(sheet.title)
        for (name, status, rows, cols, numeric), sheets in issues.items():
            LOGGER.warning(
                "[数据诊断] 主体=%s | 识别模块=%s | 文件=%s | Sheet=%s | 状态=%s | 规模=%d行×%d列 | "
                "前80行数值单元格=%d | 涉及%d个Sheet",
                name, module, filename, "、".join(sheets), status, rows, cols, numeric, len(sheets),
            )


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    subjects = manifest.get("subjects", [])
    if not subjects:
        warnings.append("未识别到任何分析主体")
    subject_ids = {subject["id"] for subject in subjects}
    subject_names = {subject["id"]: subject.get("name") or subject["id"] for subject in subjects}
    module_labels = manifest.get("config", {}).get("module_labels", {})
    source_issues = {}
    for key, dashboard in manifest.get("dashboards", {}).items():
        if dashboard.get("subject_id") not in subject_ids:
            warnings.append(f"看板主体不存在: {key}")
        seen = set()
        def invalid(value):
            if isinstance(value, str):
                return "NaN" in value or "undefined" in value
            if isinstance(value, float):
                return not math.isfinite(value)
            if isinstance(value, (dict, list)):
                if id(value) in seen:
                    return False
                seen.add(id(value))
                if isinstance(value, dict):
                    return any(invalid(k) or invalid(v) for k, v in value.items())
                return any(invalid(v) for v in value)
            return False
        if invalid(dashboard):
            warnings.append(f"看板包含无效值: {key}")
        for source in dashboard.get("sources", []):
            if not source.get("file") or not source.get("sheet"):
                name = subject_names.get(dashboard.get("subject_id"), key.split('|')[0])
                module = dashboard.get("module_id") or key.partition('|')[2]
                missing = "、".join(field for field in ("file", "sheet") if not source.get(field))
                source_issues.setdefault(("来源信息不完整", module, f"看板整体，缺{missing}"), set()).add(name)
        for grain, view in dashboard.get("views", {}).items():
            for period, page in view.get("pages", {}).items():
                for index, panel in enumerate(page.get("sections", []), start=1):
                    source = panel.get("source") or {}
                    if not source.get("file") or not source.get("sheet"):
                        name = subject_names.get(dashboard.get("subject_id"), key.split('|')[0])
                        module = dashboard.get("module_id") or key.partition('|')[2]
                        location = f"{grain}/{period}/第{index}块"
                        title = panel.get("title")
                        if title:
                            location += f"（{title}）"
                        missing = "、".join(field for field in ("file", "sheet") if not source.get(field))
                        source_issues.setdefault(("看板来源信息不完整", module, f"{location}，缺{missing}"), set()).add(name)
    for (label, module, location), names in source_issues.items():
        warnings.append(f"{label}: 主体={'、'.join(sorted(names))} | 模块={module_labels.get(module, module)} | 位置={location} | 影响=来源追溯受限，需修正生成来源信息")
    return warnings

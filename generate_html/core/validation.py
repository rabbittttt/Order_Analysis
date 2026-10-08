from __future__ import annotations

import math
from typing import Any


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

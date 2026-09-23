from __future__ import annotations

import json
from typing import Any


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    subjects = manifest.get("subjects", [])
    if not subjects:
        warnings.append("未识别到任何分析主体")
    subject_ids = {subject["id"] for subject in subjects}
    for key, dashboard in manifest.get("dashboards", {}).items():
        if dashboard.get("subject_id") not in subject_ids:
            warnings.append(f"看板主体不存在: {key}")
        text = json.dumps(dashboard, ensure_ascii=False)
        if "NaN" in text or "undefined" in text:
            warnings.append(f"看板包含无效值: {key}")
        for source in dashboard.get("sources", []):
            if not source.get("file") or not source.get("sheet"):
                warnings.append(f"来源信息不完整: {key}")
        for grain, view in dashboard.get("views", {}).items():
            for period, page in view.get("pages", {}).items():
                for index, panel in enumerate(page.get("sections", []), start=1):
                    source = panel.get("source") or {}
                    if not source.get("file") or not source.get("sheet"):
                        warnings.append(f"看板来源信息不完整: {key}/{grain}/{period}/第{index}块")
    return warnings

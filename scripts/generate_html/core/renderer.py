from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from typing import Any


def b64gzip(text: str) -> str:
    """压缩 JSON 文本为 base64,供前端 DecompressionStream 解压。"""
    return base64.b64encode(gzip.compress(text.encode("utf-8"), compresslevel=9)).decode("ascii")


def render_dashboard(manifest: dict[str, Any], template_dir: Path, output_file: Path) -> None:
    html = (template_dir / "dashboard.html").read_text(encoding="utf-8")
    css = (template_dir / "dashboard.css").read_text(encoding="utf-8")
    forecast_math = (template_dir / "forecast-math.js").read_text(encoding="utf-8")
    forecast_import = (template_dir / "forecast-import.js").read_text(encoding="utf-8")
    javascript = f"{forecast_import}\n{forecast_math}\n{(template_dir / 'dashboard.js').read_text(encoding='utf-8')}"
    logo_path = template_dir / "brand-logo.png"
    logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    # 主数据(主体/配置/底表元信息)整体压缩;看板按主体|模块分块压缩、底表行数据按表分块压缩,前端按需解压
    raw_blocks = manifest.get("raw_blocks", {})
    dashboard_blocks = {
        key: b64gzip(json.dumps(board, ensure_ascii=False, separators=(",", ":")))
        for key, board in manifest.get("dashboards", {}).items()
    }
    main_manifest = {
        key: value for key, value in manifest.items()
        if key not in ("raw_blocks", "dashboards")
    }
    main_manifest["dashboard_blocks"] = dashboard_blocks
    main_payload = b64gzip(json.dumps(main_manifest, ensure_ascii=False, separators=(",", ":")))
    raw_payload = json.dumps(raw_blocks, ensure_ascii=False, separators=(",", ":"))
    html = html.replace("__DASHBOARD_CSS__", css)
    html = html.replace("__DASHBOARD_DATA__", main_payload)
    html = html.replace("__DASHBOARD_RAW__", raw_payload)
    html = html.replace("__DASHBOARD_JS__", javascript)
    html = html.replace("__BRAND_LOGO__", f"data:image/png;base64,{logo_data}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")

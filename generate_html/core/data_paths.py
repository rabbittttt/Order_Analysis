"""Locate shared Excel inputs without mixing them with a project's old copies."""

from __future__ import annotations

import os
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = CODE_ROOT.parent if CODE_ROOT.name.lower() == "scripts" else CODE_ROOT


def shared_data_root(project_root: Path = PROJECT_ROOT) -> Path | None:
    """Resolve explicit relative roots from the project, not the shell cwd."""
    configured = os.environ.get("SHARED_DATA_ROOT", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return (candidate if candidate.is_absolute() else project_root / candidate).resolve()
    base = (project_root / os.environ["PLANHUB_DATA_ROOT"]).resolve() if os.environ.get("PLANHUB_DATA_ROOT") else project_root.parent / "工作台数据"
    return base / "shared"


def orders_input_directory(project_root: Path = PROJECT_ROOT) -> Path:
    configured = os.environ.get("ORDER_DASHBOARD_INPUT", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return (candidate if candidate.is_absolute() else project_root / candidate).resolve()
    return shared_data_root(project_root) / "订单汇总"


def persistent_directory(root):
    root = Path(root).resolve()
    value = os.environ.get("PLANHUB_DATA_ROOT", "").strip()
    base = (root / value).resolve() if value else root.parent / "工作台数据"
    destination = base / "database" / "orderiq"
    if not destination.exists() and (root / "data" / "order_dashboard" / "annotations.sqlite3").exists():
        raise RuntimeError("旧持久数据尚未迁移，请先停止服务并运行门户的数据迁移工具；不会创建空库。")
    return destination

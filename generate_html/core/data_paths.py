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
    candidate = project_root.parent / "共享数据"
    return candidate if candidate.is_dir() else None


def orders_input_directory(project_root: Path = PROJECT_ROOT) -> Path:
    configured = os.environ.get("ORDER_DASHBOARD_INPUT", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return (candidate if candidate.is_absolute() else project_root / candidate).resolve()
    # Only an explicit shared-data override may redirect the order input.
    if os.environ.get("SHARED_DATA_ROOT", "").strip():
        return shared_data_root(project_root) / "订单汇总"
    return project_root / "output_file"

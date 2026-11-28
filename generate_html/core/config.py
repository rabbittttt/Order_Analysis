from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


DISPLAY_CONFIG_KEYS = frozenset({"title", "module_order", "module_labels", "grain_labels"})


def apply_display_config(
    catalog: dict, config: dict, *, has_dashboard: Callable[[str, str], bool] | None = None,
) -> dict:
    """Use the current UI settings while keeping this batch's data and generation time."""
    original = catalog.get("config", {})
    display = {key: config[key] for key in DISPLAY_CONFIG_KEYS if key in config}
    result = {**catalog, "config": {**original, **display}}
    if "title" in display:
        result["meta"] = {**catalog.get("meta", {}), "title": display["title"]}
    order = display.get("module_order")
    if order is None or order == original.get("module_order"):
        return result

    # Original catalogs only listed boards visible in the navigation when published.
    # If a previously hidden module is restored, check for its existing payload.
    restored = set(order).difference(original.get("module_order", []), {"raw"})
    subjects = []
    for subject in catalog.get("subjects", []):
        available = set(subject.get("modules", []))
        if has_dashboard:
            available.update(module for module in restored - available if has_dashboard(subject["id"], module))
        ordered = [module for module in order if module in available]
        if "raw" in available and "raw" not in order:
            ordered.append("raw")
        subjects.append({**subject, "modules": ordered})
    return {**result, "subjects": subjects}


def strip_json_comments(text: str) -> str:
    """Remove // line comments and /* block */ comments outside of strings."""
    output: list[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if in_string:
            output.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if char == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        output.append(char)
        i += 1
    return "".join(output)


def load_config(path: Path) -> dict[str, Any]:
    """Load a JSON config file, allowing // and /* */ comments."""
    return json.loads(strip_json_comments(path.read_text(encoding="utf-8")))

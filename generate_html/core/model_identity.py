from __future__ import annotations

import re
from typing import Any


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


def usable_attribute(value: Any, default: str = "未维护") -> str:
    """Normalize blank and placeholder master-data attributes for the UI."""

    text = str(value or "").strip()
    return default if text in {"", "待维护", "未维护"} else text

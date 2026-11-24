"""Identify source deployments without attributing local edits to a clean commit."""
import json
from pathlib import Path
import re
import subprocess


def source_commit(root: Path) -> str | None:
    release = root / "release-info.json"
    try:
        if release.is_file():
            sha = json.loads(release.read_text(encoding="utf-8")).get("commit")
        else:
            if not (root.parent / ".git").exists():
                return None
            def git(*args):
                return subprocess.check_output(
                    ["git", "--no-optional-locks", "-C", str(root), *args],
                    text=True, stderr=subprocess.DEVNULL, timeout=3,
                ).strip()
            if git("status", "--porcelain", "--", "."):
                return None
            sha = git("rev-parse", "HEAD")
        return sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40,64}", sha) else None
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None

"""Validate intranet group membership against aliases supported by the order dashboard."""
import argparse
import ast
from pathlib import Path

from core.model_identity import aggregate_members, model_key


def check(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    values = [n.value for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))
              and any(isinstance(t, ast.Name) and t.id == "MERGE_GROUPS"
                      for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
    if len(values) != 1 or not isinstance(values[0], ast.Dict):
        raise ValueError("需要唯一的 MERGE_GROUPS 字典")
    checked = 0
    for key, value in zip(values[0].keys, values[0].values):
        name, members = ast.literal_eval(key), ast.literal_eval(value)
        expected = aggregate_members(name)
        if expected:
            if {model_key(m) for m in members} != {model_key(m) for m in expected}:
                raise ValueError(f"代际成员与看板规则不一致：{name}")
            checked += 1
    return checked


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    print("已对照分组数", check(parser.parse_args().config))

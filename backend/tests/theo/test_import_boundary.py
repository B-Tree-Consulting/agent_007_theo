"""Theo sample code must not import the host package."""

from __future__ import annotations

import ast
from pathlib import Path


def test_theo_does_not_import_host() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "theo"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "src.host" or name.startswith("src.host.") for name in names):
                offenders.append(str(path))
    assert offenders == []

"""Hash helpers for bfa_case_policy_parity contract vendor and integrity tests."""

from __future__ import annotations

import hashlib
from pathlib import Path


def _sorted_payload_files(root: Path) -> list[Path]:
    files: list[Path] = []
    vectors_dir = root / "vectors"
    expected_dir = root / "fixtures" / "expected"
    if vectors_dir.is_dir():
        files.extend(sorted(vectors_dir.glob("*.json")))
    if expected_dir.is_dir():
        files.extend(sorted(expected_dir.glob("*.json")))
    schema = root / "semantic_schema.json"
    if schema.is_file():
        files.append(schema)
    return files


def compute_payload_sha256(root: Path) -> str:
    """SHA256 over sorted path\\nbytes\\n for contract payload files."""
    digest = hashlib.sha256()
    for path in _sorted_payload_files(root):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\n")
        digest.update(data)
        digest.update(b"\n")
    return digest.hexdigest()

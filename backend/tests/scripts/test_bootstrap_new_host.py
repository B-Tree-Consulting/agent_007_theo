"""Fail-closed and happy-path tests for bootstrap-new-host.sh."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import subprocess_env_without_coverage

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "bootstrap-new-host.sh"


def _run(args: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    merged = subprocess_env_without_coverage()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        cwd=str(cwd or _REPO_ROOT),
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def test_script_exists() -> None:
    assert _SCRIPT.is_file()


def test_non_interactive_requires_flags() -> None:
    result = _run(["--non-interactive"])
    assert result.returncode == 1
    assert "--target" in result.stderr
    assert "--repo-name" in result.stderr
    assert "--service-slug" in result.stderr


def test_non_interactive_rejects_invalid_slug(tmp_path: Path) -> None:
    result = _run(
        [
            "--non-interactive",
            "--target",
            str(tmp_path / "out"),
            "--repo-name",
            "b-tree-example-bfa",
            "--service-slug",
            "NOT_A_SLUG",
        ]
    )
    assert result.returncode == 1
    assert "Invalid slug" in result.stderr


def test_non_interactive_rejects_invalid_repo_name(tmp_path: Path) -> None:
    result = _run(
        [
            "--non-interactive",
            "--target",
            str(tmp_path / "out"),
            "--repo-name",
            "has space",
            "--service-slug",
            "example-bfa",
        ]
    )
    assert result.returncode == 1
    assert "Invalid repo name" in result.stderr


def test_strip_postgres_requires_strip_pizza(tmp_path: Path) -> None:
    result = _run(
        [
            "--non-interactive",
            "--target",
            str(tmp_path / "out"),
            "--repo-name",
            "b-tree-example-bfa",
            "--service-slug",
            "example-bfa",
            "--strip-postgres",
        ]
    )
    assert result.returncode == 1
    assert "--strip-postgres is valid only with --strip-pizza" in result.stderr


def test_target_must_not_be_template(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / "README.md").write_text("AyDEO agent-007-theo\n", encoding="utf-8")
    result = _run(
        [
            "--non-interactive",
            "--target",
            str(template),
            "--repo-name",
            "b-tree-example-bfa",
            "--service-slug",
            "example-bfa",
            "--no-commit",
        ],
        env={"AYDEO_BOOTSTRAP_TEMPLATE_ROOT": str(template)},
    )
    assert result.returncode == 1
    assert "template repository itself" in result.stderr


def test_happy_path_renames_and_excludes(tmp_path: Path) -> None:
    if shutil.which("rsync") is None:
        pytest.skip("rsync is required for bootstrap copy")
    template = tmp_path / "template"
    target = tmp_path / "target"
    (template / "backend" / "src").mkdir(parents=True)
    (template / "postman").mkdir()
    (template / ".cursor").mkdir()
    (template / ".secrets").mkdir()
    (template / "backend" / "vendor").mkdir()
    (template / "scripts").mkdir()
    (template / "README.md").write_text("# AyDEO agent-007-theo — local dev\n", encoding="utf-8")
    (template / "backend" / "src" / "main.py").write_text(
        'title = "AyDEO agent-007-theo API"\nslug = "agent-007-theo"\n',
        encoding="utf-8",
    )
    (template / "postman" / "collection.json").write_text(
        '{"info": {"name": "AyDEO agent-007-theo"}}\n',
        encoding="utf-8",
    )
    (template / ".cursor" / "mcp.json").write_text("{}\n", encoding="utf-8")
    (template / ".cursor" / "rules.md").write_text("keep\n", encoding="utf-8")
    (template / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (template / ".env.demo").write_text("SECRET=1\n", encoding="utf-8")
    (template / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
    (template / ".knowledge").mkdir()
    (template / ".knowledge" / "x.md").write_text("hub\n", encoding="utf-8")
    (template / "backend" / "vendor" / "kit.txt").write_text("vendor\n", encoding="utf-8")
    (template / ".secrets" / "token").write_text("nope\n", encoding="utf-8")
    (template / ".secrets" / "README.md").write_text("how to store secrets\n", encoding="utf-8")
    (template / "scripts" / ".demo-last-bfa-host-tag").write_text("v1\n", encoding="utf-8")
    target.mkdir()

    result = _run(
        [
            "--non-interactive",
            "--target",
            str(target),
            "--repo-name",
            "b-tree-example-bfa",
            "--service-slug",
            "example-bfa",
            "--no-commit",
        ],
        env={"AYDEO_BOOTSTRAP_TEMPLATE_ROOT": str(template)},
    )
    assert result.returncode == 0, result.stderr
    main_py = (target / "backend" / "src" / "main.py").read_text(encoding="utf-8")
    assert "AyDEO example-bfa API" in main_py
    assert "example-bfa" in main_py
    assert "AyDEO agent-007-theo API" not in main_py
    collection = (target / "postman" / "collection.json").read_text(encoding="utf-8")
    assert "AyDEO example-bfa" in collection
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "AyDEO example-bfa" in readme
    assert not (target / ".env").exists()
    assert not (target / ".env.demo").exists()
    assert not (target / ".env.local").exists()
    assert not (target / ".knowledge").exists()
    assert not (target / ".cursor" / "mcp.json").exists()
    assert (target / ".cursor" / "rules.md").is_file()
    assert not (target / "backend" / "vendor" / "kit.txt").exists()
    assert (target / "backend" / "vendor" / ".gitkeep").is_file()
    assert not (target / "scripts" / ".demo-last-bfa-host-tag").exists()
    assert not (target / ".secrets" / "token").exists()
    assert (target / ".secrets" / "README.md").read_text(encoding="utf-8") == "how to store secrets\n"


def test_happy_path_strip_postgres_requires_pizza_files(tmp_path: Path) -> None:
    if shutil.which("rsync") is None:
        pytest.skip("rsync is required for bootstrap copy")
    live_config = (_REPO_ROOT / "backend" / "src" / "config.py").read_text(encoding="utf-8")
    live_compose = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    if "database_url: str | None" in live_config or "postgres:" not in live_compose:
        pytest.skip("live tree already postgres-stripped; cannot re-prove strip transform")
    template = tmp_path / "template"
    target = tmp_path / "target"
    host = template / "backend" / "src" / "host"
    host.mkdir(parents=True)
    (template / "backend" / "src" / "host" / "factory.py").write_text(
        (_REPO_ROOT / "backend" / "src" / "host" / "factory.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (template / "docker-compose.yml").write_text(
        (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (template / "backend" / "src" / "config.py").write_text(
        (_REPO_ROOT / "backend" / "src" / "config.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (template / "backend" / ".env.example").write_text(
        (_REPO_ROOT / "backend" / ".env.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (template / "scripts").mkdir()
    target.mkdir()

    result = _run(
        [
            "--non-interactive",
            "--target",
            str(target),
            "--repo-name",
            "b-tree-example-bfa",
            "--service-slug",
            "example-bfa",
            "--strip-pizza",
            "--strip-postgres",
            "--no-commit",
        ],
        env={"AYDEO_BOOTSTRAP_TEMPLATE_ROOT": str(template)},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    factory = (target / "backend" / "src" / "host" / "factory.py").read_text(encoding="utf-8")
    assert "register_pizza_tools" not in factory
    assert "build_aydeo_host(" in factory
    compose = (target / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgres:" not in compose

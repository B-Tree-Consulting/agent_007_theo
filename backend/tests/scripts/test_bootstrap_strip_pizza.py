"""Unit tests for bootstrap pizza-strip helper (sample#33)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND.parent
_FACTORY = _BACKEND / "src" / "host" / "factory.py"
_HELPER = _REPO_ROOT / "scripts" / "bootstrap_strip_pizza.py"

sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from bootstrap_strip_pizza import (  # noqa: E402
    neutralize_pizza_text,
    strip_pizza_from_factory_file,
    strip_pizza_from_factory_source,
    strip_pizza_from_repo,
)


@pytest.fixture(scope="module")
def factory_source() -> str:
    return _FACTORY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pizza_factory_source(factory_source: str) -> str:
    if "register_pizza_tools" not in factory_source:
        pytest.skip("pizza already stripped in this tree")
    return factory_source


def test_current_factory_has_pizza_hooks(pizza_factory_source: str) -> None:
    assert "register_pizza_tools" in pizza_factory_source
    assert "PizzaCatalogMetadataProvider" in pizza_factory_source
    assert pizza_factory_source.count("build_aydeo_host(") >= 2


def test_strip_removes_pizza_and_keeps_build_aydeo_host(pizza_factory_source: str) -> None:
    out = strip_pizza_from_factory_source(pizza_factory_source)
    ast.parse(out)
    assert "samples.pizza" not in out
    assert "PizzaCatalogMetadataProvider" not in out
    assert "register_pizza_tools" not in out
    assert "wire your bootstrap here before starting the host" in out
    assert out.count("build_aydeo_host(") >= 2
    assert "def register_sample_modules() -> None:" in out
    assert "\n    pass\n" in out
    assert "if register_pizza_tools" not in out


def test_strip_is_idempotent(pizza_factory_source: str) -> None:
    once = strip_pizza_from_factory_source(pizza_factory_source)
    twice = strip_pizza_from_factory_source(once)
    ast.parse(twice)
    assert "PizzaCatalogMetadataProvider" not in twice
    assert twice.count("build_aydeo_host(") >= 2


def test_strip_writes_file(tmp_path: Path, factory_source: str) -> None:
    target = tmp_path / "factory.py"
    target.write_text(factory_source, encoding="utf-8")
    strip_pizza_from_factory_file(target)
    text = target.read_text(encoding="utf-8")
    ast.parse(text)
    assert "register_pizza_tools" not in text


def test_strip_rejects_missing_register() -> None:
    with pytest.raises(ValueError, match="register_sample_modules"):
        strip_pizza_from_factory_source("def other() -> None:\n    pass\n")


def test_main_cli_success(tmp_path: Path, factory_source: str) -> None:
    import bootstrap_strip_pizza as mod

    target = tmp_path / "factory.py"
    target.write_text(factory_source, encoding="utf-8")
    assert mod.main([str(target)]) == 0
    assert "register_pizza_tools" not in target.read_text(encoding="utf-8")


def test_main_cli_missing_file(tmp_path: Path) -> None:
    import bootstrap_strip_pizza as mod

    assert mod.main([str(tmp_path / "nope.py")]) == 1


def test_main_cli_bad_source(tmp_path: Path) -> None:
    import bootstrap_strip_pizza as mod

    target = tmp_path / "factory.py"
    target.write_text("def other() -> None:\n    pass\n", encoding="utf-8")
    assert mod.main([str(target)]) == 1


def test_helper_script_exists() -> None:
    assert _HELPER.is_file()


def test_leftover_pizza_refs_raise(monkeypatch: pytest.MonkeyPatch, pizza_factory_source: str) -> None:
    import re

    import bootstrap_strip_pizza as mod

    never = re.compile(r"(?!x)x")
    monkeypatch.setattr(mod, "_CATALOG_IMPORT", never)
    monkeypatch.setattr(mod, "_CATALOG_KWARG", never)
    with pytest.raises(ValueError, match="pizza references remain"):
        strip_pizza_from_factory_source(pizza_factory_source)


def test_missing_build_aydeo_host_sites_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    import bootstrap_strip_pizza as mod

    class _FakeRegister:
        def search(self, _text: str) -> object:
            return object()

        def sub(self, _repl: str, _text: str, count: int = 0) -> str:
            return (
                "def register_sample_modules() -> None:\n"
                "    \"\"\"wire your bootstrap here before starting the host\"\"\"\n"
                "    pass\n"
            )

    monkeypatch.setattr(mod, "_REGISTER_FN", _FakeRegister())
    with pytest.raises(ValueError, match="build_aydeo_host"):
        strip_pizza_from_factory_source(
            "def register_sample_modules() -> None:\n    register_pizza_tools(HostSampleBFA)\n"
        )


def test_cli_entrypoint_as_main(tmp_path: Path, factory_source: str) -> None:
    import runpy

    target = tmp_path / "factory.py"
    target.write_text(factory_source, encoding="utf-8")
    old_argv = sys.argv
    try:
        sys.argv = [str(_HELPER), str(target)]
        with pytest.raises(SystemExit) as exited:
            runpy.run_path(str(_HELPER), run_name="__main__")
        assert exited.value.code == 0
    finally:
        sys.argv = old_argv
    assert "register_pizza_tools" not in target.read_text(encoding="utf-8")


def test_neutralize_pizza_text_drops_pizza_word() -> None:
    assert "pizza" not in neutralize_pizza_text("Remove the pizza sample tools").lower()


def test_strip_pizza_from_repo_tmp(tmp_path: Path, factory_source: str) -> None:
    import json

    backend = tmp_path / "backend"
    host = backend / "src" / "host"
    models = backend / "src" / "db" / "models"
    versions = backend / "migrations" / "versions"
    host.mkdir(parents=True)
    models.mkdir(parents=True)
    versions.mkdir(parents=True)
    (tmp_path / "postman").mkdir()
    (backend / "tests" / "host").mkdir(parents=True)
    (backend / "tests" / "db").mkdir(parents=True)
    (backend / "src" / "samples" / "pizza").mkdir(parents=True)
    (host / "factory.py").write_text(factory_source, encoding="utf-8")
    (models / "__init__.py").write_text(
        "from src.samples.pizza.stores import db_models as _pizza_db_models\n",
        encoding="utf-8",
    )
    (backend / "src" / "main.py").write_text(
        'description = "Removable sample: backend/src/samples/pizza/"\n',
        encoding="utf-8",
    )
    (host / "facade.py").write_text('"""pizza tools register via bootstrap."""\n', encoding="utf-8")
    (host / "README.md").write_text("PizzaCatalogMetadataProvider and register_pizza_tools\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Keep pizza sample\n", encoding="utf-8")
    (tmp_path / "POSTMAN_GUIDE.md").write_text("BFA → Pizza\n", encoding="utf-8")
    (versions / "0001_initial.py").write_text("# pizza\n", encoding="utf-8")
    (backend / "tests" / "db" / "test_migrations.py").write_text("HEAD_REVISION = '0002'\n", encoding="utf-8")
    (backend / "tests" / "host" / "test_bfa_host.py").write_text("pizza\n", encoding="utf-8")
    (tmp_path / "postman" / "collection.json").write_text(
        json.dumps({"item": [{"name": "Setup"}, {"name": "Pizza", "item": []}]}),
        encoding="utf-8",
    )
    (tmp_path / "postman" / "environment.json").write_text(
        json.dumps({"values": [{"key": "sample_menu_ref"}, {"key": "base_url"}]}),
        encoding="utf-8",
    )
    (backend / "src" / "samples" / "pizza" / "x.py").write_text("# demo\n", encoding="utf-8")
    (backend / "tests" / "host" / "http_helpers.py").write_text("# keep\n", encoding="utf-8")
    (backend / "tests" / "host" / "flow_helpers.py").write_text("# pizza helpers\n", encoding="utf-8")
    (backend / "tests" / "host" / "test_keep.py").write_text("# leftover pizza comment\n", encoding="utf-8")

    strip_pizza_from_repo(tmp_path)

    factory = (host / "factory.py").read_text(encoding="utf-8")
    assert "register_pizza_tools" not in factory
    assert "from src.samples.pizza" not in (models / "__init__.py").read_text(encoding="utf-8")
    assert (versions / "0001_empty.py").is_file()
    assert not (versions / "0001_initial.py").exists()
    assert not (backend / "tests" / "host" / "test_bfa_host.py").exists()
    assert not (backend / "src" / "samples" / "pizza").exists()
    coll = json.loads((tmp_path / "postman" / "collection.json").read_text(encoding="utf-8"))
    assert all(item.get("name") != "Pizza" for item in coll["item"])
    env = json.loads((tmp_path / "postman" / "environment.json").read_text(encoding="utf-8"))
    assert all(row.get("key") != "sample_menu_ref" for row in env["values"])
    assert "pizza" not in (tmp_path / "README.md").read_text(encoding="utf-8").lower()
    assert (backend / "tests" / "host" / "http_helpers.py").is_file()
    assert not (backend / "tests" / "host" / "flow_helpers.py").exists()
    assert "pizza" not in (backend / "tests" / "host" / "test_keep.py").read_text(encoding="utf-8").lower()
    assert "HEAD_REVISION = \"0001_empty\"" in (backend / "tests" / "db" / "test_migrations.py").read_text(
        encoding="utf-8"
    )


def test_cli_repo_root_strip(tmp_path: Path, factory_source: str) -> None:
    import bootstrap_strip_pizza as mod

    host = tmp_path / "backend" / "src" / "host"
    host.mkdir(parents=True)
    (host / "factory.py").write_text(factory_source, encoding="utf-8")
    assert mod.main([str(tmp_path)]) == 0
    assert "register_pizza_tools" not in (host / "factory.py").read_text(encoding="utf-8")


def test_cli_missing_factory_under_root(tmp_path: Path) -> None:
    import bootstrap_strip_pizza as mod

    assert mod.main([str(tmp_path)]) == 1


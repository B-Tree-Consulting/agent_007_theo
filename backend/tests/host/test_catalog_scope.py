"""Unit tests for catalog scope helpers."""

from __future__ import annotations

from src.host.catalog_scope import build_catalog_scope, build_catalog_scope_for_tools


def test_build_catalog_scope_marks_all_tools() -> None:
    tools = frozenset({"canary_query_bounded", "canary_action_direct"})
    scope = build_catalog_scope(tools)
    assert scope.is_scoped_tool("canary_query_bounded") is True
    assert scope.is_scoped_tool("other") is False
    assert scope.resolve_case_scope("canary_query_bounded") == "active_open_case"


def test_build_catalog_scope_for_tools_override() -> None:
    scope = build_catalog_scope_for_tools(
        scoped_tools=frozenset({"cms_capture_intent"}),
        scope_by_tool={"cms_capture_intent": "active_open_case"},
    )
    assert scope.is_scoped_tool("cms_capture_intent") is True
    assert scope.resolve_case_scope("cms_capture_intent") == "active_open_case"

"""SR_10 catalog scope helpers for the BFA host sample."""

from __future__ import annotations

from bfa.aydeo_host.case_state import CatalogScopeHelpers


def build_catalog_scope(tool_names: frozenset[str]) -> CatalogScopeHelpers:
    """All registered tools require an active open case (sample has no cms_capture_intent)."""

    def is_scoped_tool(tool_name: str) -> bool:
        return tool_name in tool_names

    def resolve_case_scope(tool_name: str) -> str:
        del tool_name
        return "active_open_case"

    return CatalogScopeHelpers(
        is_scoped_tool=is_scoped_tool,
        resolve_case_scope=resolve_case_scope,
    )


def build_catalog_scope_for_tools(
    *,
    scoped_tools: frozenset[str],
    scope_by_tool: dict[str, str] | None = None,
) -> CatalogScopeHelpers:
    """Build scope helpers for isolated tests (e.g. capture-spoof)."""

    overrides = scope_by_tool or {}

    def is_scoped_tool(tool_name: str) -> bool:
        return tool_name in scoped_tools

    def resolve_case_scope(tool_name: str) -> str:
        return overrides.get(tool_name, "active_open_case")

    return CatalogScopeHelpers(
        is_scoped_tool=is_scoped_tool,
        resolve_case_scope=resolve_case_scope,
    )

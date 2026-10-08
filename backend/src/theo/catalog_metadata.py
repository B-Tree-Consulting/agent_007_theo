"""Catalog operating context for the Theo host."""

from __future__ import annotations

from typing import Literal

from src.theo.operating_context import THEO_OPERATING_CONTEXT

CatalogMode = Literal["management", "runtime"]


class TheoCatalogMetadataProvider:
    def operating_context(self, *, mode: CatalogMode) -> str:
        del mode
        return THEO_OPERATING_CONTEXT

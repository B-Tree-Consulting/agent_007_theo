"""Post a host-authored case comment as the invoking digital employee."""

from __future__ import annotations

import httpx
from aydeo_cms_client import AydeoCmsClient


class CaseCommentConfigError(Exception):
    """Raised before HTTP when a case comment cannot be posted."""


class CaseCommentClient:
    """Participant CMS comment writer bound to one DE bearer."""

    def __init__(
        self,
        *,
        base_url: str | None,
        bearer: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or "").strip()
        self._bearer = (bearer or "").strip()
        self._transport = transport

    async def add_comment(self, *, case_id: str, body: str) -> None:
        if not self._base_url:
            raise CaseCommentConfigError("AYDEO_CMS_BASE_URL is required to record a case comment")
        if not self._bearer:
            raise CaseCommentConfigError("DE bearer is required to record a case comment")
        client = AydeoCmsClient(
            base_url=self._base_url,
            auth_header=self._bearer,
            transport=self._transport,
        )
        await client.add_case_comment(case_id, body=body)

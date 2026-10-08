"""Case comment client: DE bearer, fail closed, SDK body-only post."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from aydeo_cms_client.errors import CmsForbiddenError, CmsTransportError, CmsUnauthorizedError

from src.host.case_comment_client import CaseCommentClient, CaseCommentConfigError

_CASE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_BODY = "Pizza Ordered\nOrder Number: ord-1"


def _comment_payload(body: str) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid4()),
        "body": body,
        "created_at": now,
        "updated_at": now,
    }


def test_add_comment_requires_base_url() -> None:
    client = CaseCommentClient(base_url="  ", bearer="de-token")
    with pytest.raises(CaseCommentConfigError, match="AYDEO_CMS_BASE_URL"):
        asyncio.run(client.add_comment(case_id=_CASE_ID, body=_BODY))


def test_add_comment_requires_bearer() -> None:
    client = CaseCommentClient(base_url="http://cms.test", bearer=None)
    with pytest.raises(CaseCommentConfigError, match="DE bearer"):
        asyncio.run(client.add_comment(case_id=_CASE_ID, body=_BODY))


def test_add_comment_posts_body_with_de_bearer() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode())
        seen["path"] = request.url.path
        return httpx.Response(200, json=_comment_payload(_BODY))

    client = CaseCommentClient(
        base_url="http://cms.test",
        bearer="de-token",
        transport=httpx.MockTransport(handler),
    )
    asyncio.run(client.add_comment(case_id=_CASE_ID, body=_BODY))
    assert seen["auth"] == "Bearer de-token"
    assert seen["body"] == {"body": _BODY}
    assert seen["path"] == f"/api/v1/cases/{_CASE_ID}/comments"


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (401, CmsUnauthorizedError),
        (403, CmsForbiddenError),
    ],
)
def test_add_comment_propagates_cms_auth_errors(status: int, exc_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, json={"detail": "no"})

    client = CaseCommentClient(
        base_url="http://cms.test",
        bearer="de-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(exc_type):
        asyncio.run(client.add_comment(case_id=_CASE_ID, body=_BODY))


def test_add_comment_propagates_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cms down", request=request)

    client = CaseCommentClient(
        base_url="http://cms.test",
        bearer="de-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CmsTransportError):
        asyncio.run(client.add_comment(case_id=_CASE_ID, body=_BODY))

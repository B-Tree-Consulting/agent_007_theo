"""HTTP exception handler tests."""

import asyncio
import json

from fastapi import HTTPException

from src.main import http_exception_handler


def _response_json(response) -> dict:
    return json.loads(response.body.decode())


def test_http_exception_handler_passes_through_structured_error() -> None:
    detail = {"error": {"code": "validation_error", "message": "bad", "details": None}}
    exc = HTTPException(status_code=422, detail=detail, headers={"X-Test": "1"})
    response = asyncio.run(http_exception_handler(None, exc))
    assert response.status_code == 422
    assert _response_json(response) == detail
    assert response.headers["x-test"] == "1"


def test_http_exception_handler_maps_field_errors() -> None:
    exc = HTTPException(
        status_code=422,
        detail=[
            {
                "type": "value_error",
                "loc": ["quantity"],
                "msg": "Value error, must be greater than zero",
                "input": 0,
            }
        ],
    )
    response = asyncio.run(http_exception_handler(None, exc))
    body = _response_json(response)
    assert response.status_code == 422
    assert body["error"]["code"] == "submit_input_invalid"
    assert body["error"]["details"]["fields"] == [
        {"field": "quantity", "reason": "must be greater than zero"}
    ]


def test_http_exception_handler_wraps_plain_detail() -> None:
    exc = HTTPException(status_code=404, detail="not found")
    response = asyncio.run(http_exception_handler(None, exc))
    assert response.status_code == 404
    assert _response_json(response) == {
        "error": {"code": "http_error", "message": "not found", "details": None},
    }


def test_http_exception_handler_without_headers() -> None:
    exc = HTTPException(status_code=500, detail="boom")
    response = asyncio.run(http_exception_handler(None, exc))
    assert response.status_code == 500
    assert "error" in _response_json(response)

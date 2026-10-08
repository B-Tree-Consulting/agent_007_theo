"""Hello-world query registration."""

from __future__ import annotations

import asyncio

from src.host.facade import HostSampleBFA
from src.samples.hello.bootstrap import register_hello_tools
from src.samples.hello.queries.get_hello_world import GetHelloWorldInput


def test_get_hello_world_is_registered_once() -> None:
    assert register_hello_tools(HostSampleBFA) in (True, False)
    assert register_hello_tools(HostSampleBFA) is False
    names = {
        spec.get("name")
        for spec in getattr(HostSampleBFA, "_cls_specs", [])
        if isinstance(spec, dict)
    }
    assert "get_hello_world" in names


def test_get_hello_world_returns_greeting() -> None:
    register_hello_tools(HostSampleBFA)
    result = asyncio.run(HostSampleBFA.get_hello_world(None, GetHelloWorldInput()))
    assert result.message == "hello world"

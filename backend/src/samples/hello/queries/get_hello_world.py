"""Read-only hello-world query."""

from __future__ import annotations

from typing import Any

from bfa import ExecuteContext
from pydantic import BaseModel, Field


class GetHelloWorldInput(BaseModel):
    """No inputs."""


class GetHelloWorldOutput(BaseModel):
    message: str = Field(description="Greeting returned by the query.")


def register(host_cls: type) -> None:
    @host_cls.query(
        name="get_hello_world",
        describe="Return a hello-world greeting.",
        version="1.0.0",
        risk="low",
        execute_context=ExecuteContext.DE_AUTONOMOUS,
        case_tool_class="read",
        input_model=GetHelloWorldInput,
        output_model=GetHelloWorldOutput,
    )
    async def get_hello_world(self: Any, inputs: GetHelloWorldInput) -> GetHelloWorldOutput:
        del self, inputs
        return GetHelloWorldOutput(message="hello world")

    setattr(host_cls, get_hello_world.__name__, get_hello_world)

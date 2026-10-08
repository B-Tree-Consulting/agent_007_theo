"""Register the hello-world sample onto a host BFA class."""

from __future__ import annotations

from src.samples.hello.queries.get_hello_world import register as register_get_hello_world

_FLAG = "_hello_tools_registered"


def register_hello_tools(host_cls: type) -> bool:
    """Attach hello-world tools once. Returns True when this call registered them."""
    if getattr(host_cls, _FLAG, False):
        return False
    register_get_hello_world(host_cls)
    setattr(host_cls, _FLAG, True)
    return True

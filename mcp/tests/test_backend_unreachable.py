"""Rule 5, applied to a boundary this codebase has never had before.

``vinzor/photo.py`` already draws this line for a vision model reading a
passport photograph: a reader that could not be reached must come back as a
refusal, never as a document that showed nothing --
``test_a_reader_that_could_not_be_reached_is_never_a_clean_read`` in
``tests/test_photo.py`` is the test that proves it, and its own docstring
calls this "the defect this product has found four times". This is the
fifth place, one layer further out than any of the first four: the tool an
*MCP agent* calls to screen a name is exactly as able to mistake "yente never
answered" for "yente answered zero matches" as any adapter inside vinzor/
itself, and every one of those adapters had to be caught doing it before it
was fixed.

Read before touching this test: ``yente_client/mcp/errors.py``'s
``describe_error`` is where the SDK's ``TransportError`` (raised when the
connection itself fails, before any HTTP response exists) is turned into the
message this test asserts on. That module's own docstring explains why: an
httpx timeout exception stringifies to ``""``, so without this translation a
network failure would surface to the agent as an *empty* error -- which is
one step removed from surfacing as no error at all. This test is downstream
of that translation, not a duplicate of it: it proves the whole chain, from
a real connection failure through the real SDK through a real MCP tool call,
ends at a distinguishable failure and never at a clean, empty match.

The port below is never listened on. A socket is bound and immediately
closed to obtain one nobody else is using, rather than picking an
unrouteable address (``10.255.255.1``, ``192.0.2.1``) that would make this
test spend a real connect timeout finding out nobody is there -- a closed
local port refuses the connection at once.
"""

from __future__ import annotations

import asyncio
import importlib
import socket

import pytest


def _port_nobody_is_listening_on() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _mcp_server_pointed_nowhere():
    """The ``yente_client.mcp.server`` module, freshly imported after
    ``$YENTE_BASE_URL`` has been set to an address nothing answers on.

    ``server.py`` reads ``$YENTE_BASE_URL`` once, into a module-level
    constant, at import time (see ``yente_client/env.py``'s own docstring:
    the SDK client never reads the environment, only "the edges" -- the CLI,
    this server, and its own test suite -- do, precisely so the variable is
    read in one place). A test that only set the variable *after* the module
    was already imported by an earlier test in the same process would be
    asserting against a stale value it never actually configured, so the
    module is reloaded fresh here, every time, after the fixture below has
    set the variable it is about to read.
    """
    import yente_client.mcp.server as server_module

    return importlib.reload(server_module)


@pytest.fixture
def nowhere(monkeypatch):
    port = _port_nobody_is_listening_on()
    monkeypatch.setenv("YENTE_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.delenv("OPENSANCTIONS_API_KEY", raising=False)
    return port


def test_an_unreachable_yente_fails_the_call_rather_than_reporting_a_clean_screen(nowhere):
    """The one thing that must never happen: zero results read as a clean
    screen when the truth is that no screen was ever performed."""

    async def go():
        from fastmcp import Client

        server_module = _mcp_server_pointed_nowhere()
        async with Client(server_module.mcp) as client:
            return await client.call_tool("match_entity", {
                "schema": "Person",
                "properties": {"name": ["Vladimir Petrov"]},
                "dataset": "default",
            })

    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError) as failure:
        asyncio.run(go())

    message = str(failure.value)
    # Not just "an error happened" -- specifically the failure state
    # describe_error() manufactures for exactly this case, so this test
    # would fail if a future SDK version quietly started returning
    # {"results": []} for a connection it never made.
    assert "yente request failed" in message
    assert "retryable=true" in message


def test_search_entities_fails_the_same_way(nowhere):
    """The same guard, on the tool's sibling. One tool passing this and a
    second one silently returning an empty list would be exactly the kind
    of half-fixed defect BLOCKS.md records -- see screening.py's own
    ``_refuse_unless_indexed``, added after an *empty match* and a
    *not-yet-built index* turned out to answer identically."""

    async def go():
        from fastmcp import Client

        server_module = _mcp_server_pointed_nowhere()
        async with Client(server_module.mcp) as client:
            return await client.call_tool("search_entities", {"q": "Petrov"})

    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError) as failure:
        asyncio.run(go())

    assert "yente request failed" in str(failure.value)

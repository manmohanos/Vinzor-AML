"""One real MCP tool call, end to end.

This is the test version of the round trip run by hand while building this
adoption: a real FastMCP ``Client`` sends a real MCP ``call_tool`` request,
``yente_client.mcp.server.match_entity`` builds a real FollowTheMoney query
from it, ``AsyncClient.match`` speaks the real yente wire protocol --
``POST /match/<dataset>`` with the ``{"queries": {...}}`` body, the same
protocol ``vinzor/screening.py``'s own ``WatchlistClient.match`` speaks --
and gets back a real scored candidate.

The one thing standing in for the real world is ``fake_yente.py``: this
worktree has neither ``deploy/screening``'s docker-compose stack nor a
network path to it, so the fake plays the two routes a match actually walks.
Where it is genuinely reachable (``http://127.0.0.1:8090``, same as
``VINZOR_SCREENING_URL``), the exact same test passes unchanged against the
real self-hosted yente -- nothing here is fake-specific except which process
answers on that port.

A second, fully out-of-process version of this same round trip -- two real
subprocesses, a real yente-mcp bound to a real loopback port, called over
real HTTP by a client that never touches the server object directly -- was
also run by hand while building this and is written up in mcp/README.md.
This test uses FastMCP's in-memory transport instead (``Client(mcp)``
rather than ``Client("http://...")``) so it stays fast and does not need a
free TCP port on every CI run; the wire protocol it exercises against the
fake yente is identical either way, and only the MCP transport differs.
"""

from __future__ import annotations

import asyncio
import importlib

import fake_yente
import pytest


@pytest.fixture
def yente(monkeypatch):
    server, thread = fake_yente.start()
    port = server.server_address[1]
    monkeypatch.setenv("YENTE_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.delenv("OPENSANCTIONS_API_KEY", raising=False)
    try:
        yield
    finally:
        fake_yente.stop(server, thread)


def _reload_server_module():
    import yente_client.mcp.server as server_module

    return importlib.reload(server_module)


def test_a_real_match_tool_call_round_trips_through_the_real_yente_protocol(yente):
    async def go():
        from fastmcp import Client

        server_module = _reload_server_module()
        async with Client(server_module.mcp) as client:
            return await client.call_tool("match_entity", {
                "schema": "Person",
                "properties": {"name": ["Vladimir Petrov"]},
                "dataset": "default",
            })

    result = asyncio.run(go())

    assert result.data["results"], "the round trip returned no candidates"
    top = result.data["results"][0]
    assert top["caption"] == "Vladimir Petrov"
    assert top["score"] >= 0.70
    assert top["match"] is True
    # Topic and country codes arrive resolved to labels, not bare strings --
    # part of the surface this adoption actually gets over hand-rolling the
    # /match protocol a second time (see mcp/README.md's honesty about what
    # yente-client buys over vinzor/screening.py's own WatchlistClient).
    assert "sanction" in top["topics"]


def test_a_name_on_no_list_comes_back_as_no_match_not_as_an_error(yente):
    """The ordinary case a false-failure test alone cannot prove: the round
    trip has to be able to say "clean" too, or the fix for rule 5 would just
    be a server that raises on every call."""

    async def go():
        from fastmcp import Client

        server_module = _reload_server_module()
        async with Client(server_module.mcp) as client:
            return await client.call_tool("match_entity", {
                "schema": "Person",
                "properties": {"name": ["Someone Nobody Sanctioned"]},
                "dataset": "default",
            })

    result = asyncio.run(go())
    assert result.data["results"] == []
    assert result.data["total"] == 0

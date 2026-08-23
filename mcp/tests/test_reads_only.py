"""Everything built proposes; nothing establishes -- applied to a service
that was never given the chance to establish anything in the first place.

``ask.py``'s write-test and ``agents.py``'s ``ReadOnly`` wrapper are the two
enforcement points named for this rule, and neither one applies here, which
is worth saying plainly rather than pretending to bolt one on where it does
not fit. Both exist to stop a Python object that already holds a live
``Vinzor`` engine from reaching its write methods. This server is never
handed one: it is a separate process, in a separate virtualenv, that does
not import ``vinzor`` and was never told this workspace exists. There is no
``engine.ingest`` in this process's reach for a wrapper to stand in front
of -- the boundary is the operating system, not a Python attribute check,
and DESIGN.md's own reasoning for the wrapper is one of degree rather than
kind: an allowlist beats a blocklist because it does not have to be
remembered every time the thing behind it grows a new way to write. Never
importing the thing behind it at all is the same argument, taken one step
further.

So this file proves the equivalent guarantee at the boundary that actually
exists, in two parts:

1. This process cannot reach vinzor's write path because it cannot reach
   vinzor at all -- not merely "does not currently", but is not on this
   interpreter's import path, checked from an interpreter invoked exactly
   the way the deployed service is (mcp/yente-mcp.service's own
   ``ExecStart``, and mcp/run.sh's), not from whatever happened to be on
   ``sys.path`` because of how this test file itself was launched.
2. Every tool this server advertises is annotated read-only at the MCP
   protocol level -- the same signal an MCP client uses to decide whether a
   tool is safe to call without confirming with a person -- so a client
   sees the same promise this file checks.

Neither is a promise about what a *future* tool added to this server would
do; see mcp/README.md for why that risk is judged smaller here than it
would be inside vinzor/ itself.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile


def test_vinzor_is_not_on_this_process_s_import_path():
    """Run from a directory nowhere near the checkout, with a fully isolated
    interpreter (``-I``: no ``PYTHONPATH``, no user site-packages, no
    implicit "add the script's own directory" that would otherwise make this
    pass for the wrong reason if it were ever run from inside the
    checkout). What is left is exactly what mcp/yente-mcp.service's
    ``ExecStart`` would see: this venv's own site-packages, and nothing
    this project put there.
    """
    probe = (
        "import importlib.util, sys; "
        "print('FOUND' if importlib.util.find_spec('vinzor') else 'ABSENT')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tempfile.gettempdir(),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ABSENT", (
        "vinzor is importable from the MCP server's own interpreter -- the "
        "process boundary this file relies on instead of ask.py's write-test "
        "does not hold"
    )


def test_every_advertised_tool_is_marked_read_only():
    async def go():
        from fastmcp import Client
        from yente_client.mcp.server import mcp

        async with Client(mcp) as client:
            return await client.list_tools()

    tools = asyncio.run(go())
    assert tools, "no tools were advertised at all -- nothing to check"
    not_marked = [t.name for t in tools
                 if not (t.annotations and t.annotations.readOnlyHint)]
    assert not_marked == [], (
        f"these tools are not annotated read-only: {not_marked}"
    )


def test_the_service_account_has_nothing_of_its_own_to_write_to():
    """A source check, not a behavioural one -- there is no live instance of
    this unit in a test environment to start and inspect. What it can check
    is that the unit shipped in this directory does not carve out a place
    for itself to write, the way deploy/vinzor.service deliberately does
    carve out ``/var/lib/vinzor`` for the workspace it owns.
    """
    from pathlib import Path

    unit = (Path(__file__).resolve().parent.parent / "yente-mcp.service").read_text()
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=" not in unit, (
        "this unit grants itself a writable path; it should have nothing "
        "to write"
    )

"""A scripted stand-in for yente, playing only the two routes an MCP match
call actually walks.

``deploy/screening/docker-compose.yml`` runs the real thing on the live box,
reachable over loopback at the address ``VINZOR_SCREENING_URL`` already
names. A sandboxed development environment holds neither that container nor
the four-million-entity index behind it, so proving the MCP adoption works
needs something that answers the *protocol* the same way -- which is exactly
what ``vinzor/screening.py``'s own module docstring calls out as the actual
dependency: "the dependency is a protocol, not a package." This is that
protocol, played back from a script, for the same reason ``test_boundary_
audit.py``'s ``_Redirects`` handler plays back Azure's redirect behaviour
from a script instead of pointing a test at a live tenant.

Two routes, because that is all a match walks:

* ``GET /catalog`` -- yente-client's ``AsyncClient.datasets()`` calls this
  before trusting an empty match result is a clean one; it is the same
  "refuse unless indexed" check ``WatchlistClient._refuse_unless_indexed``
  performs in ``vinzor/screening.py``, now living one layer further out.
* ``POST /match/<dataset>`` -- the match itself, in the wrapped
  ``{"responses": {"<key>": {...}}}`` envelope every yente-protocol server
  uses and ``yente_client._translation.unwrap_match_response`` unwraps.

Nothing else is implemented. A fake that answered every route a real yente
serves would be worth less as documentation of what this adoption actually
needs, and more likely to drift from the two routes that matter without
anyone noticing.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Tuple

#: One sanctioned entity this fake index knows about, keyed by a lowercase
#: fragment of the name a query supplies. Enough to prove a real request
#: left the MCP process, crossed loopback HTTP, was answered, and came back
#: as a real scored candidate -- without needing an actual search index.
_KNOWN = {
    "petrov": {
        "id": "NK-fake-petrov",
        "caption": "Vladimir Petrov",
        "schema": "Person",
        "properties": {
            "name": ["Vladimir Petrov"],
            "birthDate": ["1961-03-03"],
            "nationality": ["ru"],
            "topics": ["sanction"],
        },
        "datasets": ["ru_local_sanctions"],
        "score": 0.91,
    },
}


class FakeYente(BaseHTTPRequestHandler):
    """Answers ``GET /catalog`` and ``POST /match/<dataset>``, and nothing
    else -- a 404 for anything else, same as a real server would give a
    route it does not serve."""

    server_version = "FakeYente/1"

    def log_message(self, *_args) -> None:
        pass  # the test output is noisy enough without an access log

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/catalog":
            self._send_json(200, {
                "datasets": [{
                    "name": "default",
                    "title": "OpenSanctions Default (fake)",
                    "load": True,
                    "index_current": True,
                }],
                "current": ["default"],
                "outdated": [],
                "index_stale": False,
            })
            return
        self._send_json(404, {"detail": f"this fake serves no route {self.path!r}"})

    def do_POST(self) -> None:
        if not self.path.startswith("/match/"):
            self._send_json(404, {"detail": f"this fake serves no route {self.path!r}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}

        # The wire shape yente_client._translation.unwrap_match_response
        # unwraps: {"responses": {"<key>": {"query", "results", "total"}},
        # "limit"}. Every query key sent gets an answer, exactly as
        # WatchlistClient.match in vinzor/screening.py insists a real
        # yente must -- a missing key there is treated as a broken
        # response, never as "nothing found".
        queries = body.get("queries") or {}
        responses = {}
        for key, query in queries.items():
            wanted = " ".join(
                (query.get("properties") or {}).get("name") or []
            ).lower()
            hits = [
                {**entity, "match": True}
                for needle, entity in _KNOWN.items()
                if needle in wanted
            ]
            responses[key] = {
                "query": query,
                "results": hits,
                "total": {"value": len(hits), "relation": "eq"},
            }
        self._send_json(200, {"responses": responses, "limit": 20})


def start(host: str = "127.0.0.1", port: int = 0) -> Tuple[HTTPServer, threading.Thread]:
    """Start the fake in a background thread, already serving."""
    server = HTTPServer((host, port), FakeYente)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop(server: HTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    server, thread = start(port=port)
    print(f"fake yente listening on http://127.0.0.1:{server.server_address[1]}")
    try:
        thread.join()
    except KeyboardInterrupt:
        stop(server, thread)

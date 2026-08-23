# mcp/

An MCP server that lets an LLM agent screen names against yente, kept
entirely outside the boundary `AGENTS.md` draws around `vinzor/*.py`.

| File | What it is |
| --- | --- |
| `requirements.txt` | One pinned package: `yente-client[mcp]==0.2.0`. |
| `yente-mcp.service` | The systemd unit this would run as on the live box, alongside `deploy/vinzor.service` and `deploy/screening/docker-compose.yml`. Not applied by `deploy/apply.sh` today -- see "What this is not" below. |
| `run.sh` | The by-hand counterpart of that unit: `mcp/run.sh setup` builds the venv, `mcp/run.sh start` runs the server in the foreground. |
| `tests/` | Its own suite, with its own `pytest.ini` so it never mixes with vinzor's. |

## Why this is here and not in `vinzor/`

`vinzor/screening.py`'s own module docstring already says the thing this
whole directory rests on: yente is adopted as a **protocol**, not a
package, and that is "why using the ecosystem did not cost the core its
zero-dependency property." `WatchlistClient` in that file is a couple of
hundred lines of hand-rolled `urllib` that speak `POST /match/<dataset>`
and `GET /catalog` well enough for the product's own needs.

This is a second, independent thing that speaks the same protocol: the
matching surface, wrapped for an LLM agent rather than for `vinzor`'s own
event log, by the people who publish yente itself
(`github.com/opensanctions/yente-client`, MIT). It is not a rewrite of
`WatchlistClient` and it does not replace it -- `vinzor/screening.py` still
mints `SCREENING_COMPLETED` facts and still answers to nobody but the
event log. This is a different consumer of the same service, for a
different caller: an agent working *on* or *around* this codebase (a
coding assistant, an investigator's own tooling) that wants to ask "is this
name on a list" without going through the product's UI at all.

That caller needing `pydantic`, `httpx` and `fastmcp` to talk to it is
exactly the situation `deploy/README.md` describes for Elasticsearch and
yente themselves: "the instance has no inbound SSH... nothing outside the
machine can reach it" is a sentence about a *process boundary*, and a
process boundary is what makes a dependency somebody else's problem. Yente
runs as its own process, reached over loopback HTTP, and nothing about its
internals -- indexing, matching, the search library underneath it --
touches `vinzor/`'s import graph. This server is the same shape one layer
out: its own process, its own virtualenv, reached over loopback HTTP by
whatever MCP client is configured to use it, and genuinely incapable of
being imported into `vinzor/*.py` because nothing under `vinzor/*.py` ever
imports anything under `mcp/`. `tests/test_reads_only.py`'s
`test_vinzor_is_not_on_this_process_s_import_path` checks the other
direction holds too: this process cannot see `vinzor` either.

## What this is not

**Not wired into the product.** `ask.py`'s tool registry and `agents.py`'s
`TOOLS` are how an officer's own assistant reaches the workspace today, and
neither one calls this server or is called by it. Adding "let the officer's
assistant screen a name through MCP instead of through
`vinzor/screening.py`" is a real, separate decision -- it would mean an
officer's question leaving the process over a second protocol, to a second
service, and that is exactly the kind of change `ECOSYSTEM.md`'s own
"Earmarked" table reserves for when a trigger actually fires ("MCP to
expose the engine's reads as tools" is listed there, unfired, and this is
not that). What is built here is the adapter that a *future* decision like
that would use, proven to work, sitting beside `vinzor/` rather than inside
it -- the same relationship the self-hosted yente stack itself has to the
product today.

**Not applied by `deploy/apply.sh`.** That script owns two things --
`vinzor.service` and `nginx.conf` -- and rolls both back together if either
fails to come up; `deploy/screening/` is deliberately outside that
rollback, for the reason `deploy/README.md` gives at length. Adding a third
unit to that machinery is worth doing carefully, with its own rollback
story, when something on the live box actually needs to reach this server
-- not as a side effect of writing the adapter. `yente-mcp.service` is
what that unit would look like; it is not installed by anything in this
commit.

## Configuration: the same value, a different name

`vinzor/screening.py` reads `VINZOR_SCREENING_URL`. `yente-client`'s own
tools -- the CLI, and this MCP server -- read `YENTE_BASE_URL` and
`OPENSANCTIONS_API_KEY`, because it is somebody else's package with its own
vocabulary, fixed by `yente_client/env.py` (read while building this: `pip
show`/source, not guessed). There is no way to make one process read a
variable named for a different project's adapter, so what "shares
configuration with the adapter that is already there" can honestly mean is
the *value*, kept in step by hand -- exactly how `deploy/vinzor.service`'s
`VINZOR_SCREENING_URL=http://127.0.0.1:8090` and
`deploy/screening/docker-compose.yml`'s `127.0.0.1:8090:8000` port mapping
are already two literal `8090`s in two files with a comment cross-referencing
each other, not a shared setting. `yente-mcp.service` adds a third literal
`8090` in the same style, not a new mechanism.

| Vinzor's variable | yente-client's variable | Notes |
| --- | --- | --- |
| `VINZOR_SCREENING_URL` | `YENTE_BASE_URL` | Same value on this deployment: `http://127.0.0.1:8090`. |
| `VINZOR_SCREENING_KEY` | `OPENSANCTIONS_API_KEY` | Unused against a self-hosted yente either way -- a self-hosted instance does not check a key, and `screening.py`'s own comment on `leaves_this_machine()` is why this deployment stays self-hosted. |
| `VINZOR_SCREENING_SCOPE` | *(none, server-wide)* | Honestly, does not map. `screening.py` bakes one scope into `WatchlistClient` at construction; yente-client's tools take `dataset` as a **per-call** argument on `match_entity` / `search_entities` (default `"default"`, which happens to match this deployment's own default scope). An agent calling this server chooses its own dataset on every call; it is not fixed for the process the way it is for `vinzor`'s own adapter. Said here rather than papered over with a fourth environment variable that would not actually constrain anything. |

## What was actually verified

Installed into this worktree's own `mcp/.venv`
(`python -m venv mcp/.venv && mcp/.venv/.../pip install -r
mcp/requirements.txt`) -- `vinzor`'s own environment was never touched, and
`python -m pytest -q` at the repo root still runs only `tests/`, because
`testpaths` there is `["tests"]` and `mcp/tests` has never been added to
it.

**A real self-hosted yente was not reachable in this sandbox.**
`http://127.0.0.1:8090/catalog` and `http://127.0.0.1:9200` were both
tried, from the same shell that later ran everything below, and both
refused the connection -- there is no `deploy/screening/docker-compose.yml`
stack running here. What was verified instead is the same protocol,
played back from a script: `mcp/tests/fake_yente.py` answers exactly the
two routes a match walks (`GET /catalog`, `POST /match/<dataset>`), in the
same wrapped-envelope shape a real yente uses, which
`yente_client._translation.unwrap_match_response` unwraps either way. The
fake does not know it isn't real, and neither does the client talking to
it -- that is the whole value of adopting a protocol rather than a mock.

**A genuine out-of-process round trip was run by hand**, not only inside a
test:

1. `mcp/tests/fake_yente.py 8090` started as its own subprocess, listening
   on `127.0.0.1:8090` -- the same address `VINZOR_SCREENING_URL` names.
2. `yente-mcp` (the console script `mcp/requirements.txt` installs)
   started as a second, separate subprocess,
   `YENTE_BASE_URL=http://127.0.0.1:8090`, streamable-HTTP transport,
   bound to `127.0.0.1:8091`.
3. A third process -- a plain script, no import of either server -- opened
   a real `fastmcp.Client("http://127.0.0.1:8091/mcp")` and called
   `list_tools()`, then `match_entity`.

What came back, verbatim:

```
tools advertised: ['describe_countries', 'describe_dataset', 'describe_program',
'describe_schema', 'describe_topics', 'fetch_entity_by_id',
'fetch_entity_relations', 'fetch_entity_statements', 'match_entity',
'search_entities']

MATCH RESULT: {'query_schema': 'Person', 'total': 1, 'results': [{'id':
'NK-fake-petrov', 'caption': 'Vladimir Petrov', 'schema': 'Person', 'datasets':
['ru_local_sanctions'], 'properties': {'name': ['Vladimir Petrov'], 'birthDate':
['1961-03-03'], 'nationality': ['ru']}, 'topics': {'sanction': 'Sanctioned
entity'}, 'countries': {'ru': 'Russia'}, 'score': 0.91, 'match': True,
'explanation': {}}]}
```

Server-side log from that same run, showing the MCP session actually
crossing the wire (`POST /mcp` for the call, not an in-process shortcut):

```
INFO:     Started server process
INFO:     Uvicorn running on http://127.0.0.1:8091 (Press CTRL+C to quit)
INFO:     127.0.0.1:56409 - "POST /mcp HTTP/1.1" 200 OK
INFO:     127.0.0.1:56414 - "GET /mcp HTTP/1.1" 200 OK
INFO:     127.0.0.1:56415 - "POST /mcp HTTP/1.1" 200 OK
INFO:     127.0.0.1:56416 - "POST /mcp HTTP/1.1" 200 OK
INFO:     127.0.0.1:56420 - "DELETE /mcp HTTP/1.1" 200 OK
```

`mcp/tests/test_round_trip.py` is the repeatable version of the same
chain -- FastMCP's in-memory transport instead of a real bound port, so it
runs in CI without needing a free socket, but the same real SDK call
against the same real fake-yente HTTP server.
`mcp/tests/test_backend_unreachable.py` is the failure half: pointed at a
TCP port nothing is listening on, `match_entity` raises
`fastmcp.exceptions.ToolError`, and the message is
`"yente request failed (retryable=true): All connection attempts failed"`
-- never an empty match, which is rule 5's whole point, applied to a
boundary this codebase had not yet built. That message is not this
project's wording: it is `yente_client/mcp/errors.py`'s own
`describe_error()`, which exists in the upstream package for exactly this
reason -- its docstring explains that an `httpx` timeout stringifies to
`""` on its own, so an agent given the bare exception could not tell a
network blip from a bad argument. Read before trusting it, not merely
imported.

All seven tests: `mcp/run.sh setup` then, from `mcp/`,
`.venv/Scripts/python.exe -m pytest -v` (or `.venv/bin/python3` on Linux).

## A real defect, found while installing this

`yente_client/schemas/_lookup.py` reads its bundled `model.json` with
`Path.read_text()` and no explicit encoding. On this Windows sandbox that
resolves to `cp1252`, and the file is not cp1252 -- `import yente_client`
raised `UnicodeDecodeError` on a fresh install until `PYTHONUTF8=1` was set
in the environment. Amazon Linux 2023's default locale is UTF-8, so this is
very likely a no-op on the box this would actually run on -- but "very
likely" earned the one line it costs to set unconditionally, in both
`run.sh` and `yente-mcp.service`, rather than being left as a thing that
works here because here happens to be Linux.

## The other side of rule 4

`ask.py`'s write-test and `agents.py`'s `ReadOnly` wrapper are named as the
two enforcement points a new tool must be provably bound by. Neither one is
what binds this one, and `mcp/tests/test_reads_only.py`'s own docstring
says why at length rather than forcing a fit: those two exist to stop a
Python object that already holds a live engine from reaching its write
methods, and this process is never handed one. What actually holds here is
that the process cannot reach `vinzor` at all -- checked from an
interpreter invoked the way the deployed unit invokes it, not from
whatever happened to be on `sys.path` because of where a test file lives --
and that every tool this server advertises carries MCP's own
`readOnlyHint=True` at the protocol level, which is the signal a real MCP
client uses to decide whether a tool needs confirming with a person before
it runs.

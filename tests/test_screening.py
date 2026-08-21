"""The OpenSanctions/yente boundary, exercised without a network.

The transport is injected, so every test runs offline against canned service
responses — the adapter's *protocol* is what is under test, plus the promise
that every screening outcome, including a clean one, becomes a fact on the log.
"""

from __future__ import annotations

import json

import pytest

from vinzor.model import EventType, Severity
from vinzor.screening import (
    FTM_SCHEMA,
    Hit,
    ScreeningUnavailable,
    WatchlistClient,
    screen,
)

from conftest import WHEN, company, person


def service(*results):
    """A fake yente answering every query it is asked.

    Answering only "q" was fine while there was only ever one question. An
    abbreviated name now asks a second, and a fake that ignores it made the
    real client refuse the whole check -- correctly, since a real service
    answers every query in the batch and a missing answer means something is
    wrong. The fake behaves like the service it stands in for.
    """
    calls = []

    def transport(url, body, headers):
        sent = json.loads(body)
        calls.append({"url": url, "body": sent, "headers": dict(headers)})
        answers = {key: {"results": list(results)}
                   for key in (sent.get("queries") or {"q": None})}
        return json.dumps({"responses": answers}).encode()

    return transport, calls


def sanction_result(score=0.92, entity_id="Q7747", caption="Vladimir Listed"):
    return {"id": entity_id, "caption": caption, "score": score, "match": True,
            "properties": {"topics": ["sanction"]}, "datasets": ["us_ofac_sdn"]}


def pep_result(score=0.81):
    return {"id": "Q1234", "caption": "A Minister", "score": score, "match": True,
            "properties": {"topics": ["role.pep"]}, "datasets": ["peps"]}


def client_with(*results, threshold=0.70):
    transport, calls = service(*results)
    return WatchlistClient(url="https://yente.local", scope="default",
                           threshold=threshold, transport=transport), calls


# -- the protocol ------------------------------------------------------------


def test_the_request_is_a_followthemoney_entity(engine):
    person(engine, "p1", "Rohan Desai")
    client, calls = client_with()
    screen(engine, "p1", screened_at=WHEN, client=client)

    call = calls[0]
    assert call["url"] == "https://yente.local/match/default"
    query = call["body"]["queries"]["q"]
    assert query["schema"] == "Person"
    assert query["properties"]["name"] == ["Rohan Desai"]


def test_a_person_carries_nationality_and_a_company_jurisdiction(engine):
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN,
                  payload={"kind": "PERSON", "name": "Rohan Desai",
                           "attributes": {"nationality": "IN"}})
    company(engine, "c1", "Orion Zenith Enterprises")
    client, calls = client_with()
    screen(engine, "p1", screened_at=WHEN, client=client)
    screen(engine, "c1", screened_at=WHEN, client=client)

    assert calls[0]["body"]["queries"]["q"]["properties"]["nationality"] == ["IN"]
    assert "nationality" not in calls[1]["body"]["queries"]["q"]["properties"]
    assert calls[1]["body"]["queries"]["q"]["schema"] == "Company"


def test_every_customer_type_has_an_ftm_schema():
    """A kind without a mapping would fail only on the day it is screened."""
    from vinzor.model import EntityKind

    assert set(FTM_SCHEMA) == set(EntityKind)


def test_the_api_key_travels_as_a_header_never_in_the_url(engine):
    person(engine, "p1")
    transport, calls = service()
    client = WatchlistClient(url="https://yente.local", api_key="sk-secret",
                             transport=transport)
    screen(engine, "p1", screened_at=WHEN, client=client)

    assert calls[0]["headers"]["Authorization"] == "ApiKey sk-secret"
    assert "sk-secret" not in calls[0]["url"]


# -- outcomes become facts ----------------------------------------------------


def test_a_sanctions_match_opens_a_critical_case_with_the_clauses(engine):
    person(engine, "p1", "Vladimir Similar")
    client, _ = client_with(sanction_result())
    results = screen(engine, "p1", screened_at=WHEN, client=client)

    case = results[0].cases[0]
    assert case.severity is Severity.CRITICAL
    assert case.case_type == "SCREENING_HIT"
    assert {c["clause"] for c in case.evidence[0].citations} == {"5.9", "11.2"}


def test_a_pep_match_is_high_not_critical(engine):
    person(engine, "p1", "A Minister")
    client, _ = client_with(pep_result())
    case = screen(engine, "p1", screened_at=WHEN, client=client)[0].cases[0]
    assert case.severity is Severity.HIGH
    assert case.evidence[0].policy_id == "POL_PEP_HIT"


def test_sanctions_outranks_pep_when_an_entity_is_both():
    hit = Hit(entity_id="x", caption="x", score=0.9,
              topics=("role.pep", "sanction"), datasets=())
    assert hit.list_type == "SANCTIONS"


def test_the_provenance_is_on_the_record(engine):
    """What was asked, of which service, what came back, with what score."""
    person(engine, "p1", "Vladimir Similar")
    client, _ = client_with(sanction_result(score=0.92))
    result = screen(engine, "p1", screened_at=WHEN, client=client)[0]

    basis = result.event.payload["basis"]
    assert basis["service"] == "https://yente.local"
    assert basis["matched_entity"] == "Q7747"
    assert basis["score"] == 0.92
    assert basis["datasets"] == ["us_ofac_sdn"]
    assert basis["query"]["properties"]["name"] == ["Vladimir Similar"]


def test_a_clean_screen_is_still_written_to_the_log(engine):
    """Clause 5.9 evidence: the proof that the check was performed."""
    person(engine, "p1", "Nobody Notable")
    client, _ = client_with()
    results = screen(engine, "p1", screened_at=WHEN, client=client)

    assert len(results) == 1
    assert results[0].event.payload["matched"] is False
    assert results[0].event.payload["basis"]["service"] == "https://yente.local"
    assert results[0].cases == []  # nothing to review, but the record exists


def test_rescreening_the_same_match_extends_the_case_not_duplicates_it(engine):
    """The alert id is stable per watchlist entity, so a weekly re-screen
    accumulates evidence on one Case instead of opening fifty-two."""
    person(engine, "p1", "Vladimir Similar")
    client, _ = client_with(sanction_result())

    first = screen(engine, "p1", screened_at="2026-08-01", client=client)[0].cases[0]
    second = screen(engine, "p1", screened_at="2026-08-08", client=client)[0].cases[0]

    assert first.case_id == second.case_id
    assert len(engine.state.casebook) == 1
    assert len(second.evidence) == 2  # both screenings on the record


def test_a_hit_with_no_recognised_topic_still_opens_a_case(engine):
    """OpenSanctions' own topic taxonomy has real categories -- "crime" among
    them -- that are none of SANCTIONS, PEP or ADVERSE_MEDIA, so this hit is
    recorded as ``list_type: "WATCHLIST"``. A Case used to not open for it at
    all: the match had full provenance in the event and was then invisible to
    every reader of the casebook, which is worse than an unrecognised list
    producing nothing, because "matched" and "recorded but no one will ever
    see it" are indistinguishable to the officer. ``policies.py`` now opens a
    Case on the chapeau risk-assessment obligation for exactly this situation
    -- see ``POL_WATCHLIST_HIT_UNCLASSIFIED`` -- without guessing a specific
    category or clause the register cannot back."""
    person(engine, "p1")
    # A topic this register genuinely has no rule for. "crime" used to
    # stand here and is now classified, which is the point of the rule
    # below it: an unrecognised topic still has to reach an officer.
    odd = {"id": "Q9", "caption": "On some list", "score": 0.9, "match": True,
           "properties": {"topics": ["poi"]}, "datasets": ["some_list"]}
    client, _ = client_with(odd)
    results = screen(engine, "p1", screened_at=WHEN, client=client)

    assert results[0].event.payload["list_type"] == "WATCHLIST"
    case = results[0].cases[0]
    assert case.evidence[0].policy_id == "POL_WATCHLIST_HIT_UNCLASSIFIED"
    assert case.severity is Severity.MEDIUM
    assert results[0].event.payload["basis"]["matched_entity"] == "Q9"


def test_a_score_below_the_threshold_is_no_match(engine):
    person(engine, "p1")
    weak = dict(sanction_result(score=0.40), match=False)
    client, _ = client_with(weak)
    results = screen(engine, "p1", screened_at=WHEN, client=client)
    assert results[0].event.payload["matched"] is False


# -- failure is loud and writes nothing ---------------------------------------


def test_an_unreachable_service_records_nothing(engine):
    person(engine, "p1")

    def down(url, body, headers):
        import urllib.error
        raise urllib.error.URLError("connection refused")

    before = len(engine.log)
    with pytest.raises(ScreeningUnavailable, match="not performed"):
        screen(engine, "p1", screened_at=WHEN,
               client=WatchlistClient(transport=down))
    assert len(engine.log) == before


def test_a_garbled_response_records_nothing(engine):
    person(engine, "p1")
    client = WatchlistClient(transport=lambda u, b, h: b"not json at all")
    before = len(engine.log)
    with pytest.raises(ScreeningUnavailable, match="does not recognise"):
        screen(engine, "p1", screened_at=WHEN, client=client)
    assert len(engine.log) == before


def test_screening_an_unknown_entity_is_refused_in_plain_words(engine):
    client, _ = client_with()
    with pytest.raises(ValueError, match="register the entity"):
        screen(engine, "ghost", screened_at=WHEN, client=client)


# -- unexpected-but-valid provider shapes are a refusal, never a traceback ----


@pytest.mark.parametrize(
    "raw",
    [
        # a result missing the "id" key the code indexes unconditionally
        {"responses": {"q": {"results": [
            {"caption": "x", "score": 0.9, "match": True}]}}},
        # a null score where a number was assumed
        {"responses": {"q": {"results": [
            {"id": "Q1", "score": None, "match": True}]}}},
        # a non-numeric score
        {"responses": {"q": {"results": [
            {"id": "Q1", "score": "high", "match": True}]}}},
        # "results" is a string, not a list -- iterating it would iterate
        # characters instead of raising
        {"responses": {"q": {"results": "nope"}}},
        # "results" is a dict, not a list
        {"responses": {"q": {"results": {"id": "Q1"}}}},
        # "results" is null
        {"responses": {"q": {"results": None}}},
        # the whole top-level response is a list
        [1, 2, 3],
        # the whole top-level response is null
        None,
        # "properties" is a list, not a mapping -- ".get" does not exist on it
        {"responses": {"q": {"results": [
            {"id": "Q1", "score": 0.9, "match": True,
             "properties": ["sanction"]}]}}},
    ],
    ids=[
        "missing_id", "null_score", "non_numeric_score", "results_as_string",
        "results_as_dict", "results_as_null", "top_level_as_list",
        "top_level_as_null", "properties_as_list",
    ],
)
def test_an_unexpected_but_valid_provider_shape_is_a_refusal_not_a_traceback(engine, raw):
    """The Hit-construction comprehension used to sit outside the
    ScreeningUnavailable contract: only the top-level results lookup was
    guarded, so a real-but-unanticipated provider response (a missing "id",
    a null score, "results" sent as something other than a list) escaped as
    a raw multi-line Python traceback. Neither ``_screen_cli`` nor
    ``_rescreen_cli`` catches anything but ScreeningUnavailable, and
    ``main()`` has no top-level handler either, so this used to land in front
    of a compliance officer -- which AGENTS.md forbids outright."""
    person(engine, "p1")
    client = WatchlistClient(transport=lambda u, b, h: json.dumps(raw).encode())
    before = len(engine.log)
    with pytest.raises(ScreeningUnavailable, match="does not recognise"):
        screen(engine, "p1", screened_at=WHEN, client=client)
    assert len(engine.log) == before


# -- the api key never prints ------------------------------------------------


def test_the_client_repr_cannot_print_the_api_key():
    """The default dataclass repr printed the credential in full -- confirmed:
    ``repr(client)`` contained the live key. AGENTS.md states the rule
    outright: never put a secret anywhere but the environment, "not a file,
    not an argument, not an event, not an exception, not a repr." The sibling
    module azure.py already solves this for AzureTransport; WatchlistClient
    did not."""
    client = WatchlistClient(url="https://yente.local", api_key="sk-live-secret-value")
    assert "sk-live-secret-value" not in repr(client)


# -- a real deadline on the whole call, not just each socket operation -------


def _local_server(handler_cls):
    """A real ``ThreadingHTTPServer`` on an ephemeral loopback port.

    Used instead of hand-rolled sockets so the HTTP framing itself (chunking,
    connection close, partial writes) is the standard library's problem, not
    the test's -- the thing under test is the client's deadline and read
    bound, not whether a hand-written response line parses.
    """
    import threading
    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def test_a_dripped_response_is_bounded_by_the_whole_call_not_each_recv(monkeypatch):
    """``timeout=`` on ``urlopen`` bounds each individual socket operation,
    not the exchange as a whole -- confirmed with a server that drips a valid
    response one byte at a time: with a 3 second timeout declared, the old
    code returned successfully after 17 seconds, because every individual
    recv() completed inside the 3s window even though the whole exchange did
    not. Here the declared deadline is 1 second and the server drips for well
    over a second; the call must fail well before the drip finishes."""
    import time
    from http.server import BaseHTTPRequestHandler

    from vinzor import screening

    class DripHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = b'{"responses": {}}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            for byte in body:
                time.sleep(0.3)  # comfortably inside a 1s per-op timeout
                self.wfile.write(bytes([byte]))
                self.wfile.flush()

        def log_message(self, fmt: str, *args) -> None:
            pass

    monkeypatch.setattr(screening, "REQUEST_TIMEOUT_SECONDS", 1)
    httpd, thread = _local_server(DripHandler)
    try:
        port = httpd.server_address[1]
        started = time.monotonic()
        with pytest.raises(ScreeningUnavailable, match="did not answer in time"):
            screening._http_transport(
                f"http://127.0.0.1:{port}/", b"{}",
                {"Content-Type": "application/json"},
            )
        elapsed = time.monotonic() - started
        assert elapsed < 3, (
            f"took {elapsed:.1f}s -- the deadline was per-recv, not for the call"
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_a_response_larger_than_the_limit_is_refused_not_buffered_whole(monkeypatch):
    """``response.read()`` has no ceiling of its own -- a peer that keeps
    sending is a peer that used to be kept buffering, unbounded. With the
    limit capped small here, a service answering just past it must be
    refused rather than read in full."""
    from http.server import BaseHTTPRequestHandler

    from vinzor import screening

    class BigHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = b"x" * 1000
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            pass

    monkeypatch.setattr(screening, "MAX_RESPONSE_BYTES", 16)
    httpd, thread = _local_server(BigHandler)
    try:
        port = httpd.server_address[1]
        with pytest.raises(ScreeningUnavailable, match="larger than expected"):
            screening._http_transport(
                f"http://127.0.0.1:{port}/", b"{}",
                {"Content-Type": "application/json"},
            )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# -- it is all still one auditable history -------------------------------------


def test_screening_facts_replay_like_everything_else(engine):
    person(engine, "p1", "Vladimir Similar")
    client, _ = client_with(sanction_result())
    screen(engine, "p1", screened_at=WHEN, client=client)

    rebuilt = engine.rebuild()
    assert rebuilt.casebook.cases == engine.state.casebook.cases
    assert engine.verify() == (True, None)


# -- does a name leave this machine? -----------------------------------------


def test_the_default_screening_target_is_not_this_machine():
    """The safe-looking case is the one that leaves: with nothing configured,
    every investor name is sent to a third-party API. A firm screening a real
    client book has to be told that before it happens, not after.
    """
    from vinzor.screening import DEFAULT_URL, leaves_this_machine

    assert leaves_this_machine(DEFAULT_URL)
    assert leaves_this_machine("")           # unset falls back to the default


@pytest.mark.parametrize("url,leaves", [
    ("http://127.0.0.1:8090", False),
    ("http://localhost:8090", False),
    ("http://[::1]:8090", False),
    ("https://api.opensanctions.org", True),
    ("https://yente.some-vendor.example", True),
])
def test_a_self_hosted_index_keeps_names_on_the_machine(url, leaves):
    from vinzor.screening import leaves_this_machine

    assert leaves_this_machine(url) is leaves


# -- names a book holds, and a list does not ---------------------------------


def test_an_abbreviated_name_is_asked_about_twice(engine):
    """A book holds "J. Smith"; a list holds "John Smith". Measured against 40
    genuinely listed people, asking once found 23 and missed 17, and lowering
    the threshold recovered none of them -- at 0.40 the answer was identical
    to 0.70, because those entities never came back as candidates at all.
    """
    person(engine, "p1", "J. Smith")
    transport, calls = service()
    screen(engine, "p1", screened_at=WHEN,
           client=WatchlistClient(url="https://yente.local", transport=transport))

    asked = calls[0]["body"]["queries"]
    assert len(asked) == 2, "an abbreviated name was only asked about once"
    assert asked["q"]["properties"]["name"] == ["J. Smith"]
    assert asked["q2"]["properties"]["name"] == ["Smith"]


def test_a_full_name_is_asked_about_once(engine):
    """The second question costs false positives, so it is only paid for by
    the parties whose record actually needs it."""
    person(engine, "p1", "John Smith")
    transport, calls = service()
    screen(engine, "p1", screened_at=WHEN,
           client=WatchlistClient(url="https://yente.local", transport=transport))
    assert list(calls[0]["body"]["queries"]) == ["q"]


def test_the_record_says_why_there_were_more_matches(engine):
    """An officer seeing more hits than they expected can find out why, and
    an inspector can tell a thorough check from a lucky one."""
    person(engine, "p1", "M K Patel")
    transport, _ = service()
    result = screen(engine, "p1", screened_at=WHEN,
                    client=WatchlistClient(url="https://yente.local",
                                           transport=transport))[0]
    basis = result.event.payload["basis"]
    assert basis["asked_twice"]["also_asked"] == "Patel"
    assert "abbreviated" in basis["asked_twice"]["because"]


def test_the_same_listed_party_is_not_raised_twice(engine):
    """Both questions can return the same entity. The party is one match, not
    two, and the better score is the one kept."""
    weak = sanction_result(score=0.72, entity_id="Q7747")
    transport, _ = service(weak)
    results = screen(engine, "p1", screened_at=WHEN,
                     client=WatchlistClient(url="https://yente.local",
                                            transport=transport)) \
        if person(engine, "p1", "J. Listed") is None else None
    matched = [r for r in results if (r.event.payload or {}).get("matched")]
    assert len(matched) == 1


def test_an_unanswered_question_refuses_the_whole_check(engine):
    """Skipping a missing answer would turn a broken response into "nothing
    found" -- a clean screening record for a check that did not happen."""
    person(engine, "p1", "J. Smith")

    def half_answer(url, body, headers):
        return json.dumps({"responses": {"q": {"results": []}}}).encode()

    with pytest.raises(ScreeningUnavailable):
        screen(engine, "p1", screened_at=WHEN,
               client=WatchlistClient(url="https://yente.local",
                                      transport=half_answer))


def test_the_record_keeps_what_was_considered_not_only_what_matched(engine):
    """"Three similar names came back and none was close enough" is a
    stronger clean record than silence about what was seen."""
    person(engine, "p1", "Rohan Desai")
    # Below the threshold and not flagged by the service: candidates that were
    # seen and did not qualify, which is exactly what the record should keep.
    weak = {"id": "Q1", "caption": "Rohan Desa", "score": 0.42,
            "properties": {"topics": ["sanction"]}, "datasets": ["us_ofac_sdn"]}
    weaker = {"id": "Q2", "caption": "R. Desai Kumar", "score": 0.31,
              "properties": {"topics": ["sanction"]}, "datasets": ["us_ofac_sdn"]}
    transport, _ = service(weak, weaker)
    result = screen(engine, "p1", screened_at=WHEN,
                    client=WatchlistClient(url="https://yente.local",
                                           transport=transport))[0]

    basis = result.event.payload["basis"]
    considered = basis["considered"]
    assert [c["score"] for c in considered] == [0.42, 0.31], "not best-first"
    assert considered[0]["name"] == "Rohan Desa"
    assert result.event.payload["matched"] is False


# -- the kinds the provider actually publishes ------------------------------


@pytest.mark.parametrize("topics,expected", [
    (["sanction"], "SANCTIONS"),
    (["role.pep"], "PEP"),
    (["role.rca"], "PEP_ASSOCIATE"),
    (["wanted"], "CRIMINAL"),
    (["crime"], "CRIMINAL"),
    (["crime.fraud"], "CRIMINAL"),
    (["debarment"], "DEBARRED"),
    (["poi"], "WATCHLIST"),
])
def test_each_topic_the_provider_returns_is_given_a_name(engine, topics,
                                                         expected):
    """A match an officer cannot name is a match they cannot act on.
    "Wanted by a law-enforcement agency" is actionable; "a watchlist we do
    not yet classify" is not."""
    person(engine, "p1")
    hit = {"id": "Q1", "caption": "Somebody", "score": 0.9, "match": True,
           "properties": {"topics": topics}, "datasets": ["a_list"]}
    client, _ = client_with(hit)
    results = screen(engine, "p1", screened_at=WHEN, client=client)
    assert results[0].event.payload["list_type"] == expected


def test_a_sanctioned_office_holder_is_a_sanctions_matter_first(engine):
    """Real records carry several topics at once -- one head of state comes
    back sanctioned, wanted, debarred and in public office. Only one of
    those stops the money."""
    person(engine, "p1")
    hit = {"id": "Q1", "caption": "Somebody", "score": 0.95, "match": True,
           "properties": {"topics": ["role.pep", "sanction", "wanted",
                                     "debarment"]},
           "datasets": ["a_list"]}
    client, _ = client_with(hit)
    results = screen(engine, "p1", screened_at=WHEN, client=client)
    assert results[0].event.payload["list_type"] == "SANCTIONS"


def test_no_pep_seniority_level_is_invented(engine):
    """The commercial registers sell a one-to-four scale. This provider
    publishes none and IFSCA does not use one, so nothing here may claim
    a level."""
    from vinzor.screening import _TOPIC_LISTS

    named = {kind for _, kind in _TOPIC_LISTS}
    assert not any(any(char.isdigit() for char in kind) for kind in named)
    assert "PEP" in named and "PEP_ASSOCIATE" in named

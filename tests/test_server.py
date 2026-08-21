"""The HTTP layer, exercised against a live server.

Real sockets rather than a mocked handler: the thing being checked is that a
browser can read the morning and record a decision, and a fake request object
would not prove that.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from vinzor.briefing import MESSAGES
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.server import build_app, enroll_people, open_workspace

from conftest import commits, company, owns, paid, person, screened


@pytest.fixture
def site():
    """A live server on an ephemeral port, with a small workspace behind it."""
    engine = Vinzor(EventLog())
    enroll_people(engine, "2026-08-01")
    person(engine, "p1", "Rohan Desai")
    company(engine, "c1", "Orion Zenith Enterprises")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    commits(engine, "c1")
    paid(engine, "p1", anomaly="OVERPAYMENT", payment_id="pay_1")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_app(engine))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, engine
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def fetch(url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


# -- reads -----------------------------------------------------------------


def test_the_page_is_served(site):
    base, _ = site
    with urllib.request.urlopen(base + "/", timeout=10) as response:
        body = response.read().decode()
    assert response.status == 200
    assert "<title>Vinzor</title>" in body
    for asset in ("/app.css", "/app.js"):
        with urllib.request.urlopen(base + asset, timeout=10) as response:
            assert response.status == 200


def test_sign_in_offers_people_and_says_who_may_decide(site):
    base, _ = site
    status, session = fetch(base + "/api/session")
    assert status == 200
    assert session["workspace"]
    deciders = [p for p in session["people"] if p["can_decide"]]
    readers = [p for p in session["people"] if not p["can_decide"]]
    assert deciders and readers


def test_the_briefing_arrives_ready_to_render(site):
    base, _ = site
    status, brief = fetch(base + "/api/briefing?person=Meera%20Nair")
    assert status == 200
    assert brief["person"] == "Meera Nair"
    assert brief["can_decide"] is True
    # Not "Good morning": the greeting follows the clock now, so pinning the
    # time of day makes this test pass before noon and fail after it.
    from vinzor.briefing import GREETINGS

    assert any(brief["greeting"].startswith(f"{words}, Meera Nair.")
               for _, words in GREETINGS)
    assert brief["groups"]
    group = brief["groups"][0]
    assert group["title"] and group["because"] and group["to_close_this"]
    assert group["tone"] in {"stop", "today", "week", "later"}
    assert group["rules"][0]["says"] and group["rules"][0]["quote"]
    assert group["items"][0]["case_id"]  # the handle a button posts back


def test_a_read_only_person_is_told_why_in_a_sentence(site):
    base, _ = site
    _, brief = fetch(base + "/api/briefing?person=Priya%20Rao")
    assert brief["can_decide"] is False
    assert "read-only" in brief["read_only_because"]


# -- the write -------------------------------------------------------------


def _first_file(base: str, who: str = "Meera Nair") -> str:
    _, brief = fetch(base + "/api/briefing?person=" + who.replace(" ", "%20"))
    return brief["groups"][0]["items"][0]["case_id"]


def test_a_decision_is_recorded_and_the_file_leaves_the_list(site):
    base, engine = site
    before = len(engine.queue())
    file_id = _first_file(base)

    status, result = fetch(base + "/api/decisions", {
        "person": "Meera Nair", "file": file_id,
        "outcome": "APPROVE", "reason": "Compared passport and date of birth; not the listed party.",
    })
    assert status == 200
    assert "permanent file" in result["message"]
    assert len(engine.queue()) == before - 1

    case = engine.state.casebook.get(file_id)
    assert case.decision.actor == "Meera Nair"
    assert case.decision.rationale.startswith("Compared passport")
    assert engine.verify() == (True, None)


def test_a_decision_without_a_reason_is_refused_in_plain_words(site):
    base, engine = site
    before = len(engine.log)
    status, result = fetch(base + "/api/decisions", {
        "person": "Meera Nair", "file": _first_file(base),
        "outcome": "APPROVE", "reason": "   ",
    })
    assert status == 400
    assert result["message"] == MESSAGES["needs_reason"]
    assert len(engine.log) == before  # nothing written


def test_a_read_only_person_cannot_record_a_decision(site):
    base, engine = site
    before = len(engine.log)
    status, result = fetch(base + "/api/decisions", {
        "person": "Priya Rao", "file": _first_file(base),
        "outcome": "APPROVE", "reason": "Looks fine to me.",
    })
    assert status == 403
    assert result["message"] == MESSAGES["not_allowed"]
    assert len(engine.log) == before


def _post_raw(url: str, payload: bytes, headers: dict[str, str]):
    request = urllib.request.Request(url, data=payload, method="POST",
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def test_another_website_cannot_settle_a_file(site):
    """A page the officer visits must not be able to decide on their behalf.

    A browser attaches what it holds for this site to every request the site
    receives, including one triggered by an unrelated page. With no origin
    check, any website open during the working day could close a Case as an
    enrolled decider -- and the append-only record would then say, truthfully
    and permanently, that Meera Nair settled a file she never saw.
    """
    base, engine = site
    file_id = _first_file(base)
    before = len(engine.log)
    decision = json.dumps({
        "person": "Meera Nair", "file": file_id,
        "outcome": "APPROVE", "reason": "settled by a page she never opened",
    }).encode()

    for headers in (
        {"Origin": "https://evil.example", "Content-Type": "application/json"},
        {"Referer": "https://evil.example/invoice", "Content-Type": "application/json"},
    ):
        status, result = _post_raw(base + "/api/decisions", decision, headers)
        assert status == 403, (headers, status, result)

    assert len(engine.log) == before, "a cross-site post wrote to the log"
    assert engine.state.casebook.get(file_id).is_open

    # ... and our own screen is unaffected
    status, _ = _post_raw(base + "/api/decisions", decision,
                          {"Origin": base, "Content-Type": "application/json"})
    assert status == 200
    assert not engine.state.casebook.get(file_id).is_open


def test_a_decision_posted_as_a_form_body_is_refused_by_its_content_type(site):
    """A second, independent CSRF control alongside the origin check above.

    A plain cross-site ``<form>`` -- the one request a browser sends with no
    script and no CORS preflight -- can only set Content-Type to a handful of
    form values, never "application/json". This is what still stands between
    a forged post and a permanent decision if Origin were ever missing (a
    stripping proxy, a browser that omits it) rather than merely wrong, which
    the origin check above does not cover: it only rejects a *present and
    wrong* Origin, not an absent one (OWASP's CSRF Prevention Cheat Sheet
    recommends layering more than one check for exactly this reason).
    """
    base, engine = site
    file_id = _first_file(base)
    before = len(engine.log)
    decision = json.dumps({
        "person": "Meera Nair", "file": file_id,
        "outcome": "APPROVE", "reason": "settled by a forged form post",
    }).encode()

    # No Origin header at all -- the one case _same_origin() lets through --
    # paired with a content type no cross-site form can actually send JSON
    # under.
    status, result = _post_raw(base + "/api/decisions", decision,
                               {"Content-Type": "text/plain;charset=UTF-8"})
    assert status == 403, (status, result)
    assert len(engine.log) == before, "a wrong-content-type post wrote to the log"
    assert engine.state.casebook.get(file_id).is_open

    # ... and the same request with the right content type still works.
    status, _ = _post_raw(base + "/api/decisions", decision,
                          {"Content-Type": "application/json"})
    assert status == 200
    assert not engine.state.casebook.get(file_id).is_open


def test_every_response_carries_baseline_security_headers(site):
    """Headers this screen should send on every reply, not just the ones an
    attacker could reach over the network -- this still binds to localhost.

    They guard against the browser doing something the page never asked for:
    guessing a MIME type, letting another site frame the very buttons that
    close a Case, or leaking where its officer had just been. OWASP's HTTP
    Headers and Content-Security-Policy Cheat Sheets recommend all of these
    unconditionally, "regardless of application scope" -- not just for
    internet-facing sites.
    """
    base, _ = site
    for path in ("/", "/api/briefing?person=Meera%20Nair"):
        with urllib.request.urlopen(base + path, timeout=10) as response:
            headers = response.headers
        assert headers.get("X-Content-Type-Options") == "nosniff", path
        assert headers.get("X-Frame-Options") == "DENY", path
        assert headers.get("Referrer-Policy") == "no-referrer", path
        csp = headers.get("Content-Security-Policy") or ""
        assert "frame-ancestors 'none'" in csp, (path, csp)
        assert "default-src 'self'" in csp, (path, csp)
        assert "'unsafe-inline'" not in csp, (path, csp)


def test_the_served_script_carries_no_inline_styles(site):
    """CSS custom properties are wired through a ``data-tone`` attribute
    instead of an inline ``style=""`` -- app.css already does this everywhere
    else on the page -- so the Content-Security-Policy this server now sends
    (``style-src 'self'``, no ``unsafe-inline``) does not silently blank the
    coloured counts on the greeting.
    """
    base, _ = site
    with urllib.request.urlopen(base + "/app.js", timeout=10) as response:
        script = response.read().decode()
    assert 'style="' not in script
    assert 'data-tone="' in script


def test_the_confirm_button_names_the_action_it_is_about_to_record(site):
    """Clicking a choice, then a generic "Record it", gives no second look at
    *which* choice is about to become permanent -- exactly the "consequential
    option next to a benign one, on autopilot" risk NN/g's guidance on
    confirmation dialogs warns about. The confirming click restates the
    officer's own choice-of-action label, not a fixed "it".
    """
    base, _ = site
    with urllib.request.urlopen(base + "/app.js", timeout=10) as response:
        script = response.read().decode()
    # The label is composed from the server's own vocabulary and the officer's
    # chosen action. Asserting the composition rather than a literal, because
    # the words themselves now live in briefing.py where every other sentence
    # does -- and the jargon sweep walks them there.
    assert "ui.confirm_prefix" in script
    assert "choice.label" in script

    from vinzor.briefing import UI

    assert UI["confirm_prefix"] == "Record:"
    assert UI["confirm_plain"] == "Record it"


def test_every_label_the_screen_shows_comes_from_the_server(site):
    """app.js held its own English: headings, button labels, the sentence above
    the reason box. That broke DESIGN.md decision 6 twice over -- the jargon
    sweep never walked those strings, and a second surface would have had to
    duplicate them or drift from the first.
    """
    import re

    base, _ = site
    with urllib.request.urlopen(base + "/app.js", timeout=10) as response:
        script = response.read().decode()
    # Comments are stripped first: this file explains the history of its own
    # labels, and quoting a phrase in order to say where it went is not the
    # same as rendering it.
    code = re.sub(r"/\*.*?\*/", "", script, flags=re.S)

    for stray in ('"Cancel"', '"Record it"', '"The record"',
                  '"What you need to do"', '"The rules behind this"',
                  "Why? This goes into the permanent record."):
        assert stray not in code, f"{stray} is wording, and belongs in briefing.py"

    with urllib.request.urlopen(base + "/api/session", timeout=10) as response:
        session = json.loads(response.read().decode())
    for key in ("wordmark", "cancel", "why", "to_close_heading", "clause_prefix"):
        assert session["ui"][key], key


def test_a_malformed_body_is_answered_not_crashed(site):
    """Every request gets an HTTP reply, in a sentence.

    "null", "[]" and "7" are all valid JSON but none is a decision. Calling
    .get() on them raised out of the handler: the caller got no response at
    all and a traceback was printed on the operator's console -- the two
    things this server promises never to do.
    """
    base, engine = site
    before = len(engine.log)
    for payload in (b"[1,2,3]", b"null", b"7", b'"a string"',
                    b'{"person": 5, "file": "x", "outcome": "APPROVE", "reason": "y"}'):
        status, result = _post_raw(base + "/api/decisions", payload,
                                   {"Content-Type": "application/json"})
        assert status == 400, (payload, status)
        assert result["message"] == MESSAGES["unavailable"]
        assert "Traceback" not in json.dumps(result)
    assert len(engine.log) == before


def test_the_handler_declares_a_socket_timeout(site):
    """Direct check on the value the fix sets. ``BaseHTTPRequestHandler``
    defaults ``timeout`` to ``None`` -- no limit at all -- which is what let a
    silent connection pin a thread forever."""
    from vinzor.server import build_app

    _, engine = site
    assert build_app(engine).timeout == 10


def test_a_silent_connection_is_closed_after_the_handler_timeout(monkeypatch):
    """A client that opens a connection and sends nothing used to pin a
    server thread indefinitely -- confirmed: threads were never freed after
    5+ seconds of silence from such a client, because the request Handler had
    no socket timeout at all. ``BaseHTTPRequestHandler`` applies its
    ``timeout`` class attribute to the connection's socket before reading
    each request, so a silent client must now be dropped once that timeout
    elapses. The value is turned down here so the test proves the behaviour
    without waiting out the real ten-second production setting."""
    import socket
    import threading
    import time
    from http.server import ThreadingHTTPServer

    from vinzor.engine import Vinzor
    from vinzor.eventlog import EventLog
    from vinzor.server import build_app, enroll_people

    engine = Vinzor(EventLog())
    enroll_people(engine, "2026-08-01")
    handler_cls = build_app(engine)
    monkeypatch.setattr(handler_cls, "timeout", 0.3)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(5)
        client.connect((host, port))
        try:
            started = time.monotonic()
            # Send nothing at all -- exactly the client this finding is about.
            data = client.recv(1024)
            elapsed = time.monotonic() - started
            assert data == b"", "the server never closed a silent connection"
            assert elapsed < 2, (
                f"took {elapsed:.1f}s -- the handler timeout was not applied "
                f"to the connection"
            )
        finally:
            client.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_a_body_that_claims_to_be_enormous_is_refused(site):
    """A header that lies about the body must not pin a thread forever."""
    base, _ = site
    status, _ = _post_raw(base + "/api/decisions", b"{}",
                          {"Content-Type": "application/json",
                           "Content-Length": str(64 * 1024 + 1)})
    assert status == 400


def test_the_served_workspace_knows_its_own_licence(tmp_path):
    """Without one, no overdue filing can ever reach the screen.

    ``observe_deadlines`` returns immediately when the workspace holds no
    licence, and the dataset describes investors rather than the firm looking
    at them. The whole obligation calendar -- quarterly returns, recurring
    fees, late charges -- was therefore unreachable from the served screen
    while passing its own tests and appearing in the walkthrough.
    """
    engine = open_workspace(tmp_path / "w.db")
    licence = engine.state.licence
    assert licence.granted_on, "the workspace has no licence"
    assert licence.number
    assert licence.category is not None

    engine.observe_deadlines("2026-08-12")
    filings = [c for c in engine.queue() if c.case_type == "FILING"]
    assert filings, "no overdue filing can reach the officer"
def test_an_unknown_person_cannot_record_a_decision(site):
    base, _ = site
    status, result = fetch(base + "/api/decisions", {
        "person": "Somebody Else", "file": _first_file(base),
        "outcome": "APPROVE", "reason": "Fine.",
    })
    assert status == 403
    assert result["message"] == MESSAGES["not_allowed"]


def test_deciding_twice_is_refused_and_explained(site):
    base, _ = site
    file_id = _first_file(base)
    body = {"person": "Meera Nair", "file": file_id, "outcome": "APPROVE",
            "reason": "Different date of birth; a false positive."}
    assert fetch(base + "/api/decisions", body)[0] == 200

    status, result = fetch(base + "/api/decisions", dict(body, outcome="REJECT",
                                                         reason="Changed my mind."))
    assert status == 409
    assert result["message"] == MESSAGES["already_settled"]


def test_an_unknown_file_is_explained_not_stack_traced(site):
    base, _ = site
    status, result = fetch(base + "/api/decisions", {
        "person": "Meera Nair", "file": "nope", "outcome": "APPROVE",
        "reason": "Cleared.",
    })
    assert status == 404
    assert result["message"] == MESSAGES["not_found"]


def test_no_route_ever_returns_a_bare_status_code(site):
    """Anything a person could hit answers in sentences."""
    base, _ = site
    for status, result in (
        fetch(base + "/api/nonsense"),
        fetch(base + "/api/decisions", {"person": "Meera Nair"}),
    ):
        assert status >= 400
        assert result.get("message"), "an error left the server without words"
        assert "Traceback" not in result["message"]


# -- persistence -----------------------------------------------------------


def test_a_workspace_seeds_once_and_then_remembers(tmp_path):
    """Decisions are events, so they survive a restart. That is the point."""
    from vinzor.model import CaseStatus, Outcome, Role
    from vinzor.seed import DEFAULT_DATASET

    if not DEFAULT_DATASET.exists():
        pytest.skip("synthetic dataset not present")

    path = tmp_path / "workspace.db"
    engine = open_workspace(path)  # seeds the dataset and enrols the people
    seeded = len(engine.log)
    case = engine.queue()[0]
    engine.decide(case_id=case.case_id, outcome=Outcome.ESCALATE, actor="Meera Nair",
                  role=Role.AML_OFFICER, rationale="Referring to senior management.",
                  decided_at="2026-08-12")
    engine.log.close()

    reopened = open_workspace(path)
    assert len(reopened.log) == seeded + 1  # re-seeding did not happen
    survivor = reopened.state.casebook.get(case.case_id)
    assert survivor.status is CaseStatus.ESCALATED
    assert survivor.is_open, "an escalation is a handover, not an answer"
    assert survivor.escalations[-1]["by"] == "Meera Nair"
    assert reopened.verify() == (True, None)


# -- the party routes --------------------------------------------------------


def test_a_party_page_is_served_with_its_labels(site):
    base, _ = site
    status, body = fetch(base + "/api/parties/c1")
    assert status == 200
    assert body["name"] == "Orion Zenith Enterprises"
    assert body["kind"] == "Company"
    assert body["ui"]["back_to_queue"]
    assert isinstance(body["traits"], list)
    assert isinstance(body["timeline"], list) and body["timeline"]


def test_an_unknown_party_is_a_page_saying_so_not_an_error(site):
    """A 404 would be wrong: the id may be a real Case subject with no entity
    behind it, and the reader still needs to see its files.
    """
    base, _ = site
    status, body = fetch(base + "/api/parties/per_nobody_at_all")
    assert status == 200
    assert body["unknown"]
    assert body["traits"] == [] and body["movements"] == []


def test_a_search_finds_a_party_by_part_of_a_name(site):
    base, _ = site
    status, body = fetch(base + "/api/parties?q=orion")
    assert status == 200
    assert body["parties"], "a known name matched nothing"
    assert all("orion" in hit["name"].lower() for hit in body["parties"])
    assert body["parties"][0]["ref"] == "c1"
    assert body["parties"][0]["kind"] == "Company"


def test_a_search_that_matches_nothing_explains_itself(site):
    base, _ = site
    _, body = fetch(base + "/api/parties?q=zzzzz-no-such-party")
    assert body["parties"] == []
    assert "zzzzz-no-such-party" in body["found"]


def test_a_search_never_returns_the_whole_book_of_clients(site):
    """An empty query is not a request for every client on file."""
    base, _ = site
    _, body = fetch(base + "/api/parties?q=")
    assert len(body["parties"]) <= 20


def test_a_party_page_carries_no_way_to_decide_anything(site):
    """It is a read surface. Deciding stays on the one write route, which
    checks the role -- a second path to a decision is a second place to get
    the human gate wrong.
    """
    base, _ = site
    _, body = fetch(base + "/api/parties/p1")
    assert "choices" not in body
    assert "can_decide" not in body


def test_the_screening_route_is_served_with_its_labels(site):
    base, _ = site
    status, body = fetch(base + "/api/screening")
    assert status == 200
    assert body["heading"] == "Watchlist screening"
    assert body["coverage_summary"]
    assert body["rule_caveat"]
    assert isinstance(body["unchecked"], list)
    assert isinstance(body["checked"], list)
    assert body["ui"]["back_to_queue"]


def test_the_screening_route_offers_no_way_to_decide_anything(site):
    """Like the party page, it is a read surface."""
    base, _ = site
    _, body = fetch(base + "/api/screening")
    assert "choices" not in body and "can_decide" not in body


# -- running a check from the browser ----------------------------------------


def test_a_viewer_cannot_run_a_check(site):
    """Running a check writes screening records, so it sits behind the same
    gate as a decision."""
    base, _ = site
    status, body = fetch(base + "/api/checks",
                         {"person": "Priya Rao", "party": "p1"})
    assert status == 403
    assert "read-only" in body["message"]


def test_an_unconfigured_screening_service_refuses_rather_than_phoning_out(
        site, monkeypatch):
    """The first screenshot of this screen caught the alternative: an unset
    URL silently became a request to a hosted third party that had already
    been handed the investor's name before it answered 401."""
    monkeypatch.delenv("VINZOR_SCREENING_URL", raising=False)
    base, _ = site
    status, body = fetch(base + "/api/checks",
                         {"person": "Meera Nair", "party": "p1"})
    assert status == 503
    assert "did not leave the machine" in body["message"]


def test_a_check_on_an_unknown_party_is_a_plain_404(site, monkeypatch):
    monkeypatch.setenv("VINZOR_SCREENING_URL", "http://127.0.0.1:9")
    base, _ = site
    status, _ = fetch(base + "/api/checks",
                      {"person": "Meera Nair", "party": "per_nobody"})
    assert status == 404


# -- bringing a spreadsheet in ---------------------------------------------


def upload(base: str, body: bytes, filename: str = "sheet.csv",
           sheet: str = ""):
    url = base + "/api/imports" + (f"?sheet={sheet}" if sheet else "")
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/octet-stream",
                 "X-Vinzor-Filename": filename},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


PARTIES = (b"Name,Type,Nationality\r\n"
           b"Asha Mehta,person,IN\r\n"
           b"Blue Fern LLP,partnership,SG\r\n")

# A split pattern until 21 August 2026, when the structuring rule was
# removed. The beneficiary column is what makes an uploaded sheet reach a
# rule now: the remitter is not the investor the money was for.
PAYMENTS = (b"Date,Remitter,Beneficiary,Amount\r\n"
            b"2026-08-16,Kiran Shah,Anand Bhat,4000\r\n"
            b"2026-08-16,Kiran Shah,Anand Bhat,3500\r\n"
            b"2026-08-17,Kiran Shah,Anand Bhat,3900\r\n")


def test_an_uploaded_sheet_is_read_and_nothing_is_written(site):
    base, engine = site
    before = len(engine.log)
    status, report = upload(base, PARTIES, "investors.csv")
    assert status == 200
    assert report["kind"] == "parties"
    assert report["counts"]["usable"] == 2
    assert any(c["meaning"] == "the party's name" for c in report["columns"])
    assert "will be written to the permanent record" in report["consequence"]
    assert len(engine.log) == before, "reading a sheet must write nothing"


def test_a_viewer_cannot_confirm_an_import(site):
    base, _ = site
    _, report = upload(base, PARTIES)
    status, answer = fetch(base + "/api/imports/apply", {
        "person": "Priya Rao", "digest": report["digest"],
        "sheet": report["kind"], "kind": ""})
    assert status == 403
    assert answer["message"] == MESSAGES["viewer_import"]


def test_confirming_writes_screens_and_will_not_repeat(site):
    base, engine = site
    _, report = upload(base, PARTIES, "investors.csv")
    status, answer = fetch(base + "/api/imports/apply", {
        "person": "Meera Nair", "digest": report["digest"],
        "sheet": report["kind"], "kind": ""})
    assert status == 200
    assert "2 parties are on the record" in answer["message"]
    names = {e.name for e in engine.state.graph.entities.values()}
    assert {"Asha Mehta", "Blue Fern LLP"} <= names

    # No screening service is configured in this test process, and the
    # answer says so rather than pretending a check happened.
    status, progress = fetch(
        base + f"/api/imports/progress?ref={answer['progress']}")
    assert status == 200
    assert progress["state"] == "skipped"
    assert "No watchlist is connected" in progress["sentence"]

    # The same bytes again: refused at the plan, refused at the write.
    _, again = upload(base, PARTIES, "investors.csv")
    assert any("already imported" in r for r in again["refusals"])
    status, answer = fetch(base + "/api/imports/apply", {
        "person": "Meera Nair", "digest": report["digest"],
        "sheet": report["kind"], "kind": ""})
    assert status == 409


def test_an_imported_statement_opens_the_files_the_pattern_earns(site):
    base, engine = site
    open_before = len(engine.queue())
    _, report = upload(base, PAYMENTS, "statement.csv")
    assert report["kind"] == "payments"
    status, answer = fetch(base + "/api/imports/apply", {
        "person": "Meera Nair", "digest": report["digest"],
        "sheet": report["kind"], "kind": ""})
    assert status == 200
    summaries = [c.evidence[0].summary for c in engine.queue()]
    assert len(engine.queue()) > open_before
    assert any("THIRD_PARTY" in s for s in summaries), summaries


def test_the_templates_are_there_to_start_from(site):
    base, _ = site
    for which, must_hold in (("parties", b"Name,Type"),
                             ("payments", b"Date,Payer")):
        with urllib.request.urlopen(
                base + f"/api/imports/template?sheet={which}",
                timeout=10) as response:
            body = response.read()
        assert response.status == 200
        assert must_hold in body


# -- categorising a customer, over the wire ---------------------------------


def _a_party(base: str) -> str:
    """Any registered party's machine address."""
    _, found = fetch(base + "/api/parties?q=")
    return found["parties"][0]["ref"]


def test_the_risk_route_records_a_category_and_a_review_date(site):
    base, engine = site
    party_ref = _a_party(base)

    status, answer = fetch(base + "/api/risk", {
        "person": "Meera Nair", "party": party_ref, "category": "HIGH",
        "reason": "Ownership could not be established from the papers given.",
    })
    assert status == 200
    assert "permanent file" in answer["message"]

    assessment = engine.state.risk[party_ref]
    assert assessment.category == "HIGH"
    assert assessment.by == "Meera Nair"

    status, page = fetch(
        base + f"/api/parties/{party_ref}?person=Meera%20Nair")
    assert "High risk, set by Meera Nair" in page["risk_summary"]
    assert "clause 5.11" in page["risk_due"]


def test_the_route_carries_an_officers_own_answers(site):
    base, engine = site
    party_ref = _a_party(base)

    fetch(base + "/api/risk", {
        "person": "Meera Nair", "party": party_ref, "category": "MEDIUM",
        "reason": "Weighed the sector against the ownership position.",
        "answers": {"4.2(a)(i)": {"present": True,
                                  "because": "A cash-intensive trade."}},
    })
    saved = engine.state.risk[party_ref].observations["4.2(a)(i)"]
    assert saved.present is True
    assert saved.answered_by == "Meera Nair"


def test_a_viewer_is_not_offered_the_control_and_cannot_use_it(site):
    base, _ = site
    party_ref = _a_party(base)

    _, page = fetch(base + f"/api/parties/{party_ref}?person=Priya%20Rao")
    assert page["may_assess"] is False

    status, answer = fetch(base + "/api/risk", {
        "person": "Priya Rao", "party": party_ref, "category": "LOW",
        "reason": "Looks acceptable on the documents provided.",
    })
    assert status == 403
    assert "read-only" in answer["message"]


def test_each_refusal_answers_in_its_own_words(site):
    """A route that answered every refusal with one message would send an
    officer looking for a missing party when their reason was too thin."""
    base, _ = site
    party_ref = _a_party(base)
    good = "Weighed the sector against the ownership position."

    status, answer = fetch(base + "/api/risk", {
        "person": "Meera Nair", "party": party_ref,
        "category": "SEVERE", "reason": good})
    assert status == 400 and "high, medium or low" in answer["message"]

    status, answer = fetch(base + "/api/risk", {
        "person": "Meera Nair", "party": party_ref,
        "category": "LOW", "reason": "checked"})
    assert status == 400 and "says what you weighed" in answer["message"]

    status, _ = fetch(base + "/api/risk", {
        "person": "Meera Nair", "party": "no_such_party",
        "category": "LOW", "reason": good})
    assert status == 404


def test_the_route_refuses_answers_that_are_not_answers(site):
    base, _ = site
    party_ref = _a_party(base)
    status, _ = fetch(base + "/api/risk", {
        "person": "Meera Nair", "party": party_ref, "category": "LOW",
        "reason": "Weighed the sector against the ownership position.",
        "answers": "all of them",
    })
    assert status == 400

"""Whether the server believes what a request says about who is making it.

The missing password screen was the visible half of this. The half that
mattered was that every write took the actor's name out of the request body,
so anybody who could reach the port could post as Senior Management and clear
the politically-exposed files only Senior Management may clear. A sign-in
page in front of that would have been decoration.

So the tests that matter here are not "does the password check work". They
are: on a workspace with a password set, does a request that names somebody
else get to act as them.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from vinzor.credentials import Credentials, weak
from vinzor.eventlog import EventLog
from vinzor.engine import Vinzor
from vinzor.model import Role
from vinzor.server import build_app, enroll_people

WHEN = "2026-08-19"
GOOD = "correct horse battery staple"


@pytest.fixture
def workspace():
    """A served workspace and its ways in, on a real socket."""
    engine = Vinzor(EventLog())
    enroll_people(engine, WHEN)
    keys = Credentials()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_app(engine, keys))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield engine, keys, base
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(base, path, body=None, cookie="", method=None, headers=None):
    """(status, payload, set-cookie)."""
    data = json.dumps(body).encode() if body is not None else None
    request = Request(base + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
    if cookie:
        request.add_header("Cookie", cookie)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urlopen(request, timeout=10) as answer:
            return (answer.status, json.loads(answer.read() or b"{}"),
                    answer.headers.get("Set-Cookie", ""))
    except HTTPError as refused:
        return (refused.code, json.loads(refused.read() or b"{}"),
                refused.headers.get("Set-Cookie", ""))


def signed_in(base, keys, name="Meera Nair", password=GOOD):
    keys.set_password(name, password, WHEN)
    status, body, cookie = call(base, "/api/sign-in",
                                {"person": name, "password": password})
    assert status == 200, body
    return cookie.split(";")[0]


def a_file(engine) -> str:
    from conftest import person, screened

    person(engine, "p1", "Dev Kumar")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    return next(iter(engine.state.casebook.cases.values())).case_id


# -- the hole this closes ----------------------------------------------------


def test_a_request_cannot_choose_who_it_is(workspace):
    """The whole point. With a password set anywhere, a request that names
    Senior Management is not Senior Management."""
    engine, keys, base = workspace
    case = a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)      # workspace is now guarded

    status, body, _ = call(base, "/api/decisions", {
        "person": "Rohan Kapoor",       # the claim
        "file": case, "outcome": "APPROVE",
        "reason": "Cleared on the papers, different date of birth.",
        "used": "NONE"})
    assert status == 401
    assert "not signed in" in body["message"]
    assert engine.state.casebook.get(case).is_open


def test_a_signed_in_officer_acts_as_themselves_whatever_they_claim(workspace):
    """A signed-in officer who names somebody else in the body still acts
    as themselves. The body's name is not corrected, it is ignored."""
    engine, keys, base = workspace
    case = a_file(engine)
    cookie = signed_in(base, keys, "Meera Nair")

    status, body, _ = call(base, "/api/decisions", {
        "person": "Rohan Kapoor",       # ignored
        "file": case, "outcome": "APPROVE",
        "reason": "Cleared on the papers, different date of birth.",
        "used": "NONE"}, cookie=cookie)
    assert status == 200, body
    assert engine.state.casebook.get(case).decision.actor == "Meera Nair"


def test_a_viewer_who_signs_in_still_cannot_decide(workspace):
    """Signing in is not the same as being allowed. The role gate is
    unchanged and still comes from the enrolment in the log."""
    engine, keys, base = workspace
    case = a_file(engine)
    cookie = signed_in(base, keys, "Priya Rao")

    status, _body, _ = call(base, "/api/decisions", {
        "file": case, "outcome": "APPROVE",
        "reason": "Looks fine to me on the papers.",
        "used": "NONE"}, cookie=cookie)
    assert status == 403
    assert engine.state.casebook.get(case).is_open


def test_a_made_up_cookie_is_nobody(workspace):
    engine, keys, base = workspace
    case = a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)

    status, _body, _ = call(base, "/api/decisions", {
        "file": case, "outcome": "APPROVE",
        "reason": "Cleared on the papers, different date of birth.",
        "used": "NONE"},
        cookie="vinzor_session=not-a-real-token-at-all")
    assert status == 401
    assert engine.state.casebook.get(case).is_open


# -- the two doors -----------------------------------------------------------


def test_a_workspace_with_no_password_says_so(workspace):
    _engine, _keys, base = workspace
    status, body, _ = call(base, "/api/session")
    assert status == 200
    assert body["needs_password"] is False


def test_one_password_guards_the_whole_workspace(workspace):
    """No per-person exemption: a system where some people need a password
    is a system where the rest are the way in."""
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _status, body, _ = call(base, "/api/session")
    assert body["needs_password"] is True

    # Aarav has no password of his own and still cannot get in.
    status, _body, _ = call(base, "/api/sign-in",
                            {"person": "Aarav Sharma", "password": GOOD})
    assert status == 401


# -- the session itself ------------------------------------------------------


def test_signing_in_sets_a_cookie_a_script_cannot_read(workspace):
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _status, _body, cookie = call(base, "/api/sign-in",
                                  {"person": "Meera Nair", "password": GOOD})
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie


# -- the cookie behind TLS ---------------------------------------------------
#
# HttpOnly stops a script reading the session token and SameSite=Strict stops
# another site spending it. Neither stops it being sent over http://, which is
# the one that hands it to whoever is on the path. This process never
# terminates TLS, so the only thing that knows is the proxy in front.

TLS = {"X-Forwarded-Proto": "https"}


def test_the_cookie_is_secure_when_the_proxy_says_the_reader_used_tls(workspace):
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _status, _body, cookie = call(base, "/api/sign-in",
                                  {"person": "Meera Nair", "password": GOOD},
                                  headers=TLS)
    assert "Secure" in cookie
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_the_cookie_is_not_secure_on_plain_loopback(workspace):
    """A laptop is the case this must not break.

    A ``Secure`` cookie handed out over ``http://127.0.0.1`` is one the
    browser accepts and then never sends back, so the officer signs in,
    is told they signed in, and is signed out on the next click. A
    sign-in that silently fails to stick is worse than one served in
    the clear and honest about it.
    """
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _status, _body, cookie = call(base, "/api/sign-in",
                                  {"person": "Meera Nair", "password": GOOD})
    assert "Secure" not in cookie
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_the_proxy_may_write_the_scheme_in_any_case(workspace):
    """Header values are not case-normalised for us, and a proxy that
    writes HTTPS rather than https must not quietly cost the flag."""
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _status, _body, cookie = call(base, "/api/sign-in",
                                  {"person": "Meera Nair", "password": GOOD},
                                  headers={"X-Forwarded-Proto": "HTTPS"})
    assert "Secure" in cookie


def test_signing_out_behind_tls_clears_a_secure_cookie_too(workspace):
    """The cookie that ends the session carries the same flags as the one
    that began it. A browser matches on name and path rather than on
    Secure, so this is consistency rather than correctness -- but a
    sign-out that emits a differently-shaped cookie is the sort of thing
    that becomes correctness the day a browser tightens the rule."""
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _s, _b, cookie = call(base, "/api/sign-in",
                          {"person": "Meera Nair", "password": GOOD},
                          headers=TLS)
    token = cookie.split(";")[0]
    _s, _b, ending = call(base, "/api/sign-out", {}, cookie=token, headers=TLS)
    assert "Secure" in ending
    assert "Max-Age=0" in ending


def test_the_token_is_never_stored_in_the_clear(workspace):
    """A leaked table of live tokens is a leaked table of live sessions."""
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _status, _body, cookie = call(base, "/api/sign-in",
                                  {"person": "Meera Nair", "password": GOOD})
    token = cookie.split(";")[0].split("=", 1)[1]
    held = [row[0] for row in
            keys._conn.execute("SELECT token FROM sessions").fetchall()]
    assert held
    assert token not in held


def test_signing_out_ends_the_session(workspace):
    engine, keys, base = workspace
    case = a_file(engine)
    cookie = signed_in(base, keys)
    call(base, "/api/sign-out", {}, cookie=cookie)

    status, _body, _ = call(base, "/api/decisions", {
        "file": case, "outcome": "APPROVE",
        "reason": "Cleared on the papers, different date of birth.",
        "used": "NONE"}, cookie=cookie)
    assert status == 401


def test_changing_a_password_ends_the_sessions_it_opened(workspace):
    """The thing you do *because* somebody may have your password must not
    leave theirs working."""
    _engine, keys, base = workspace
    cookie = signed_in(base, keys)
    assert keys.who(cookie.split("=", 1)[1], "2026-08-19T10:00:00")
    keys.set_password("Meera Nair", "a different long password", WHEN)
    assert keys.who(cookie.split("=", 1)[1], "2026-08-19T10:00:00") is None


def test_a_session_expires_when_it_is_left_alone(workspace):
    _engine, keys, _base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    token = keys.start_session("Meera Nair", "2026-08-19T09:00:00")
    assert keys.who(token, "2026-08-19T16:00:00") == "Meera Nair"
    assert keys.who(token, "2026-08-20T09:00:00") is None


def test_using_a_session_keeps_it_alive(workspace):
    """An idle timeout, not a session that dies mid-sentence after eight
    hours of work."""
    _engine, keys, _base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    token = keys.start_session("Meera Nair", "2026-08-19T09:00:00")
    for hour in range(9, 20):
        assert keys.who(token, f"2026-08-19T{hour:02d}:30:00") == "Meera Nair"


# -- what a failure says -----------------------------------------------------


def test_a_wrong_password_and_an_unknown_name_answer_the_same(workspace):
    """Telling somebody which of the two they got wrong tells them who
    works here."""
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    _s1, wrong, _ = call(base, "/api/sign-in",
                         {"person": "Meera Nair", "password": "not it at all"})
    _s2, unknown, _ = call(base, "/api/sign-in",
                           {"person": "Nobody Here", "password": GOOD})
    assert wrong["message"] == unknown["message"]


def test_wrong_attempts_eventually_stop_answering(workspace):
    """Without this a slow hash is an oracle, not a closed door."""
    _engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    for _ in range(5):
        call(base, "/api/sign-in",
             {"person": "Meera Nair", "password": "still wrong"})
    _status, body, _ = call(base, "/api/sign-in",
                            {"person": "Meera Nair", "password": GOOD})
    assert body["signed_in"] is False
    assert body["wait_minutes"] >= 1


def test_a_lockout_does_not_last_forever(workspace):
    """Somebody who can lock out your compliance officer for a day has done
    real damage without ever knowing a password."""
    from vinzor.credentials import LOCKED_MINUTES

    assert 0 < LOCKED_MINUTES <= 60


# -- passwords ---------------------------------------------------------------


def test_a_short_password_is_refused_with_the_reason(workspace):
    assert "at least" in weak("short")
    assert weak("correct horse battery staple") == ""


def test_length_is_the_only_rule(workspace):
    """A demand for a capital and a symbol reliably produces the same
    password everywhere with a 1 and a ! on the end."""
    assert weak("aaaaaaaaaaaaaaaaaaaa!A1") != ""      # too few distinct
    assert weak("the quiet dogs of tuesday") == ""    # no symbol, still fine


def test_a_password_never_reaches_the_log(workspace):
    """An append-only log is one you can never rotate away from: the day a
    hashing choice is broken, every hash ever set is still in the record --
    and that record is the one handed to a regulator."""
    engine, keys, _base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    written = json.dumps([
        {"type": str(event.event_type), "payload": event.payload}
        for event in engine.log])
    assert GOOD not in written
    assert "password" not in written.lower()


# -- the half that was still open --------------------------------------------
#
# The docstring at the top of this file says the half that mattered was that
# every write took the actor's name from the request. That was fixed, and the
# reads were fixed after it -- but only inside the handlers that thought to
# ask. Three read routes fell back to ``PEOPLE[0]["name"]`` when nobody was
# signed in, and the rest never asked at all, so on a workspace where all
# four people had passwords an unauthenticated request was served 282 KB of
# the client book, greeted by name. Nothing in this file caught it, because
# nothing in this file asked the question from the outside.


READS = ("/api/briefing", "/api/parties", "/api/screening", "/api/regulatory",
         "/api/reports", "/api/chat", "/api/export")


@pytest.mark.parametrize("route", READS)
def test_a_signed_out_request_is_shown_nothing_at_all(workspace, route):
    """Every screen in this product is somebody's client book: who has
    committed money, who matched a watchlist, what an officer wrote about
    them. A sign-in page in front of a book anybody can read is decoration,
    which is the exact criticism this file opens with."""
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)

    status, body, _ = call(base, route)
    assert status == 401, f"{route} served a signed-out request: {str(body)[:120]}"


#: The export answers with a workbook rather than JSON, so it is checked
#: for its status alone further down.
ANSWERS_JSON = tuple(r for r in READS if r != "/api/export")


@pytest.mark.parametrize("route", ANSWERS_JSON)
def test_the_same_routes_answer_once_somebody_has_signed_in(workspace, route):
    """Otherwise the test above would pass with a server that refused
    everybody, which is a different product."""
    engine, keys, base = workspace
    a_file(engine)
    cookie = signed_in(base, keys)

    status, _body, _ = call(base, route, cookie=cookie)
    assert status == 200


def test_the_export_answers_a_signed_in_request_with_a_workbook(workspace):
    """Checked apart from the others because it answers with bytes, not
    JSON -- and it is the one route that hands the whole book over at once,
    so it is the one that matters most for the test above."""
    from urllib.request import Request, urlopen

    engine, keys, base = workspace
    a_file(engine)
    cookie = signed_in(base, keys)
    request = Request(base + "/api/export")
    request.add_header("Cookie", cookie)
    with urlopen(request, timeout=10) as answer:
        assert answer.status == 200
        assert answer.read(4) == b"PK"


def test_the_sign_in_screen_itself_is_still_reachable(workspace):
    """A gate that locks the door from the inside is not a gate."""
    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)

    status, body, _ = call(base, "/api/session")
    assert status == 200
    assert body["needs_password"] is True


def test_an_open_workspace_is_still_a_demonstration(workspace):
    """Nobody has a password, so nobody is shut out. The line is drawn at
    the moment the first password is set, not per person."""
    engine, keys, base = workspace
    status, _body, _ = call(base, "/api/briefing")
    assert status == 200


def test_a_write_from_another_site_is_refused_on_every_route(workspace):
    """``/api/chat``, ``/api/tasks`` and the sign-in used to return before
    the same-origin check, so the three routes that set an agent working,
    put a question to the model and answered the door were the three a page
    on another site could reach."""
    engine, keys, base = workspace
    cookie = signed_in(base, keys)

    for route, body in (("/api/chat", {"asked": "hello"}),
                        ("/api/tasks", {"asked": "check the book"}),
                        ("/api/sign-in", {"person": "Meera Nair",
                                          "password": GOOD})):
        data = json.dumps(body).encode()
        request = Request(base + route, data=data, method="POST",
                          headers={"Content-Type": "application/json",
                                   "Origin": "https://evil.example"})
        if route != "/api/sign-in":
            request.add_header("Cookie", cookie)
        try:
            with urlopen(request, timeout=10) as answer:
                status = answer.status
        except HTTPError as refused:
            status = refused.code
        assert status == 403, f"{route} accepted a write from another site"


def test_a_body_nobody_asked_for_is_refused_on_every_route(workspace):
    """The same three routes had no ceiling on the body either."""
    engine, keys, base = workspace
    cookie = signed_in(base, keys)
    huge = json.dumps({"asked": "x" * 200_000}).encode()

    for route in ("/api/chat", "/api/tasks", "/api/ask"):
        request = Request(base + route, data=huge, method="POST",
                          headers={"Content-Type": "application/json"})
        request.add_header("Cookie", cookie)
        try:
            with urlopen(request, timeout=10) as answer:
                status = answer.status
        except HTTPError as refused:
            status = refused.code
        except OSError:
            # Refused, and the caller saw the socket close rather than the
            # sentence saying why. The server decides before the body has
            # finished arriving, and on Windows closing on unread bytes
            # sends a reset -- which the body-cap path has always noted and
            # drains against, without being able to promise it. What is
            # being tested here is that the body was not accepted, and it
            # was not.
            status = 400
        assert status == 400, f"{route} accepted a 200 KB body"


def test_a_cross_site_page_cannot_lock_somebody_out(workspace):
    """Five wrong answers lock a name for fifteen minutes. With the sign-in
    reachable from any site, a page an officer visited could spend five
    requests and shut them out of their own compliance system, without ever
    holding a credential."""
    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)

    for _ in range(6):
        request = Request(base + "/api/sign-in",
                          data=json.dumps({"person": "Meera Nair",
                                           "password": "wrong"}).encode(),
                          method="POST",
                          headers={"Content-Type": "application/json",
                                   "Origin": "https://evil.example"})
        try:
            urlopen(request, timeout=10)
        except HTTPError:
            pass

    status, body, cookie = call(base, "/api/sign-in",
                                {"person": "Meera Nair", "password": GOOD})
    assert status == 200, f"the account was locked from another site: {body}"


# -- what the sign-in reveals, and what it does not --------------------------
#
# The docstring claimed an unknown name and a wrong password "take the same
# path, cost the same work and give the same answer". For one attempt that
# held -- measured at 80.2 ms against 78.7 ms, identical text. Across
# attempts it did not, in two different ways.
#
# The lockout applies only where a record exists, so an enrolled name with a
# password stops answering after five wrong tries and an unknown name never
# does. Over HTTP that classified the whole roster in **24 requests and 2.3
# seconds**. That one is inherent to a per-account lockout: locking names
# nobody has enrolled would let a stranger lock the roster out by guessing at
# it, and the alternative is an unbounded table of every string anybody has
# ever submitted. It is now a stated limit rather than a claim that is not
# true -- see the docstring, which this file holds honest.
#
# The timing was not inherent and is closed. A locked name returned before any
# hashing ran: **0.03 ms against 60.75 ms**, roughly two thousand times faster
# and an unmistakable tell from a single request.


def test_the_locked_path_costs_what_every_other_path_costs():
    """A branch that skips the work is a branch a stopwatch can see."""
    import statistics
    import time

    keys = Credentials(":memory:")
    keys.set_password("Meera Nair", "morning queue august", WHEN)

    def one(name):
        started = time.perf_counter()
        keys.sign_in(name, "not the password", WHEN)
        return (time.perf_counter() - started) * 1000

    unknown, locked = [], []
    for _ in range(12):          # strictly alternating, so drift cancels
        unknown.append(one("Nobody Here"))
        locked.append(one("Meera Nair"))

    # By now the enrolled name is locked out; that is the path being timed.
    _token, refused = keys.sign_in("Meera Nair", "not the password", WHEN)
    assert refused.wait_minutes > 0, "the enrolled name never locked"

    quick, slow = statistics.median(unknown), statistics.median(locked)
    assert slow > quick / 3, (
        f"the locked path returned in {slow:.2f} ms against {quick:.2f} ms "
        f"for an unknown name, which is an enrolment tell")


def test_one_attempt_still_says_nothing_about_who_is_enrolled():
    keys = Credentials(":memory:")
    keys.set_password("Meera Nair", "morning queue august", WHEN)

    _t1, wrong = keys.sign_in("Meera Nair", "not the password", WHEN)
    _t2, unknown = keys.sign_in("Nobody Here", "not the password", WHEN)
    assert wrong.said == unknown.said
    assert wrong.wait_minutes == unknown.wait_minutes == 0


def test_what_the_sign_in_does_not_hide_is_written_down():
    """A limit that is not stated is a limit somebody will mistake for a
    guarantee. The whole roster was classifiable in 24 requests, and the
    docstring said the opposite."""
    from vinzor.credentials import Credentials as _C

    said = _C.sign_in.__doc__
    assert "stated limit" in said
    assert "rate limit" in said
    assert "24 requests" in said


from vinzor.model import EventType          # noqa: E402

# ---------------------------------------------------------------------------
# Who the watchlist returned
#
# Screening a name gives back candidates, not answers. The officer's job is
# to eliminate the ones who are not their investor, and they do that on date
# of birth, nationality and document number -- all of which screening.py has
# recorded since it was written, and none of which reached the screen.
# ---------------------------------------------------------------------------


def test_a_match_is_shown_with_what_would_rule_it_out(workspace):
    """A caption and a score is an alert an officer can only close by
    guessing. What they need is the entry's own identifying detail beside
    the firm's."""
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    engine.ingest(
        event_type=EventType.SCREENING_COMPLETED,
        subject=party, occurred_at="2026-08-22", actor="system",
        payload={"matched": True, "list_types": ["SANCTIONS"],
                 "basis": {"caption": "Somebody Else", "score": 0.86,
                           "datasets": ["us_ofac_sdn"],
                           "listed_properties": {"birthDate": ["1965-02-20"],
                                                 "nationality": ["RU"]}}})

    status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    assert status == 200
    found = body.get("candidates") or []
    assert found, "a recorded match reached the screen as nothing at all"
    entry = found[0]
    assert entry["caption"] == "Somebody Else"
    assert entry["score"] == 0.86
    labels = {row["label"]: row for row in entry["compared"]}
    assert labels["Date of birth"]["theirs"] == "1965-02-20"
    assert labels["Nationality"]["theirs"] == "RU"


def test_a_field_only_one_side_holds_is_not_called_a_difference(workspace):
    """Reading a blank as a disagreement would hand an officer a reason to
    clear an alert that nothing supports."""
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    engine.ingest(
        event_type=EventType.SCREENING_COMPLETED,
        subject=party, occurred_at="2026-08-22", actor="system",
        payload={"matched": True, "list_types": ["SANCTIONS"],
                 "basis": {"caption": "Somebody Else", "score": 0.7,
                           "listed_properties": {}}})

    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    for entry in body.get("candidates") or []:
        for row in entry["compared"]:
            if not row["theirs"] or not row["ours"]:
                assert row["verdict"] == "", (
                    "a blank on one side was reported as a difference")


def test_a_match_with_nothing_to_show_is_not_listed_as_a_suspect(workspace):
    """An empty row in this list reads as a second person under suspicion."""
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    engine.ingest(
        event_type=EventType.SCREENING_COMPLETED,
        subject=party, occurred_at="2026-08-22", actor="system",
        payload={"matched": True, "basis": {}})

    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    for entry in body.get("candidates") or []:
        assert entry["caption"], "an entry with no name was offered as a match"


def test_one_record_field_answered_twice_is_printed_once(workspace):
    """A watchlist entry can carry both a passport number and an identity
    number, and both answer the same question about our record. Listed
    separately they printed the same blank row twice."""
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    engine.ingest(
        event_type=EventType.SCREENING_COMPLETED,
        subject=party, occurred_at="2026-08-22", actor="system",
        payload={"matched": True,
                 "basis": {"caption": "Somebody Else", "score": 0.8,
                           "listed_properties": {
                               "passportNumber": ["X1234567"],
                               "idNumber": ["ID-9999"]}}})

    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    entry = (body.get("candidates") or [{}])[0]
    numbers = [r for r in entry.get("compared", [])
               if r["theirs"] in ("X1234567", "ID-9999")]
    assert len(numbers) == 1, "the same question was asked twice"
    assert numbers[0]["theirs"] == "X1234567", "a stated value was preferred"


def test_the_strongest_match_is_offered_first(workspace):
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    for caption, score in (("Weak One", 0.71), ("Strong One", 0.95)):
        engine.ingest(
            event_type=EventType.SCREENING_COMPLETED,
            subject=party, occurred_at="2026-08-22",
            actor="system",
            payload={"matched": True,
                     "basis": {"caption": caption, "score": score,
                               "listed_properties": {"nationality": ["RU"]}}})

    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    captions = [c["caption"] for c in body.get("candidates") or []]
    assert captions[0] == "Strong One"


def test_one_watchlist_entry_found_twice_is_listed_once(workspace):
    """A name is screened more than once on purpose: an abbreviated name is
    asked again in full, because measured against forty listed people the
    initialled form missed seventeen. So the same entry comes back from both
    searches.

    Listed twice it does not read as one entry found twice. It reads as two
    people under suspicion, which is the same defect as showing a match with
    no name -- and on a live run of "Vladimir Putin" it turned three genuine
    candidates into six.
    """
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    for score in (0.86, 0.94):
        engine.ingest(
            event_type=EventType.SCREENING_COMPLETED,
            subject=party, occurred_at="2026-08-22", actor="system",
            payload={"matched": True, "list_types": ["SANCTIONS"],
                     "basis": {"caption": "Vladimir Putin", "score": score,
                               "matched_entity": "os:one-and-the-same",
                               "datasets": ["us_ofac_sdn"],
                               "listed_properties": {
                                   "birthDate": ["1952-10-07"]}}})

    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    found = body.get("candidates") or []
    assert len(found) == 1, f"one entry was offered as {len(found)} suspects"
    assert found[0]["score"] == 0.94, "the stronger of the two searches stands"


def test_two_different_entries_sharing_a_name_are_both_listed(workspace):
    """The other half of the same rule. Two people really can share a name --
    the sanctioned Vladimir Putin and a Vladimir Putin born in 2019 both come
    back from a live search -- and collapsing them would hide one."""
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    for who, born in (("os:the-president", "1952-10-07"),
                      ("os:somebody-else", "2019")):
        engine.ingest(
            event_type=EventType.SCREENING_COMPLETED,
            subject=party, occurred_at="2026-08-22", actor="system",
            payload={"matched": True, "list_types": ["SANCTIONS"],
                     "basis": {"caption": "Vladimir Putin", "score": 1.0,
                               "matched_entity": who,
                               "listed_properties": {"birthDate": [born]}}})

    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    found = body.get("candidates") or []
    assert len(found) == 2, "two different entries were collapsed into one"
    dates = {row["theirs"] for entry in found for row in entry["compared"]
             if row["label"] == "Date of birth"}
    assert dates == {"1952-10-07", "2019"}


def test_the_screen_is_told_what_kinds_of_document_there_are(workspace):
    """The upload posted no kind at all, so every document filed through the
    interface arrived as "other" -- and "other" is allowed to evidence
    nothing. The reader then answered every single one with "this system
    does not know what a document of that kind is allowed to evidence",
    which reads as a broken product and was a missing question.

    The screen cannot ask it without knowing the answers, and the answers
    belong to documents.KINDS rather than to a list retyped in JavaScript.
    """
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    offered = body.get("kinds") or []
    assert offered, "the screen has no way to ask what a document is"

    from vinzor.documents import KINDS

    values = {one["value"] for one in offered}
    assert "passport" in values and "utility_bill" in values
    assert "other" not in values, (
        "'other' evidences nothing, so offering it is offering a document "
        "that cannot be read")
    for one in offered:
        assert one["label"] == KINDS[one["value"]][0]
        assert one["evidences"], (
            "a kind that evidences nothing should not be on the list")


def test_what_a_kind_may_evidence_is_said_in_words_a_person_uses(workspace):
    """"id_document_number" is not a phrase anybody says out loud, and this
    list is shown to an officer choosing what a document is."""
    engine, keys, base = workspace
    a_file(engine)
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    party = next(iter(engine.state.graph.entities))
    _status, body, _ = call(base, f"/api/onboarding/{party}", cookie=cookie)
    passport = [k for k in body["kinds"] if k["value"] == "passport"][0]
    assert "date of birth" in passport["evidences"]
    assert "document number" in passport["evidences"]
    for one in body["kinds"]:
        for said in one["evidences"]:
            assert "_" not in said, f"{said!r} is a field name, not a phrase"


# ---------------------------------------------------------------------------
# What the officer already knows, before any document arrives
# ---------------------------------------------------------------------------


def test_the_questions_asked_come_from_the_clause_they_cite(workspace):
    """An investor is usually sitting opposite with their papers at home, and
    they know their own date of birth. There was nowhere to put it, so the
    checks ran against a name and a party kind and clause 5.4.2 reported six
    things missing that the person in the room could have answered.

    The questions are derived from readiness.py's own table rather than
    written out again, so the screen collecting them and the check reporting
    them missing cannot drift apart.
    """
    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    status, body, _ = call(base, "/api/onboarding/questions?kind=PERSON",
                           cookie=cookie)
    assert status == 200
    asked = {q["field"]: q for q in body["questions"]}
    assert {"dob", "nationality", "country_of_residence"} <= set(asked)
    assert asked["dob"]["clause"] == "5.4.2(a)(iii)"
    assert asked["dob"]["sort"] == "date"
    assert asked["nationality"]["sort"] == "country"
    # Three upfront and the rest folded away: an officer handed thirty
    # fields fills in the easy ones and stops.
    assert sum(1 for q in body["questions"] if q["upfront"]) == 3

    _status, company, _ = call(base, "/api/onboarding/questions?kind=COMPANY",
                               cookie=cookie)
    fields = {q["field"] for q in company["questions"]}
    assert "date_of_incorporation" in fields
    assert "dob" not in fields, "a company does not have a date of birth"


def test_what_the_officer_knows_is_recorded_and_reaches_the_checks(workspace):
    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    status, body, _ = call(
        base, "/api/onboarding",
        {"name": "Anand Bhat", "kind": "PERSON",
         "known": {"dob": "1981-03-14", "nationality": "in",
                   "country_of_residence": "IN"}},
        cookie=cookie)
    assert status == 200
    held = engine.state.graph.entities[body["party_id"]].attributes
    assert held["dob"] == "1981-03-14"
    assert held["nationality"] == "IN", "a country is kept as this record keeps one"
    assert held["country_of_residence"] == "IN"


def test_a_date_that_is_not_a_date_is_refused_rather_than_written(workspace):
    """A malformed date on a permanent record is worse than an empty field,
    because the empty one is visibly empty."""
    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    status, _body, _ = call(
        base, "/api/onboarding",
        {"name": "Somebody", "kind": "PERSON",
         "known": {"dob": "14/03/1981"}},
        cookie=cookie)
    assert status == 400

    status, _body, _ = call(
        base, "/api/onboarding",
        {"name": "Somebody", "kind": "PERSON",
         "known": {"nationality": "India"}},
        cookie=cookie)
    assert status == 400


def test_a_field_nobody_asked_about_is_not_written(workspace):
    """Only what clause 5.4.2 names is accepted. A caller cannot post
    arbitrary attributes onto a party's permanent record."""
    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    _status, body, _ = call(
        base, "/api/onboarding",
        {"name": "Anand Bhat", "kind": "PERSON",
         "known": {"dob": "1981-03-14", "pep_flag": "0",
                   "cleared_by": "nobody"}},
        cookie=cookie)
    held = engine.state.graph.entities[body["party_id"]].attributes
    assert held.get("dob") == "1981-03-14"
    assert "cleared_by" not in held
    assert "pep_flag" not in held


def test_a_country_is_not_quietly_cut_down_until_it_passes(workspace):
    """"India" was being shortened to "IN" and then validated, which is even
    the right answer. "Indonesia" became the same "IN", which is not. A
    truncation that changes a value's meaning and then passes its own check
    is how a party ends up recorded in the wrong country."""
    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    for said in ("India", "Indonesia", "Singapore", "I"):
        status, _body, _ = call(
            base, "/api/onboarding",
            {"name": "Somebody " + said, "kind": "PERSON",
             "known": {"nationality": said}},
            cookie=cookie)
        assert status == 400, f"{said!r} was accepted as a country code"

    status, body, _ = call(
        base, "/api/onboarding",
        {"name": "Anand Bhat", "kind": "PERSON", "known": {"nationality": "in"}},
        cookie=cookie)
    assert status == 200
    assert engine.state.graph.entities[body["party_id"]].attributes[
        "nationality"] == "IN"


def test_the_gather_is_bounded_once_for_the_pair_not_once_each(workspace):
    """Two observations run at once and the waiting was serial.

    ``join(GATHER_SECONDS)`` in a loop gives the second thread its own full
    countdown after the first has already spent one, so a cap described in
    the module as thirty seconds was in fact a minute -- and the officer
    watching "0 of 8" was watching it for twice as long as anybody intended.
    """
    import inspect

    from vinzor import server

    source = inspect.getsource(server)
    start = source.index("def _gather_then_check(")
    body = source[start:source.index("\n        def ", start + 1)]
    assert "deadline" in body, (
        "the pair needs one deadline between them, not one each")
    assert "one.join(GATHER_SECONDS)" not in body, (
        "joining each thread with the full timeout doubles the cap")


def test_a_run_reports_what_the_outside_world_is_doing(workspace):
    """The eight checks are pure functions over the log and land in
    milliseconds. Everything an officer waits for happens at the two
    boundaries before them, and it was invisible -- so the screen sat at
    "0 of 8" for half a minute and then showed all eight at once, which is a
    progress bar over a sleep.
    """
    import time

    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    from vinzor.server import GATHERING

    _status, started, _ = call(
        base, "/api/onboarding",
        {"name": "Somebody New", "kind": "PERSON"}, cookie=cookie)
    task_id = started["task_id"]

    # Let the real run finish, so nothing is writing to the store underneath
    # this. Both observations fail immediately here -- there is no watchlist
    # and no news service in a test -- which is itself the point: they fail
    # and the run continues.
    for _ in range(100):
        _status, body, _ = call(base, f"/api/tasks/{task_id}", cookie=cookie)
        if not body["task"].get("running"):
            break
        time.sleep(0.1)

    # Nothing is being waited on, so nothing is reported.
    assert "gathering" not in body["task"]

    # And while something is, it reaches the screen.
    GATHERING[task_id] = {"watchlist": "looking", "press": "failed"}
    try:
        _status, body, _ = call(base, f"/api/tasks/{task_id}", cookie=cookie)
        assert body["task"]["gathering"] == {"watchlist": "looking",
                                             "press": "failed"}
    finally:
        GATHERING.pop(task_id, None)


def test_a_source_that_fails_does_not_stop_the_run(workspace):
    """A watchlist that is down and a news service that is rate-limiting are
    ordinary states of the world. Neither may stop an onboarding, and
    neither may be recorded as a clean result -- the checks report the
    absence, which is the finding an officer acts on."""
    import time

    engine, keys, base = workspace
    keys.set_password("Meera Nair", GOOD, WHEN)
    cookie = signed_in(base, keys)

    _status, started, _ = call(
        base, "/api/onboarding",
        {"name": "Nobody Reachable", "kind": "PERSON"}, cookie=cookie)

    for _ in range(100):
        _status, body, _ = call(base, f"/api/tasks/{started['task_id']}",
                                cookie=cookie)
        if not body["task"].get("running"):
            break
        time.sleep(0.1)
    task = body["task"]
    assert not task.get("running"), "a failed observation held the run open"
    assert task["done_count"] == task["step_count"], (
        "every check should have run even though both sources failed")

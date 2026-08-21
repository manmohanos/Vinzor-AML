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


def call(base, path, body=None, cookie="", method=None):
    """(status, payload, set-cookie)."""
    data = json.dumps(body).encode() if body is not None else None
    request = Request(base + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
    if cookie:
        request.add_header("Cookie", cookie)
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

"""A small HTTP layer over the engine, and the page that talks to it.

Standard library only, like everything else here. The API surface is three
reads and one write; an ASGI stack, a build step and a dependency tree would
buy nothing a user could see, and "clone it and run it" is worth more right now
than a generated OpenAPI page. Moving to FastAPI later is a rewrite of this one
module and nothing else.

**This is not a deployment.** It binds to localhost, serves one workspace, and
does not authenticate anybody -- you say who you are and it believes you. The
human gate in ``cases.py`` is real and structural: an AI actor can never settle
a file. But *which human* is self-asserted here, and the sign-in page says so
rather than implying otherwise. Real identity is the first thing to add before
this touches a customer's data.
"""

from __future__ import annotations

import dataclasses
import json
import hashlib

import os
import re
import sys
import threading
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from .assist import DEFAULT_BUDGET_USD, draft_use
from .dossier import dossier
from .credentials import Credentials, Refused, weak
from .briefing import (CHOICES, MESSAGES, PARTY_KINDS, UI, brief, case_file,
                       import_progress, import_receipt, import_report, party,
                       qualified_name, regulatory, report, screening,
                       shared_names)
from .cases import (DecisionDenied, EscalationNeedsAnotherOfficer,
                    SeniorManagementMustApprove, UnknownCase)
from .importing import already_imported, apply as apply_import, read as read_sheet
from .engine import Vinzor
from .eventlog import EventLog
from .model import DECIDING_ROLES, Outcome, Role
from .quality import measure
from .reporting import period_report
from .seed import DEFAULT_DATASET, seed

WEB = Path(__file__).resolve().parent / "web"

#: The demonstration people. They are *enrolled into the workspace* as events
#: on first open -- who may act is workspace data in the log, not server
#: configuration, so a decision's audit record traces to a recorded enrolment.
PEOPLE = (
    {"name": "Meera Nair", "title": "AML Officer", "role": Role.AML_OFFICER},
    {"name": "Aarav Sharma", "title": "Compliance Officer", "role": Role.COMPLIANCE},
    {"name": "Rohan Kapoor", "title": "Senior Management", "role": Role.SENIOR_MGMT},
    {"name": "Priya Rao", "title": "Read-only access", "role": Role.VIEWER},
)


def enroll_people(engine: Vinzor, when: str) -> None:
    """Enrol the demonstration people, once per workspace."""
    if engine.state.actors:
        return
    for person in PEOPLE:
        engine.enroll(name=person["name"], role=person["role"],
                      title=person["title"], enrolled_at=when)

def _utcnow() -> datetime:
    """The clock the Bedrock boundary signs with, supplied from here.

    SigV4 signatures are time-scoped, so ``bedrock.py`` genuinely needs a
    timestamp -- and no module under ``vinzor/`` may read a clock. Rather
    than add that file to the short list of exceptions, the clock enters at
    this boundary, which already reads one for every decision, and is passed
    down like every other date in this system.

    It signs a request and is then discarded. It never reaches the log, which
    is the reason the doctrine exists and the reason this is not a hole in it.
    """
    return datetime.now(timezone.utc)


WORKSPACE = "Acme GIFT Fund Managers Ltd"

#: A decision is a few hundred bytes: a name, a file, an outcome, a reason.
#: Anything past this is not a compliance officer settling a file, and reading
#: an unbounded body because a header claimed one would hand a stranger the
#: server's memory.
MAX_BODY_BYTES = 64 * 1024

#: How long an onboarding will wait for the outside world before running the
#: checks anyway. Both observations are attempted at once and either may be
#: slow; past this the checks run and report honestly that the watchlist or
#: the press was not reached, which is a finding an officer can act on and is
#: better than a screen that sits still.
GATHER_SECONDS = 30

#: A spreadsheet is allowed to be a spreadsheet. Twenty megabytes covers
#: years of statement lines; anything past it is not a sheet a person read.
MAX_SHEET_BYTES = 20 * 1024 * 1024

#: A document is allowed to be a photograph.
#:
#: This route was inheriting ``MAX_BODY_BYTES``, which is sized for "a
#: decision is a few hundred bytes" -- so every upload over 64 KB was refused
#: with the sentence about nothing having been recorded. It went unnoticed
#: because the pack this was built against is hand-written PDFs of about a
#: kilobyte each. A real passport photographed on a phone is a few hundred
#: kilobytes, and the first genuine document anybody tried was rejected.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


def _ceiling_for(route: str) -> int:
    """How large a body this route is allowed to have.

    One place, because there were two of these checks reading the same
    expression and a third route that needed a different answer from both.
    """
    if route == "/api/imports":
        return MAX_SHEET_BYTES
    if route.startswith("/api/onboarding/") and route.endswith("/documents"):
        return MAX_DOCUMENT_BYTES
    return MAX_BODY_BYTES

#: How many uploaded sheets are held awaiting confirmation. Comfortably more
#: than anyone reads at once, and a bound rather than none at all: an
#: officer who opens twenty files and confirms one should not leave the
#: other nineteen on the disk forever.
#:
#: **This constant did not mean what it said.** The holding area was a fresh
#: ``tempfile.mkdtemp()`` per process, so every restart minted a new
#: directory, reset the count to zero and orphaned the last one, and nothing
#: ever removed a directory. Measured on the development machine: 170
#: leftover ``vinzor-imports-*`` directories holding 491 uploaded sheets, the
#: oldest four days old -- customers' own spreadsheets, in the clear, under
#: their own filenames, in a shared OS temp folder that outlives the
#: workspace and sits outside the tenant boundary the product claims the
#: workspace file is. The area now lives beside the workspace, is pruned by
#: age as well as by count, and is removed when the server stops.
_HELD_UPLOADS = 25

#: And how long one may be held. A sheet nobody confirmed by tomorrow is a
#: sheet nobody is going to confirm.
_HOLD_UPLOADS_FOR_SECONDS = 24 * 60 * 60

_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8"}


def _encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {f.name: _encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if hasattr(value, "value"):  # an enum
        return value.value
    return value


def _filename(name: str, suffix: str = "xlsx") -> str:
    """A download name that survives every operating system.

    A quotation mark or a slash in a filename is how a download arrives
    with no extension and will not open, and party names contain both.

    The extension is an argument rather than a constant. It was ``.xlsx``,
    written into the function, because for a while a workbook was the only
    thing this server handed out -- so the first PDF route to use it would
    have sent a correct PDF down under a name that told the operating system
    to open it in a spreadsheet.
    """
    keep = [ch if (ch.isalnum() or ch in " -_") else " " for ch in name]
    clean = " ".join("".join(keep).split())[:90] or "vinzor"
    return f"{clean}.{suffix}"


def _task_json(task, today: str = "") -> dict:
    """One task as the watching panel needs it.

    ``today`` lets a job that was left mid-flight say so. Without it a run
    whose process stopped read "Working now" in the present tense for ever,
    and the browser polled for it indefinitely.
    """
    now_doing = task.now_doing
    stopped = bool(today) and task.stopped(today)
    return {
        "task_id": task.task_id,
        "asked": task.asked,
        "about": task.about,
        "asked_by": task.asked_by,
        "given_at": task.given_at,
        # Not "no record of it ending". A stopped job is not a running one,
        # and telling the screen it is running is what kept the browser
        # polling for a thread that no longer existed.
        "running": task.running and not stopped,
        "stopped": stopped,
        "how_far": round(task.how_far * 100),
        "done_count": task.done_count,
        "step_count": len(task.plan),
        "now_doing": "" if stopped else (now_doing.says if now_doing else ""),
        "outcome": task.outcome or (
            f"This run stopped before it finished. {task.done_count} of "
            f"{len(task.plan)} steps had been recorded; the rest were never "
            f"run. Start it again when you need it."
            if stopped else ""),
        "said": task.about,
        "plan": [
            {"number": step.number, "agent": step.agent, "says": step.says,
             "headline": step.headline, "how": step.how,
             "details": list(step.details)}
            for step in task.plan
        ],
    }


def build_app(engine: Vinzor, keys=None):
    """A request handler bound to one engine and its ways in."""

    # Ways in live beside the log, in the same file, never in it. Where no
    # store is supplied the workspace is in memory and so are the
    # credentials, which is what tests want.
    if keys is None:
        keys = Credentials(getattr(engine.log, "path", ":memory:"))

    #: One per application, not one per process: two workspaces served from
    #: one process must not be able to read each other's uploads.
    held: list = []

    def exhibits() -> Path:
        """The upload area, made on first use."""
        if not held:
            where = getattr(engine.log, "path", "") or ""
            if where and where != ":memory:":
                home = Path(where).parent / ".vinzor-imports"
            else:
                # A workspace with no file on disk is a test or a demo, and
                # its uploads have nowhere of their own to live.
                import tempfile

                home = Path(tempfile.mkdtemp(prefix="vinzor-imports-"))
            home.mkdir(parents=True, exist_ok=True)
            held.append(home)
        return held[0]

    def forget_exhibits() -> None:
        """Remove the upload area. Called when the server stops."""
        import shutil

        for home in held:
            shutil.rmtree(home, ignore_errors=True)
        held.clear()

    class Handler(BaseHTTPRequestHandler):
        server_version = "vinzor"
        #: Seconds. Without this a client that opens a connection and sends
        #: nothing pins a server thread forever -- confirmed: threads were
        #: never freed after 5+ seconds of silence from such a client. This is
        #: a socket-level read timeout (``SocketServer.StreamRequestHandler``
        #: sets it on the connection before each request), not an HTTP
        #: response deadline.
        timeout = 10

        # -- plumbing -----------------------------------------------------

        def _send(self, status: HTTPStatus, body: bytes, content_type: str,
                  close: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # A compliance officer's screen is not a page to embed, script
            # into from elsewhere, or let a browser guess the type of. None of
            # this needs configuring per response -- the whole site is one
            # origin serving itself, so the strictest setting of each header
            # is also the correct one everywhere. (OWASP HTTP Headers and CSP
            # Cheat Sheets: nosniff, frame-ancestors/X-Frame-Options against
            # clickjacking on the very buttons that close a Case, and a CSP
            # that admits only this origin as a second line of defence behind
            # the HTML-escaping already done for every value app.js renders.)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self'; base-uri 'none'; form-action 'self'; "
                "object-src 'none'; frame-ancestors 'none'",
            )
            pending = getattr(self, "_pending_cookie", "")
            if pending:
                self.send_header("Set-Cookie", pending)
                self._pending_cookie = ""
            if close:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        #: The cookie the session token travels in. HttpOnly so a script
        #: cannot read it, SameSite=Strict so another site cannot cause a
        #: decision to be recorded in somebody's name, and Secure whenever
        #: the reader reached us over TLS -- see ``_over_tls``.
        COOKIE = "vinzor_session"

        def _token(self) -> str:
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                name, _, value = part.strip().partition("=")
                if name == self.COOKIE:
                    return value.strip()
            return ""

        def _signed_in_as(self) -> Optional[str]:
            """Who is making this request, worked out rather than believed.

            The whole point of the sign-in. Every write used to take the
            actor's name out of the request body, so anybody who could
            reach the port could post as Senior Management and clear the
            files only Senior Management may clear.
            """
            return keys.who(self._token(), datetime.now().isoformat())

        def _open_workspace(self) -> bool:
            """True where nobody has a password yet.

            A workspace where no way in has been set is a demonstration,
            and behaves as it did before: pick a name, no password. The
            moment anybody is given one, everybody needs one. There is no
            middle state and no per-person exemption, because a system
            where some people need a password is a system where the rest
            are the way in.
            """
            return not keys.anybody_can_sign_in()

        def _who(self, body: Optional[dict] = None) -> Optional[str]:
            """The name to act as, or nothing.

            The line this whole change exists to draw. On a **guarded**
            workspace -- one where anybody has been given a password --
            this is the session and nothing else, so what the request says
            about who it is cannot matter. On an **open** one it is
            whatever the request claims, which is what makes a
            demonstration on a laptop work and is stated on its own screen
            in a red box.

            There is no third case, and no per-person exemption. A system
            where some people need a password is a system where the rest
            are the way in.
            """
            if not self._open_workspace():
                return self._signed_in_as()
            asked = (str((body or {}).get("person") or "")
                     or self._query("person") or "")
            return asked or (PEOPLE[0]["name"] if PEOPLE else None)

        def _over_tls(self) -> bool:
            """Whether the person's browser reached us over HTTPS.

            This process never terminates TLS itself and is not meant to:
            it binds to loopback and something in front of it -- nginx, and
            a CDN in front of that -- does the certificate. So the only
            place the answer can come from is what that proxy tells us,
            which is ``X-Forwarded-Proto``.

            **Trusting a header a client can set is deliberate here, and it
            is safe in the only direction that matters.** A stranger who
            lies and claims HTTPS over a plain connection gets a cookie
            marked ``Secure``, which their own browser then refuses to send
            back over that same plain connection: they have locked
            themselves out, not got in. The failure worth preventing is the
            opposite one -- omitting ``Secure`` on a connection that really
            is TLS, so the cookie is willing to travel in the clear -- and
            no lie in this header can cause that.

            Absent the header we say no, which is right on a laptop: a
            ``Secure`` cookie on ``http://127.0.0.1`` is one the browser
            will not return, and a sign-in that silently fails to stick is
            worse than a demonstration served in the clear.
            """
            return (self.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"

        def _onboard(self, body: dict, entry) -> None:
            """Take on a new investor: register them, then start the checks.

            One call, because it is one intention. An officer with somebody
            waiting should not have to create a record, find its reference and
            then start a job against it -- that is this product's filing
            system leaking into their afternoon.

            The run is started and its reference returned at once. Nothing
            waits for the checks: they take seconds, the officer watches them,
            and each lands on the log as it finishes.
            """
            from .model import EntityKind, EventType

            acting = self._who(body)
            if acting is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return

            name = str(body.get("name") or "").strip()[:200]
            if not name:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            try:
                kind = EntityKind(str(body.get("kind") or "").strip().upper())
            except ValueError:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return

            today = date.today().isoformat()
            # Derived from what was typed, so onboarding the same party twice
            # by accident extends one record rather than making two -- which
            # is the mistake duplicates.py exists to find, and there is no
            # sense manufacturing work for it.
            party = "imp_" + hashlib.sha256(
                ("%s|%s" % (name, kind.value)).encode("utf-8")).hexdigest()[:12]
            attributes = {}
            country = str(body.get("country") or "").strip().upper()[:2]
            if country:
                where = "nationality" if kind is EntityKind.PERSON else "jurisdiction"
                attributes[where] = country
            if party not in engine.state.graph.entities:
                engine.ingest(
                    event_type=EventType.ENTITY_REGISTERED,
                    subject=party, occurred_at=today, actor=acting,
                    payload={"kind": kind.value, "name": name,
                             "attributes": attributes})

            task_id = engine.give_task(recipe_key="onboard", actor=acting,
                                       given_at=today, party=party)
            self._json({"party_id": party, "task_id": task_id})
            # Started after the reply, so the officer watches an empty plan
            # fill in rather than waiting on a blank page for the whole run.
            # The plan is already on the record; only the results are not.
            threading.Thread(
                target=self._gather_then_check, args=(task_id, today, party),
                daemon=True).start()

        def _gather_then_check(self, task_id: str, today: str,
                               party: str) -> None:
            """Observe the outside world, then run the checks that read it.

            The order matters and it is the architecture rather than a
            convenience. An agent tool is handed a read-only view and has no
            way to write anything -- which is what stops one settling a file,
            and is not something to work around here. So the two facts that
            come from outside this machine are minted at this boundary, the
            way ``DESIGN.md`` says facts arrive, and the agents that read them
            run afterwards.

            Neither observation may stop an onboarding. A watchlist that is
            down and a news service that is rate-limiting are ordinary states
            of the world; what must never happen is either being recorded as
            a clean result, and both adapters refuse rather than do that. The
            checks then report the absence honestly, which is the finding an
            officer acts on.
            """
            # Both at once, not one after the other. Run serially they cost
            # up to a minute and a half before the first check could start,
            # and an officer watching eight rows sit at "waiting" for that
            # long has been given a progress bar over a sleep -- which is the
            # one thing agents.py refuses to do. They are independent
            # questions to independent services; there is no reason to make
            # the press wait for the watchlist.
            gathering = [
                threading.Thread(target=self._screen_quietly,
                                 args=(party, today), daemon=True),
                threading.Thread(target=self._press_quietly,
                                 args=(party, today), daemon=True),
            ]
            for one in gathering:
                one.start()
            for one in gathering:
                one.join(GATHER_SECONDS)
            try:
                engine.run_task(task_id, when=today, party=party)
            except Exception as broke:      # noqa: BLE001
                print("  an onboarding run stopped: %s: %s"
                      % (type(broke).__name__, broke), file=sys.stderr)

        def _screen_quietly(self, party: str, today: str) -> None:
            """The watchlist. Silent to the officer, loud in the log.

            They will see it on screen as "nobody has run a watchlist check",
            which is true, is the thing they have to act on, and is the one
            sentence this product will not soften.
            """
            import os

            from .screening import ScreeningUnavailable, WatchlistClient, screen

            try:
                screen(engine, party, screened_at=today,
                       client=WatchlistClient(
                           url=os.environ.get("VINZOR_SCREENING_URL",
                                              "https://api.opensanctions.org"),
                           api_key=os.environ.get("VINZOR_SCREENING_KEY", ""),
                           scope=os.environ.get("VINZOR_SCREENING_SCOPE",
                                                "default")))
            except ScreeningUnavailable as why:
                print("  onboarding could not screen: %s" % why,
                      file=sys.stderr)
            except Exception as broke:      # noqa: BLE001
                print("  onboarding could not screen: %s: %s"
                      % (type(broke).__name__, broke), file=sys.stderr)

        def _press_quietly(self, party: str, today: str) -> None:
            """The news. Least decisive of the eight, so it never holds the
            others up: a sanctions match stops the money and this does not."""
            from .adversemedia import AdverseMediaUnavailable
            from .adversemedia import check as read_the_press

            try:
                read_the_press(engine, party, checked_at=today)
            except AdverseMediaUnavailable as why:
                print("  onboarding could not read the press: %s" % why,
                      file=sys.stderr)
            except Exception as broke:      # noqa: BLE001
                print("  onboarding could not read the press: %s: %s"
                      % (type(broke).__name__, broke), file=sys.stderr)

        def _observe_world(self, party: str, today: str) -> None:
            """The watchlist and the press, recorded as facts about the day.

            Each is attempted independently: a news service being busy is no
            reason not to have screened, and a screening failure is no reason
            to skip the press.
            """
            import os

            from .screening import ScreeningUnavailable, WatchlistClient, screen

            try:
                screen(engine, party, screened_at=today,
                       client=WatchlistClient(
                           url=os.environ.get("VINZOR_SCREENING_URL",
                                              "https://api.opensanctions.org"),
                           api_key=os.environ.get("VINZOR_SCREENING_KEY", ""),
                           scope=os.environ.get("VINZOR_SCREENING_SCOPE",
                                                "default")))
            except ScreeningUnavailable as why:
                # Silent to the officer and loud in the log. They will see it
                # on the screen as "nobody has run a watchlist check", which
                # is true and is the thing they have to act on.
                print("  onboarding could not screen: %s" % why,
                      file=sys.stderr)
            except Exception as broke:      # noqa: BLE001
                print("  onboarding could not screen: %s: %s"
                      % (type(broke).__name__, broke), file=sys.stderr)

            from .adversemedia import AdverseMediaUnavailable
            from .adversemedia import check as read_the_press

            try:
                read_the_press(engine, party, checked_at=today)
            except AdverseMediaUnavailable as why:
                print("  onboarding could not read the press: %s" % why,
                      file=sys.stderr)
            except Exception as broke:      # noqa: BLE001
                print("  onboarding could not read the press: %s: %s"
                      % (type(broke).__name__, broke), file=sys.stderr)

        def _file_document(self, party: str) -> None:
            """Put a document on a party's record during onboarding.

            The wizard's second step is the whole trick of this product: it
            shows only what is still outstanding, and the list shrinks as
            papers arrive. Without somewhere to send them the step was a drop
            zone that accepted a file and told the officer nothing here could
            file it -- which is worse than not offering one.

            The bytes arrive raw with the name in the query string rather
            than as a multipart form, for the reason ``/api/imports`` already
            does it that way: a form post is the one cross-site request a
            browser will send without script, and requiring a content type a
            form cannot set is the second CSRF layer this server relies on.

            **What the document evidences is not asserted here.** The kind is
            taken from what the officer chose, and ``documents.refuse``
            decides whether a kind like that could support anything at all;
            saying it *does* support a nationality is a person's assertion
            and belongs to the screen that asks them. A file arrives held and
            unevidenced, which is exactly the state clause 5.4.5 exists to
            distinguish, and the outstanding list says so in those words.
            """
            from .documents import KINDS

            acting = self._who()
            if acting is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            if party not in engine.state.graph.entities:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return

            asked = {}
            if "?" in self.path:
                from urllib.parse import parse_qs, urlsplit

                asked = parse_qs(urlsplit(self.path).query)
            filename = (asked.get("filename") or [""])[0][:200]
            kind = (asked.get("kind") or ["other"])[0].strip().lower()
            if kind not in KINDS:
                kind = "other"

            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            if length <= 0 or length > MAX_SHEET_BYTES:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            data = self.rfile.read(length)

            try:
                engine.file_document(
                    entity_id=party, kind=kind,
                    filename=filename or "a document",
                    data=data, supports=(), actor=acting,
                    filed_on=date.today().isoformat(),
                    cabinet=self._cabinet())
            except ValueError as refused:
                # documents.refuse says why in a sentence -- the bytes are not
                # what the name claims, the kind is not one we can hold, the
                # file is empty. All of those are the officer's to act on.
                self._json({"filed": False, "said": str(refused)},
                           HTTPStatus.BAD_REQUEST)
                return
            except KeyError:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return

            # Read it, and propose nothing more. What the document appears
            # to show comes back beside what the record already holds; a
            # person confirms, because "an officer looked at this passport
            # and said it shows this date of birth" is the record clause
            # 5.4.5 asks for and "our software read a PDF" is not.
            from .extraction import read as read_document

            from . import providers

            entity = engine.state.graph.entities.get(party)
            # A customer photographs their passport; they do not generate a
            # PDF with a text layer in it. Where a file has no text to parse,
            # the reader for photographs is asked instead -- and its answers
            # arrive marked as a model's, which is why ``read_by`` travels
            # with every proposal below.
            try:
                looking = providers.eyes(now=_utcnow)
            except Exception:               # noqa: BLE001
                looking = None
            reading = read_document(
                data, kind=kind, eyes=looking,
                today=date.today().isoformat(),
                holds=dict(getattr(entity, "attributes", {}) or {},
                           name=getattr(entity, "name", "")))
            self._json({
                "filed": True, "filename": filename, "kind": kind,
                "read": {
                    "unreadable": reading.unreadable,
                    "expired": reading.expired,
                    "proposals": [
                        {"field": p.field, "value": p.value,
                         "seen_as": p.seen_as, "agrees": p.agrees,
                         "on_record": p.on_record, "read_by": p.read_by}
                        for p in reading.proposals],
                },
            })

        def _cabinet(self):
            """Where the bytes live: in the workspace file, beside the log.

            A twenty-megabyte scan inside an append-only log is a log nobody
            can replay, so the fingerprint goes on the record and the file
            goes in a table next to it -- the same division credentials make.
            One file per workspace still, which is what tenant isolation
            here rests on.

            Built the way __main__.py already builds one, which is by handing
            Cabinet the workspace path itself. Giving it a path of its own
            would put a firm's scanned passports in a second file that the
            workspace boundary does not cover.
            """
            from .documents import Cabinet

            return Cabinet(getattr(engine.log, "path", ":memory:"))

        def _latest_checks(self, party: str) -> list:
            """The most recent onboarding run for this party, step by step.

            Read off the log rather than held anywhere: a run is a sequence
            of recorded events and the newest one about this party is the
            answer. Empty where nobody has run the checks, which the report
            then says rather than implying they passed.
            """
            from .model import EventType

            newest, steps = "", {}
            for event in engine.log:
                if event.event_type is not EventType.TASK_GIVEN:
                    continue
                if str((event.payload or {}).get("inputs", {}).get("party")
                       or "") == party:
                    newest = event.subject
            if not newest:
                return []
            for event in engine.log:
                if event.event_type is EventType.TASK_STEP                         and event.subject == newest:
                    steps[event.payload.get("number")] = event.payload
            return [steps[k] for k in sorted(steps)]

        def _onboarding(self, party: str) -> None:
            """Everything an officer reads before deciding about this party.

            Assembled here rather than concluded anywhere: what was checked,
            what is outstanding, what was found, who is behind them, and the
            three things only a person may do next. There is no overall
            verdict in this payload and there is deliberately nowhere to put
            one.
            """
            from .model import EntityKind
            from .requirements import NOT_MODELLED, outstanding

            if self._who() is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            entity = engine.state.graph.entities.get(party)
            if entity is None:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return

            still = outstanding(entity.kind,
                                engine.state.papers.held_for(party))
            open_files = [c for c in engine.queue() if c.subject == party]
            answer = None
            if entity.kind is not EntityKind.PERSON:
                answer = engine.state.graph.resolve_ubo(party)

            self._json({
                "party": {"id": party, "name": entity.name,
                          "kind": entity.kind.value if entity.kind else ""},
                "outstanding": [
                    {"asks_for": o.requirement.asks_for,
                     "because": o.requirement.because,
                     "mandatory": o.requirement.mandatory,
                     "basis": o.requirement.basis,
                     "held_but_unevidenced": o.held_but_unevidenced}
                    for o in still],
                "not_modelled": list(NOT_MODELLED),
                # Each finding carries the clause **and its words**. A file
                # saying "clause 5.4.2" and nothing else is the shape of an
                # answer nobody can check: the officer cannot tell whether
                # the rule says what we claim, and neither can the inspector
                # they are answering to. The register already holds the
                # extract, the page, the edition and the link -- it was
                # simply not being sent.
                "findings": [
                    {"summary": c.evidence[0].summary if c.evidence else "",
                     "severity": c.severity.value,
                     "case_id": c.case_id,
                     "case_type": c.case_type,
                     "status": c.status.value,
                     "clauses": [
                         {"clause": cited.get("clause"),
                          "heading": cited.get("heading"),
                          "says": cited.get("extract"),
                          "document": cited.get("document"),
                          "edition": cited.get("version"),
                          "page": cited.get("page"),
                          "amended": cited.get("amended"),
                          "url": cited.get("url"),
                          # Shown, never hidden. Every clause in this
                          # register was extracted by machine and no
                          # qualified person has signed it off, and a
                          # product that overstates the provenance of its
                          # own rules is worse than one that has none.
                          "verified": bool(cited.get("verified")),
                          "checked_on": cited.get("source_checked")}
                         for evidence in c.evidence
                         for cited in (evidence.citations or ())
                     ]}
                    for c in open_files],
                # The three things only a person may do, named by briefing.py
                # rather than by this handler -- the screen was reconstructing
                # them from a case file, which works and means the contract
                # and the server disagreed about where the wording lives.
                "decision": {
                    "required": True,
                    "permanence": UI.get("why", ""),
                    "options": [
                        {"outcome": choice.outcome.value,
                         "label": choice.label,
                         "explains": choice.means}
                        for choice in CHOICES
                    ],
                },
                # Including the checks that found nothing, which is the
                # evidence an inspector asks for and the thing a screen most
                # easily leaves out.
                "checks": [
                    {"what": step.get("labelled") or step.get("tool"),
                     "said": step.get("headline"),
                     "outcome": step.get("how"),
                     "detail": list(step.get("details") or ())}
                    for step in self._latest_checks(party)
                ],
                # Every watchlist entry the name brought back, with what
                # each one says about itself beside what we hold. Screening
                # returns candidates and the officer eliminates them; they
                # cannot do that from a caption and a score.
                "candidates": self._candidates(party),
                "ownership": ({
                    "conclusion": answer.conclusion.value,
                    "explains": answer.explain(),
                    "owners": [{"name": o.name,
                                "percentage": round(o.effective_percentage, 1)}
                               for o in answer.owners],
                    "cycles": [list(c) for c in answer.cycles],
                } if answer is not None else None),
            })

        def _set_cookie(self, token: str, ending: bool = False) -> None:
            bits = [f"{self.COOKIE}={token}", "Path=/", "HttpOnly",
                    "SameSite=Strict"]
            # Behind TLS the session token must never be willing to travel
            # in the clear. HttpOnly stops a script reading it and
            # SameSite=Strict stops another site spending it, but neither
            # stops it being sent over http:// -- which is the one that
            # hands it to anybody on the path.
            if self._over_tls():
                bits.append("Secure")
            if ending:
                bits.append("Max-Age=0")
            self._pending_cookie = "; ".join(bits)

        def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK,
                  close: bool = False) -> None:
            self._send(status, json.dumps(_encode(payload)).encode("utf-8"),
                       "application/json; charset=utf-8", close=close)

        def _problem(self, message_key: str, status: HTTPStatus,
                     close: bool = False) -> None:
            """Errors leave here as sentences, never as codes or tracebacks."""
            self._json({"message": MESSAGES[message_key]}, status, close=close)

        def _static(self, name: str) -> None:
            path = (WEB / name).resolve()
            if WEB not in path.parents or not path.is_file():
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return
            self._send(HTTPStatus.OK, path.read_bytes(),
                       _TYPES.get(path.suffix, "application/octet-stream"))

        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # the console belongs to the operator, not to access logs

        def _drain(self, limit: int = MAX_BODY_BYTES, seconds: float = 0.5) -> None:
            """Swallow whatever the sender already sent, briefly and boundedly.

            Used only when refusing a request whose body we will not read. The
            timeout is what keeps this from becoming the very denial-of-service
            it exists beside: a sender who promises bytes and never sends them
            costs us half a second, not a thread.
            """
            original = self.connection.gettimeout()
            self.connection.settimeout(seconds)
            try:
                while limit > 0:
                    chunk = self.rfile.read1(min(limit, 8192))
                    if not chunk:
                        break
                    limit -= len(chunk)
            except OSError:
                pass  # nothing more is coming, which is the normal case
            finally:
                self.connection.settimeout(original)

        def _same_origin(self) -> bool:
            """Whether this write came from our own screen.

            A browser attaches whatever it holds for a site to every request
            that site receives, including one triggered by a *different* page
            the officer happens to have open. Without this check, any web page
            visited during the working day could post a decision here and
            close a Case as an enrolled decider -- and, because the log is
            append-only and honest, the record would truthfully show that
            Meera Nair settled a file she never saw.

            The Origin header is set by the browser and cannot be forged by
            page script, so comparing it to the address we are serving is a
            real control. A request with no Origin at all is not from a
            browser form post: that is curl or our own tests, and is allowed.
            """
            claimed = self.headers.get("Origin") or self.headers.get("Referer")
            if claimed is None:
                return True
            from urllib.parse import urlparse

            sent = urlparse(claimed)
            host = (self.headers.get("Host") or "").strip()
            # Compare host and port, ignoring a default port written either
            # way round ("localhost" and "localhost:80" are the same place).
            here = host.rsplit(":", 1) if ":" in host else [host, ""]
            there = [sent.hostname or "", str(sent.port or "")]
            default = {"http": "80", "https": "443"}.get(sent.scheme, "")
            return here[0] == there[0] and (
                here[1] == there[1] or {here[1], there[1]} <= {"", default}
            )

        # -- reads --------------------------------------------------------

        def _import_home(self):
            """Where uploaded sheets are kept as exhibits.

            Beside the workspace file, so an uploaded customer sheet shares
            the lifetime and the boundary of the records it is about. It used
            to be an OS temp directory, which is neither: it outlived the
            workspace, it was shared with every other program on the machine,
            and two workspaces in one process shared one of them because the
            path was memoised on ``build_app`` itself rather than on this
            application.
            """
            return exhibits()

        #: The only routes a signed-out request may have on a guarded
        #: workspace: the page itself, the two files it is built from, and
        #: the question "do I need to sign in". Everything else is the
        #: client book.
        SIGNED_OUT_MAY_SEE = frozenset({
            "/", "/app.css", "/app.js", "/api/session", "/api/sign-in",
        })

        def _may_read(self, route: str) -> bool:
            """Whether this request may see anything but the sign-in screen.

            The gate lives here, once, rather than in each route, because
            the last time it lived in each route it was put on the writes
            and forgotten on the reads. Every screen in this product is
            somebody's client book: who has committed money, who matched a
            watchlist, what an officer wrote about them.

            An **open** workspace -- one where nobody has been given a
            password -- is a demonstration and behaves as it always did.
            The moment anybody has one, everybody needs one.
            """
            if route in self.SIGNED_OUT_MAY_SEE or self._open_workspace():
                return True
            if self._signed_in_as() is not None:
                return True
            self._refuse_politely("sign_in_first", HTTPStatus.UNAUTHORIZED)
            return False

        def _refuse_politely(self, said: str, status) -> None:
            """Say no to a request that is still talking.

            A refusal decided before the body is read leaves bytes in the
            receive buffer, and closing a socket on unread bytes makes
            Windows send a reset -- so the caller sees a dropped connection
            instead of the sentence explaining why. The body-cap check has
            said this since it was written; every other early refusal on a
            write needs it too, and two of them were found without it by
            the tests for those very refusals.
            """
            if self.headers.get("Content-Length"):
                self._drain()
                self.close_connection = True
                self._problem(said, status, close=True)
                return
            self._problem(said, status)

        def do_GET(self) -> None:  # noqa: N802
            route = self.path.split("?", 1)[0]
            if not self._may_read(route):
                return
            if route == "/":
                self._static("index.html")
            elif route in ("/app.css", "/app.js"):
                self._static(route.lstrip("/"))
            elif route == "/api/session":
                signed = self._signed_in_as()
                self._json({
                    "workspace": WORKSPACE,
                    "ui": UI,
                    "needs_password": not self._open_workspace(),
                    "signed_in_as": signed or "",
                    "people": [
                        {"name": name, "title": entry["title"],
                         "can_decide": entry["role"] in DECIDING_ROLES}
                        for name, entry in engine.state.actors.items()
                    ],
                })
            elif route == "/api/briefing":
                self._briefing()
            elif route.startswith("/api/cases/"):
                self._case(route[len("/api/cases/"):])
            elif route == "/api/parties":
                self._parties(self._query("q") or "")
            elif route == "/api/chat":
                self._thread()
            elif route == "/api/export":
                self._export()
            elif route == "/api/report.pdf":
                self._printed_report()
            elif route == "/api/tasks":
                self._tasks()
            elif route.startswith("/api/tasks/"):
                self._task(route[len("/api/tasks/"):])
            elif route.startswith("/api/records/"):
                self._record(route[len("/api/records/"):])
            elif route.startswith("/api/parties/"):
                self._party(route[len("/api/parties/"):])
            elif route.startswith("/api/onboarding/"):
                from urllib.parse import unquote as _unquote

                self._onboarding(_unquote(route[len("/api/onboarding/"):]))
            elif route == "/api/screening":
                payload = _encode(screening(engine, date.today().isoformat()))
                payload["ui"] = UI
                payload["workspace"] = WORKSPACE
                self._json(payload)
            elif route == "/api/regulatory":
                name = self._who() or PEOPLE[0]["name"]
                entry = engine.state.actors.get(name)
                if entry is None:
                    name, entry = next(iter(engine.state.actors.items()))
                payload = _encode(regulatory(engine, date.today().isoformat()))
                payload["ui"] = UI
                payload["workspace"] = WORKSPACE
                payload["person"] = name
                # Who may put their name to a clause is the same question as
                # who may settle a file, and is answered from the enrolment.
                payload["may_confirm"] = entry["role"] in DECIDING_ROLES
                self._json(payload)
            elif route == "/api/quality":
                self._json(report(measure(engine, DEFAULT_BUDGET_USD)))
            elif route == "/api/reports":
                from .reporting import PeriodUnreadable

                today = date.today().isoformat()
                try:
                    payload = _encode(period_report(
                        engine, today, since=self._query("since") or "",
                        workspace=WORKSPACE))
                except PeriodUnreadable:
                    # The screen only ever asks for the periods this server
                    # computed. An edited or shared link can ask for anything,
                    # and this page prints with the firm's name on it.
                    self._problem("period_unreadable", HTTPStatus.BAD_REQUEST)
                    return
                payload["ui"] = UI
                payload["periods"] = _periods(today)
                self._json(payload)
            elif route == "/api/imports/progress":
                ref = self._query("ref") or ""
                progress = SCREENING_RUNS.get(ref)
                if progress is None:
                    self._problem("not_found", HTTPStatus.NOT_FOUND)
                    return
                self._json({"state": progress.get("state", ""),
                            "sentence": import_progress(progress)})
            elif route == "/api/imports/template":
                which = self._query("sheet") or "parties"
                ending = "\r\n"
                if which == "payments":
                    body = ("Date,Payer,Beneficiary,Amount,Currency,"
                            "Reference,Narration" + ending)
                else:
                    which = "parties"
                    body = ("Name,Type,Nationality,Date of Birth,"
                            "ID Document Type,ID Document Number,PAN,"
                            "Commitment Amount,Currency,Fund,"
                            "Name of UBO,Ownership %" + ending)
                data = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{which}.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            else:
                self._problem("not_found", HTTPStatus.NOT_FOUND)

        def _briefing(self) -> None:
            name = self._who() or PEOPLE[0]["name"]
            entry = engine.state.actors.get(name)
            if entry is None:
                name, entry = next(iter(engine.state.actors.items()))
            # A boundary is the only place that knows the date, so this is
            # where a passed deadline gets noticed and written down. It is
            # idempotent: looking twice records nothing the second time.
            engine.observe_deadlines(date.today().isoformat())
            # Which group, if any, the reader asked to see in full. Only ever
            # a bucket key the briefing itself issued: an unknown value simply
            # matches nothing and every group stays capped, so this widens no
            # surface a caller could not already reach.
            # The hour travels with the date, from here rather than from the
            # core: this is the only place that knows what time it is.
            payload = _encode(brief(engine, person=name,
                                    today=date.today().isoformat(),
                                    hour=datetime.now().hour,
                                    expand=self._query("expand")))
            payload["person"] = name
            payload["title"] = entry["title"]
            payload["workspace"] = WORKSPACE
            payload["can_decide"] = entry["role"] in DECIDING_ROLES
            payload["read_only_because"] = (
                "" if entry["role"] in DECIDING_ROLES else MESSAGES["viewer"]
            )
            payload["all_clear"] = MESSAGES["all_clear"] if not payload["groups"] else ""
            payload["ui"] = UI
            self._json(payload)

        def _case(self, case_id: str) -> None:
            """One file in full. Reads only -- deciding stays on the write route."""
            from urllib.parse import unquote

            name = self._who() or PEOPLE[0]["name"]
            entry = engine.state.actors.get(name)
            if entry is None:
                name, entry = next(iter(engine.state.actors.items()))
            try:
                payload = _encode(case_file(engine, unquote(case_id)))
            except UnknownCase:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return
            payload["person"] = name
            payload["title"] = entry["title"]
            payload["workspace"] = WORKSPACE
            payload["can_decide"] = entry["role"] in DECIDING_ROLES
            payload["read_only_because"] = (
                "" if entry["role"] in DECIDING_ROLES else MESSAGES["viewer"]
            )
            payload["ui"] = UI
            self._json(payload)

        def _parties(self, query: str) -> None:
            """Find a party by name.

            Capped at twenty. An officer looking for one investor is served by
            the first few; a caller sending an empty query is not handed the
            whole book of clients in one response.
            """
            wanted = query.strip().lower()
            graph = engine.state.graph
            shared = shared_names(graph)
            hits = []
            for entity in graph.entities.values():
                if wanted and wanted not in entity.name.lower():
                    continue
                hits.append({
                    "name": qualified_name(graph, entity.entity_id, shared),
                    "kind": PARTY_KINDS.get(str(entity.kind), "Party"),
                    "ref": entity.entity_id,
                })
            hits.sort(key=lambda hit: hit["name"])
            shown = hits[:20]
            self._json({
                "parties": shown,
                "found": (
                    "" if not wanted else
                    MESSAGES["no_party"].format(query=query) if not hits else
                    f"{len(hits)} found." if len(hits) <= 20 else
                    f"{len(hits)} found. Showing the first 20."
                ),
                "ui": UI,
                "workspace": WORKSPACE,
            })

        def _party(self, entity_id: str) -> None:
            """Everything on one party. Reads only."""
            from urllib.parse import unquote

            payload = _encode(party(engine, unquote(entity_id),
                                    today=date.today().isoformat()))
            payload["ui"] = UI
            payload["workspace"] = WORKSPACE
            # Whether the person reading may categorise. The engine refuses
            # anyway; this only decides whether the control is offered, so
            # a viewer is not shown a button that would be refused.
            who = self._who() or ""
            entry = engine.state.actors.get(who)
            payload["may_assess"] = bool(
                entry and entry["role"] in DECIDING_ROLES)
            self._json(payload)

        def _thread(self) -> None:
            """One person's conversation, read out of the record."""
            from .conversation import OPENERS

            today = date.today().isoformat()
            who = self._who()
            if who is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            talk = engine.state.talk
            running = engine.state.runs
            turns = []
            for turn in talk.thread(who):
                shaped = {
                    "kind": turn.kind, "asked": turn.asked,
                    # Every turn here is this person's, since the thread is
                    # read for them -- but a turn that does not say who asked
                    # it renders as one nobody asked, and the screen showing
                    # a name beside a new question and none beside an old one
                    # reads as two different kinds of record.
                    "asked_by": turn.asked_by,
                    "when": turn.when, "said": turn.said,
                    "withheld": turn.withheld,
                    "looked_at": list(turn.looked_at),
                    "task": None,
                }
                if turn.task_id:
                    task = running.tasks.get(turn.task_id)
                    if task is not None:
                        shaped["task"] = _task_json(task, today)
                turns.append(shaped)
            self._json({
                "ui": UI, "person": who, "workspace": WORKSPACE,
                "turns": turns,
                "openers": [{"heading": heading, "asks": list(asks)}
                            for heading, asks in OPENERS],
                "again": [t.asked for t in talk.recent_asks(who)],
            })

        def _printed_report(self) -> None:
            """One party's record as the PDF somebody actually sends.

            The download was an HTML file, which is a fine thing to read and
            the wrong thing to attach to an email going to a board or an
            auditor: it opens differently on every machine and the recipient
            cannot tell whether the copy they were sent is the copy that was
            written.

            Rendered from the same ``dossier`` the screen draws, so the
            document a firm sends and the screen its officer read cannot
            disagree with each other.
            """
            from .dossier import dossier as build
            from .printing import filename_for, render

            if self._who() is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            party = self._query("party") or ""
            if party not in engine.state.graph.entities:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return
            today = date.today().isoformat()
            # ``record=False``: asking for a printable copy is not an event,
            # and a download that wrote to an append-only log would put a row
            # in the ledger every time somebody pressed a button twice.
            paper = build(engine, party, today, workspace=WORKSPACE,
                          record=False)
            data = render(paper)

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(data)))
            self.send_header(
                "Content-Disposition",
                'attachment; filename="%s"' % _filename(
                    filename_for(paper, today).rsplit(".", 1)[0], "pdf"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()

        def _export(self) -> None:
            """The book as a workbook, or one party's record.

            Handed over as a download rather than rendered, because the
            whole point is that it opens somewhere this product is not.
            """
            from .exporting import one_party, the_book

            if self._who() is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            today = date.today().isoformat()
            party = self._query("party") or ""
            if party:
                data = one_party(engine, party, today)
                if data is None:
                    self._problem("not_found", HTTPStatus.NOT_FOUND)
                    return
                name = engine.state.graph.name_of(party)
                filename = _filename(f"{name} record {today}")
            else:
                data = the_book(engine, today)
                filename = _filename(f"{WORKSPACE} book {today}")

            self.send_response(HTTPStatus.OK)
            self.send_header(
                "Content-Type",
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition",
                             f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()

        def _tasks(self) -> None:
            """Everything delegated, and the jobs that can be delegated."""
            from .agents import RECIPES

            today = date.today().isoformat()
            who = self._who()
            payload = {
                "ui": UI,
                "workspace": WORKSPACE,
                "person": who or "",
                "jobs": [
                    {"key": recipe.key, "asked": recipe.asked,
                     "about": recipe.about,
                     "steps": [agent for agent, _tool in recipe.steps]}
                    for recipe in RECIPES.values()
                ],
                "tasks": [_task_json(task, today)
                          for task in engine.state.runs.recent(24)],
            }
            self._json(payload)

        def _task(self, task_id: str) -> None:
            """One task, for the panel that watches it."""
            from urllib.parse import unquote

            today = date.today().isoformat()
            task = engine.state.runs.tasks.get(unquote(task_id))
            if task is None:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return
            self._json({"ui": UI, "task": _task_json(task, today)})

        def _record(self, entity_id: str) -> None:
            """Everything on one party as one document. Reads only.

            Deliberately available to every role including a viewer: this
            document creates nothing and decides nothing, and a compliance
            function where only two people can produce the file an inspector
            asked for is a compliance function with a bottleneck.
            """
            from urllib.parse import unquote

            # The written opening is the one part of this page that costs
            # a model call, so it is prepared here at the boundary rather
            # than inside the fold. A slow assistant delays a page; it must
            # never delay a decision.
            transport = None
            from . import providers
            try:
                # Inside the try, not beside it: an assistant that cannot be
                # built is a page without a suggestion on it, never a page
                # that fails to load.
                if providers.configured():
                    transport = providers.drafter(now=_utcnow).transport
            except Exception:
                transport = None
            payload = _encode(dossier(engine, unquote(entity_id),
                                      today=date.today().isoformat(),
                                      workspace=WORKSPACE,
                                      transport=transport))
            payload["ui"] = UI
            self._json(payload)

        #: What a watchlist entry calls a field, against what the record
        #: calls it. Only the four an officer actually eliminates a match on.
        MATCH_ON = (
            ("birthDate", "dob", "Date of birth"),
            ("nationality", "nationality", "Nationality"),
            ("passportNumber", "id_document_number", "Document number"),
            ("idNumber", "id_document_number", "Identity number"),
        )

        def _candidates(self, party: str) -> list:
            """Every watchlist entry this party's name brought back, with the
            details that let an officer rule one out.

            Screening a name returns candidates, not answers. "Vladimir
            Putin" matches the sanctioned one; it also matches every other
            person of that name, and the officer's actual job is to
            eliminate the ones who are not their investor. They do that on
            date of birth, nationality and document number.

            All of that was already recorded -- ``screening.py`` captures the
            identifying properties off each entry precisely because "a
            possible match is a name and nothing else" is useless -- and the
            screen showed a caption and a score. So the officer was told
            there was a match and given nothing to resolve it with, which is
            the shape of an alert that gets cleared by guessing.

            Nothing here decides. Where the record and the entry disagree it
            says so; where either side is silent it says nothing rather than
            reading a blank as a difference.
            """
            from .model import EventType

            entity = engine.state.graph.entities.get(party)
            if entity is None:
                return []
            ours = {k: str(v or "") for k, v in
                    (getattr(entity, "attributes", {}) or {}).items()}

            # One row per watchlist entry, however many times it was found.
            # A name is screened more than once on purpose -- an abbreviated
            # name is asked again in full, because measured against forty
            # listed people the initialled form missed seventeen -- so the
            # same entry comes back from both searches and was being listed
            # twice. Two identical rows do not read as one entry found twice;
            # they read as two people under suspicion.
            out, already = [], {}
            for event in engine.log:
                if event.event_type is not EventType.SCREENING_COMPLETED:
                    continue
                if event.subject != party or not event.payload.get("matched"):
                    continue
                basis = event.payload.get("basis") or {}
                if not basis.get("caption"):
                    # A match with nothing to show is not a candidate. An
                    # empty row in this list reads as a second suspect.
                    continue
                listed = basis.get("listed_properties") or {}
                # Grouped by the field on *our* record, because two watchlist
                # properties can answer the same question -- passportNumber
                # and idNumber are both the document number, and listing them
                # separately printed the same blank row twice.
                rows: dict = {}
                for theirs_key, ours_key, label in self.MATCH_ON:
                    values = listed.get(theirs_key) or []
                    theirs = ", ".join(str(v) for v in values)[:120]
                    mine = ours.get(ours_key, "")
                    if not theirs and not mine:
                        continue
                    held = rows.get(ours_key)
                    if held and (held["theirs"] or not theirs):
                        continue
                    verdict = ""
                    if theirs and mine:
                        verdict = ("same"
                                   if theirs.strip().lower() == mine.strip().lower()
                                   else "different")
                    rows[ours_key] = {"label": label, "theirs": theirs,
                                      "ours": mine, "verdict": verdict}
                compared = list(rows.values())
                # Keyed on the watchlist's own identifier for the entry,
                # which is the only thing that says "this is the same entry".
                # Two people really can share a caption.
                key = (basis.get("matched_entity")
                       or (basis.get("caption"), tuple(basis.get("datasets") or ())))
                seen_before = already.get(key)
                if seen_before is not None:
                    # Keep whichever search scored it higher; a second look
                    # at the same entry is not new information.
                    if float(basis.get("score") or 0) > seen_before["score"]:
                        seen_before["score"] = round(
                            float(basis.get("score") or 0), 2)
                    continue
                aliases = listed.get("alias") or []
                already[key] = {"score": round(float(basis.get("score") or 0), 2)}
                out.append(already[key])
                already[key].update({
                    "caption": basis.get("caption") or "",
                    "score": round(float(basis.get("score") or 0), 2),
                    "datasets": list(basis.get("datasets") or []),
                    "topics": list(basis.get("topics") or []),
                    "kinds": list(event.payload.get("list_types") or []),
                    "compared": compared,
                    "aliases": [str(a) for a in aliases][:6],
                    "position": ", ".join(
                        str(v) for v in (listed.get("position") or []))[:200],
                    "address": ", ".join(
                        str(v) for v in (listed.get("address") or []))[:200],
                })
                already[key]["score"] = round(float(basis.get("score") or 0), 2)
            # Strongest first: the one most likely to be the investor is the
            # one the officer should look at before the rest.
            out.sort(key=lambda one: -one["score"])
            return out

        def _checks_in_words(self, party: str) -> str:
            """What the eight checks recorded about one party, as prose.

            The division this product draws is that the checks *establish* and
            a model may only *interpret*. This is the seam: eight deterministic
            agents write their findings to the log, and this reads them back
            into the few hundred words a reader can be handed. Nothing is
            concluded here, and no check is re-run -- a sentence in here that
            disagreed with the report beside it would be the worst defect this
            product could ship.

            An absent check is carried through as absent, in those words. It
            is the one thing that must survive being summarised: a check that
            did not happen, flattened into silence, reads to an officer as a
            check that found nothing.
            """
            from .model import EntityKind

            entity = engine.state.graph.entities.get(party)
            if entity is None:
                return ""
            lines = [f"Party: {entity.name} ({entity.kind.value if entity.kind else 'unknown'})"]

            lines.append("")
            lines.append("What the eight checks recorded:")
            for step in self._latest_checks(party):
                said = step.get("headline") or ""
                how = step.get("how") or ""
                what = step.get("labelled") or step.get("tool") or ""
                mark = {"DONE": "settled",
                        "FOUND_SOMETHING": "needs attention",
                        "FAILED": "THE CHECK ITSELF FAILED - this was not checked",
                        "SKIPPED": "not checked"}.get(how, how.lower())
                lines.append(f"- {what} [{mark}]: {said}")
                for detail in list(step.get("details") or ())[:4]:
                    lines.append(f"    {detail}")
            if len(lines) == 2:
                lines.append("- no check has been run on this party at all.")

            if entity.kind is not EntityKind.PERSON:
                answer = engine.state.graph.resolve_ubo(party)
                lines.append("")
                lines.append("Beneficial ownership: " + answer.explain())
                for owner in answer.owners:
                    lines.append(
                        f"- {owner.name}: {round(owner.effective_percentage, 1)}%")
                for circle in answer.cycles:
                    lines.append("- ownership loops back: "
                                 + " owns ".join(circle))

            from .requirements import outstanding

            still = outstanding(entity.kind, engine.state.papers.held_for(party))
            if still:
                lines.append("")
                lines.append("Documents still outstanding:")
                for owed in still[:12]:
                    lines.append(f"- {owed.requirement.asks_for} "
                                 f"(clause {owed.requirement.basis})")
            return "\n".join(lines)[:6000]

        def _say(self) -> None:
            """One turn of the conversation.

            Routing, then one of two things. A question is read and
            answered in seconds by the reader, which can look but never
            write. A job is planned and set going, and the thread shows it
            running. The officer types a sentence either way and does not
            have to know which it will be.
            """
            from . import providers
            from .ask import ask
            from .planning import Plan, plan_from

            acting = self._who()
            if acting is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            if engine.state.actors.get(acting) is None:
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(body, dict):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            asked = str(body.get("asked") or "").strip()[:1000]
            if not asked:
                self._problem("needs_question", HTTPStatus.BAD_REQUEST)
                return

            # What the officer has open. The screen sends an identifier and
            # nothing else, and everything the model is shown about it is read
            # here, out of the engine. That division is the whole safety of
            # this: a browser that could post the *contents* of a report could
            # tell our own assistant that a sanctioned party was cleared, and
            # the answer would come back over the firm's name. It can name a
            # party; it cannot describe one.
            looking_at = None
            where = body.get("looking_at")
            if isinstance(where, dict):
                at = str(where.get("id") or "").strip()[:64]
                entity = engine.state.graph.entities.get(at)
                if entity is not None:
                    looking_at = {
                        "kind": "party", "id": at, "label": entity.name,
                        "record": self._checks_in_words(at),
                    }

            transport = None
            from . import providers
            try:
                if providers.configured():
                    transport = providers.drafter(now=_utcnow).transport
            except Exception:
                transport = None

            # Routed only when there is a routing question to answer. A
            # sentence typed into the box on a party's own report is a
            # question about that party -- it is not a request to set agents
            # working, and putting it through the router meant "what matters
            # most here?" came back as "nothing in that matched a job this
            # can do", because the words name no subject. The subject is the
            # report it was typed into.
            plan = (Plan(kind="answer") if looking_at
                    else plan_from(asked, transport))
            today = date.today().isoformat()

            if plan.refused:
                self._json({"kind": "refused", "said": plan.refused,
                            "guessed": plan.guessed})
                return

            if plan.kind == "answer":
                # What was said before, read back out of the log rather than
                # taken from the browser. The screen posts a question and
                # nothing else: a history arriving from the client would be a
                # way to hand our own assistant a conversation that never
                # happened, and the reply goes out with the firm's name on it.
                # Keyed on who is asking, so the same officer picks the thread
                # up on another machine and somebody else never sees it.
                earlier = tuple(
                    {"asked": turn.asked, "said": turn.said}
                    for turn in engine.state.talk.thread(acting)
                    if turn.kind == "answer" and turn.said and not turn.withheld
                )
                try:
                    answered = ask(engine, asked,
                                   transport=providers.conversation(now=_utcnow),
                                   person=acting, asked_at=today,
                                   earlier=earlier, looking_at=looking_at)
                except Exception as failure:
                    # A reader that cannot be reached is a normal state,
                    # not an error page: the officer is told and can ask
                    # for the work instead.
                    #
                    # The operator is told which failure it was, on the
                    # console and nowhere near the officer. Catching every
                    # exception and printing one sentence about the network
                    # made a Bedrock configuration fault look identical to a
                    # dropped connection, and cost an hour of guessing at a
                    # box that was answering perfectly well when asked
                    # directly. A guard that fires silently is a guard
                    # nobody can audit -- including us.
                    #
                    # The class and its message, never a traceback and never
                    # the question: the first two say what to fix, and the
                    # rest is either noise or a customer's records in a log.
                    print(f"  the reader refused a question: "
                          f"{type(failure).__name__}: {failure}",
                          file=sys.stderr)
                    self._json({
                        "kind": "refused",
                        "said": "The reader could not be reached just now, "
                                "so nothing was answered and nothing was "
                                "recorded. Ask again, or ask for the work "
                                "to be run instead."})
                    return
                self._json({
                    "kind": "answer",
                    "said": answered.answer,
                    "withheld": answered.refused,
                    "looked_at": [step.shown or step.tool
                                  for step in answered.steps],
                })
                return

            task_id, _plan = engine.give_asked_task(
                asked=asked, actor=acting, given_at=today,
                transport=transport)
            if task_id is None:
                self._json({"kind": "refused", "said": plan.refused
                            or "Nothing here can answer that."})
                return

            def work():
                try:
                    engine.run_task(task_id, when=today)
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()
            task = engine.state.runs.tasks.get(task_id)
            self._json({"kind": "work", "said": plan.said,
                        "task_id": task_id,
                        "task": _task_json(task, today) if task else {}})

        def _give_task(self) -> None:
            """Delegate a job, and start it running.

            The plan is recorded before the reply goes back, so the screen
            that opens next already knows every step that was undertaken.
            The work itself runs on its own thread and each step lands in
            the log as it finishes -- which is what makes the progress a
            person watches a reading of the record rather than an
            animation.
            """
            acting = self._who()
            if acting is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            if engine.state.actors.get(acting) is None:
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(body, dict):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return

            today = date.today().isoformat()
            asked = str(body.get("asked") or "").strip()

            if asked:
                # Somebody typed a sentence. The model picks the tools and
                # says what it is about to do; it never says what was
                # found. Where it cannot be reached, a keyword fallback
                # answers and the screen says so.
                transport = None
                from . import providers
                try:
                    if providers.configured():
                        transport = providers.drafter(now=_utcnow).transport
                except Exception:
                    transport = None
                task_id, plan = engine.give_asked_task(
                    asked=asked, actor=acting, given_at=today,
                    transport=transport)
                if task_id is None:
                    self._json({"refused": plan.refused,
                                "guessed": plan.guessed,
                                "dropped": list(plan.invented)},
                               HTTPStatus.OK)
                    return
            else:
                try:
                    task_id = engine.give_task(
                        recipe_key=str(body.get("job") or ""),
                        actor=acting, given_at=today,
                        party=str(body.get("party") or ""))
                except ValueError as refused:
                    self._json({"message": str(refused)},
                               HTTPStatus.BAD_REQUEST)
                    return

            def work():
                try:
                    engine.run_task(task_id, when=today,
                                    party=str(body.get("party") or ""))
                except Exception:
                    # The run records its own failures step by step. This
                    # catch only stops a dead thread taking the server
                    # with it.
                    pass

            threading.Thread(target=work, daemon=True).start()
            task = engine.state.runs.tasks.get(task_id)
            self._json({"task": _task_json(task, today) if task else {},
                        "task_id": task_id})

        def _doorway(self, route: str) -> None:
            """Signing in and out. The only routes that answer unsigned."""
            if route == "/api/sign-out":
                keys.end_session(self._token())
                self._set_cookie("", ending=True)
                self._json({"signed_in": False, "message": UI["signed_out"]})
                return

            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            if length < 0 or length > MAX_BODY_BYTES:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(body, dict):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return

            name = str(body.get("person") or "")[:200]
            password = str(body.get("password") or "")[:1000]
            token, refused = keys.sign_in(name, password,
                                          datetime.now().isoformat())
            if refused is not None:
                # Deliberately the same answer whichever way it failed, and
                # deliberately slow: the work is done before we know.
                self._json({"signed_in": False, "message": refused.said,
                            "wait_minutes": refused.wait_minutes},
                           HTTPStatus.UNAUTHORIZED)
                return
            self._set_cookie(token)
            entry = engine.state.actors.get(name) or {}
            self._json({"signed_in": True, "person": name,
                        "title": entry.get("title", "")})

        def _query(self, key: str) -> Optional[str]:
            from urllib.parse import parse_qs, urlparse

            values = parse_qs(urlparse(self.path).query).get(key)
            return values[0] if values else None

        # -- the one write ------------------------------------------------

        def do_POST(self) -> None:  # noqa: N802
            route = self.path.split("?", 1)[0]
            if not self._may_read(route):
                return
            # Every write, without exception, before any route is chosen.
            #
            # These two checks used to sit further down, after ``/api/chat``,
            # ``/api/tasks`` and the sign-in had already returned -- so the
            # three routes that set an agent working, put a question to the
            # model and answered the door were the three with no ceiling on
            # the body and no check that the request came from our own
            # screen. A guard that each route has to remember to ask for is
            # a guard that some route will forget.
            if not self._same_origin():
                # Drained before answering, for the reason spelled out at
                # the body-cap check further down: the sender is still
                # putting bytes on the wire, and closing a socket on unread
                # bytes makes Windows send a reset rather than a clean
                # finish -- so the caller sees a dropped connection instead
                # of the sentence explaining the refusal. Found by the test
                # for this very guard, one run in one.
                self._refuse_politely("not_allowed", HTTPStatus.FORBIDDEN)
                return
            try:
                declared = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            ceiling = _ceiling_for(route)
            if declared < 0 or declared > ceiling:
                self._drain()
                self.close_connection = True
                self._problem("unavailable", HTTPStatus.BAD_REQUEST, close=True)
                return
            if route == "/api/chat":
                self._say()
                return
            if route == "/api/tasks":
                self._give_task()
                return
            if route in ("/api/sign-in", "/api/sign-out"):
                self._doorway(route)
                return
            if route.startswith("/api/onboarding/") and route.endswith("/documents"):
                # Raw bytes, not JSON: handled before the body is read, since
                # nothing here should try to parse a PDF as an object.
                self._file_document(
                    route[len("/api/onboarding/"):-len("/documents")])
                return
            if route not in ("/api/decisions", "/api/confirmations",
                             "/api/ask", "/api/checks", "/api/imports",
                             "/api/imports/apply", "/api/risk", "/api/tasks",
                             "/api/filings", "/api/chat", "/api/onboarding"):
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return
            cap = _ceiling_for(route)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            if length < 0 or length > cap:
                # Refusing is the easy half. The hard half is ending the
                # conversation politely: bytes the sender already put on the
                # wire are sitting in our receive buffer, and closing a socket
                # on unread bytes makes Windows send a reset rather than a
                # clean finish -- so the caller sees a dropped connection
                # instead of the sentence explaining why it was refused. This
                # path failed about one run in five before the drain below.
                #
                # We cannot read what the header *claims*; that is the whole
                # point of refusing. So we drain briefly for whatever actually
                # arrived, cap it so a liar cannot make us buffer their body
                # anyway, and give up quickly if nothing more is coming.
                self._drain()
                self.close_connection = True
                self._problem("unavailable", HTTPStatus.BAD_REQUEST, close=True)
                return
            # Read the body before deciding anything, even when the answer is
            # going to be no. Replying while the client is still sending
            # leaves unread bytes in the socket, and closing on them resets
            # the connection: the caller would see a dropped connection
            # instead of the sentence explaining why it was refused.
            try:
                raw = self.rfile.read(length)
            except OSError:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            if not self._same_origin():
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
                return
            if route == "/api/imports":
                # The upload is raw bytes, not JSON. An HTML form cannot
                # send application/octet-stream any more than it can send
                # application/json, so the CSRF property of the check below
                # is kept, just against a different type.
                content_type = (self.headers.get("Content-Type") or "")
                content_type = content_type.split(";")[0].strip()
                if content_type != "application/octet-stream":
                    self._problem("not_allowed", HTTPStatus.FORBIDDEN)
                    return
                self._import_sheet(raw)
                return

            # A second, independent CSRF control alongside the origin check
            # above (OWASP CSRF Prevention Cheat Sheet recommends layering
            # both rather than relying on Origin/Referer alone): a plain HTML
            # form -- the one cross-site request a browser will send without
            # any script and without a CORS preflight -- cannot set this
            # header to anything but one of a handful of form values, none of
            # them "application/json". A page that Origin somehow failed to
            # catch still cannot shape a body we will parse as a decision.
            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if content_type != "application/json":
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
                return
            try:
                body = json.loads(raw or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            # "null", "[]" and "7" are all valid JSON. Only an object carries
            # a decision, and .get() on anything else raised straight out of
            # the handler: the client got no reply at all and the officer's
            # console filled with a traceback.
            if not isinstance(body, dict):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            expected = {
                "/api/confirmations": ("person", "clause", "qualification",
                                       "note"),
                "/api/ask": ("person", "question", "context_kind",
                             "context_id", "context_label"),
                "/api/checks": ("person", "party"),
                "/api/risk": ("person", "party", "category", "reason"),
                "/api/imports/apply": ("person", "digest", "sheet", "kind"),
            }.get(route, ("person", "file", "reason", "outcome", "used", "code"))
            if not all(isinstance(body.get(k, ""), str) for k in expected):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return

            # Who is acting is worked out here and nowhere else. It used
            # to be read from ``body["person"]``, which meant anybody who
            # could reach this port could post as Senior Management and
            # clear the politically-exposed files only Senior Management
            # may clear. The body may still carry a name -- older clients
            # send one -- and it is ignored.
            acting = self._who(body)
            if acting is None:
                self._problem("sign_in_first", HTTPStatus.UNAUTHORIZED)
                return
            entry = engine.state.actors.get(acting)
            if entry is None:
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
                return
            body = {**body, "person": acting}

            if route == "/api/imports/apply":
                self._apply_import(body, entry)
                return
            if route == "/api/confirmations":
                self._confirm(body, entry)
                return
            if route == "/api/ask":
                self._ask(body)
                return
            if route == "/api/checks":
                self._check(body, entry)
                return
            if route == "/api/risk":
                self._assess(body, entry)
                return
            if route == "/api/filings":
                self._filed(body)
                return
            if route == "/api/onboarding":
                self._onboard(body, entry)
                return
            reason = (body.get("reason") or "").strip()
            if not reason:
                self._problem("needs_reason", HTTPStatus.BAD_REQUEST)
                return
            try:
                outcome = Outcome(body.get("outcome", ""))
            except ValueError:
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return

            # What happened to any suggestion on this file is settled here,
            # not in the browser: the screen reports whether its wording was
            # used, but whether the decision *contradicted* the suggestion is
            # read off the record, because that is the number a firm would be
            # tempted not to report.
            try:
                case = engine.state.casebook.get(body.get("file", ""))
            except UnknownCase:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return
            used = draft_use(case, outcome, body.get("used", "NONE"))

            try:
                engine.decide(
                    case_id=body.get("file", ""),
                    outcome=outcome,
                    actor=body["person"],
                    role=entry["role"],
                    rationale=reason,
                    decided_at=date.today().isoformat(),
                    draft_use=used,
                    # Passed whole. The engine refuses a code it does not
                    # offer, which is the right answer; cutting it here
                    # turned an invalid code into a different invalid code.
                    reason_code=str(body.get("code", "")),
                )
            except SeniorManagementMustApprove:
                self._problem("senior_only", HTTPStatus.FORBIDDEN)
            except EscalationNeedsAnotherOfficer:
                self._problem("four_eyes", HTTPStatus.FORBIDDEN)
            except DecisionDenied:
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
            except UnknownCase:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                if "already" in str(exc):
                    key = "already_settled"
                elif "says nothing" in str(exc):
                    key = "reason_too_thin"
                else:
                    key = "needs_reason"
                self._problem(key, HTTPStatus.CONFLICT)
            else:
                self._json({"message": MESSAGES["settled"]})

        def _import_sheet(self, raw: bytes) -> None:
            """Read an uploaded sheet and answer with what it says.

            A read, not a write: the file is kept as an exhibit and the
            plan is rebuilt from it at confirm time, so what gets written
            is a function of the file alone -- never of anything a browser
            claims about it.
            """
            import hashlib as _hashlib
            from urllib.parse import unquote

            digest = _hashlib.sha256(raw).hexdigest()
            claimed = unquote(self.headers.get("X-Vinzor-Filename") or "sheet")
            filename = Path(claimed.replace("\\", "/")).name or "sheet"
            home = self._import_home()
            stored = home / f"{digest[:12]}-{filename}"
            if not stored.exists():
                stored.write_bytes(raw)
                # Uploads are held only long enough for the officer reading
                # the report to confirm it. Keeping every sheet anyone ever
                # opened would let a morning of browsing fill the disk, and
                # the sheets that matter are the ones already written into
                # the log, not these.
                import time as _time

                oldest_kept = _time.time() - _HOLD_UPLOADS_FOR_SECONDS
                on_disk = sorted(home.iterdir(),
                                 key=lambda f: f.stat().st_mtime)
                stale = set(on_disk[:-_HELD_UPLOADS])
                stale.update(f for f in on_disk
                             if f.stat().st_mtime < oldest_kept)
                stale.discard(stored)
                for gone in stale:
                    try:
                        gone.unlink()
                    except OSError:
                        pass

            sheet = self._query("sheet") or ""
            kind = self._query("kind") or ""
            try:
                plan = read_sheet(stored, default_kind=kind or None,
                                  sheet=sheet)
            except ValueError as exc:
                self._json({"message": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            repeat = already_imported(engine, digest)
            if repeat:
                plan.refusals.insert(0, repeat)
            self._json(import_report(
                plan, digest, filename,
                screening=bool(os.environ.get("VINZOR_SCREENING_URL", ""))))

        def _apply_import(self, body: dict, entry: dict) -> None:
            """The one write: a person confirms, the rows land, screening
            of everyone new starts on its own."""
            if entry["role"] not in DECIDING_ROLES:
                self._problem("viewer_import", HTTPStatus.FORBIDDEN)
                return
            import hashlib as _hashlib

            # The digest arrives from the browser, so it is treated as a
            # claim rather than a fact: anything but a plain hash is refused
            # before it reaches the filesystem (a "*" or "[" here would
            # otherwise make the lookup below match somebody else's upload),
            # and the digest written to the permanent record is recomputed
            # from the bytes on disk, never copied from the request.
            claimed = str(body.get("digest", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", claimed):
                self._problem("upload_expired", HTTPStatus.NOT_FOUND)
                return
            home = self._import_home()
            stored = next(iter(home.glob(f"{claimed[:12]}-*")), None)
            if stored is None:
                self._problem("upload_expired", HTTPStatus.NOT_FOUND)
                return
            digest = _hashlib.sha256(stored.read_bytes()).hexdigest()
            if digest != claimed:
                self._problem("upload_expired", HTTPStatus.NOT_FOUND)
                return

            plan = read_sheet(stored, default_kind=body.get("kind") or None,
                              sheet=body.get("sheet") or "")
            if plan.refusals:
                self._json({"message": plan.refusals[0]},
                           HTTPStatus.CONFLICT)
                return

            before = set(engine.state.graph.entities)
            filename = stored.name.split("-", 1)[-1]
            try:
                counts = apply_import(
                    engine, plan, date.today().isoformat(),
                    by=body["person"], filename=filename, digest=digest)
            except ValueError as exc:
                self._json({"message": str(exc)}, HTTPStatus.CONFLICT)
                return
            fresh = [entity_id for entity_id in engine.state.graph.entities
                     if entity_id not in before]

            url = os.environ.get("VINZOR_SCREENING_URL", "")
            if url:
                SCREENING_RUNS[digest] = {"done": 0, "total": len(fresh),
                                          "matches": 0, "state": "running",
                                          "kind": plan.kind, "problem": ""}
                thread = threading.Thread(
                    target=_screen_fresh, args=(engine, fresh, digest),
                    daemon=True)
                thread.start()
                screening = True
            else:
                SCREENING_RUNS[digest] = {
                    "done": 0, "total": len(fresh), "matches": 0,
                    "state": "skipped", "kind": plan.kind, "problem": ""}
                screening = False

            self._json({
                "message": import_receipt(counts, plan.kind, screening),
                "progress": digest,
                "counts": counts,
            })

        def _check(self, body: dict, entry: dict) -> None:
            """Run one party through the watchlists, live, and narrate it.

            A write, behind the same gate as a decision: the check mints
            screening records and may open files, and an inspector reading
            them will ask who ran it.
            """
            import os

            from .check import run_check
            from .screening import WatchlistClient

            if entry["role"] not in DECIDING_ROLES:
                self._problem("viewer_check", HTTPStatus.FORBIDDEN)
                return
            # No configured service means no check -- never a silent fall
            # back to the hosted API, which would send this party's name off
            # the machine without anyone having decided that. The first
            # screenshot of this screen caught exactly that: an unset URL
            # quietly became a 401 from a third party that had already been
            # handed the name.
            url = os.environ.get("VINZOR_SCREENING_URL", "").strip()
            if not url:
                self._problem("no_screening_service",
                              HTTPStatus.SERVICE_UNAVAILABLE)
                return
            client = WatchlistClient(
                url=url,
                api_key=os.environ.get("VINZOR_SCREENING_KEY", ""),
                scope=os.environ.get("VINZOR_SCREENING_SCOPE", "default"),
            )
            drafter = None
            from . import providers
            try:
                if providers.configured():
                    drafter = providers.drafter(now=_utcnow)
            except Exception:
                drafter = None          # a missing drafter is not an error
            try:
                investigation = run_check(
                    engine, body.get("party", ""), client=client,
                    today=date.today().isoformat(), drafter=drafter,
                )
            except KeyError:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
                return
            payload = _encode(investigation)
            payload["ui"] = UI
            payload["workspace"] = WORKSPACE
            self._json(payload)

        def _ask(self, body: dict) -> None:
            """A question about this workspace, answered from this workspace.

            A POST because it writes: what the assistant was asked and what it
            said go on the log. It settles nothing -- there is no tool behind
            it that can.
            """
            from . import providers
            from .ask import AskingUnavailable, ask

            question = (body.get("question") or "").strip()
            if not question:
                self._problem("needs_question", HTTPStatus.BAD_REQUEST)
                return
            if len(question) > 1_000:
                self._problem("question_too_long", HTTPStatus.BAD_REQUEST)
                return
            try:
                answer = ask(engine, question,
                             transport=providers.conversation(now=_utcnow),
                             person=body.get("person", ""),
                             # The date is supplied here, at the boundary,
                             # because nothing inside vinzor/ reads a clock.
                             asked_at=date.today().isoformat(),
                             looking_at={
                                 "kind": body.get("context_kind", "")[:32],
                                 "id": body.get("context_id", "")[:128],
                                 "label": body.get("context_label", "")[:200],
                             })
            except AskingUnavailable as problem:
                self._json({"question": question, "answer": "",
                            "refused": str(problem), "steps": [],
                            "ui": UI})
                return
            self._json({
                "question": answer.question,
                "answer": answer.answer,
                "refused": answer.refused,
                "steps": [{"tool": s.tool, "why": s.why} for s in answer.steps],
                "ui": UI,
            })

        def _filed(self, body: dict) -> None:
            """Record that a return or a fee went in.

            The other half of the calendar, which did not exist. Lateness was
            swept for on every briefing load; nothing anywhere could record a
            filing, so a firm licensed three years before its first day on
            this system collected nineteen permanent overdue records in one
            call and had no way to say it had filed any of them.

            Not gated to a deciding role. Recording that a return went in is
            bookkeeping, not judgement about a customer.
            """
            reported = {}
            for field in ("aum_usd", "investors", "schemes",
                          "capital_received_usd"):
                if body.get(field) not in (None, ""):
                    reported[field] = body[field]
            try:
                engine.record_filing(
                    obligation=body.get("obligation", ""),
                    period=body.get("period", ""),
                    submitted_on=body.get("submitted_on", ""),
                    actor=body.get("person", ""),
                    reported=reported or None,
                    note=body.get("note", ""))
            except ValueError as refused:
                # The sentence the engine wrote, not a code. It names the
                # remedy -- which obligations exist, how to write the date --
                # and inventing a second wording here would lose that.
                self._json({"message": str(refused)}, HTTPStatus.BAD_REQUEST)
                return
            self._json({"message": MESSAGES["filing_recorded"]})

        def _assess(self, body: dict, entry: dict) -> None:
            """A person categorising a customer under clause 4.2.

            Gated as a decision is: the category sets how often the customer
            is looked at again under clause 5.11, so nothing automatic may
            set one.
            """
            if entry["role"] not in DECIDING_ROLES:
                self._problem("viewer", HTTPStatus.FORBIDDEN)
                return
            answers = body.get("answers")
            if answers is not None and not isinstance(answers, dict):
                self._problem("unavailable", HTTPStatus.BAD_REQUEST)
                return
            try:
                engine.assess_risk(
                    entity_id=body.get("party", ""),
                    category=body.get("category", ""),
                    actor=body["person"],
                    role=entry["role"],
                    reason=body.get("reason", ""),
                    assessed_at=date.today().isoformat(),
                    answers=answers or None,
                )
            except KeyError:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
            except DecisionDenied:
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
            except ValueError as exc:
                key = ("risk_bad_category" if "high, medium or low" in str(exc)
                       else "risk_needs_reason")
                self._problem(key, HTTPStatus.BAD_REQUEST)
            else:
                self._json({"message": MESSAGES["risk_recorded"]})

        def _confirm(self, body: dict, entry: dict) -> None:
            """A qualified person putting their name to a clause.

            The same human gate as a decision, for the same reason: this is
            the assertion an inspector leans on hardest, and the one nothing
            automatic may make.
            """
            if entry["role"] not in DECIDING_ROLES:
                self._problem("viewer", HTTPStatus.FORBIDDEN)
                return
            try:
                engine.confirm_clause(
                    clause_id=body.get("clause", ""),
                    reviewer=body["person"],
                    role=entry["role"],
                    qualification=body.get("qualification", ""),
                    note=body.get("note", ""),
                    confirmed_at=date.today().isoformat(),
                )
            except KeyError:
                self._problem("not_found", HTTPStatus.NOT_FOUND)
            except DecisionDenied:
                self._problem("not_allowed", HTTPStatus.FORBIDDEN)
            except ValueError:
                self._problem("needs_confirmation_detail", HTTPStatus.BAD_REQUEST)
            else:
                self._json({"message": MESSAGES["confirmed"]})

    # Hung on the class so ``serve()`` can clear the upload area when it
    # stops. Nothing in a request ever reaches it.
    Handler.forget_exhibits = staticmethod(forget_exhibits)
    return Handler


#: Progress of each import's screening run, by file digest. Read by the
#: progress route; written by the one thread running that screening.
SCREENING_RUNS: dict[str, dict] = {}


def _screen_fresh(engine, entity_ids, digest: str) -> None:
    """Screen every party an import just registered, keeping count.

    Each check is an ordinary screening fact on the log; a match opens a
    file exactly the way a hand-run check would. If the service stops
    answering mid-run, the run stops and says where -- what was screened
    is on the record, and the rest can be screened again later.
    """
    from .screening import ScreeningUnavailable, WatchlistClient, screen

    progress = SCREENING_RUNS[digest]
    client = WatchlistClient(
        url=os.environ.get("VINZOR_SCREENING_URL", ""),
        api_key=os.environ.get("VINZOR_SCREENING_KEY", ""),
        scope=os.environ.get("VINZOR_SCREENING_SCOPE", "default"),
    )
    today = date.today().isoformat()
    for entity_id in entity_ids:
        try:
            for result in screen(engine, entity_id, screened_at=today,
                                 client=client):
                if result.cases:
                    progress["matches"] += 1
        except ScreeningUnavailable as exc:
            progress["state"] = "stopped"
            progress["problem"] = str(exc)
            return
        progress["done"] += 1
    progress["state"] = "finished"


def _periods(today: str) -> list:
    """The periods a compliance function actually reports on, each as the
    first day it covers. Computed at the boundary, because this is the only
    layer that knows what day it is."""
    year, month = int(today[:4]), int(today[5:7])
    last_year, last_month = (year, month - 1) if month > 1 else (year - 1, 12)
    quarter_start = ((month - 1) // 3) * 3 + 1
    return [
        {"label": UI["report_this_month"], "since": f"{year:04d}-{month:02d}-01"},
        {"label": UI["report_last_month"],
         "since": f"{last_year:04d}-{last_month:02d}-01"},
        {"label": UI["report_this_quarter"],
         "since": f"{year:04d}-{quarter_start:02d}-01"},
        {"label": UI["report_this_year"], "since": f"{year:04d}-01-01"},
        {"label": UI["report_everything"], "since": "0001-01-01"},
    ]


def open_workspace(path: Optional[Path] = None, dataset: Path = DEFAULT_DATASET,
                   demo: bool = True) -> Vinzor:
    """Load the workspace, seeding it from the dataset the first time only.

    Decisions are events, so they survive a restart -- which is the whole point
    of the log and the easiest way to see it working.

    ``demo=False`` opens an empty workspace and leaves it empty. A firm loading
    its own investor book must never find 204 invented parties mixed in with
    it: they would be indistinguishable from real ones on every screen, and
    the log is append-only, so there would be no taking them out again.
    """
    if path is None:
        engine = seed(dataset=dataset) if demo else Vinzor(EventLog())
    else:
        engine = Vinzor(EventLog(path))
        if len(engine.log) == 0 and demo:
            seed(engine, dataset=dataset)
    enroll_people(engine, date.today().isoformat())
    return engine


def serve(host: str = "127.0.0.1", port: int = 8000,
          workspace: Optional[Path] = None) -> None:
    from .providers import check_region

    # Loudly, and at boot. A region outside India used to be discovered once
    # per page view, as a dropped connection and a traceback on this console.
    check_region()

    engine = open_workspace(workspace)
    keys = Credentials(getattr(engine.log, "path", ":memory:"))
    handler = build_app(engine, keys)
    httpd = ThreadingHTTPServer((host, port), handler)
    open_files = len(engine.queue())
    print(f"  {WORKSPACE}: {len(engine.log)} records, {open_files} files open")
    print(f"  http://{host}:{port}")
    if keys.anybody_can_sign_in():
        print("  Signing in is required. The session cookie is HttpOnly and")
        print("  SameSite=Strict, and gains Secure on any request a proxy")
        print("  in front reports as HTTPS. On loopback it does not, because")
        print("  a Secure cookie is one this browser would never send back.")
    else:
        print("  No password is set, so anybody reaching this port can act")
        print("  as anybody. Fine on a laptop, not for real customer data:")
        print('    python -m vinzor password --name "Their Name" '
              "--workspace live.db")
    print("  Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()
        # Uploaded customer sheets do not outlive the server that was shown
        # them. They used to outlive everything.
        handler.forget_exhibits()

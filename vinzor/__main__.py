"""``python -m vinzor`` -- run the whole chain against the synthetic dataset.

This is a boundary, so this is where the clock lives. The core never reads one;
a caller out here supplies the date, which is exactly why the log can be
replayed and the demo is reproducible.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .cases import DecisionDenied
from .enforcement import COVERAGE, roadmap, scorecard
from .citations import coverage
from .graph import Conclusion, OwnershipTest
from .model import Outcome, Role, Severity
from .seed import DEFAULT_DATASET, seed

RULE = "-" * 78


def _h(title: str) -> None:
    print(f"\n{title}\n{RULE}")


def _wrapped(text: str, width: int) -> list:
    """A long sentence broken to a readable width. A caveat printed as one
    unbroken line is a caveat that has failed at its only job."""
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


USAGE = """vinzor

  python -m vinzor              walk the whole chain against the dataset
  python -m vinzor serve        run the workspace and open it in a browser
  python -m vinzor screen NAME  check one name against live watchlists
                                (--kind PERSON|COMPANY|TRUST, --country XX;
                                 uses OpenSanctions/yente via
                                 VINZOR_SCREENING_URL / VINZOR_SCREENING_KEY /
                                 VINZOR_SCREENING_SCOPE; see selfhost/)
  python -m vinzor rescreen     screen every investor in a workspace against
                                the live watchlist, recording what matched
  python -m vinzor readiness    check the client book against clause 5.4.2,
                                which is what any KYC registration agency
                                upload needs before it needs anything else
  python -m vinzor capital      show the minimum this licence requires and
                                what the firm last reported (--worth N)
  python -m vinzor document     file a document against a party and say
                                what it evidences (--kinds lists them)
  python -m vinzor password     set or remove somebody's way in
                                (--name "Their Name", --remove)
  python -m vinzor notice       record a letter from a regulator, or the
                                answer to one. --list shows what is open
  python -m vinzor assist       prepare suggestions for open name checks
                                (India only, whichever is configured:
                                 Azure OpenAI -- AZURE_OPENAI_ENDPOINT /
                                 _DEPLOYMENT / _REGION / _KEY; or Bedrock --
                                 VINZOR_BEDROCK=1, VINZOR_BEDROCK_REGION and
                                 a role on the machine.
                                 --limit N, --budget USD, --dry-run)

  serve options:
    --port N        default 8000
    --workspace P   persist to P instead of memory (decisions survive a restart)

  rescreen and assist take --workspace P too, and want it: both write facts
  that are only worth having if they outlive the process.
"""


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Read ``KEY=value`` lines from ``.env`` into the environment.

    Stdlib only, deliberately minimal -- this is not a general-purpose parser,
    it is the ten lines this project needs so a founder can paste a key into a
    file once instead of exporting it in every new terminal. A variable
    already set in the real environment is never overwritten: the file is a
    convenience default, not an authority over a session someone configured
    on purpose. Nothing here ever prints a value -- a loader that echoed what
    it loaded would defeat the point of keeping secrets out of the console.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class Misused(SystemExit):
    """The command line was wrong. Says so in a sentence and stops."""

    def __init__(self, message: str) -> None:
        super().__init__(f"\n  {message}\n")


def _value(argv: list[str], name: str) -> Optional[str]:
    """The value after ``name``, or a plain complaint if there isn't one.

    ``argv[argv.index(name) + 1]`` walks off the end when a flag is typed last
    -- "--workspace" with nothing after it dumped an IndexError traceback on a
    compliance officer. A stack trace is not an error message.
    """
    if name not in argv:
        return None
    position = argv.index(name) + 1
    if position >= len(argv) or argv[position].startswith("--"):
        raise Misused(f"{name} needs a value after it. For example: {name} fund.db")
    return argv[position]


def _flag(argv: list[str], name: str, fallback):
    value = _value(argv, name)
    if value is None:
        return fallback
    if fallback is None:
        return value
    try:
        return type(fallback)(value)
    except ValueError:
        raise Misused(
            f"{name} expects {type(fallback).__name__.replace('int', 'a whole number')}"
            f", not {value!r}."
        ) from None


def _open(argv: list[str]):
    """Open the workspace named on the command line, or a throwaway one."""
    from pathlib import Path as _Path

    from .server import open_workspace

    where = _value(argv, "--workspace")
    return open_workspace(_Path(where) if where else None)


def _rescreen_cli(argv: list[str]) -> int:
    """Screen everyone in the workspace, recording the watchlist detail.

    The synthetic dataset's alerts say *that* a name matched but not *what* it
    matched -- no date of birth, no nationality, no list entry. That is enough
    to open a file and not enough to review one. This replaces guesswork with a
    real answer from the watchlist, on the record, with its provenance.
    """
    import os

    from .model import EntityKind
    from .screening import (OFF_MACHINE_WARNING, ScreeningUnavailable,
                        WatchlistClient, leaves_this_machine, screen)

    engine = _open(argv)
    limit = _flag(argv, "--limit", 25)
    client = WatchlistClient(
        url=os.environ.get("VINZOR_SCREENING_URL", "https://api.opensanctions.org"),
        api_key=os.environ.get("VINZOR_SCREENING_KEY", ""),
        scope=os.environ.get("VINZOR_SCREENING_SCOPE", "default"),
    )
    today = date.today().isoformat()
    people = [e for e in engine.state.graph.entities.values()
              if e.kind is EntityKind.PERSON][:limit]

    print(f"  screening {len(people)} investors against {client.url}")
    if leaves_this_machine(client.url):
        from urllib.parse import urlparse

        print(OFF_MACHINE_WARNING.format(
            host=urlparse(client.url).hostname or client.url))
    opened = 0
    for entity in people:
        try:
            for result in screen(engine, entity.entity_id, screened_at=today,
                                 client=client):
                for case in result.cases:
                    opened += 1
                    print(f"  {case.severity.value:<8} {case.evidence[0].summary}")
        except ScreeningUnavailable as exc:
            print(f"  stopped: {exc}")
            return 1
    print(f"  {opened} file(s) opened or extended; every check is on the record.")
    return 0


def _assist_cli(argv: list[str]) -> int:
    """Prepare suggestions for open name checks. A boundary: it knows the date.

    Nothing here can close anything. Each suggestion is written to the log as
    a fact about what the system said, and waits for a person.
    """
    from .assist import DEFAULT_BUDGET_USD, DraftingUnavailable, prepare_drafts
    from .azure import DataResidencyError
    from . import providers
    from .briefing import report
    from .compare import comparison_for
    from .quality import measure

    engine = _open(argv)
    limit = _flag(argv, "--limit", 10)
    budget = _flag(argv, "--budget", DEFAULT_BUDGET_USD)

    waiting = [c for c in engine.queue()
               if c.case_type == "SCREENING_HIT" and c.draft is None]
    ready = [c for c in waiting if comparison_for(engine, c) is not None]
    print(f"  {len(waiting)} open name check(s); {len(ready)} carry enough "
          f"watchlist detail to review")
    if len(ready) < len(waiting):
        print("  the rest matched a name and nothing else - run "
              "'python -m vinzor rescreen' to record what they matched")

    if "--dry-run" in argv:
        for case in ready[:limit]:
            comparison = comparison_for(engine, case)
            print(f"\n  {comparison.our_name}  vs  {comparison.listed_name}")
            for item in comparison.fields:
                print(f"    {item.field:<20} {item.verdict.value:<10} {item.note}")
        return 0

    try:
        # A boundary, so the clock lives here and is handed down: Bedrock
        # signs with it and no module below may read one.
        prepared = providers.drafter(now=lambda: datetime.now(timezone.utc))
    except DraftingUnavailable as exc:
        print(f"  {exc}")
        print("  For Azure: set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT,")
        print("  AZURE_OPENAI_REGION and AZURE_OPENAI_KEY.")
        print("  For Bedrock: set VINZOR_BEDROCK=1 and VINZOR_BEDROCK_REGION,")
        print("  and give the machine credentials or a role.")
        print("  The region must be one inside India; nothing else is accepted.")
        return 1
    except DataResidencyError as exc:
        print(f"  refused: {exc}")
        return 1

    print(f"  drafting with {prepared.model} in {prepared.region}, "
          f"up to US$ {budget:,.2f}")
    try:
        drafts = prepare_drafts(engine, prepared_at=date.today().isoformat(),
                                drafter=prepared, limit=limit,
                                budget_usd=budget)
    except DataResidencyError as exc:
        print(f"  STOPPED - {exc}")
        return 2

    for draft in drafts:
        print(f"\n  {draft.recommendation}")
        print(f"    {draft.reasoning}")
    written = measure(engine, budget)
    print(f"\n  {len(drafts)} suggestion(s) prepared, "
          f"US$ {written.spend_usd:.4f} spent.")
    print(f"  {report(written).standing}")
    return 0


def _screen_cli(argv: list[str]) -> int:
    """Screen one name against a live watchlist service, from the shell.

    A boundary: reads the clock and the network, mints facts into a throwaway
    workspace, and reports in plain words what would land on the morning list.
    """
    import os

    from .eventlog import EventLog
    from .engine import Vinzor
    from .model import EntityKind, EventType
    from .screening import ScreeningUnavailable, WatchlistClient, screen

    if not argv or argv[0].startswith("-"):
        print('usage: python -m vinzor screen "Full Name" [--kind PERSON] [--country XX]')
        return 1
    name = argv[0]
    kind = EntityKind((_value(argv, "--kind") or "PERSON").upper())
    country = _value(argv, "--country") or ""

    client = WatchlistClient(
        url=os.environ.get("VINZOR_SCREENING_URL", "https://api.opensanctions.org"),
        api_key=os.environ.get("VINZOR_SCREENING_KEY", ""),
        # A self-hosted yente indexes a named collection; ours indexes
        # "sanctions" (see selfhost/manifest.yml). The hosted API calls its
        # full collection "default".
        scope=os.environ.get("VINZOR_SCREENING_SCOPE", "default"),
    )
    engine = Vinzor(EventLog())
    today = date.today().isoformat()
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="subject",
                  occurred_at=today,
                  payload={"kind": kind.value, "name": name,
                           "attributes": {"nationality": country} if country else {}})
    try:
        results = screen(engine, "subject", screened_at=today, client=client)
    except ScreeningUnavailable as exc:
        print(f"  {exc}")
        print("  To screen for real: self-host yente (github.com/opensanctions/yente)")
        print("  and set VINZOR_SCREENING_URL, or set VINZOR_SCREENING_KEY for the")
        print("  hosted OpenSanctions API.")
        return 1

    matched = [r for r in results if r.event.payload.get("matched")]
    cased = [c for r in results for c in r.cases]
    if not cased:
        basis = results[0].event.payload.get("basis", {})
        print(f"  No qualifying match for \"{name}\" ({kind.value.title()}) "
              f"against {basis.get('scope', 'the watchlists')}.")
        print("  The screening itself is on the record — that is the clause 5.9 evidence.")
        return 0
    for result in matched:
        basis = result.event.payload.get("basis", {})
        for case in result.cases:
            print(f"  {case.severity.value:<8} {case.evidence[0].summary}")
        print(f"           matched: {basis.get('caption')}  "
              f"score {basis.get('score')}  "
              f"lists: {', '.join(basis.get('datasets', [])[:4])}")
    print(f"  {len(cased)} file(s) would open on the morning list, "
          f"citing the clauses behind them.")
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv and argv[0] == "screen":
        return _screen_cli(argv[1:])
    if argv and argv[0] == "rescreen":
        return _rescreen_cli(argv[1:])
    if argv and argv[0] == "assist":
        return _assist_cli(argv[1:])
    if argv and argv[0] == "import":
        from pathlib import Path as _Path

        from .importing import apply as _apply, describe, read
        from .server import open_workspace

        if "--file" not in argv:
            print("usage: python -m vinzor import --file investors.csv "
                  "[--workspace live.db] [--kind person] [--confirm]",
                  file=sys.stderr)
            return 2
        source = _Path(_value(argv, "--file"))
        if not source.exists():
            print(f"no such file: {source}", file=sys.stderr)
            return 1
        workspace = (_Path(_value(argv, "--workspace"))
                     if "--workspace" in argv else None)
        kind = _value(argv, "--kind") if "--kind" in argv else None

        plan = read(source, default_kind=kind)
        print(describe(plan, source))
        if plan.refusals:
            return 1
        if "--confirm" not in argv:
            print()
            print("  Nothing was written. Read the mapping above, then run "
                  "the same command again with --confirm.")
            return 0

        # A firm's own book must not arrive mixed with invented parties, and
        # an append-only log offers no way to take them out afterwards.
        engine = open_workspace(workspace, demo="--demo-data" in argv)
        import hashlib as _hashlib

        try:
            counts = _apply(engine, plan, on=date.today().isoformat(),
                            filename=source.name,
                            digest=_hashlib.sha256(
                                source.read_bytes()).hexdigest())
        except ValueError as refused:
            print(f"  {refused}")
            return 1
        print()
        if plan.kind == "payments":
            print(f"  {counts['payments_recorded']} payments recorded, "
                  f"{counts['payers_registered']} payers registered, "
                  f"{counts['already_recorded']} already on record.")
        else:
            print(f"  {counts['registered']} parties added, "
                  f"{counts['already_known']} already on record, "
                  f"{counts['committed']} commitments recorded.")
        intact, why = engine.verify()
        print("  chain " + ("verifies" if intact else f"BROKEN: {why}"))
        return 0 if intact else 1

    if argv and argv[0] == "readiness":
        from pathlib import Path as _Path

        from .readiness import (FOR_A_LEGAL_PERSON, FOR_A_PERSON, measure)
        from .server import open_workspace

        workspace = (_Path(_value(argv, "--workspace"))
                     if "--workspace" in argv else None)
        engine = open_workspace(workspace, demo="--demo-data" in argv)
        result = measure(engine)
        words = {clause: what for clause, what, _ in
                 FOR_A_PERSON + FOR_A_LEGAL_PERSON}

        total = len(result.parties)
        print()
        print(f"  {total:,} parties on the record")
        print(f"  {len(result.ready):,} could be handed over as they stand")
        print(f"  {len(result.short):,} are short of something clause 5.4.2 "
              f"requires")
        if not total:
            return 0

        if result.by_clause:
            print()
            print("  what is missing, and how often:")
            for clause, count in sorted(result.by_clause.items(),
                                        key=lambda kv: -kv[1]):
                what = words.get(clause, "what kind of party this is")
                print(f"    {count:>6}  {what:<42} {clause}")

        if result.short:
            print()
            print("  the first parties to fix:")
            for standing in result.short[:10]:
                missing = ", ".join(g.what for g in standing.gaps)
                print(f"    {standing.name}")
                print(f"        missing {missing}")
            if len(result.short) > 10:
                print(f"    ... and {len(result.short) - 10:,} more")

        print()
        print("  This measures clause 5.4.2 -- the identification information")
        print("  the guidelines say a Regulated Entity shall obtain at least.")
        print("  It is upstream of any upload: a record missing what 5.4.2")
        print("  requires is not ready for anybody. It is not a check against")
        print("  the registration agency's own file layout, which we do not")
        print("  hold, so passing this does not promise a file will be")
        print("  accepted -- the agency may want more.")
        print()
        from .readiness import NOT_MEASURED
        print("  Nor is it the whole of 5.4.2. These the clause asks for and")
        print("  this does not look at:")
        for _clause, what in NOT_MEASURED:
            for line in _wrapped(what, 62):
                print(f"    - {line}" if line == _wrapped(what, 62)[0]
                      else f"      {line}")
        print()
        return 0

    if argv and argv[0] == "export":
        from pathlib import Path as _Path

        from .evidence import write as _write
        from .server import open_workspace

        workspace = None
        if "--workspace" in argv:
            workspace = _Path(_value(argv, "--workspace"))
        out = _Path(_value(argv, "--out") if "--out" in argv else "evidence-pack")
        engine = open_workspace(workspace)
        intact, why = engine.verify()
        written = _write(engine, out, workspace=str(workspace or "demo workspace"),
                         today=date.today().isoformat())
        for path in written:
            print(f"  wrote {path}  ({path.stat().st_size:,} bytes)")
        print(f"  {len(engine.log)} events; chain "
              + ("verifies" if intact else f"DOES NOT VERIFY: {why}"))
        return 0 if intact else 1

    if argv and argv[0] == "capital":
        from pathlib import Path as _Path

        from .capital import NOT_CONFIRMED, in_words, required
        from .server import open_workspace

        workspace = (_Path(_value(argv, "--workspace"))
                     if "--workspace" in argv else None)
        engine = open_workspace(workspace)
        today = date.today().isoformat()

        if "--worth" in argv:
            try:
                engine.report_net_worth(
                    amount_usd=float(_value(argv, "--worth")),
                    as_at=(_value(argv, "--as-at") if "--as-at" in argv
                           else today),
                    actor=(_value(argv, "--by") if "--by" in argv
                           else "the officer"),
                    note=(_value(argv, "--note") if "--note" in argv
                          else ""))
            except (ValueError, TypeError) as refused:
                print()
                print(f"  {refused}", file=sys.stderr)
                print()
                return 1
            print()
            print("  Recorded.")
            print(f"  {in_words(engine.state.licence, engine.state.capital)}")
            print()
            return 0

        minimum, confirmed, why = required(engine.state.licence,
                                           engine.state.capital)
        print()
        print(f"  {in_words(engine.state.licence, engine.state.capital)}")
        print(f"  {why}")
        if minimum is not None and not confirmed:
            print()
            for line in _wrapped(NOT_CONFIRMED, 68):
                print(f"  {line}")
            print()
            print("  Record a figure:   python -m vinzor capital "
                  "--worth 620000 --as-at 2026-06-30")
        print()
        return 0
    if argv and argv[0] == "document":
        from pathlib import Path as _Path

        from .documents import Cabinet, KINDS, can_support
        from .server import open_workspace

        workspace = (_Path(_value(argv, "--workspace"))
                     if "--workspace" in argv else None)

        if "--kinds" in argv:
            print()
            print("  Document kinds, and what each may be said to evidence:")
            print()
            for key, (called, supports) in sorted(KINDS.items()):
                print(f"    {key:<20} {called}")
                print(f"    {chr(32)*20} {', '.join(supports) or 'nothing on its own'}")
            print()
            return 0

        if "--file" not in argv or "--party" not in argv or "--kind" not in argv:
            print('usage: python -m vinzor document --party per_0001 '
                  '--kind passport --file scan.pdf '
                  '--supports name,dob,nationality '
                  '[--expires 2031-04-30] [--by "Meera Nair"] '
                  '[--workspace live.db]', file=sys.stderr)
            print('       python -m vinzor document --kinds','',
                  file=sys.stderr)
            print('       python -m vinzor document --list --party per_0001',
                  file=sys.stderr)
            return 2

        engine = open_workspace(workspace)
        party = _value(argv, "--party")
        if party not in engine.state.graph.entities:
            print(f"  no party with reference {party} on this workspace",
                  file=sys.stderr)
            return 1
        source = _Path(_value(argv, "--file"))
        if not source.exists():
            print(f"  no such file: {source}", file=sys.stderr)
            return 1
        kind = _value(argv, "--kind")
        supports = ([s.strip() for s in _value(argv, "--supports").split(",")
                     if s.strip()] if "--supports" in argv
                    else list(can_support(kind)))
        cabinet = Cabinet(getattr(engine.log, "path", ":memory:"))
        try:
            engine.file_document(
                entity_id=party, kind=kind, filename=source.name,
                data=source.read_bytes(), supports=supports,
                actor=(_value(argv, "--by") if "--by" in argv
                       else "the officer"),
                filed_on=date.today().isoformat(),
                expires_on=(_value(argv, "--expires")
                            if "--expires" in argv else ""),
                cabinet=cabinet)
        except (ValueError, KeyError) as refused:
            print()
            print(f"  {str(refused).strip(chr(39))}", file=sys.stderr)
            print()
            return 1
        name = engine.state.graph.name_of(party)
        print()
        print(f"  Filed against {name}, evidencing "
              f"{', '.join(supports) or 'nothing in particular'}.")
        print()
        return 0
    if argv and argv[0] == "password":
        import getpass

        from .model import EventType
        from pathlib import Path as _Path

        from .credentials import Credentials, weak
        from .server import open_workspace

        if "--name" not in argv:
            print('usage: python -m vinzor password --name "Meera Nair" '
                  '[--workspace live.db] [--remove]', file=sys.stderr)
            return 2
        name = _value(argv, "--name")
        workspace = (_Path(_value(argv, "--workspace"))
                     if "--workspace" in argv else None)
        engine = open_workspace(workspace)
        if name not in engine.state.actors:
            print()
            print(f"  {name} is not enrolled in this workspace. Who may",
                  file=sys.stderr)
            print("  act is recorded in the log, and a password without",
                  file=sys.stderr)
            print("  an enrolment behind it would be a way in for",
                  file=sys.stderr)
            print("  somebody nobody authorised.", file=sys.stderr)
            print("  On the record:", ", ".join(sorted(engine.state.actors)),
                  file=sys.stderr)
            print()
            return 1

        keys = Credentials(getattr(engine.log, "path", ":memory:"))
        if "--remove" in argv:
            keys.forget(name)
            print()
            print(f"  {name} can no longer sign in, and any session they")
            print("  had is ended.")
            print()
            return 0

        print()
        print(f"  Setting a password for {name}.")
        if not keys.anybody_can_sign_in():
            print("  This is the first one. Once it is set, everybody")
            print("  needs a password -- the name picker stops being a")
            print("  way in for anyone.")
        print()
        try:
            first = getpass.getpass("  Password: ")
            again = getpass.getpass("  Again: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if first != again:
            print()
            print("  Those do not match. Nothing was changed.",
                  file=sys.stderr)
            print()
            return 1
        problem = weak(first)
        if problem:
            print()
            print(f"  {problem}", file=sys.stderr)
            print()
            return 1
        today = date.today().isoformat()
        keys.set_password(name, first, today)
        # The secret stays out of the log; that somebody was given a way
        # in does not. It is who could have decided something, which is
        # exactly what an inspector asks.
        engine.ingest(
            event_type=EventType.ACTOR_ENROLLED,
            subject=name,
            occurred_at=today,
            actor="the administrator",
            payload={"name": name,
                     "role": str(engine.state.actors[name]["role"]),
                     "title": engine.state.actors[name].get("title", ""),
                     "way_in_set": True},
        )
        print()
        print(f"  Done. {name} can sign in.")
        print()
        return 0
    if argv and argv[0] == "filing":
        # The other half of the calendar. Lateness was swept for on every
        # briefing load and there was no way at all to record that something
        # had been filed, so a firm licensed three years ago and opened here
        # for the first time collected nineteen permanent overdue records in
        # one call -- and, the log being append-only, no way to take them off.
        from pathlib import Path as _Path

        from .calendar import Obligation
        from .server import open_workspace

        workspace = (_Path(_value(argv, "--workspace"))
                     if "--workspace" in argv else None)
        engine = open_workspace(workspace)
        today = date.today().isoformat()

        if "--list" in argv or "--obligation" not in argv:
            filed = engine.state.calendar.submitted
            print()
            if not filed:
                print("  Nothing is recorded as filed on this workspace.")
                print()
                print('  usage: python -m vinzor filing '
                      '--obligation QUARTERLY_REPORT '
                      '--period "Q1 FY2026-27" --on 2026-07-18 '
                      '[--by "Meera Nair"] [--investors 87] '
                      '[--capital 12400023] [--aum 48000000] '
                      '[--schemes 3] [--workspace live.db]')
                print(f"  The ones tracked: "
                      f"{', '.join(o.value for o in Obligation)}")
                print()
                return 0
            print(f"  {len(filed)} recorded as filed:")
            print()
            for key, when in sorted(filed.items()):
                obligation, _, period = key.partition("|")
                print(f"    {obligation:28} {period:20} filed {when}")
            print()
            return 0

        reported = {}
        for flag, field in (("--aum", "aum_usd"), ("--investors", "investors"),
                            ("--schemes", "schemes"),
                            ("--capital", "capital_received_usd")):
            if flag in argv:
                reported[field] = _value(argv, flag)

        try:
            engine.record_filing(
                obligation=_value(argv, "--obligation"),
                period=(_value(argv, "--period") if "--period" in argv else ""),
                submitted_on=(_value(argv, "--on") if "--on" in argv else today),
                actor=(_value(argv, "--by") if "--by" in argv
                       else "the officer"),
                reported=reported or None,
                note=(_value(argv, "--note") if "--note" in argv else ""))
        except (KeyError, ValueError) as refused:
            print()
            print(f"  {str(refused).strip(chr(39))}", file=sys.stderr)
            print()
            return 1

        print()
        print("  Recorded as filed.")
        if reported:
            print("  The figures on it are now beside what the records hold, "
                  "on \"Where you stand with IFSCA\".")
        print()
        return 0

    if argv and argv[0] == "notice":
        from pathlib import Path as _Path

        from .correspondence import how_long_left, who_sent_it
        from .server import open_workspace

        workspace = (_Path(_value(argv, "--workspace"))
                     if "--workspace" in argv else None)
        engine = open_workspace(workspace)
        today = date.today().isoformat()

        listing = ("--list" in argv
                   or not {"--ref", "--about", "--answer"} & set(argv))
        if listing:
            open_ones = engine.state.correspondence.open_notices()
            print()
            if not open_ones:
                print("  No letter from a regulator is waiting for an "
                      "answer.")
                print()
                return 0
            print(f"  {len(open_ones)} waiting for an answer:")
            print()
            for notice in open_ones:
                print(f"    {notice.reference}")
                print(f"      from {who_sent_it(notice.from_whom)}, "
                      f"received {notice.received_on}")
                print(f"      {how_long_left(notice, today)}")
                print(f"      {notice.about[:96]}")
                print()
            return 0

        if "--answer" in argv:
            reference = _value(argv, "--ref") if "--ref" in argv else ""
            try:
                engine.notice_answered(
                    reference=reference,
                    answer=_value(argv, "--answer"),
                    actor=(_value(argv, "--by") if "--by" in argv
                           else "the officer"),
                    answered_on=(_value(argv, "--on") if "--on" in argv
                                 else today))
            except (KeyError, ValueError) as refused:
                print()
                print(f"  {str(refused).strip(chr(39))}", file=sys.stderr)
                print()
                return 1
            print()
            print(f"  Recorded. {reference} is answered.")
            print()
            return 0

        if "--ref" not in argv or "--about" not in argv:
            print('usage: python -m vinzor notice --ref "IFSCA/AML/2026/0417" '
                  '--from IFSCA --about "what they asked for" '
                  '[--by 2026-08-31] [--on 2026-08-05] '
                  '[--workspace live.db]', file=sys.stderr)
            print('       python -m vinzor notice --list '
                  '[--workspace live.db]', file=sys.stderr)
            print('       python -m vinzor notice --ref REF --answer '
                  '"what was sent" --by "Meera Nair" [--on 2026-08-19]',
                  file=sys.stderr)
            return 2

        try:
            engine.notice_received(
                reference=_value(argv, "--ref"),
                from_whom=_value(argv, "--from") if "--from" in argv else "",
                about=_value(argv, "--about"),
                received_on=(_value(argv, "--on") if "--on" in argv
                             else today),
                answer_by=_value(argv, "--by") if "--by" in argv else "",
                actor="the officer")
        except ValueError as refused:
            print()
            print(f"  {refused}", file=sys.stderr)
            print()
            return 1
        opened = engine.observe_deadlines(today)
        print()
        print("  Recorded. " + ("It is already past its date, so a file "
                                "is open." if opened
                                else "The clock is running."))
        print()
        return 0

    if argv and argv[0] == "serve":
        from pathlib import Path as _Path

        from .server import serve

        port = 8000
        workspace = None
        if "--port" in argv:
            port = _flag(argv, "--port", 8000)
        if "--workspace" in argv:
            workspace = _Path(_value(argv, "--workspace"))
        from .azure import DataResidencyError

        try:
            serve(port=port, workspace=workspace)
        except DataResidencyError as wrong:
            # One sentence, at start-up. This used to be discovered per page
            # view, as a dropped connection with a traceback behind it.
            print(f"  cannot start: {wrong}", file=sys.stderr)
            print("  Correct AZURE_OPENAI_REGION, or unset the assistant's "
                  "settings to run without it.", file=sys.stderr)
            return 1
        return 0

    if not DEFAULT_DATASET.exists():
        print(f"dataset not found at {DEFAULT_DATASET}", file=sys.stderr)
        return 1

    today = date.today().isoformat()

    _h("1. INGEST  events -> graph -> policies -> cases")
    engine = seed()
    counts: dict[str, int] = {}
    for event in engine.log:
        counts[str(event.event_type)] = counts.get(str(event.event_type), 0) + 1
    for event_type, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>5}  {event_type}")
    print(f"  {len(engine.log):>5}  events total")

    _h("2. QUEUE  what a compliance officer sees this morning")
    queue = engine.queue()
    by_severity: dict[Severity, int] = {}
    for case in queue:
        by_severity[case.severity] = by_severity.get(case.severity, 0) + 1
    for severity in reversed(list(Severity)):
        if severity in by_severity:
            print(f"  {by_severity[severity]:>5}  {severity.value}")
    print(f"  {len(queue):>5}  open cases\n")
    for case in queue[:5]:
        print(f"  {case.severity.value:<8} {case.case_type:<17} {case.subject:<10} "
              f"{case.evidence[0].summary[:44]}")

    _h("3. EVIDENCE  one case: says who, on what, from where")
    ubo_case = next(
        c for c in queue
        if c.case_type == "UBO_REVIEW" and c.evidence[0].detail.get("cycles")
    )
    print(f"  case      {ubo_case.case_id}   ({ubo_case.severity.value})")
    print(f"  subject   {ubo_case.subject}  {engine.state.graph.name_of(ubo_case.subject)}")
    evidence = ubo_case.evidence[0]
    print(f"\n  [{evidence.kind.value}] {evidence.policy_id}")
    print(f"    {evidence.summary}")
    for citation in evidence.citations:
        flag = "verified" if citation["verified"] else "UNVERIFIED"
        print(f"\n    says who   : {citation['ref']}  ({flag})")
        print(f"                 {citation['heading']}")
        print(f"      \"{citation['extract'][:150]}...\"")
        if citation["amended"]:
            print(f"      amended  : {citation['amended']}")
    source = next(e for e in engine.log if e.seq == evidence.source_seq)
    print(f"\n    from event : seq {source.seq}  {source.event_type}  {source.occurred_at}")
    print(f"    hash       : {source.event_hash[:32]}...")

    _h("4. UBO  computed from the edges, against IFSCA's test (not FATF's 25%)")
    fatf = OwnershipTest(25.0, False, "FATF R.24")
    for entity in ("cmp_0006", "cmp_0001", "trs_0006"):
        result = engine.state.graph.resolve_ubo(entity)
        kind = result.subject_kind.value if result.subject_kind else "?"
        print(f"  {entity} ({kind})  {result.conclusion.value}   "
              f"test: {result.test.describe()} per {result.test.clause}")
        print(f"    {result.explain()[:110]}")
        for owner in result.owners[:3]:
            for path in owner.paths:
                print(f"      {' <- '.join(path)}  = {owner.effective_percentage:.1f}%")
        for cycle in result.cycles:
            print(f"      cycle: {' -> '.join(cycle)}")
        missed = [o for o in result.owners
                  if o not in engine.state.graph.resolve_ubo(entity, test=fatf).owners]
        for owner in missed:
            print(f"      ^ a 25% test would have missed {owner.name} "
                  f"({owner.effective_percentage:.1f}%)")

    _h("5. CLAUSE COVERAGE  what the register knows, and what it admits it does not")
    cov = coverage()
    print(f"  {cov['clauses']} clauses from {cov['documents']} document(s); "
          f"{cov['verified']} human-verified, {cov['unverified']} UNVERIFIED")
    for pending in cov["pending_amendments"]:
        print(f"  NOT INCORPORATED: circular {pending['circular_date']} "
              f"affecting {', '.join(pending['affects'])}")
        print(f"    {pending['summary'][:150]}...")

    _h("6. HUMAN GATE  ai prepares, enrolled humans approve")
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER,
                  title="AML Officer", enrolled_at=today)
    engine.enroll(name="Priya Rao", role=Role.VIEWER,
                  title="Read-only access", enrolled_at=today)
    # Enrolled because the walkthrough passes a file up below, and passing one
    # up when nobody is left to answer it is refused rather than allowed --
    # it would leave the file open forever, waiting on nobody. Meera and a
    # read-only viewer are not enough on their own, and a demonstration that
    # skipped the second decider would be showing an escalation the product
    # does not actually permit.
    engine.enroll(name="Rohan Kapoor", role=Role.SENIOR_MGMT,
                  title="Senior Management", enrolled_at=today)
    target = queue[0]
    print(f"  case {target.case_id}  ({target.severity.value} {target.case_type})")
    attempts = (("copilot", Role.AI, "not enrolled at all"),
                ("Priya Rao", Role.VIEWER, "enrolled, but read-only"))
    for who, role, note in attempts:
        try:
            engine.decide(case_id=target.case_id, outcome=Outcome.APPROVE,
                          actor=who, role=role, rationale="Looks fine to me.",
                          decided_at=today)
            print(f"  {who:<11} DECIDED  <-- should be impossible")
        except DecisionDenied as exc:
            print(f"  {who:<11} denied ({note}): {str(exc)[:60]}")

    engine.decide(case_id=target.case_id, outcome=Outcome.ESCALATE, actor="Meera Nair",
                  role=Role.AML_OFFICER,
                  rationale="Payer matches a sanctions entry; escalating for senior review.",
                  decided_at=today)
    # Passing a file up is a handover, not an answer: the Case stays open and
    # gains a step on its record, so there is no decision to read here yet.
    # Printing one would have said the file was settled by the officer who
    # only asked somebody else to settle it -- which is the opposite of what
    # four eyes means.
    passed_up = engine.state.casebook.get(target.case_id)
    step = passed_up.escalations[-1]
    print(f"  {step['role']:<11} {passed_up.status.value} by {step['by']}")
    print(f"              \"{step['why']}\"")

    # And the second pair of eyes answers it. The officer who passed it up
    # cannot, which is the point of having passed it up.
    engine.decide(case_id=target.case_id, outcome=Outcome.APPROVE,
                  actor="Rohan Kapoor", role=Role.SENIOR_MGMT,
                  rationale="Compared the payer against the listed entry: "
                            "different date of birth and nationality, and the "
                            "passport does not match. Not the same party.",
                  decided_at=today)
    decided = engine.state.casebook.get(target.case_id)
    print(f"  {decided.decision.role.value:<11} {decided.status.value} by "
          f"{decided.decision.actor}")
    print(f"              \"{decided.decision.rationale}\"")
    print(f"  queue is now {len(engine.queue())} open (was {len(queue)})")

    _h("7. CALENDAR  what is owed to IFSCA, and what is late")
    from .calendar import instances

    # The licence is seeded with the workspace now, rather than invented here.
    # It used to exist only in this demo, which is why the obligation calendar
    # worked in the walkthrough and was invisible on the served screen.
    granted = engine.state.licence.granted_on
    schedule = instances(granted, today, engine.state.calendar.submitted)
    print(f"  licence granted {granted}; {len(schedule)} obligations since then")
    late = engine.observe_deadlines(today)
    print(f"  {len(late)} overdue, now open as work:")
    for case in late[:4]:
        detail = case.evidence[0].detail
        charge = detail.get("late_charge_usd") or 0
        print(f"    {case.severity.value:<8} {detail['period']:<14} "
              f"due {detail['due_on']}  {detail['days_late']} days late"
              + (f", USD {charge} charged" if charge else ""))

    _h("8. SCORECARD  what IFSCA has actually enforced against, and our coverage")
    score = scorecard()
    print(f"  {score.published} actions published Jul 2024 - Jun 2026; "
          f"{score.scored} recorded here in detail "
          f"({score.read_from_primary} read from the primary order)")
    print(f"  this system would have surfaced {score.would_surface} of "
          f"{score.scored} ({score.percent:.0f}%)\n")
    for ground, count in score.by_ground.items():
        state = "covered" if COVERAGE[ground].covered else "NOT COVERED"
        print(f"  {count:>3}x  {ground.value:<12} {state}")
    print("\n  next, ordered by what has actually cost an entity its licence:")
    for i, (ground, count, needs) in enumerate(roadmap()[:3], 1):
        print(f"    {i}. {ground.value} ({count}x) — {needs[:66]}")

    _h("9. AUDIT  the log is the audit trail; nothing sits beside it")
    ok, reason = engine.verify()
    print(f"  chain of {len(engine.log)} events verifies: {ok}{'' if ok else '  ' + str(reason)}")
    rebuilt = engine.rebuild()
    same = rebuilt.casebook.cases == engine.state.casebook.cases
    print(f"  full replay reproduces live state exactly: {same}")
    print(f"  cases {len(rebuilt.casebook)}, of which open {len(rebuilt.casebook.queue())}")

    print()
    return 0 if ok and same else 1


if __name__ == "__main__":
    raise SystemExit(main())

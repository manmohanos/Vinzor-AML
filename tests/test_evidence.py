"""The evidence pack, and the one property that makes it worth anything.

A pack that only its own producer can check is a screenshot with extra steps.
These tests run the verifier *as shipped*, in a separate process, with no
Vinzor import at all -- because that is how a recipient will run it, and
because the first version of the rule described the hash wrongly and would
have declared an honest pack forged.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from vinzor.evidence import pack, write

from vinzor.model import Outcome, Role

from conftest import commits, company, officer, paid, person, screened


@pytest.fixture
def worked(engine):
    """A workspace with something in it, including a settled file."""
    officer(engine)
    person(engine, "p1", "Rohan Desai")
    company(engine, "c1", "Orion Zenith Enterprises")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    commits(engine, "c1")
    paid(engine, "p1", anomaly="OVERPAYMENT", payment_id="pay_1")

    case = next(iter(engine.state.casebook.cases.values()))
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at="2026-08-12",
                  rationale="Different date of birth and nationality.")
    return engine


def _run(path, *args):
    return subprocess.run([sys.executable, str(path), *args],
                          capture_output=True, text=True)


def test_the_pack_holds_the_record_a_reading_of_it_and_a_checker(worked):
    files = pack(worked, workspace="test.db", today="2026-08-14")
    assert set(files) == {"record.jsonl", "evidence.html", "verify.py"}
    assert files["record.jsonl"].count("\n") == len(worked.log)


def test_the_shipped_checker_confirms_a_genuine_pack(worked, tmp_path):
    write(worked, tmp_path, workspace="test.db", today="2026-08-14")
    done = _run(tmp_path / "verify.py", str(tmp_path / "record.jsonl"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "INTACT" in done.stdout


@pytest.mark.parametrize("what,mutate", [
    ("a hidden sanctions hit",
     lambda e: e["event_type"] == "SCREENING_COMPLETED"
     and e["payload"].update({"matched": False}) is None),
    ("a rewritten decision",
     lambda e: e["event_type"] == "CASE_DECIDED"
     and e["payload"].update({"rationale": "Approved, no concerns."}) is None),
    ("an altered amount",
     lambda e: e["event_type"] == "PAYMENT_RECEIVED"
     and e["payload"].update({"amount": 1.0}) is None),
])
def test_the_checker_catches_a_record_that_was_changed(worked, tmp_path,
                                                       what, mutate):
    write(worked, tmp_path, workspace="test.db", today="2026-08-14")
    source = tmp_path / "record.jsonl"
    lines, hit = [], False
    for line in source.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if not hit and mutate(event):
            hit = True
        lines.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
    assert hit, f"the fixture has no event to alter for {what}"
    (tmp_path / "bad.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    done = _run(tmp_path / "verify.py", str(tmp_path / "bad.jsonl"))
    assert done.returncode == 1, f"{what} was not caught: {done.stdout}"
    assert "BROKEN" in done.stdout and "altered" in done.stdout


def test_the_checker_catches_a_record_that_was_removed(worked, tmp_path):
    """Deleting an inconvenient record is the likelier fraud, and it leaves a
    hole rather than a changed value."""
    write(worked, tmp_path, workspace="test.db", today="2026-08-14")
    lines = (tmp_path / "record.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) > 3
    (tmp_path / "bad.jsonl").write_text(
        "\n".join(lines[:2] + lines[3:]) + "\n", encoding="utf-8")

    done = _run(tmp_path / "verify.py", str(tmp_path / "bad.jsonl"))
    assert done.returncode == 1
    assert "BROKEN" in done.stdout


def test_the_reading_repeats_the_caveats_rather_than_quietly_dropping_them(worked):
    """An export that presents machine-extracted clauses as settled law is the
    most dangerous document this system can produce.
    """
    html = pack(worked, workspace="test.db", today="2026-08-14")["evidence.html"]
    assert "not confirmed by a person" in html
    assert "does not say how often" in html          # the screening interval
    assert "not a legal opinion" in html
    assert "is a reading of the record, not the record" in html


def test_the_reading_shows_who_decided_and_why(worked):
    html = pack(worked, workspace="test.db", today="2026-08-14")["evidence.html"]
    assert "Meera Nair" in html
    assert "Different date of birth and nationality." in html


def test_a_decision_reason_cannot_smuggle_markup_into_the_pack(engine, tmp_path):
    """The reason is free text a person types. It lands in an HTML file that
    someone else opens.
    """
    officer(engine)
    person(engine, "p1", "Rohan Desai")
    screened(engine, "p1", "SANCTIONS", alert_id="alt_1")
    case = next(iter(engine.state.casebook.cases.values()))
    engine.decide(case_id=case.case_id, outcome=Outcome.APPROVE,
                  actor="Meera Nair", role=Role.AML_OFFICER,
                  decided_at="2026-08-12",
                  rationale="<script>alert('x')</script> cleared")

    html = pack(engine, workspace="test.db", today="2026-08-14")["evidence.html"]
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


# -- the verifier the pack ships with ----------------------------------------
#
# The pack's whole design argument is that the recipient does not have to
# trust the tool that produced it: they run verify.py, which reads nothing
# but the file. That argument is only as good as verify.py, and verify.py
# had the same hole the ledger itself was audited for on 20 August 2026 --
# a chain cannot see what was taken off its own ends. Ten lines cut from the
# front and it printed "INTACT: 30 records, none altered, none missing";
# ten from the back and it printed the same. The anchors are written in when
# the pack is made, because a file cannot testify about its own ends.


def _pack_into(tmp_path, how_many=30):
    from vinzor.engine import Vinzor
    from vinzor.eventlog import EventLog
    from vinzor.evidence import write
    from vinzor.model import EntityKind, EventType

    engine = Vinzor(EventLog())
    for index in range(how_many):
        engine.ingest(event_type=EventType.ENTITY_REGISTERED,
                      subject=f"p{index}", occurred_at="2026-08-20",
                      actor="t",
                      payload={"kind": EntityKind.PERSON.value,
                               "name": f"Party {index}", "attributes": {}})
    write(engine, tmp_path, "Acme GIFT Fund Managers Ltd", "2026-08-20")
    return tmp_path


def _run_verifier(folder, filename="record.jsonl"):
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(folder / "verify.py"),
         str(folder / filename)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(folder))
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def test_the_shipped_verifier_passes_the_record_it_shipped_with(tmp_path):
    folder = _pack_into(tmp_path)
    code, said = _run_verifier(folder)
    assert code == 0, said
    assert "INTACT" in said
    assert "none missing from either end" in said


def test_records_cut_from_the_front_are_caught(tmp_path):
    """The chain still checks perfectly -- that is the point. Every
    surviving link follows the one before it; what is gone is the
    beginning, and only an anchor can say so."""
    folder = _pack_into(tmp_path)
    lines = (folder / "record.jsonl").read_text(encoding="utf-8").splitlines()
    (folder / "cut.jsonl").write_text("\n".join(lines[10:]) + "\n",
                                      encoding="utf-8")
    code, said = _run_verifier(folder, "cut.jsonl")
    assert code == 1, said
    assert "removed from the front" in said


def test_records_cut_from_the_end_are_caught(tmp_path):
    folder = _pack_into(tmp_path)
    lines = (folder / "record.jsonl").read_text(encoding="utf-8").splitlines()
    (folder / "cut.jsonl").write_text("\n".join(lines[:-10]) + "\n",
                                      encoding="utf-8")
    code, said = _run_verifier(folder, "cut.jsonl")
    assert code == 1, said
    assert "removed from the end" in said


def test_an_altered_record_is_still_caught(tmp_path):
    """The case that always worked, kept so the anchors are not mistaken
    for the whole of the check."""
    folder = _pack_into(tmp_path)
    lines = (folder / "record.jsonl").read_text(encoding="utf-8").splitlines()
    lines[15] = lines[15].replace("Party 15", "Party XX")
    (folder / "bent.jsonl").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")
    code, said = _run_verifier(folder, "bent.jsonl")
    assert code == 1, said
    assert "altered since it was written" in said


def test_a_record_cut_from_the_middle_is_still_caught(tmp_path):
    folder = _pack_into(tmp_path)
    lines = (folder / "record.jsonl").read_text(encoding="utf-8").splitlines()
    del lines[15]
    (folder / "gap.jsonl").write_text("\n".join(lines) + "\n",
                                      encoding="utf-8")
    code, said = _run_verifier(folder, "gap.jsonl")
    assert code == 1, said


def test_the_pack_says_what_its_verifier_actually_checks(tmp_path):
    """The sentence printed inside every pack claimed the chain alone
    caught removal. It does not, and saying so is the difference between a
    document a regulator can rely on and one that reads well."""
    from vinzor.evidence import CHAIN_RULE

    assert "cannot speak about" in CHAIN_RULE
    assert "anchors" in CHAIN_RULE
    assert "sixty-four zeroes" in CHAIN_RULE

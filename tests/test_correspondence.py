"""Letters from the regulator, and the quietest failure in compliance.

Three of IFSCA's twenty-five published enforcement actions are on this
ground and nothing was built for it. It is unlike everything else in the
product: no transaction happens, no rule is broken at the moment of breach,
and the file simply sits. The breach is the silence, and by the time
anybody notices it is months old.

So half these tests are about the clock, and the other half are about the
two ways this could quietly not work -- lateness that nobody looks for, and
a date this product invented rather than the regulator.
"""

from __future__ import annotations

import pytest

from vinzor.correspondence import how_long_left, who_sent_it
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import Role

WHEN = "2026-06-01"
TODAY = "2026-08-19"


@pytest.fixture
def engine() -> Vinzor:
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    engine.enroll(name="Priya Rao", role=Role.VIEWER, enrolled_at=WHEN)
    return engine


def letter(engine, reference="IFSCA/AML/2026/0417", from_whom="IFSCA",
           about="The ownership records for three named investors.",
           received_on="2026-07-10", answer_by="2026-07-31",
           actor="Meera Nair"):
    return engine.notice_received(
        reference=reference, from_whom=from_whom, about=about,
        received_on=received_on, answer_by=answer_by, actor=actor)


def files(engine) -> list:
    return [case for case in engine.state.casebook.cases.values()
            if case.case_type == "NOTICE"]


# -- recording a letter ------------------------------------------------------


def test_a_letter_goes_on_the_record(engine):
    letter(engine)
    notice = engine.state.correspondence.notices["IFSCA/AML/2026/0417"]
    assert notice.is_open
    assert notice.from_whom == "IFSCA"


def test_anyone_may_record_that_a_letter_arrived(engine):
    """Not gated to a deciding role. A system where recording that the
    regulator wrote to you needs an officer's authority is a system where
    letters sit in an inbox until somebody senior is free."""
    letter(engine, actor="Priya Rao")
    assert engine.state.correspondence.notices["IFSCA/AML/2026/0417"]


def test_a_letter_needs_the_reference_the_regulator_put_on_it(engine):
    with pytest.raises(ValueError, match="reference"):
        letter(engine, reference="")


def test_a_letter_needs_a_line_saying_what_was_asked(engine):
    with pytest.raises(ValueError, match="what was asked"):
        letter(engine, about="   ")


def test_the_same_reference_cannot_be_recorded_twice(engine):
    letter(engine)
    with pytest.raises(ValueError, match="already on this record"):
        letter(engine)


# -- the clock ---------------------------------------------------------------


def test_days_left_counts_down_and_then_up(engine):
    letter(engine)
    notice = engine.state.correspondence.notices["IFSCA/AML/2026/0417"]
    assert notice.days_left("2026-07-21") == 10
    assert notice.days_left("2026-07-31") == 0
    assert notice.days_left("2026-08-19") == -19


def test_how_late_is_said_in_days_not_rounded_to_overdue(engine):
    """An answer eleven days late is a different conversation from one a
    day late, and rounding both to "overdue" loses the difference."""
    letter(engine)
    notice = engine.state.correspondence.notices["IFSCA/AML/2026/0417"]
    assert "19 days past the date they set" == how_long_left(notice, TODAY)


def test_a_letter_with_no_date_is_not_given_one(engine):
    """Inventing a deadline would put a date on a compliance record the
    regulator never wrote, and every later report would repeat it as
    though it were theirs."""
    letter(engine, reference="IFSCA/INSP/2026/0033", answer_by="")
    notice = engine.state.correspondence.notices["IFSCA/INSP/2026/0033"]
    assert notice.answer_by == ""
    assert notice.days_left(TODAY) is None
    assert "no date was set" in how_long_left(notice, TODAY)


def test_an_undated_letter_is_carried_as_open_and_unmeasurable(engine):
    letter(engine, reference="IFSCA/INSP/2026/0033", answer_by="")
    correspondence = engine.state.correspondence
    assert len(correspondence.undated()) == 1
    assert not correspondence.overdue(TODAY)


# -- answering ---------------------------------------------------------------


def test_an_answer_is_recorded_with_who_sent_it_and_what_they_said(engine):
    letter(engine)
    engine.notice_answered(
        reference="IFSCA/AML/2026/0417", actor="Meera Nair",
        answered_on="2026-08-12",
        answer="Sent the ownership chains for all three with trust deeds.")
    notice = engine.state.correspondence.notices["IFSCA/AML/2026/0417"]
    assert not notice.is_open
    assert notice.answered_by == "Meera Nair"
    assert "trust deeds" in notice.answer


def test_how_late_the_answer_was_is_kept(engine):
    letter(engine)
    engine.notice_answered(
        reference="IFSCA/AML/2026/0417", actor="Meera Nair",
        answered_on="2026-08-12",
        answer="Sent the ownership chains for all three with trust deeds.")
    assert engine.state.correspondence.notices[
        "IFSCA/AML/2026/0417"].was_late() == 12


def test_an_answer_that_says_nothing_is_refused(engine):
    """The question an inspector asks is not whether you replied, it is
    what you told them."""
    letter(engine)
    with pytest.raises(ValueError, match="nothing an inspector could read"):
        engine.notice_answered(reference="IFSCA/AML/2026/0417",
                               actor="Meera Nair", answered_on=TODAY,
                               answer="Done.")


def test_a_letter_cannot_be_answered_twice(engine):
    letter(engine)
    engine.notice_answered(
        reference="IFSCA/AML/2026/0417", actor="Meera Nair",
        answered_on="2026-08-12",
        answer="Sent the ownership chains for all three with trust deeds.")
    with pytest.raises(ValueError, match="already answered"):
        engine.notice_answered(
            reference="IFSCA/AML/2026/0417", actor="Meera Nair",
            answered_on=TODAY,
            answer="Sent the registers again for completeness.")


def test_an_answer_to_a_letter_nobody_recorded_is_refused(engine):
    with pytest.raises(KeyError):
        engine.notice_answered(reference="NOT/ON/RECORD", actor="Meera Nair",
                               answered_on=TODAY,
                               answer="We sent the shareholder register.")


# -- the sweep ---------------------------------------------------------------


def test_a_letter_past_its_date_opens_a_file(engine):
    letter(engine)
    engine.observe_deadlines(TODAY)
    assert len(files(engine)) == 1


def test_it_stops_everything(engine):
    """The most severe thing this product opens. A missed payment query is
    a question about a customer; this is a question about the firm, asked
    by the body that licenses it, and left unanswered."""
    letter(engine)
    engine.observe_deadlines(TODAY)
    from vinzor.model import Severity

    assert files(engine)[0].severity is Severity.CRITICAL


def test_a_letter_still_in_time_opens_nothing(engine):
    letter(engine)
    engine.observe_deadlines("2026-07-21")
    assert not files(engine)


def test_lateness_is_recorded_once_not_every_time_somebody_looks(engine):
    letter(engine)
    first = engine.observe_deadlines(TODAY)
    second = engine.observe_deadlines(TODAY)
    assert len(first) == 1 and not second


def test_a_workspace_with_no_licence_date_still_reports_a_late_letter(engine):
    """The bug this test exists for: the sweep was written inside the check
    that skips the filing schedule when no licence grant date is recorded.
    A letter is late because a date passed, which has nothing to do with
    when a licence was granted -- so the obligation with the most
    enforcement against it was silently invisible."""
    assert not engine.state.licence.granted_on
    letter(engine)
    assert len(engine.observe_deadlines(TODAY)) == 1


def test_an_answered_letter_never_becomes_late(engine):
    letter(engine)
    engine.notice_answered(
        reference="IFSCA/AML/2026/0417", actor="Meera Nair",
        answered_on="2026-07-29",
        answer="Sent the ownership chains for all three with trust deeds.")
    assert not engine.observe_deadlines(TODAY)


def test_an_undated_letter_never_becomes_late(engine):
    letter(engine, reference="IFSCA/INSP/2026/0033", answer_by="")
    assert not engine.observe_deadlines(TODAY)


def test_the_sweep_survives_a_rebuild(engine):
    letter(engine)
    engine.observe_deadlines(TODAY)
    rebuilt = engine.rebuild().correspondence
    assert rebuilt.reported_late == engine.state.correspondence.reported_late
    assert rebuilt.notices == engine.state.correspondence.notices


# -- how it reads ------------------------------------------------------------


def test_the_file_says_who_wrote_when_and_how_long_ago(engine):
    from vinzor.briefing import case_file

    letter(engine)
    engine.observe_deadlines(TODAY)
    said = " ".join(case_file(engine, files(engine)[0].case_id, TODAY).because)
    assert "IFSCA wrote on 10 July 2026" in said
    assert "19 days ago" in said


def test_the_file_repeats_what_was_asked_for(engine):
    from vinzor.briefing import case_file

    letter(engine)
    engine.observe_deadlines(TODAY)
    said = " ".join(case_file(engine, files(engine)[0].case_id, TODAY).because)
    assert "ownership records for three named investors" in said


def test_the_file_asks_for_a_letter_not_an_analysis(engine):
    """There is nothing to analyse. Somebody has to write back."""
    from vinzor.briefing import case_file

    todo = " ".join(case_file(engine, "x", TODAY).to_close_this) \
        if False else ""
    letter(engine)
    engine.observe_deadlines(TODAY)
    todo = " ".join(
        case_file(engine, files(engine)[0].case_id, TODAY).to_close_this)
    assert "Send the answer" in todo
    assert "extension" in todo


def test_a_sender_is_named_the_way_a_person_says_it(engine):
    assert who_sent_it("FIU") == "FIU-IND"
    assert who_sent_it("IFSCA") == "IFSCA"


def test_an_unrecognised_sender_is_carried_through_as_written(engine):
    """A firm hearing from an authority we did not anticipate should not
    be told their letter is unrecognised."""
    assert who_sent_it("Enforcement Directorate") == "Enforcement Directorate"


def test_nothing_new_speaks_jargon(engine):
    import re

    from vinzor.briefing import brief
    from test_briefing import JARGON, _strings

    letter(engine)
    letter(engine, reference="FIU-IND/2026/9921", from_whom="FIU",
           about="An explanation of the delay in the quarterly return.",
           received_on="2026-06-20", answer_by="2026-07-11")
    engine.observe_deadlines(TODAY)

    offences = []
    briefing = brief(engine, person="Meera Nair", today=TODAY)
    for path, text in _strings(briefing, "briefing"):
        for pattern, what in JARGON:
            found = re.search(pattern, text)
            if found:
                offences.append(f"{path}: {what} ({found.group(0)!r})")
    assert not offences, ("jargon reached the reader:\n  "
                          + "\n  ".join(offences))


def test_the_queue_says_it_in_words_a_person_uses(engine):
    from vinzor.briefing import brief

    letter(engine)
    engine.observe_deadlines(TODAY)
    titles = " ".join(group.title for group in
                      brief(engine, person="Meera Nair", today=TODAY).groups)
    assert "from a regulator was never answered" in titles


# -- the deadline a regulator set --------------------------------------------
#
# Every date in this product goes through ``check_date`` at the door except
# one: the date the Authority set for an answer. That one went into the
# permanent log as whatever arrived, cut to ten characters. So "31-07-2026",
# which is how a date is written in India, was stored untouched and read back
# as no date at all -- the letter was nineteen days overdue and the screen
# said "no date was set, so nothing here can tell you when it is late". And a
# date pasted out of a PDF with a leading space became " 2026-07-3", a real
# date twenty-eight days earlier than the one the regulator gave.


def _letter(engine, answer_by, reference="R/1"):
    return engine.notice_received(
        reference=reference, from_whom="IFSCA",
        about="Ownership chains for three investors",
        received_on="2026-07-10", actor="Meera", answer_by=answer_by)


@pytest.mark.parametrize("written", [
    "2026-07-31",     # as this product writes one
    "31-07-2026",     # as a person in India writes one
    "31/07/2026",
    " 2026-07-31",    # pasted out of a PDF
    "2026-07-31 ",
])
def test_a_deadline_is_read_however_a_person_wrote_it(engine, written):
    _letter(engine, written)
    notice = engine.state.correspondence.notices["R/1"]
    assert notice.answer_by == "2026-07-31"
    assert notice.days_left("2026-08-19") == -19


@pytest.mark.parametrize("written", ["07-08-2026", "next Friday", "31 July 2026"])
def test_a_deadline_nobody_can_read_without_guessing_is_refused(engine, written):
    """07-08-2026 is either August or July depending on who typed it.
    Guessing on a regulator's deadline is not this product's to do, and
    storing it unread was the same thing with the guess deferred."""
    with pytest.raises(ValueError, match="without guessing"):
        _letter(engine, written)


def test_a_deadline_before_the_letter_arrived_is_refused(engine):
    with pytest.raises(ValueError, match="before the letter arrived"):
        _letter(engine, "2026-06-01")


def test_a_letter_with_no_deadline_is_still_recorded(engine):
    """The Authority does not always set one, and inventing a date would be
    repeated in every later report as though they had."""
    _letter(engine, "")
    assert engine.state.correspondence.notices["R/1"].answer_by == ""


# -- and what the file says once it has been answered ------------------------


def _answered(engine):
    _letter(engine, "2026-07-31")
    engine.observe_deadlines("2026-08-19")
    engine.notice_answered(
        reference="R/1", actor="Meera", answered_on="2026-08-12",
        answer="Sent the ownership chains for all three investors, with the "
               "registers of members behind each one.")
    return engine.queue()[0]


def test_an_answered_letter_stops_saying_nothing_was_sent(engine):
    """It said it on the queue, on the case page and in the evidence pack an
    inspector reads -- twelve days after the answer went, with the
    projection knowing otherwise the whole time. The file was reading the
    finding frozen at the moment the rule fired."""
    from vinzor.briefing import case_file

    case = _answered(engine)
    said = case_file(engine, case.case_id, "2026-08-19")

    assert "nothing has been recorded as sent" not in " ".join(said.because)
    assert "12 August 2026" in said.because[0]
    assert "12 days after the date they set" in said.because[0]
    assert "was answered" in said.headline


def test_the_answer_itself_is_on_the_file(engine):
    from vinzor.briefing import case_file

    case = _answered(engine)
    said = " ".join(case_file(engine, case.case_id, "2026-08-19").because)
    assert "registers of members" in said


def test_the_file_stays_open_until_a_person_settles_it(engine):
    """Answering a regulator and closing the record of having been asked are
    two different acts, and only the second is a person's to make."""
    case = _answered(engine)
    assert case.is_open


def test_an_unanswered_letter_still_says_so(engine):
    """The sentence that was right, kept so the fix is not mistaken for
    switching the warning off."""
    from vinzor.briefing import case_file

    _letter(engine, "2026-07-31")
    engine.observe_deadlines("2026-08-19")
    said = case_file(engine, engine.queue()[0].case_id, "2026-08-19")
    assert "nothing has been recorded as sent" in said.because[0]
    assert "is waiting for an answer" in said.headline

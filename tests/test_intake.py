"""Spreadsheets the way institutions actually export them.

The party importer was built against tidy investor lists. A bank hands over
a statement with split debit and credit columns; a registrar hands over
names in three pieces wearing honorifics; everything arrives as .xlsx. These
tests hold the intake to those files -- and to the refusals that keep a
guess off the record when a file is genuinely ambiguous.
"""

from __future__ import annotations

import zipfile

import pytest

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.importing import already_imported, apply, read
from vinzor.model import EntityKind, EventType
from vinzor.xlsx import grid, is_workbook

from conftest import WHEN


@pytest.fixture
def engine() -> Vinzor:
    return Vinzor(EventLog())


def sheet(tmp_path, body: str, name: str = "sheet.csv"):
    path = tmp_path / name
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


# -- reading a workbook ------------------------------------------------------

_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_WB = (f'<?xml version="1.0"?><workbook {_NS} xmlns:r="http://schemas.'
       'openxmlformats.org/officeDocument/2006/relationships">'
       '<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>'
       '</workbook>')
_RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.'
         'openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
         'officeDocument/2006/relationships/worksheet" '
         'Target="worksheets/sheet1.xml"/></Relationships>')


def workbook(tmp_path, sheet_xml: str, shared: str = "",
             styles: str = "", name: str = "book.xlsx"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", _WB)
        archive.writestr("xl/_rels/workbook.xml.rels", _RELS)
        if shared:
            archive.writestr("xl/sharedStrings.xml", shared)
        if styles:
            archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return path


def test_a_workbook_reads_shared_strings_dates_and_gaps(tmp_path):
    shared = (f'<sst {_NS}><si><t>Name</t></si>'
              '<si><r><t>Amou</t></r><r><t>nt</t></r></si>'
              '<si><t>Rohan Desai</t></si></sst>')
    styles = (f'<styleSheet {_NS}><cellXfs count="2">'
              '<xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
    body = (f'<worksheet {_NS}><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c>'
            '<c r="B1" t="s"><v>1</v></c>'
            '<c r="C1" t="inlineStr"><is><t>Date</t></is></c></row>'
            '<row r="2"><c r="A2" t="s"><v>2</v></c>'
            '<c r="C2" s="1"><v>46251</v></c></row>'
            '</sheetData></worksheet>')
    rows, notes = grid(workbook(tmp_path, body, shared, styles))
    assert rows[0] == ["Name", "Amount", "Date"]
    assert rows[1][0] == "Rohan Desai"
    assert rows[1][1] == ""                      # absent cell, not shifted
    assert rows[1][2] == "2026-08-17"            # a serial wearing a date
    assert "Excel workbook" in notes[0]


def test_a_renamed_text_file_is_refused_in_words(tmp_path):
    fake = tmp_path / "list.xlsx"
    fake.write_text("Name,Type\nRohan,person\n", encoding="utf-8")
    assert not is_workbook(fake)
    with pytest.raises(ValueError, match="not an Excel workbook"):
        grid(fake)


def test_an_excel_party_sheet_imports_end_to_end(tmp_path, engine):
    shared = (f'<sst {_NS}><si><t>Investor Name</t></si><si><t>Type</t></si>'
              '<si><t>Asha Mehta</t></si><si><t>person</t></si></sst>')
    body = (f'<worksheet {_NS}><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c>'
            '<c r="B1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>2</v></c>'
            '<c r="B2" t="s"><v>3</v></c></row>'
            '</sheetData></worksheet>')
    plan = read(workbook(tmp_path, body, shared))
    assert plan.kind == "parties"
    assert not plan.refusals
    counts = apply(engine, plan, WHEN)
    assert counts["registered"] == 1
    assert any(e.kind is EntityKind.PERSON and e.name == "Asha Mehta"
               for e in engine.state.graph.entities.values())


# -- what a payments sheet is ------------------------------------------------


BANK = """
Date,Narration,Chq./Ref.No.,Remitter Name,Withdrawal Amt.,Deposit Amt.,Closing Balance
16/08/2026,NEFT CR,UTR001,Ravi Kumar,,40000,140000
17/08/2026,NEFT DR,UTR002,Ravi Kumar,15000,,125000
18/08/2026,IMPS CR,UTR003,Sunita Devi,,9000,134000
"""


def test_a_bank_statement_reads_as_payments(tmp_path):
    plan = read(sheet(tmp_path, BANK))
    assert plan.kind == "payments"
    assert not plan.refusals
    assert len(plan.usable_payments) == 2       # the two credits
    assert len(plan.outgoing_payments) == 1     # the debit, counted not lost
    assert any("going out" in note for note in plan.notes)
    assert "Closing Balance" in plan.ignored


def test_the_dates_of_a_statement_settle_their_own_format(tmp_path):
    plan = read(sheet(tmp_path, BANK))
    assert plan.usable_payments[0].date == "2026-08-16"   # 16/08 is day-first


def test_a_sheet_of_undecidable_dates_is_refused(tmp_path):
    plan = read(sheet(tmp_path, """
Date,Remitter,Amount
03/04/2026,Ravi Kumar,9000
05/06/2026,Ravi Kumar,9000
"""))
    assert plan.refusals
    assert "3 April in Mumbai" in plan.refusals[0]


def test_named_month_dates_need_no_settling(tmp_path):
    plan = read(sheet(tmp_path, """
Date,Remitter,Amount
03-Apr-26,Ravi Kumar,9000
"""))
    assert not plan.refusals
    assert plan.usable_payments[0].date == "2026-04-03"


def test_a_crdr_column_reads_direction(tmp_path):
    plan = read(sheet(tmp_path, """
Txn Date,Remitter,Amount,Cr/Dr
2026-08-16,Ravi Kumar,40000,CR
2026-08-17,Ravi Kumar,15000,DR
"""))
    assert len(plan.usable_payments) == 1
    assert len(plan.outgoing_payments) == 1


def test_a_tally_suffix_reads_direction(tmp_path):
    plan = read(sheet(tmp_path, """
Date,Remitter,Amount
2026-08-16,Ravi Kumar,"40,000.00 Cr"
2026-08-17,Ravi Kumar,"15,000.00 Dr"
"""))
    assert len(plan.usable_payments) == 1
    assert plan.usable_payments[0].amount == 40000.0


def test_unmarked_amounts_are_read_as_arriving_and_say_so(tmp_path):
    plan = read(sheet(tmp_path, """
Date,Remitter,Amount
2026-08-16,Ravi Kumar,40000
"""))
    assert len(plan.usable_payments) == 1
    assert any("read as money arriving" in note for note in plan.notes)


def test_a_statement_without_remitters_is_refused(tmp_path):
    plan = read(sheet(tmp_path, """
Date,Narration,Amount
2026-08-16,NEFT CR,40000
"""))
    assert plan.refusals
    assert "who each payment came from" in plan.refusals[0]


def test_a_blank_remitter_cell_is_an_unattributed_payment(tmp_path, engine):
    """The row is still read, still filed and still recorded. Nobody is told.

    Until 21 August 2026 this opened a file saying no payer was recorded --
    the case the whole blank-remitter path was built to produce. That rule
    was removed, so the payment now lands on the log against a deliberately
    unregistered party and raises nothing. The import behaviour is asserted
    here because it is unchanged and still right; the silence is asserted
    because it is the part a reader would otherwise assume had been checked.
    """
    plan = read(sheet(tmp_path, """
Date,Remitter,Amount
2026-08-16,,40000
"""))
    row = plan.usable_payments[0]
    assert row.payer == ""
    assert row.subject.startswith("unk_")
    apply(engine, plan, WHEN)
    assert engine.queue() == [], (
        "nothing looks for a payment with no sender any more")


def test_two_identical_rows_are_two_payments_not_one(tmp_path):
    plan = read(sheet(tmp_path, """
Date,Remitter,Amount
2026-08-16,Ravi Kumar,9000
2026-08-16,Ravi Kumar,9000
"""))
    ids = [r.payment_id for r in plan.usable_payments]
    assert len(set(ids)) == 2
    again = read(sheet(tmp_path, """
Date,Remitter,Amount
2026-08-16,Ravi Kumar,9000
2026-08-16,Ravi Kumar,9000
"""))
    assert [r.payment_id for r in again.usable_payments] == ids


# -- writing payments --------------------------------------------------------


def test_payments_land_as_facts_and_the_payer_becomes_a_party(tmp_path,
                                                              engine):
    plan = read(sheet(tmp_path, BANK))
    counts = apply(engine, plan, WHEN)
    assert counts["payments_recorded"] == 2
    assert counts["payers_registered"] == 2
    payer = next(e for e in engine.state.graph.entities.values()
                 if e.name == "Ravi Kumar")
    assert payer.kind is EntityKind.UNKNOWN
    payments = [e for e in engine.log
                if e.event_type is EventType.PAYMENT_RECEIVED]
    assert [p.occurred_at for p in payments] == sorted(
        p.occurred_at for p in payments), "written in date order"


def test_reapplying_the_same_rows_records_nothing_twice(tmp_path, engine):
    plan = read(sheet(tmp_path, BANK))
    apply(engine, plan, WHEN)
    counts = apply(engine, read(sheet(tmp_path, BANK)), WHEN)
    assert counts["payments_recorded"] == 0
    assert counts["already_recorded"] == 2


# A test that a split pattern in a sheet opens a structuring file stood here
# until 21 August 2026. It went with the rule.


def test_the_import_itself_is_on_the_record(tmp_path, engine):
    plan = read(sheet(tmp_path, BANK))
    apply(engine, plan, WHEN, by="Meera Nair", filename="statement.csv",
          digest="d" * 64)
    record = engine.state.imports["d" * 64]
    assert record["by"] == "Meera Nair"
    assert record["file"] == "statement.csv"
    assert engine.rebuild().imports == engine.state.imports
    assert engine.verify() == (True, None)


def test_the_same_bytes_cannot_be_imported_twice(tmp_path, engine):
    plan = read(sheet(tmp_path, BANK))
    apply(engine, plan, WHEN, digest="d" * 64)
    sentence = already_imported(engine, "d" * 64)
    assert "already imported" in sentence
    assert "corrected file will differ" in sentence
    with pytest.raises(ValueError, match="already imported"):
        apply(engine, read(sheet(tmp_path, BANK)), WHEN, digest="d" * 64)


# -- parties, the way registrars write them ----------------------------------


def test_split_names_are_joined(tmp_path, engine):
    plan = read(sheet(tmp_path, """
First Name,Middle Name,Last Name,Type
Rajesh,Kumar,Sharma,person
Priya,,Iyer,person
"""))
    assert not plan.refusals
    assert [r.name for r in plan.usable] == ["Rajesh Kumar Sharma",
                                             "Priya Iyer"]


def test_honorifics_come_off_and_the_plan_says_so(tmp_path):
    plan = read(sheet(tmp_path, """
Name,Type
MR RAJESH KUMAR SHARMA,person
M/S ABC TRADING CO,company
Priya Iyer,person
"""))
    assert [r.name for r in plan.usable] == [
        "RAJESH KUMAR SHARMA", "ABC TRADING CO", "Priya Iyer"]
    assert any("honorifics" in note.lower() for note in plan.notes)


def test_pan_joins_the_identity_only_when_present(tmp_path):
    with_pan = read(sheet(tmp_path, """
Name,Type,PAN No
Rohan Desai,person,ABCPD1234E
""")).usable[0]
    without = read(sheet(tmp_path, """
Name,Type
Rohan Desai,person
""")).usable[0]
    assert with_pan.entity_id != without.entity_id
    assert with_pan.attributes["pan"] == "ABCPD1234E"


def test_an_owner_column_declares_ownership(tmp_path, engine):
    """The edge goes on the record, and the resolution stays honest: a
    sheet says who the owner is, not what the owner is, so the resolver
    reports the owner as the dead end an officer has to resolve rather
    than assuming a natural person and calling the chain established."""
    plan = read(sheet(tmp_path, """
Name,Type,Name of UBO,Ownership %
Blue Fern LLP,partnership,Kavita Rao,35%
"""))
    assert not plan.refusals
    apply(engine, plan, WHEN)
    owned = next(e for e in engine.state.graph.entities.values()
                 if e.name == "Blue Fern LLP")
    owner = next(e for e in engine.state.graph.entities.values()
                 if e.name == "Kavita Rao")
    assert owner.kind is EntityKind.UNKNOWN
    resolved = engine.state.graph.resolve_ubo(owned.entity_id)
    assert owner.entity_id in resolved.dead_ends
    assert str(resolved.conclusion) == "INCOMPLETE"


def test_an_owner_without_a_share_refuses_the_sheet(tmp_path):
    plan = read(sheet(tmp_path, """
Name,Type,Name of UBO
Blue Fern LLP,partnership,Kavita Rao
"""))
    assert plan.refusals
    assert "how much of it they hold" in plan.refusals[0]


def test_a_fractional_share_is_read_as_the_percentage_it_means(tmp_path):
    plan = read(sheet(tmp_path, """
Name,Type,Name of UBO,Ownership %
Blue Fern LLP,partnership,Kavita Rao,0.35
"""))
    assert plan.usable[0].owner["share"] == 35.0


# -- one sheet, one reading --------------------------------------------------


def test_a_sheet_that_reads_both_ways_is_refused_until_told(tmp_path):
    body = """
Amount,Currency
40000,INR
"""
    assert read(sheet(tmp_path, body)).refusals
    told = read(sheet(tmp_path, body), sheet="payments")
    assert told.kind == "payments"
    assert told.refusals, "still refused: no payer, no date"


def test_every_refusal_and_note_is_a_sentence(tmp_path):
    """The refusals are the UI. No identifiers, no SCREAMING constants."""
    import re

    bodies = [BANK, "Amount,Currency\n1,INR\n",
              "Date,Narration,Amount\n2026-08-16,x,1\n",
              "Date,Remitter,Amount\n03/04/2026,a,1\n05/06/2026,b,2\n"]
    for body in bodies:
        plan = read(sheet(tmp_path, body))
        for text in plan.refusals + plan.notes:
            assert not re.search(r"\b[a-z]+_[a-z_]+\b", text), text
            assert not re.search(r"\b[A-Z]{2,}_[A-Z_]+\b", text), text


# -- the words a receipt speaks ----------------------------------------------


def test_receipts_and_progress_read_as_english_at_one_and_many():
    from vinzor.briefing import import_progress, import_receipt

    assert import_receipt({"payments_recorded": 1, "payers_registered": 1},
                          "payments", False) == \
        "1 payment is on the record. 1 payer was registered as a party."
    assert import_receipt({"registered": 4, "committed": 2}, "parties",
                          True) == (
        "4 parties are on the record. 2 commitments were recorded. "
        "Screening against the watchlists has begun; matches will appear "
        "in your list.")
    assert import_progress({"done": 1, "total": 1, "matches": 1,
                            "state": "finished"}) == \
        "The one new party was screened: 1 possible match. It is in your list."
    assert import_progress({"done": 3, "total": 8, "matches": 0,
                            "state": "running"}) == \
        "Screened 3 of 8 parties so far: no matches."
    # A statement screens the payers it registered, and says so.
    assert import_progress({"done": 2, "total": 5, "matches": 0,
                            "state": "running", "kind": "payments"}) == \
        "Screened 2 of 5 payers so far: no matches."
    # Nobody new is not a failure, and does not read as one.
    assert "nobody new to screen" in import_progress(
        {"done": 0, "total": 0, "matches": 0, "state": "finished"})
    # The skipped sentence explains itself without naming a setting.
    skipped = import_progress({"done": 0, "total": 3, "matches": 0,
                               "state": "skipped"})
    assert "No watchlist is connected" in skipped
    assert "VINZOR" not in skipped


# -- what the review found, held down ----------------------------------------
#
# Every test below stands for a defect an adversarial review found in the
# first cut of this intake. They share one cause: a sheet was being read the
# way the code wished it had been written.


def test_a_statement_with_zero_fillers_imports(tmp_path):
    """The commonest bank export there is: the column a payment did not use
    holds 0.00 rather than nothing. Reading that as a broken row rejected
    every line of every ICICI and SBI statement."""
    plan = read(sheet(tmp_path, """
Txn Date,Remitter,Withdrawal Amount,Deposit Amount
16/08/2026,Ravi Kumar,0.00,40000.00
17/08/2026,Sunita Devi,15000.00,0.00
"""))
    assert not plan.rejected_payments
    assert len(plan.usable_payments) == 1
    assert len(plan.outgoing_payments) == 1
    assert plan.usable_payments[0].amount == 40000.0


def test_a_reversal_in_the_deposit_column_is_money_leaving(tmp_path):
    plan = read(sheet(tmp_path, """
Date,Remitter,Withdrawal,Deposit
2026-08-16,Ravi Kumar,,"(1,000.00)"
"""))
    assert not plan.usable_payments, "a reversal is not money arriving"
    assert len(plan.outgoing_payments) == 1


def test_a_direction_marker_flush_against_the_figure():
    """"1,000.00Cr" is a thousand credited. Read as crore it became ten
    billion -- a payment ten million times its real size."""
    from vinzor.importing import _payment_amount

    assert _payment_amount("1,000.00Cr") == (1000.0, "", "in", "")
    assert _payment_amount("1,000.00 Dr") == (1000.0, "", "out", "")


def test_crore_and_lakh_still_read_as_written():
    from vinzor.importing import _amount

    assert _amount("2.5 crore")[0] == 25_000_000
    assert _amount("2.5cr")[0] == 25_000_000
    assert _amount("50l")[0] == 5_000_000
    assert _amount("2.5mn")[0] == 2_500_000


def test_a_comma_decimal_is_a_decimal_not_a_thousand():
    """No convention groups digits in twos, so a comma with one or two
    digits behind it can only be a decimal point. Stripping it multiplied
    every European and SWIFT-derived amount by a hundred."""
    from vinzor.importing import _money

    assert _money("1.234,56")[0] == 1234.56
    assert _money("1234,56")[0] == 1234.56
    assert _money("1,00,00,000")[0] == 10_000_000     # Indian grouping
    assert _money("10,000,000")[0] == 10_000_000      # Western grouping


def test_a_share_written_as_a_percentage_stays_that_percentage():
    """0.5% is half a per cent. Read as a fraction it became fifty -- a
    controlling stake, on the permanent record, that nobody declared."""
    from vinzor.importing import _share

    assert _share("0.5%") == 0.5
    assert _share("0.25") == 25.0        # a bare fraction, as forms write it
    assert _share("35%") == 35.0
    assert _share("110%") is None


@pytest.mark.parametrize("written", ["2026-13-45", "31/02/2026",
                                     "2026-02-30", "30-Feb-2026"])
def test_a_day_that_never_existed_is_refused(tmp_path, written):
    """These used to pass the plan and be refused at the log instead --
    halfway through writing an import that cannot be taken back."""
    plan = read(sheet(tmp_path, f"""
Date,Remitter,Amount
{written},Ravi Kumar,9000
"""))
    assert not plan.usable_payments
    assert plan.refusals or plan.rejected_payments


def test_a_commitment_sheet_naming_its_fund_imports(tmp_path):
    """"Fund Name" claimed the party's name, so an ordinary commitment
    sheet was refused for holding two name columns -- and a sheet without
    an investor column registered the fund itself as the customer."""
    plan = read(sheet(tmp_path, """
Investor Name,Type,Fund Name,Commitment,Currency
Asha Mehta,person,Alpha Fund I,2.5 crore,INR
"""))
    assert not plan.refusals
    row = plan.usable[0]
    assert row.name == "Asha Mehta"
    assert row.commitment["fund"] == "Alpha Fund I"
    assert row.commitment["amount"] == 25_000_000


def test_initials_are_not_mistaken_for_a_courtesy_title(tmp_path):
    """MS Dhoni's initials are M and S. Taking them off would leave a
    surname, and screen a different person."""
    plan = read(sheet(tmp_path, """
Name,Type
MS Dhoni,person
MR RAJESH KUMAR SHARMA,person
"""))
    assert [r.name for r in plan.usable] == ["MS Dhoni",
                                             "RAJESH KUMAR SHARMA"]


def test_a_rejected_row_names_the_row_the_reader_will_open(tmp_path):
    """Exports open with a banner and a blank line. Counting from the
    header sent the officer to the wrong line of their own file."""
    plan = read(sheet(tmp_path, """
ACME BANK STATEMENT OF ACCOUNT
CONFIDENTIAL

Date,Remitter,Amount
2026-08-16,Ravi Kumar,not-a-number
"""))
    assert [r.number for r in plan.rejected_payments] == [5]
    assert any("above it" in note for note in plan.notes)


def test_a_hidden_first_sheet_is_not_the_spreadsheet(tmp_path):
    """A hidden sheet is one its author took off the screen. Reading it
    would import figures nobody was looking at."""
    workbook_xml = (
        f'<?xml version="1.0"?><workbook {_NS} xmlns:r="http://schemas.'
        'openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        '<sheet name="Lookups" sheetId="1" state="hidden" r:id="rId1"/>'
        '<sheet name="Data" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.'
            'openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.'
            'org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/hidden.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.'
            'org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>')
    page = (f'<worksheet {_NS}><sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>%s</t></is></c>'
            '</row></sheetData></worksheet>')

    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/hidden.xml", page % "SECRET")
        archive.writestr("xl/worksheets/sheet1.xml", page % "Name")
    rows, _ = grid(path)
    assert rows[0] == ["Name"]


def test_a_corrected_file_does_not_promise_the_same_money_twice(tmp_path,
                                                                engine):
    """The flow tells the officer to fix rejected rows and import again.
    Commitments were re-recorded every time they did."""
    first = read(sheet(tmp_path, """
Name,Type,Commitment,Currency,Fund
Asha Mehta,person,1000000,USD,Alpha Fund I
,person,500000,USD,Alpha Fund I
""", "a.csv"))
    apply(engine, first, WHEN)
    assert len([e for e in engine.log
                if e.event_type is EventType.COMMITMENT_MADE]) == 1

    corrected = read(sheet(tmp_path, """
Name,Type,Commitment,Currency,Fund
Asha Mehta,person,1000000,USD,Alpha Fund I
Rohan Desai,person,500000,USD,Alpha Fund I
""", "b.csv"))
    apply(engine, corrected, WHEN)
    assert len([e for e in engine.log
                if e.event_type is EventType.COMMITMENT_MADE]) == 2


def test_one_investor_can_commit_to_two_funds(tmp_path, engine):
    plan = read(sheet(tmp_path, """
Name,Type,Commitment,Currency,Fund
Asha Mehta,person,1000000,USD,Alpha Fund I
Asha Mehta,person,2000000,USD,Beta Fund II
"""))
    apply(engine, plan, WHEN)
    commitments = [e for e in engine.log
                   if e.event_type is EventType.COMMITMENT_MADE]
    assert len(commitments) == 2
    assert len({e.payload["commitment_id"] for e in commitments}) == 2


def test_an_import_is_one_indivisible_act(tmp_path, engine):
    """Two officers confirming the same sheet at the same moment must not
    each read the log before the other writes to it, and record every row
    twice -- permanently, because nothing can be removed."""
    import threading

    plan_a = read(sheet(tmp_path, BANK, "one.csv"))
    plan_b = read(sheet(tmp_path, BANK, "two.csv"))
    barrier = threading.Barrier(2)

    def confirm(plan):
        barrier.wait()
        apply(engine, plan, WHEN)

    threads = [threading.Thread(target=confirm, args=(p,))
               for p in (plan_a, plan_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    recorded = [e for e in engine.log
                if e.event_type is EventType.PAYMENT_RECEIVED]
    assert len(recorded) == 2, "the same payments were written twice"
    assert engine.verify() == (True, None)


# -- who the money was for ---------------------------------------------------


def reasons(engine) -> list:
    """Every reason recorded on every file in this workspace."""
    out = []
    for case in engine.state.casebook.cases.values():
        for evidence in case.evidence:
            because = (evidence.detail or {}).get("because", "")
            if because:
                out.append(because)
    return out


def payments(engine, tmp_path, body: str):
    apply(engine, read(sheet(tmp_path, body, "pay.csv")), WHEN)


def test_a_sheet_naming_the_investor_files_the_payment_against_them(
        engine, tmp_path):
    """A statement says who sent the money. A payment file also says who it
    was for, and that is the party whose file it belongs on."""
    payments(engine, tmp_path, """Date,Remitter,Beneficiary,Amount
2026-03-02,Kesari Holdings,Anand Bhat,4500000""")

    names = {engine.state.graph.name_of(case.subject)
             for case in engine.state.casebook.cases.values()}
    assert "Anand Bhat" in names


# Two tests stood here: one sender funding three investors, and one investor
# funded from three senders. Both went with their rules on 21 August 2026.
# What is left of what they held is the test below: the beneficiary column
# exists so that an imported payment has two parties to compare, and the one
# surviving rule reads them.


def test_a_sender_who_is_not_the_beneficiary_is_seen_in_a_sheet(
        engine, tmp_path):
    """The importer's own output has to reach the rules.

    Until the sheet could name a beneficiary, every imported payment was
    filed against its own sender -- so sender and subject were one party and
    no payment rule could ever fire on anything the importer wrote. That is
    the failure this holds shut, and after 21 August 2026 the third-party
    rule is the only rule left able to demonstrate it.
    """
    payments(engine, tmp_path, """Date,Remitter,Beneficiary,Amount
2026-03-02,Kesari Holdings,Anand Bhat,4500000""")

    said = reasons(engine)
    assert any("someone other than the investor" in line
               for line in said), said


def test_a_sheet_with_no_beneficiary_still_files_against_the_sender(
        engine, tmp_path):
    """Most bank statements never say who a payment was for. Those must go
    on working exactly as they did, against the sender."""
    payments(engine, tmp_path, """Date,Remitter,Amount
2026-03-02,Kesari Holdings,4500000""")

    filed = [event.subject for event in engine.log.read()
             if event.event_type is EventType.PAYMENT_RECEIVED]
    assert [engine.state.graph.name_of(s) for s in filed] == ["Kesari Holdings"]


def test_a_party_paying_its_own_call_opens_no_third_party_file(engine,
                                                               tmp_path):
    """A sheet whose remitter and beneficiary are the same party is the
    ordinary case, and the one rule left must be silent on it.

    This used to read the counterparty projection and assert that no
    relationship had been built. That projection was removed on 21 August
    2026, so the same property is asserted where a reader can now see it:
    no file opens.
    """
    payments(engine, tmp_path, """Date,Remitter,Beneficiary,Amount
2026-03-02,Anand Bhat,Anand Bhat,4500000""")

    assert engine.queue() == []


def test_the_reader_is_told_the_beneficiary_column_was_used(engine, tmp_path):
    """The mapping a person confirms before an import lands must name this
    column in the same plain words as every other."""
    from vinzor.importing import MEANINGS
    plan = read(sheet(tmp_path, """Date,Remitter,Beneficiary,Amount
2026-03-02,Kesari Holdings,Anand Bhat,4500000""", "pay.csv"))
    assert "beneficiary" in plan.mapped
    assert MEANINGS["beneficiary"] == "who each payment was for"

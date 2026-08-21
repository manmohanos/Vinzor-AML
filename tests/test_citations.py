"""The clause register, and the rule that nothing reaches a Case uncited."""

from __future__ import annotations

import pytest

from vinzor.citations import CLAUSES, DOCUMENTS, cite, clause, coverage
from vinzor.model import Finding, Severity
from vinzor.policies import PolicyContext, UncitedFinding, evaluate

from conftest import person, screened


def test_every_clause_resolves_to_a_registered_document():
    for c in CLAUSES.values():
        assert c.doc_id in DOCUMENTS


def test_every_clause_carries_a_verbatim_extract_and_a_link():
    for c in CLAUSES.values():
        assert len(c.extract) > 40, f"{c.clause_id} has no usable extract"
        assert DOCUMENTS[c.doc_id].url.startswith("https://")


def test_a_citation_says_whether_a_human_has_checked_it():
    """Machine-extracted clauses must not present as authoritative."""
    citation = clause("1.3.3(a)").cite()
    assert citation["verified"] is False
    assert coverage()["verified"] == 0
    assert coverage()["unverified"] == len(CLAUSES)


def test_the_register_records_amendments_that_changed_the_rule():
    assert "twenty-five" in clause("1.3.3(a)").amended
    assert "May 23, 2023" in clause("1.3.3(a)").amended


def test_every_known_amendment_is_recorded_with_its_standing():
    """The register was two circulars behind and did not know it, and the one
    it did know about was filed against clauses that circular never touched.
    Both are now cited from the master that already incorporates them, so
    nothing is outstanding -- but every amendment stays on the record with
    what it changed, because "nothing pending" has to be a finding rather
    than an absence of looking.
    """
    from vinzor.citations import KNOWN_PENDING_AMENDMENTS

    dates = [a["circular_date"] for a in KNOWN_PENDING_AMENDMENTS]
    assert dates == ["2026-02-26", "2026-08-03"]
    assert all(a["incorporated"] for a in KNOWN_PENDING_AMENDMENTS)
    # Neither circular touches a clause this system enforces: the August one
    # amends 10.3, and 1.2.1/1.2.3 of Annexure II. We hold 10.1 and 10.2.
    assert all(a["affects"] == () for a in KNOWN_PENDING_AMENDMENTS)
    assert not coverage()["pending_amendments"]


def test_the_aml_version_matches_what_ifsca_currently_publishes():
    """IFSCA republishes a consolidated master after each circular. Citing a
    superseded one gives page numbers that point at the wrong lines: the
    August master runs to 73 pages where January's ran to 82, and clause 5.9
    moved from page 40 to page 34.
    """
    assert DOCUMENTS["IFSCA-AML-2022"].version == "updated as on August 03, 2026"
    assert "Master_Guidelines_as_on_03_Aug_2026" in DOCUMENTS["IFSCA-AML-2022"].url


def test_an_unknown_clause_fails_loudly():
    with pytest.raises(KeyError, match="no registered clause"):
        clause("99.9")


def test_cite_returns_one_entry_per_clause():
    citations = cite("5.9", "11.2")
    assert [c["clause"] for c in citations] == ["5.9", "11.2"]


def test_a_policy_cannot_open_a_case_on_an_uncited_finding(engine):
    """The guard that keeps opinion out of the Case file."""

    def opinionated(ctx):
        return (
            Finding(
                policy_id="POL_VIBES",
                case_type="SCREENING_HIT",
                severity=Severity.HIGH,
                summary="feels wrong",
            ),
        )

    person(engine, "p1")
    event = next(iter(engine.log))
    ctx = PolicyContext(event=event, graph=engine.state.graph)

    with pytest.raises(UncitedFinding, match="POL_VIBES"):
        evaluate(ctx, policies=(opinionated,))


def test_real_findings_carry_the_clause_through_to_the_case(engine):
    person(engine, "p1", "Alice")
    case = screened(engine, "p1", "SANCTIONS").cases[0]

    refs = {c["clause"] for c in case.evidence[0].citations}
    assert refs == {"5.9", "11.2"}
    citation = case.evidence[0].citations[0]
    assert "United Nations Security Council" in citation["extract"]
    assert citation["url"].startswith("https://ifsca.gov.in/")


# -- corrections from cross-checking against IFSCA's own published text -----
# AI-assisted, not a CA/CS's sign-off -- verified stays False on every one of
# these. What changed is that the extract, heading and page now match the
# primary source rather than an earlier machine extraction nobody had
# reread. See BACKLOG.md for what this is and is not a substitute for.


def test_4_2_no_longer_grafts_a_different_subsections_sentence_on():
    """It quoted "(a) Customer risk ... (v) Whether the countries or
    jurisdictions are subject to sanctions" as one passage. That sentence is
    real, but it is item (b)(v), "Country or Geographic risk" -- a different
    subsection than the one the citation claimed. The source has no clause
    that names "adverse media" at all, so the honest citation is the chapeau
    obligation itself, not an invented match to a specific bullet."""
    extract = clause("4.2").extract
    assert "sanctions" not in extract
    assert extract.rstrip().endswith("among other things:")


def test_beneficial_owner_clauses_no_longer_drop_a_clause_silently():
    """1.3.3(b) and (c) both dropped "who, whether acting alone or together,
    or through one or more juridical person," with no ellipsis marking the
    omission -- reading as a complete quotation when it was not one."""
    for clause_id in ("1.3.3(b)", "1.3.3(c)"):
        assert "whether acting alone or together" in clause(clause_id).extract


def test_the_pep_clause_includes_the_life_insurance_beneficiary_limb():
    """It stopped at "...is a politically exposed person (PEP)." and silently
    dropped the rest of the same source sentence, which extends the same
    test to a life-insurance policy's beneficiary."""
    assert "beneficiary of the policy" in clause("5.5").extract


def test_the_beneficial_owner_pages_match_the_current_pdf():
    """All four sub-clauses of 1.3.3 sit on page 5 of the master as it stands
    on 3 August 2026. They were on pages 4-5 of the January consolidation."""
    for clause_id in ("1.3.3(a)", "1.3.3(b)", "1.3.3(c)", "1.3.3(d)"):
        assert clause(clause_id).page == 5


def test_every_clause_carries_a_page_in_the_document_it_cites():
    """A citation a reader cannot turn to is one they must take on trust."""
    from vinzor.citations import CLAUSES

    assert all(c.page for c in CLAUSES.values())
    aml = [c for c in CLAUSES.values() if c.doc_id == "IFSCA-AML-2022"]
    assert all(c.page <= 73 for c in aml), "a page beyond the 73-page master"
    fmr = [c for c in CLAUSES.values() if c.doc_id == "IFSCA-FMR-2025"]
    assert all(c.page <= 102 for c in fmr), "a page beyond the 102-page FMR"


def test_the_fmr_version_matches_what_ifsca_currently_publishes():
    """"as amended up to July 30, 2025" was the version this register was
    built against. IFSCA's own legal index no longer offers that version --
    only a January 2026 consolidation that includes a further amendment."""
    assert DOCUMENTS["IFSCA-FMR-2025"].version == "as amended up to January 30, 2026"


def test_7_5_s_amendment_note_covers_the_2026_substitution():
    """The chapeau sentence this clause quotes is unchanged, but the
    experience-requirement sub-clause immediately beneath it, 7(5)(b), was
    substituted with effect from 30 January 2026 -- a later, substantive
    amendment the record did not mention until now."""
    assert "30 January 2026" in clause("7(5)").amended


def test_10_1_no_longer_claims_fiu_ind_reporting_as_its_own():
    """The old extract did not appear anywhere in the source -- it was a
    paraphrase, not a quotation -- and it wrongly folded FIU-IND reporting
    into this clause. That is a separate provision, Clause 10.3, which is not
    registered here."""
    extract = clause("10.1").extract
    assert "FIU-IND" not in extract
    assert "Principal Officer" in extract


def test_two_clauses_cannot_share_an_id():
    """The register was a dict comprehension, which keeps the last duplicate.
    Clause ids are short and span two documents, so a collision was a matter of
    time -- and it would have produced a Case citing the right number attached
    to the wrong document's text, with nothing on screen to suggest it."""
    import pytest

    from vinzor.citations import Clause, _register

    clash = [
        Clause("5.1", "IFSCA-AML-2022", "one", "first text"),
        Clause("5.1", "IFSCA-FMR-2025", "two", "second text"),
    ]
    with pytest.raises(ValueError) as raised:
        _register(clash)
    assert "share the id" in str(raised.value)
    assert "IFSCA-AML-2022" in str(raised.value)


def test_the_shipped_register_has_no_collisions():
    from vinzor.citations import CLAUSES

    assert len(CLAUSES) == 29

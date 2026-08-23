"""SPEC-001 agent #2 -- the Ownership explainer.

The first agent in this codebase that plans its own next step rather than
following a fixed sequence, so most of what follows tests the two properties
that shape mirror what ``test_ask.py`` and ``test_boundary_audit.py`` already
prove for the assistant this agent borrows its whole discipline from:

* it decides, from what the internal chain already shows, whether an
  external lookup is worth making at all -- not always, and not never;
* a check that did not run is never mistaken, in the draft the officer
  reads, for a check that found nothing.

Every test here runs offline against a scripted model and a canned registry
transport; none of it touches a network or a credential.
"""

from __future__ import annotations

import inspect

import pytest

from vinzor.agents import ReadOnly
from vinzor.ask import Spoken
from vinzor.assist import DEFAULT_BUDGET_USD, spent_so_far
from vinzor.model import EventType, Relation
from vinzor.policies import CASE_UBO_REVIEW
from vinzor.registries import CompaniesHouseClient
from vinzor.ubo_explainer import (
    EXTERNAL_ADDS_A_NAME,
    EXTERNAL_CHECK_FAILED,
    EXTERNAL_CONFIRMS,
    EXTERNAL_DISAGREES,
    NO_EXTERNAL_CHECK_NEEDED,
    TOOLS,
    Explanation,
    ExplanationRejected,
    ExplanationUnavailable,
    already_explained,
    explain_ownership,
    invented_names,
    prepare_explanations,
    record,
)

from conftest import WHEN, company, officer, owns, person, trust_of

WHEN2 = "2026-08-20"


def scripted(*replies):
    """A model that says exactly these things, in order. Copied rather than
    imported from ``test_ask.py``, so this file stands on its own -- the
    same choice ``test_registries.py`` makes."""
    said = list(replies)
    seen = []

    def talk(messages):
        seen.append([dict(m) for m in messages])
        return said.pop(0) if said else {"answer": "Nothing further.", "used": []}

    talk.seen = seen
    return talk


def _open_case(engine, subject: str) -> str:
    for case in engine.queue():
        if case.case_type == CASE_UBO_REVIEW and case.subject == subject:
            return case.case_id
    raise AssertionError(f"no open UBO_REVIEW case for {subject!r}")


# ---------------------------------------------------------------------------
# UK Companies House canned transports -- the same shape test_registries.py
# builds, kept local so this file stands on its own.
# ---------------------------------------------------------------------------


def _uk_profile():
    return {
        "company_number": "12345678",
        "company_name": "Meridian Holdings Ltd",
        "company_status": "active",
        "type": "ltd",
        "date_of_creation": "2015-06-01",
        "registered_office_address": {
            "address_line_1": "1 Poultry", "locality": "London",
            "postal_code": "EC2R 8EJ", "country": "United Kingdom",
        },
    }


def _uk_psc(name="Priya Menon"):
    return {"items": [
        {"name": name,
         "kind": "individual-person-with-significant-control",
         "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
         "nationality": "British", "country_of_residence": "United Kingdom"},
    ]}


def uk_transport_for(profiles, psc=None, search_results=None):
    import json as _json
    import urllib.error

    def transport(url, body, headers):
        if "/persons-with-significant-control" in url:
            number = url.split("/company/")[1].split("/")[0]
            found = (psc or {}).get(number)
            if found is None:
                raise urllib.error.HTTPError(url, 404, "not found", {}, None)
            return _json.dumps(found).encode()
        if "/search/companies" in url:
            return _json.dumps({"items": list(search_results or [])}).encode()
        number = url.rsplit("/company/", 1)[1]
        found = profiles.get(number)
        if found is None:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return _json.dumps(found).encode()

    return transport


def _broken_transport(url, body, headers):
    """The shape a dead connection takes. Never an HTTP answer -- an HTTP
    answer of any code is the registry having been reached."""
    raise OSError("connection refused")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@pytest.fixture
def with_officer(engine):
    officer(engine)
    return engine


def _trust_missing_its_trustee(engine):
    """A gap no company register can help with: a person who was never
    named. Opens a UBO_REVIEW Case whose only shortfall is a missing role."""
    trust_of(engine, "trs_1", "Meridian Family Trust")
    engine.ingest(event_type=EventType.COMMITMENT_MADE, subject="trs_1",
                 occurred_at=WHEN,
                 payload={"investor": "trs_1", "fund": "fnd_1",
                         "amount": 1_000_000})
    return "trs_1"


def _company_owned_by_an_unresolved_uk_parent(engine):
    """A gap a company register might genuinely help with: the chain runs
    out at a company, not a person."""
    company(engine, "cmp_investor", "Silverline Capital Partners Ltd")
    company(engine, "cmp_parent_uk", "Meridian Holdings Ltd")
    owns(engine, "cmp_parent_uk", "cmp_investor", 100.0)
    engine.ingest(event_type=EventType.COMMITMENT_MADE, subject="cmp_investor",
                 occurred_at=WHEN,
                 payload={"investor": "cmp_investor", "fund": "fnd_1",
                         "amount": 1_000_000})
    return "cmp_investor"


# ---------------------------------------------------------------------------
# It decides -- the one property this agent exists to demonstrate
# ---------------------------------------------------------------------------


def test_it_does_not_call_a_register_when_nothing_there_could_help(with_officer):
    """A missing trustee is a person nobody has named yet, not a company
    waiting to be looked up. The agent has to work that out itself -- there
    is no flag telling it so -- from what the internal chain shows."""
    engine = with_officer
    subject = _trust_missing_its_trustee(engine)
    case_id = _open_case(engine, subject)

    talk = scripted({
        "internal_explanation": (
            "Meridian Family Trust has not named an author or a trustee, "
            "so its beneficial ownership under clause 1.3.3(d) is not yet "
            "established."),
        "external_explanation": (
            "Nothing in the internal chain points to a company or similar "
            "entity, so a register lookup would not help here."),
        "document_request": "Ask for the trust deed naming the settlor and the trustee.",
        "checks": ["Confirm the trust deed is the current, signed version"],
    })

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == NO_EXTERNAL_CHECK_NEEDED
    assert explanation.steps == ()
    assert "trustee" in explanation.internal_explanation.lower()
    assert "would not help" in explanation.external_explanation


def test_no_external_check_falls_back_to_a_plain_sentence_if_the_model_gave_none(
        with_officer):
    engine = with_officer
    subject = _trust_missing_its_trustee(engine)
    case_id = _open_case(engine, subject)

    talk = scripted({
        "internal_explanation": (
            "Meridian Family Trust has not named an author or a trustee, "
            "so its beneficial ownership under clause 1.3.3(d) is not yet "
            "established."),
        "external_explanation": "",
        "document_request": "Ask for the trust deed naming the settlor and the trustee.",
        "checks": [],
    })

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, budget_usd=DEFAULT_BUDGET_USD)
    assert explanation.status == NO_EXTERNAL_CHECK_NEEDED
    assert explanation.external_explanation == "No external register was checked."


def test_it_calls_a_register_when_the_chain_runs_out_at_a_company(with_officer):
    """The other half of the same decision: a company the chain never
    resolved is exactly what a register might add to."""
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    uk_client = CompaniesHouseClient(
        transport=uk_transport_for({"12345678": _uk_profile()},
                                   {"12345678": _uk_psc("Priya Menon")}))

    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "Meridian Holdings Ltd is where the chain runs out"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there with "
                "nothing declared above it."),
            "external_explanation": (
                "The UK register names Priya Menon as a person with "
                "significant control of Meridian Holdings Ltd, which our "
                "own file does not show."),
            "document_request": (
                "Ask Silverline Capital Partners Ltd to confirm who "
                "ultimately controls Meridian Holdings Ltd, including "
                "Priya Menon."),
            "checks": ["Confirm Priya Menon's identity documents"],
        },
    )

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=uk_client,
                                    budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == EXTERNAL_ADDS_A_NAME
    assert [s.tool for s in explanation.steps] == ["lookup_company_uk"]
    assert explanation.steps[0].outcome == "ok"
    assert "Priya Menon" in explanation.external_explanation
    assert "Meridian Holdings Ltd" in explanation.external_explanation


def test_a_register_that_confirms_the_internal_chain_says_so(with_officer):
    """Checked, reached, and agrees -- the plain, unremarkable case."""
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    # The chain names nobody as a beneficial owner of Meridian Holdings Ltd
    # yet, so a PSC list naming exactly the entities already on file --
    # here, none at all -- confirms rather than adds.
    uk_client = CompaniesHouseClient(
        transport=uk_transport_for({"12345678": _uk_profile()}, psc={}))

    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "checking Meridian Holdings Ltd"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there."),
            "external_explanation": (
                "The UK register confirms Meridian Holdings Ltd is an "
                "active company, with no person with significant control "
                "on file there either."),
            "document_request": (
                "Ask Silverline Capital Partners Ltd who controls Meridian "
                "Holdings Ltd."),
            "checks": [],
        },
    )

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=uk_client,
                                    budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == EXTERNAL_CONFIRMS
    assert "confirmed" in explanation.external_explanation.lower()


def test_a_register_that_cannot_confirm_the_entity_exists_disagrees(with_officer):
    """The registry was reached and plainly could not find the company our
    own file names -- a real, useful disagreement, not a failure."""
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    uk_client = CompaniesHouseClient(transport=uk_transport_for({}))

    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "checking Meridian Holdings Ltd"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there."),
            "external_explanation": (
                "The UK register was checked and did not have a company "
                "matching this number."),
            "document_request": (
                "Ask Silverline Capital Partners Ltd for Meridian Holdings "
                "Ltd's correct registration details."),
            "checks": [],
        },
    )

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=uk_client,
                                    budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == EXTERNAL_DISAGREES
    assert "did not confirm" in explanation.external_explanation.lower()


# ---------------------------------------------------------------------------
# The rule this file is named for: a failed check is never shown as a clean
# one, however the model itself describes it.
# ---------------------------------------------------------------------------


def test_a_broken_registry_call_is_surfaced_never_swallowed(with_officer):
    """The critical property. The model is handed the tool's own error and
    then, in this scenario, describes the run as though nothing was wrong
    -- exactly the confident-closing failure a dynamic agent makes newly
    possible. The draft that reaches the officer must say the check failed
    regardless of what the model wrote, not proceed as if the register had
    nothing to add."""
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    uk_client = CompaniesHouseClient(transport=_broken_transport)

    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "checking Meridian Holdings Ltd"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there."),
            # A model glossing over its own tool's failure -- the exact
            # confident-closing text this property exists to catch.
            "external_explanation": (
                "Nothing further was found, so the chain looks complete "
                "as it stands."),
            "document_request": (
                "Ask Silverline Capital Partners Ltd who controls Meridian "
                "Holdings Ltd."),
            "checks": [],
        },
    )

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=uk_client,
                                    budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == EXTERNAL_CHECK_FAILED
    assert explanation.steps[0].outcome == "unavailable"
    said = explanation.external_explanation.lower()
    assert "could not be" in said  # "could not be reached" / "completed"
    assert "nothing further was found" not in said
    assert "looks complete" not in said

    # And the record an inspector would actually read carries the same
    # words -- not a rejected draft, a produced one that tells the truth.
    result = record(engine, explanation, prepared_at=WHEN2)
    case = engine.case(case_id)
    assert case.draft["recommendation"] == EXTERNAL_CHECK_FAILED
    assert "could not be" in case.draft["external_explanation"].lower()


def test_a_broken_registry_is_visible_even_if_the_model_says_nothing_about_it(with_officer):
    """The weaker version of the same failure mode: the model does not lie
    about the check, it simply never mentions it went wrong."""
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    uk_client = CompaniesHouseClient(transport=_broken_transport)

    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "checking Meridian Holdings Ltd"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there."),
            "external_explanation": "",
            "document_request": (
                "Ask Silverline Capital Partners Ltd who controls Meridian "
                "Holdings Ltd."),
            "checks": [],
        },
    )

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=uk_client,
                                    budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == EXTERNAL_CHECK_FAILED
    assert "could not be" in explanation.external_explanation.lower()


def test_a_lookup_declined_before_it_was_attempted_is_not_a_clean_answer(
        with_officer):
    """The sharper version of the same property, and a real bug found by
    adversarial review rather than by this suite.

    registries.py declines a lookup that has nothing to ask about -- a
    blank company argument -- by returning a plain ``{"error": ...}`` dict
    rather than raising, because nothing went wrong; there was simply
    nothing to look up. No network call is even attempted: ``uk_client`` is
    left ``None`` here, so one could not have happened.

    That decline is still a check that did not run. An earlier version of
    this function only caught raised exceptions when deciding whether a
    tool call succeeded, so a model calling the tool with a missing
    argument produced a step marked "ok", which ``_classify_external`` then
    read as a genuine answer -- manufacturing an affirmative sentence
    claiming the register was checked and confirmed what the file already
    shows, for a lookup that never sent a byte over the wire. That is worse
    than "found nothing": it is confidently wrong about whether the check
    happened at all, and it is exactly the class of bug this codebase has
    already found and fixed five times elsewhere.
    """
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    talk = scripted(
        # A realistic model slip: the tool is called with no company named
        # at all, rather than the one it was just shown in the chain.
        {"tool": "lookup_company_uk", "arguments": {},
         "why": "checking the parent company"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there."),
            "external_explanation": (
                "The register was checked and confirmed our records."),
            "document_request": (
                "Ask Silverline Capital Partners Ltd who controls Meridian "
                "Holdings Ltd."),
            "checks": [],
        },
    )

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=None,
                                    budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == EXTERNAL_CHECK_FAILED, (
        "a lookup with nothing to ask about was read as a genuine answer")
    assert "could not be" in explanation.external_explanation.lower() or \
        "not the same as a clean search" in explanation.external_explanation.lower()
    assert "the register was checked and confirmed" not in \
        explanation.external_explanation.lower(), (
        "the module must never claim a register confirmed anything it was "
        "never actually asked")


def test_one_broken_register_does_not_hide_behind_a_working_one(with_officer):
    """A run may try both registers. The failed one still forces this
    status -- masking one broken check behind one working one is the same
    defect this file exists to close -- but the sentence names which was
    which rather than reporting an undifferentiated failure."""
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    uk_client = CompaniesHouseClient(transport=_broken_transport)

    def oc_transport(url, body, headers):
        import json as _json

        return _json.dumps({"results": {"companies": [
            {"company": {"company_number": "1", "name": "Meridian Holdings Ltd",
                        "jurisdiction_code": "gb", "current_status": "Active",
                        "incorporation_date": "2015-06-01"}}]}}).encode()

    from vinzor.registries import OpenCorporatesClient

    oc_client = OpenCorporatesClient(api_token="tok_123", transport=oc_transport)

    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "checking the UK register first"},
        {"tool": "lookup_company", "arguments": {"company": "Meridian Holdings Ltd"},
         "why": "the UK register did not answer, trying worldwide"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there."),
            "external_explanation": (
                "The UK register could not be reached. The worldwide "
                "register did find a matching company."),
            "document_request": (
                "Ask Silverline Capital Partners Ltd who controls Meridian "
                "Holdings Ltd."),
            "checks": [],
        },
    )

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=uk_client,
                                    oc_client=oc_client,
                                    budget_usd=DEFAULT_BUDGET_USD)

    assert explanation.status == EXTERNAL_CHECK_FAILED
    said = explanation.external_explanation.lower()
    assert "checked separately and did answer" in said


# ---------------------------------------------------------------------------
# The invented-fact guard -- assist.py's own discipline, applied here to
# names as well as figures.
# ---------------------------------------------------------------------------


def test_invented_names_pass_only_what_was_actually_shown():
    seen = ['{"subject_name": "Meridian Family Trust", "dead_ends": []}']
    assert invented_names("Meridian Family Trust has no trustee.", seen) == []
    # "Dmitri" and "Volkov" appear nowhere in what was read; "Contact" is an
    # ordinary instruction verb, exempted the same way "Ask" is.
    assert invented_names("Contact Dmitri Volkov about this.", seen) == ["Dmitri", "Volkov"]


def test_a_fabricated_name_destroys_the_whole_draft(with_officer):
    engine = with_officer
    subject = _trust_missing_its_trustee(engine)
    case_id = _open_case(engine, subject)

    talk = scripted({
        "internal_explanation": (
            "Meridian Family Trust has not named a trustee. The beneficial "
            "owner appears to be Dmitri Volkov."),
        "external_explanation": "No external register was checked.",
        "document_request": "Ask for the trust deed.",
        "checks": [],
    })

    with pytest.raises(ExplanationRejected, match="Volkov"):
        explain_ownership(engine, subject, case_id=case_id, transport=talk,
                          budget_usd=DEFAULT_BUDGET_USD)

    before = len(engine.log)
    assert engine.case(case_id).draft is None
    assert len(engine.log) == before


def test_a_fabricated_percentage_destroys_the_whole_draft(with_officer):
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    talk = scripted({
        "internal_explanation": (
            "Silverline Capital Partners Ltd is 63% owned by Meridian "
            "Holdings Ltd, and the chain runs out there."),
        "external_explanation": "No external register was checked.",
        "document_request": "Ask who controls Meridian Holdings Ltd.",
        "checks": [],
    })

    with pytest.raises(ExplanationRejected, match="63"):
        explain_ownership(engine, subject, case_id=case_id, transport=talk,
                          budget_usd=DEFAULT_BUDGET_USD)


def test_too_short_a_draft_is_rejected(with_officer):
    engine = with_officer
    subject = _trust_missing_its_trustee(engine)
    case_id = _open_case(engine, subject)

    talk = scripted({
        "internal_explanation": "Not much here.",
        "external_explanation": "",
        "document_request": "Ask.",
        "checks": [],
    })

    with pytest.raises(ExplanationRejected, match="too short"):
        explain_ownership(engine, subject, case_id=case_id, transport=talk,
                          budget_usd=DEFAULT_BUDGET_USD)


# ---------------------------------------------------------------------------
# Bounded, like ask.py's own loop
# ---------------------------------------------------------------------------


def test_it_stops_looking_things_up_eventually(with_officer):
    from vinzor.ubo_explainer import MAX_STEPS

    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    uk_client = CompaniesHouseClient(
        transport=uk_transport_for({"12345678": _uk_profile()}, psc={}))

    talk = scripted(*[
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "again"}
        for _ in range(MAX_STEPS + 4)
    ])

    with pytest.raises(ExplanationUnavailable, match="kept looking"):
        explain_ownership(engine, subject, case_id=case_id, transport=talk,
                          uk_client=uk_client, budget_usd=DEFAULT_BUDGET_USD)


def test_an_already_identified_chain_is_refused(with_officer):
    """This agent explains a gap. A chain with no gap is out of scope, and
    it says so rather than manufacturing something to write about."""
    engine = with_officer
    company(engine, "cmp_investor", "Silverline Capital Partners Ltd")
    person(engine, "per_owner", "Rohan Desai")
    owns(engine, "per_owner", "cmp_investor", 100.0)
    engine.ingest(event_type=EventType.COMMITMENT_MADE, subject="cmp_investor",
                 occurred_at=WHEN,
                 payload={"investor": "cmp_investor", "fund": "fnd_1",
                         "amount": 1_000_000})
    # A fully identified chain opens no Case at all -- there is nothing to
    # explain -- so this is exercised directly rather than through a Case.
    with pytest.raises(ExplanationUnavailable, match="already fully identified"):
        explain_ownership(engine, "cmp_investor", case_id="case_doesnotmatter",
                          transport=scripted(), budget_usd=DEFAULT_BUDGET_USD)


# ---------------------------------------------------------------------------
# The spend ceiling -- shared with the rest of the assistant, not a second
# one of its own.
# ---------------------------------------------------------------------------


def test_the_spend_is_counted_against_the_shared_ceiling(with_officer):
    engine = with_officer
    subject = _trust_missing_its_trustee(engine)
    case_id = _open_case(engine, subject)

    def priced(_messages):
        return Spoken(
            reply={
                "internal_explanation": (
                    "Meridian Family Trust has not named an author or a "
                    "trustee, so its ownership is not yet established."),
                "external_explanation": "No external register was checked.",
                "document_request": "Ask for the trust deed.",
                "checks": [],
            },
            tokens_in=800, tokens_out=200, cost_usd=0.30,
            model="model-router", region="southindia",
        )

    assert spent_so_far(engine) == 0.0
    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=priced,
                                    budget_usd=DEFAULT_BUDGET_USD)
    record(engine, explanation, prepared_at=WHEN2)

    assert spent_so_far(engine) == 0.30
    assert explanation.model == "model-router"
    assert explanation.cost_usd == 0.30


def test_a_workspace_over_its_ceiling_is_refused_before_a_model_is_called(with_officer):
    engine = with_officer
    subject = _trust_missing_its_trustee(engine)
    case_id = _open_case(engine, subject)

    def spend(_messages):
        return Spoken(reply={"internal_explanation": "x" * 30,
                             "external_explanation": "",
                             "document_request": "y" * 20, "checks": []},
                     cost_usd=4.0, model="m", region="r")

    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=spend, budget_usd=1.0)
    record(engine, explanation, prepared_at=WHEN2)
    assert spent_so_far(engine) >= 1.0

    def must_not_be_called(_messages):
        raise AssertionError("a model was called after the ceiling was reached")

    with pytest.raises(ExplanationUnavailable, match="allowance"):
        explain_ownership(engine, subject, case_id=case_id,
                          transport=must_not_be_called, budget_usd=1.0)


# ---------------------------------------------------------------------------
# Never reachable from a write path -- the two enforcement points this
# module is bound by, tested the same way test_ask.py and test_registries.py
# test the other two boundaries that make the same promise.
# ---------------------------------------------------------------------------


def test_running_every_tool_writes_nothing(with_officer):
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    uk_client = CompaniesHouseClient(
        transport=uk_transport_for({"12345678": _uk_profile()},
                                   {"12345678": _uk_psc()}))
    before = len(engine.log)

    result = TOOLS["lookup_company_uk"].run(ReadOnly(engine), company="12345678",
                                            client=uk_client)
    assert result["found"] is True
    assert len(engine.log) == before

    from vinzor.registries import RegistryUnavailable

    # No token configured -- must fail loudly, not write, and never return
    # a quiet empty result that would read as a clean search.
    with pytest.raises(RegistryUnavailable):
        TOOLS["lookup_company"].run(ReadOnly(engine),
                                    company="Meridian Holdings Ltd",
                                    client=None)
    assert len(engine.log) == before

    intact, why = engine.verify()
    assert intact, why


def test_no_tool_reaches_a_write_path_in_its_source():
    for name, tool in TOOLS.items():
        source = inspect.getsource(tool.run)
        for forbidden in (".ingest(", ".decide(", ".confirm_clause(",
                          ".enroll(", "log.append(", ".observe_deadlines("):
            assert forbidden not in source, f"{name} can write: {forbidden}"


def test_the_deciding_loop_itself_never_writes():
    """``explain_ownership`` is where this agent decides what to do next,
    turn by turn. ``record`` is the one place this boundary may write, and
    a caller has to reach for it separately -- the loop that plans is not
    the function that is allowed to write, mirroring how ``ask.ask`` never
    calls ``engine.ingest`` for anything but its own audit record."""
    source = inspect.getsource(explain_ownership)
    for forbidden in (".decide(", ".confirm_clause(", ".enroll(",
                      "log.append(", ".observe_deadlines(", "OWNERSHIP_DECLARED"):
        assert forbidden not in source, f"the loop can write: {forbidden}"
    # It also never calls ``.ingest(`` directly -- only ``record`` below it
    # does, and only once the caller has already validated a produced
    # Explanation is worth keeping.
    assert ".ingest(" not in source


def test_tools_are_called_through_the_readonly_handle(with_officer, monkeypatch):
    """Defence in depth beyond the source scan: even a tool that reached for
    the workspace would find only what ``agents.ReadOnly`` allows, because
    that is the handle the loop actually calls it with."""
    from vinzor import ubo_explainer

    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)

    seen = {}
    original = TOOLS["lookup_company_uk"]

    def spy(handed_engine, **kwargs):
        seen["type"] = type(handed_engine).__name__
        return original.run(handed_engine, **kwargs)

    monkeypatch.setitem(
        ubo_explainer.TOOLS, "lookup_company_uk",
        ubo_explainer.Tool(name="lookup_company_uk", takes=original.takes,
                           does=original.does, run=spy, shown=original.shown))

    uk_client = CompaniesHouseClient(
        transport=uk_transport_for({"12345678": _uk_profile()}, psc={}))
    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "checking"},
        {"internal_explanation": "x" * 30, "external_explanation": "",
         "document_request": "y" * 20, "checks": []},
    )
    explain_ownership(engine, subject, case_id=case_id, transport=talk,
                      uk_client=uk_client, budget_usd=DEFAULT_BUDGET_USD)

    assert seen["type"] == "ReadOnly"


def test_an_end_to_end_run_writes_only_the_draft_it_produces(with_officer):
    """Behavioural, not just structural: run the whole agent and record its
    output, then check the log for exactly what changed."""
    engine = with_officer
    subject = _company_owned_by_an_unresolved_uk_parent(engine)
    case_id = _open_case(engine, subject)
    before_types = [str(e.event_type) for e in engine.log]

    uk_client = CompaniesHouseClient(
        transport=uk_transport_for({"12345678": _uk_profile()},
                                   {"12345678": _uk_psc()}))
    talk = scripted(
        {"tool": "lookup_company_uk", "arguments": {"company": "12345678"},
         "why": "checking Meridian Holdings Ltd"},
        {
            "internal_explanation": (
                "Silverline Capital Partners Ltd is wholly owned by "
                "Meridian Holdings Ltd, and the chain runs out there."),
            "external_explanation": (
                "The UK register names Priya Menon as a person with "
                "significant control of Meridian Holdings Ltd."),
            "document_request": (
                "Ask Silverline Capital Partners Ltd who ultimately "
                "controls Meridian Holdings Ltd."),
            "checks": [],
        },
    )
    explanation = explain_ownership(engine, subject, case_id=case_id,
                                    transport=talk, uk_client=uk_client,
                                    budget_usd=DEFAULT_BUDGET_USD)
    record(engine, explanation, prepared_at=WHEN2)

    after_types = [str(e.event_type) for e in engine.log]
    added = after_types[len(before_types):]
    assert added == ["DRAFT_PREPARED"]
    assert "OWNERSHIP_DECLARED" not in after_types[len(before_types):]
    assert not any(str(e.event_type) == "CASE_DECIDED" for e in engine.log)

    intact, why = engine.verify()
    assert intact, why

    case = engine.case(case_id)
    assert case.draft["recommendation"] == EXTERNAL_ADDS_A_NAME
    assert case.is_open  # drafting never settles anything


# ---------------------------------------------------------------------------
# The batch wrapper
# ---------------------------------------------------------------------------


def test_prepare_explanations_skips_a_case_already_explained(with_officer):
    engine = with_officer
    subject = _trust_missing_its_trustee(engine)
    case_id = _open_case(engine, subject)

    talk = scripted({
        "internal_explanation": (
            "Meridian Family Trust has not named an author or a trustee."),
        "external_explanation": "No external register was checked.",
        "document_request": "Ask for the trust deed.",
        "checks": [],
    })
    written = prepare_explanations(engine, prepared_at=WHEN2, transport=talk)
    assert len(written) == 1
    assert case_id in already_explained(engine)

    # A second pass, with a transport that must not be called, proves the
    # Case is skipped rather than redrafted.
    def must_not_be_called(_messages):
        raise AssertionError("a case that already has a draft was redrafted")

    written_again = prepare_explanations(engine, prepared_at=WHEN2,
                                         transport=must_not_be_called)
    assert written_again == []

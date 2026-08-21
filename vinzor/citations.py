"""The regulatory clauses this system enforces.

Every policy cites the clause it implements, so a Case can answer *"says who?"*
with a document, a clause number, a page, and the operative sentence — not with
a paraphrase someone wrote into a docstring.

Three rules for this file:

1. **Only clauses that are actually enforced appear here.** A register of every
   regulation IFSCA has ever issued is a research artefact, not a control.

2. **Extracts are short and verbatim**, kept to the operative sentence, with a
   link to the source. Enough to show a compliance officer why the system did
   what it did; not a reproduction of the Guidelines.

3. **Nothing is marked verified until a human verifies it.** Every clause below
   was extracted by machine from a PDF. ``verified=False`` is not a formality:
   until a qualified person signs a clause off, the system says so, in the
   Case, out loud. A compliance product that overstates the provenance of its
   own rules is worse than one that has none.

To verify a clause: read it in the source PDF at the cited page, and if the
extract and reading are right, flip ``verified`` to ``True`` and add your
initials and the date to ``verified_by``.

**13 August 2026, no CA/CS available.** Every extract, heading and page below
was cross-checked against IFSCA's own published documents by hand -- fetched
fresh, read page by page, compared character by character where practical.
This found and fixed 12 real problems: four wrong page numbers, several
extracts that silently dropped a clause of the source sentence with no
ellipsis to mark it, one clause (4.2) that had quoted a sentence from the
wrong subsection entirely, one (10.1) whose extract did not appear in the
source at all and wrongly folded in a different clause's obligation, and one
document version tag (the FMR Regulations) that named a superseded edition.
All of it is recorded here, in each clause's own history.

**20 August 2026: the check became a test.** A copy of each document now
sits in ``docs/``, pinned by digest, and ``tests/test_rulebook_sources.py``
rematches every extract, page and heading against it on each build. Doing
it by machine found five more defects the hand reading had passed -- three
of punctuation, one list quoted in a shape the Regulations never printed,
and one claim about the headings that was simply the wrong way round. An
extract can no longer drift from its source in silence, which is what it
had been free to do for the week in between.

**This is not what ``verified=True`` means, and none of it was flipped.**
Confirming a quotation matches its source is not the same thing as a
qualified person confirming the rule is being applied correctly -- that a
compliance officer's intuition about a clause's purpose is right, that
nothing in it has been reinterpreted since, that the policy citing it is
citing the correct clause for what it actually checks. A CA or CS still needs
to do that. What changed is that the quotations they will be checking are now
accurate, and stay accurate, instead of being right on the day somebody read
them and unguarded ever after.
"""

from __future__ import annotations

import hashlib

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    regulator: str
    version: str
    url: str


@dataclass(frozen=True)
class Clause:
    clause_id: str
    doc_id: str
    heading: str
    #: The operative sentence, verbatim from the source.
    extract: str
    page: Optional[int] = None
    #: Amendment history that changed the substance of the rule.
    amended: Optional[str] = None
    verified: bool = False
    verified_by: Optional[str] = None
    #: When this extract was last matched, character for character, against the
    #: regulator's own PDF by machine. Deliberately not ``verified``: a string
    #: comparison proves the words were copied faithfully, and proves nothing
    #: at all about whether the right clause was chosen or read correctly. Only
    #: a qualified person can say that, and until one does ``verified`` stays
    #: False and every Case citing the clause says so.
    source_checked: Optional[str] = None

    @property
    def ref(self) -> str:
        return f"{self.doc_id} {self.clause_id}"

    def cite(self) -> dict[str, object]:
        """The citation as it is attached to Evidence."""
        document = DOCUMENTS[self.doc_id]
        return {
            "ref": self.ref,
            "document": document.title,
            "version": document.version,
            "clause": self.clause_id,
            "heading": self.heading,
            "extract": self.extract,
            "page": self.page,
            "amended": self.amended,
            "url": document.url,
            "verified": self.verified,
            "source_checked": self.source_checked,
        }


IFSCA_AML = Document(
    doc_id="IFSCA-AML-2022",
    title=(
        "IFSCA (Anti Money Laundering, Counter-Terrorist Financing and "
        "Know Your Customer) Guidelines, 2022"
    ),
    regulator="IFSCA",
    version="updated as on August 03, 2026",
    url=(
        "https://ifsca.gov.in/CommonDirect/DownloadFile"
        "?id=29709e474fe6b066fc0cb19f7db21df2"
        "&fileName=Master_Guidelines_as_on_03_Aug_2026_20260804_0158.pdf"
    ),
)

IFSCA_FMR = Document(
    doc_id="IFSCA-FMR-2025",
    title="IFSCA (Fund Management) Regulations, 2025",
    regulator="IFSCA",
    # "July 30, 2025" was the version this file was originally built against.
    # IFSCA's own legal index no longer publishes that version at all -- the
    # only one available now is this one, which itself incorporates a further
    # amendment (see 7(5)'s ``amended`` note below).
    version="as amended up to January 30, 2026",
    url="https://ifsca.gov.in/Legal/Index?MId=vsIDVTDhEds%3D",
)

DOCUMENTS: Mapping[str, Document] = {
    IFSCA_AML.doc_id: IFSCA_AML,
    IFSCA_FMR.doc_id: IFSCA_FMR,
}

#: A later circular exists that this register does not yet reflect. Recorded
#: rather than ignored, so the gap is visible instead of silent.
#: Amendments to the Guidelines, and whether the text above already reflects
#: them. Recorded rather than assumed: the register was two circulars behind
#: and did not know it, and the one circular it did know about was recorded
#: against the wrong clauses.
KNOWN_PENDING_AMENDMENTS = (
    {
        "doc_id": "IFSCA-AML-2022",
        "circular_date": "2026-02-26",
        "summary": (
            "Adds OTP-based Aadhaar e-KYC authentication to the permitted "
            "methods of customer verification."
        ),
        # Annexure II, Part A, clause 1.2.2(viii)(e). None of the clauses this
        # system enforces sits in Annexure II.
        "affects": (),
        "incorporated": True,
    },
    {
        "doc_id": "IFSCA-AML-2022",
        "circular_date": "2026-08-03",
        "summary": (
            "References Rule 8 alongside Rule 7 of the PML (Maintenance of "
            "Records) Rules, 2005; requires all reports to be filed at the "
            "FINgate 2.0 portal; adds Cross Border Wire Transfer Reports to "
            "the reports a Regulated Entity files; and replaces the list of "
            "countries from which a Non-Resident Indian may be onboarded "
            "through video verification."
        ),
        # Clause 10.3 and its Guidance Note, plus clauses 1.2.1 and 1.2.3 of
        # Annexure II Part A. The register previously recorded this against
        # 10.1 and 11.1, which the circular does not touch. This system holds
        # 10.1 and 10.2 but not 10.3, so no clause here changed.
        "affects": (),
        "incorporated": True,
    },
)


#: The day every extract below was matched against the regulator's published
#: PDF, word for word. See SOURCE_CHECK_NOTE.
SOURCE_CHECKED_ON = "2026-08-20"

SOURCE_CHECK_NOTE = (
    "Every clause here is compared against the regulator's own published "
    "document -- the AML Guidelines as updated on 3 August 2026, 73 pages, "
    "and the Fund Management Regulations as amended to 30 January 2026, "
    "102 pages. A copy of each is kept beside this register and pinned by "
    "digest, and the comparison is made afresh every time the tests run, so "
    "neither an extract nor a page number can drift from its source without "
    "the drift showing. That establishes only that the words were copied "
    "faithfully and the pages point where they say. It does not establish "
    "that the right clause was chosen, or that it means what this system "
    "takes it to mean. Both remain for a qualified person."
)


@dataclass(frozen=True)
class Source:
    """The exact copy of a document this register can be checked against.

    Held by digest rather than by name because IFSCA does not version its
    filenames. When a circular lands the Authority republishes a
    consolidated master at the same address, and every page number in this
    file silently starts pointing at the wrong page -- the failure mode that
    moved all four beneficial-ownership clauses from page 4 to page 5 with
    nothing to announce it. A digest turns that from a discovery into a
    test failure.
    """

    filename: str
    pages: int
    digest: str

    @property
    def path(self):
        from pathlib import Path
        return Path(__file__).resolve().parent.parent / "docs" / self.filename


#: The documents a copy is kept of. A document absent from here is not
#: unimportant -- it is unchecked, and every clause citing it says so.
SOURCES: Mapping[str, Source] = {
    IFSCA_AML.doc_id: Source(
        filename="ifsca-aml-guidelines-master-2026-08-03.pdf",
        pages=73,
        digest="932d53d34afd38bb911a5785cec90b0599bf114"
               "14f34561f12863985e98285db",
    ),
    IFSCA_FMR.doc_id: Source(
        filename="ifsca-fund-management-regulations-2026-01-30.pdf",
        pages=102,
        digest="a13be299bf809468967bb36e9fabaaa59592610"
               "e5a1b8717f3d2ef26701bcad7",
    ),
}


def held(doc_id: str) -> Optional[Source]:
    """The copy of a document kept for checking, if there is one."""
    return SOURCES.get(doc_id)


#: Clauses whose heading is this register's description of what the clause
#: says, rather than a caption the document itself prints. Everything not
#: named here is IFSCA's own wording and a test holds it to that -- a
#: heading presented as the regulator's when it is not is the same defect
#: as an extract presented as verbatim when it is not, and harder to spot
#: because a heading is short enough to look obviously right.
EDITORIAL_HEADINGS = frozenset({
    # The Guidelines caption 1.3.3 once, as "Beneficial Owner". These four
    # say which customer type each limb is about, which the document
    # conveys by its (a) to (d) lettering and not in words.
    "1.3.3(a)", "1.3.3(b)", "1.3.3(c)", "1.3.3(d)",
    # The schedule is headed "NET WORTH REQUIREMENTS" and 107F "Net worth
    # requirement" -- neither says which of the several net-worth
    # provisions in this document it is, which is the one thing a reader
    # scanning the register needs.
    "Second Schedule", "107F",
    # The guidelines number this one and do not caption it. "Guidance Note
    # (4)" is what a reader would have to be told to find it; what it says
    # is what a reader needs to know it says.
    "5.5 Guidance Note (4)",
    # 5.5 is captioned once, as "Accounts of Politically Exposed Persons".
    # Its lettered limbs are not captioned at all, and the two registered
    # here are the ones the product enforces -- so what they need beside them
    # is which measure they are, not the heading of the clause they sit in.
    "5.5(b)(iii)", "5.5(b)(iv)",
})


def checkable() -> tuple:
    """Clause ids a stored copy of the document exists to check them against.

    These are rematched against that copy every time the tests run, so an
    extract cannot drift from its source without the drift showing.
    """
    return tuple(sorted(clause.clause_id for clause in CLAUSES.values()
                        if clause.doc_id in SOURCES))


def uncheckable() -> tuple:
    """Clause ids whose document no copy is kept of.

    Empty, and a test holds it empty. It was not always: for a week this
    register quoted nine clauses of the Fund Management Regulations with no
    copy of that document anywhere near it, which meant the rules on who a
    fund manager must appoint and what it must tell the Authority rested on
    one person having read them once. Keeping the function after the list
    emptied is the point -- it is what makes registering a document without
    a copy of it fail rather than pass quietly.
    """
    return tuple(sorted(clause.clause_id for clause in CLAUSES.values()
                        if clause.doc_id not in SOURCES))


def _c(clause_id: str, heading: str, extract: str, page: int | None = None,
       amended: str | None = None, doc_id: str = IFSCA_AML.doc_id) -> Clause:
    return Clause(
        clause_id=clause_id,
        doc_id=doc_id,
        heading=heading,
        extract=extract,
        page=page,
        amended=amended,
        source_checked=SOURCE_CHECKED_ON,
    )


def wording_digest(clause: Clause) -> str:
    """A fingerprint of exactly what a reviewer would be shown.

    Covers the extract, the document and the page, because "I checked this
    sentence" means nothing without which document and where. Change any of
    the three and an existing sign-off stops applying, which is the point.
    """
    body = f"{clause.doc_id}|{clause.clause_id}|{clause.page}|{clause.extract}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def verified_now(clause_id: str, verifications: Mapping[str, Any]):
    """The sign-off in force for a clause, or None.

    A sign-off recorded against wording that has since been corrected is not
    in force. Returning None rather than a stale signature is the whole reason
    the digest is stored: nobody signed the words now on the screen.
    """
    record = (verifications or {}).get(clause_id)
    clause = CLAUSES.get(clause_id)
    if record is None or clause is None:
        return None
    if record.get("wording") != wording_digest(clause):
        return None
    return record


def _register(clauses: Sequence[Clause]) -> Mapping[str, Clause]:
    """Index the clauses by id, refusing to lose one silently.

    A dict comprehension keeps the last of any duplicate. Clause ids are
    short and this register spans two documents, so a collision is a matter
    of time -- "5.1" is a plausible clause number in either. The failure it
    would cause is the worst kind available here: a Case citing the right
    number attached to the wrong document's text, on a permanent record,
    with nothing on screen to suggest anything was wrong.

    Failing at import is the correct severity. A missing citation stops a
    Case from opening (``UncitedFinding``); a *wrong* one is worse, because
    it looks like an answer.
    """
    register: dict[str, Clause] = {}
    for clause in clauses:
        existing = register.get(clause.clause_id)
        if existing is not None:
            raise ValueError(
                f"two clauses share the id {clause.clause_id!r}: "
                f"{existing.doc_id} and {clause.doc_id}. Clause ids index this "
                f"register, so one would silently replace the other and every "
                f"Case citing it would quote the wrong document."
            )
        register[clause.clause_id] = clause
    return register


CLAUSES: Mapping[str, Clause] = _register([
    c
    for c in (
        # -- beneficial ownership: the definition, by customer type ----------
        _c(
            "1.3.3(a)",
            "Beneficial Owner - company",
            "Where the customer is a company, the beneficial owner is the natural "
            "person(s), who, whether acting alone or together, or through one or "
            "more juridical persons, has a controlling ownership interest or who "
            "exercises control through other means. ... “Controlling ownership "
            "interest” means ownership of or entitlement to more than ten per "
            "cent. of the shares or capital or profits of the company;",
            page=5,
            amended="Ten per cent substituted for twenty-five per cent by "
                    "Circular dated May 23, 2023.",
        ),
        _c(
            "1.3.3(b)",
            "Beneficial Owner - partnership firm",
            "Where the customer is a partnership firm, the beneficial owner is the "
            "natural person(s), who, whether acting alone or together, or through "
            "one or more juridical person, has/have ownership of/entitlement to "
            "more than ten per cent. of capital or profits of the partnership or "
            "who exercises control through other means.",
            page=5,
            amended="Ten per cent substituted for fifteen per cent by Circular "
                    "dated September 8, 2023; “or who exercises control "
                    "through other means” was inserted by the same circular.",
        ),
        _c(
            "1.3.3(c)",
            "Beneficial Owner - unincorporated association, and the senior "
            "managing official fallback",
            "Where the customer is an unincorporated association or body of "
            "individuals, the beneficial owner is the natural person(s), who, "
            "whether acting alone or together, or through one or more juridical "
            "person, has/have ownership of or entitlement to more than fifteen "
            "per cent. of the property or capital or profits of the "
            "unincorporated association or body of individuals. ... Where no "
            "natural person is identified under (a) to (c) above, the "
            "beneficial owner is the relevant natural person who holds the "
            "position of senior managing official.",
            page=5,
        ),
        _c(
            "1.3.3(d)",
            "Beneficial Owner - trust",
            "Where the customer is a trust, the identification of beneficial "
            "owner(s) shall include identification of the author of the trust, the "
            "trustee, the beneficiaries with ten per cent. or more interest in the "
            "trust and any other natural person exercising ultimate effective "
            "control over the trust through a chain of control or ownership.",
            page=5,
            amended="Ten per cent substituted for fifteen per cent by Circular "
                    "dated May 23, 2023.",
        ),
        _c(
            "5.4.5",
            "Identification and Verification of Identity of Beneficial Owners",
            "Where there is one or more Beneficial Owners in relation to a "
            "customer, the Regulated Entity shall identify the Beneficial Owners "
            "and take reasonable measures to verify their identities using the "
            "relevant information or data obtained from reliable, independent "
            "sources.",
            page=26,
        ),
        # -- screening -------------------------------------------------------
        # -- what a firm must hold, and how often it must look again -------
        # These two arrived on 20 August 2026, and the reason they were
        # missing is worse than the fact of it. The product had been
        # telling officers what clause 5.4.2 requires on the dossier, in
        # the export, on the readiness screen and in the assistant's
        # answers -- in its own words, from ten different modules, with no
        # verified extract anywhere. That is exactly the paraphrase-in-a-
        # docstring this register was built to replace, and it sat beside
        # a register of clauses each checked against the PDF on every
        # build.
        _c(
            "5.4.2",
            "Identification of Customer",
            "If a customer is a natural person, a Regulated Entity shall obtain "
            "at least the following information: (i) Full name, including any "
            "aliases; ... (b) If a customer is a legal person or legal "
            "arrangement, a Regulated Entity shall obtain at least the following "
            "information: (i) The full name and any trading name; ... (c) "
            "Further, in cases where the customer is a legal person or legal "
            "arrangement, a Regulated Entity shall, also identify the legal "
            "form, constitution and powers that regulate and bind the legal "
            "person or legal arrangement.",
            page=22,
            amended="Limb (c) also requires a Regulated Entity to identify and "
                    "screen the connected parties of a legal person, and to "
                    "remain appraised of changes to them. The readiness check "
                    "measures limbs (a) and (b) only and says so; nothing in "
                    "this system reads a legal form, a constitution, or a list "
                    "of connected parties. Two qualifiers inside (a) and (b) "
                    "are also unmeasured: an address must not be a post office "
                    "box, and a trading name is asked for beside the full name.",
        ),
        _c(
            "5.11",
            "Periodic Updation",
            "A Regulated Entity shall adopt a risk-based approach for periodic "
            "updation of CDD. The periodicity of updation from the date of "
            "opening of the account / last CDD updation for different categories "
            "of customers is as follows: (i) Annually- for high-risk customers; "
            "(ii) once in three years- for medium risk customer; and (iii) once "
            "in every five years- for low-risk customers.",
            page=35,
            amended="A proviso on the same page sets a longer cycle -- two, "
                    "eight and ten years -- for a resident Indian customer who "
                    "already has a client relationship with the Financial Group "
                    "in India. It is longer, not shorter, so applying the "
                    "ordinary schedule to such a customer is early rather than "
                    "late. This system holds both and takes the shorter unless "
                    "the group relationship is recorded.",
        ),
        _c(
            "5.5 Guidance Note (4)",
            "A politically exposed person is not automatically high risk",
            "A Regulated Entity should not automatically treat all individuals "
            "who are PEPs, as a high-risk customer. Each PEP should be assessed "
            "on risk sensitive basis and the Regulated Entity shall determine "
            "what risk category is appropriate for such PEPs.",
            page=30,
            amended="Shown to an officer at the moment they categorise a party "
                    "who holds public office, which makes it one of the most "
                    "consequential sentences in the product and one of the "
                    "last to be registered. The system rendered it with a "
                    "hyphen the guidelines do not use -- risk-sensitive for "
                    "risk sensitive -- which is the whole of the difference "
                    "between the two.",
        ),
        _c(
            "5.9",
            "Ongoing sanctions screening",
            "A Regulated Entity shall review its customers, their business and "
            "transactions against United Nations Security Council sanctions lists "
            "and also against any other relevant sanctions list when complying "
            "with Clause 5.4.1 (d).",
            page=34,
        ),
        _c(
            "11.2",
            "Freezing of Assets under Section 51A of Unlawful Activities "
            "(Prevention) Act, 1967",
            "The procedure laid down in the UAPA Order bearing file "
            "no.14014/01/2019/CFT dated February 2, 2021, issued by the CTCR "
            "Division "
            "of the Ministry of Home Affairs, Government of India, shall be "
            "strictly followed and compliance with the Order shall be ensured.",
            page=56,
        ),
        _c(
            "5.5",
            "Accounts of Politically Exposed Persons",
            "A Regulated Entity shall implement appropriate internal risk "
            "management systems, policies and procedures to determine if a "
            "customer or any natural person appointed to act on behalf of the "
            "customer, or any beneficial owner of the customer is a politically "
            "exposed person (PEP) or in case of a life insurance or other similar "
            "policy, if a beneficiary of the policy, or a Beneficial Owner of a "
            "beneficiary, is a PEP.",
            page=29,
        ),
        # The one hard permission boundary in the product. ``cases.py`` names
        # 5.5(b)(iii) in an exception's docstring, ``engine.decide`` names it
        # in a refusal an officer reads on screen, and the fold names it
        # again -- and it was quoted nowhere a reader could check, because the
        # register held 5.5(a) under the bare id "5.5". A rule the product
        # enforces twice and cannot show the words of is a rule the firm
        # cannot defend to the person asking about it.
        _c(
            "5.5(b)(iii)",
            "Senior management approves a politically exposed person",
            "A Regulated Entity shall, in addition to undertaking CDD "
            "measures, undertake at least the following additional measures "
            "where a customer or any beneficial owner of the customer or "
            "beneficiary of a life insurance or other similar policy, or a "
            "beneficial owner of a beneficiary is determined by the Regulated "
            "Entity to be a PEP: ... (iii) obtain approval from its Senior "
            "Management before opening an account of a PEP or making any "
            "payout under the life insurance or other similar policy to the "
            "PEP;",
            page=29,
        ),
        _c(
            "5.5(b)(iv)",
            "And again when an existing customer becomes one",
            "(iv) in the event of an existing customer or the beneficial "
            "owner of an existing account subsequently becoming a PEP, obtain "
            "the Senior Management's approval to continue the business "
            "relationship;",
            page=29,
        ),
        _c(
            "5.6",
            "Enhanced Due Diligence",
            "Where the risks of ML/TF are high, a Regulated Entity shall conduct "
            "enhanced CDD measures, consistent with the risks identified.",
            page=31,
        ),
        _c(
            "4.2",
            "Factors that may indicate high ML/TF risk",
            # The extract this replaced quoted "(a) Customer risk ... (v) Whether
            # the countries or jurisdictions are subject to sanctions" as one
            # continuous passage. That sentence is real, but it is item (b)(v),
            # "Country or Geographic risk" -- grafted here under a label that
            # claims it is (a)(v), "Customer risk", which is a different item
            # about asset-holding vehicles. Neither subsection actually names
            # "adverse media": the document searched end to end has no clause
            # using that term. The honest citation for a policy that flags press
            # reporting about a customer is the chapeau obligation itself -- that
            # a risk-based assessment is required at all -- not an invented match
            # to a specific bullet the source does not make.
            "When assessing if there is a high risk of ML/TF in a particular "
            "situation, a Regulated Entity shall take into account, among other "
            "things:",
            page=16,
        ),
        # -- transactions and reporting --------------------------------------
        _c(
            "10.2",
            "Indications of Suspicious Transactions",
            "A Regulated Entity can identify suspicious transactions by following "
            "these four steps: (a) Detect a suspicious indicator(s); (b) Ask the "
            "customer questions; (c) Review customer’s records; and "
            "(d) Evaluate the above information.",
            page=50,
        ),
        # -- licence scope and governance ------------------------------------
        # Added after reading IFSCA's own enforcement orders: these are the
        # provisions entities actually lose their registration over.
        _c(
            "3(4)",
            # IFSCA's own wording, but it captions the whole of Regulation
            # 3 rather than sub-regulation (4) on its own -- as is true of
            # 7(1) to 7(5) and 8(1) below, which each carry their parent
            # regulation's heading. This file used to record the opposite,
            # that the label was an editorial description; a machine check
            # of every heading against the documents found it on page 5.
            "Obligation to seek registration",
            # The three categories are a lettered list, each with numbered
            # sub-clauses running over the page break onto page 6. This
            # quoted them as "Authorised FME; Registered FME (Non-Retail);
            # Registered FME (Retail)" -- a semicolon list that appears
            # nowhere in the document, presented as verbatim. The structure
            # below is the document's own, with the sub-clauses elided.
            "The applicant shall seek registration under any of the following "
            "three categories: (a) Authorised FME: ... (b) Registered FME "
            "(Non-Retail): ... (iii) Such FMEs shall also be able to undertake "
            "all activities as permitted to Authorised FMEs. (c) Registered "
            "FME (Retail): ...",
            page=5,
            doc_id="IFSCA-FMR-2025",
            amended="The closing sentence quoted here is (4)(b)(iii)'s, about a "
                    "Registered FME (Non-Retail). The parallel sentence under "
                    "(4)(c)(iii), for a Registered FME (Retail), reads "
                    "differently: it may also undertake everything an "
                    "Authorised FME or a Registered FME (Non-Retail) may.",
        ),
        _c(
            "137",
            "Restrictions on business activities of the FME",
            "The FME shall not undertake any business activities other than as "
            "specified under these regulations, without prior approval of the "
            "Authority:",
            page=79,
            doc_id="IFSCA-FMR-2025",
            amended="The regulation continues with two provisos, for FMEs "
                    "operating as a branch, not quoted here.",
        ),
        _c(
            "7(1)",
            "Appointment of Principal Officers and other Key managerial "
            "personnel(s) (KMP)",
            "The applicant shall designate a principal officer who shall be "
            "responsible for overall activities of the FME including but not "
            "limited to fund management, risk management and compliance.",
            page=7,
            doc_id="IFSCA-FMR-2025",
        ),
        _c(
            "7(2)",
            "Appointment of Principal Officers and other Key managerial "
            "personnel(s) (KMP)",
            "In case of Registered FME, in addition to the principal officer, "
            "one (1) additional KMP shall be designated as Compliance Officer "
            "who shall be responsible for compliance with these regulations and "
            "ensure implementation of risk management policies and practices at "
            "the FME.",
            page=8,
            doc_id="IFSCA-FMR-2025",
        ),
        _c(
            "7(3)",
            "Appointment of Principal Officers and other Key managerial "
            "personnel(s) (KMP)",
            "In case of Registered FME (Retail), the FME shall, in addition to "
            "the principal officer and compliance officer, appoint, before "
            "filing with the Authority the offer document of its first retail "
            "scheme or ETF, an additional KMP who shall be assigned with the "
            "responsibility of fund management.",
            page=8,
            doc_id="IFSCA-FMR-2025",
        ),
        _c(
            "7(4)",
            "Appointment of Principal Officers and other Key managerial "
            "personnel(s) (KMP)",
            "Any FME that is managing an AUM of at least USD 1 billion, "
            "excluding the AUM of fund of funds schemes, as at the close of a "
            "financial year shall, in addition to the principal officer and "
            "compliance officer, appoint an additional KMP, who shall be "
            "assigned with the responsibility of fund management. Provided that "
            "appointment of the additional KMP shall be made within 6 months "
            "from the end of such financial year.",
            page=8,
            doc_id="IFSCA-FMR-2025",
            amended="Two further provisos follow in the source, not modelled "
                    "here: the appointment may become optional again after 2 "
                    "consecutive financial years back below USD 1 billion with "
                    "no near-term expectation of crossing it again, and certain "
                    "government-related investors may be exempt from the "
                    "requirement altogether.",
        ),
        _c(
            "7(5)",
            "Appointment of Principal Officers and other Key managerial "
            "personnel(s) (KMP)",
            "The applicant shall ensure that the aforementioned principal "
            "officer as specified under sub-regulation (1) and other KMPs as "
            "specified under sub-regulations (2), (3) and (4), shall be based "
            "out of IFSC and meet the following educational qualification and "
            "experience requirements:",
            page=8,
            doc_id="IFSCA-FMR-2025",
            amended="The 2022 Regulations carried this requirement at "
                    "Regulation 7(4); IFSCA's order against Neo Asset "
                    "Management (2 May 2025) was made under that provision. "
                    "The experience-requirement sub-clause, 7(5)(b), was "
                    "substituted by the IFSCA (Fund Management) (Amendment) "
                    "Regulations, 2026, with effect from 30 January 2026. The "
                    "consolidation checked here carries that substitution, on "
                    "page 9: five years in related activities in an eligible "
                    "institution, three for the compliance officer if "
                    "professionally qualified. Only the location limb of this "
                    "clause is enforced -- nothing in this system reads a "
                    "KMP's qualifications or counts their years.",
        ),
        _c(
            "10(1)",
            "Infrastructure Requirements",
            "The entity has the necessary infrastructure like adequate office "
            "space, equipment, communication facilities and manpower to "
            "effectively discharge its activities under these regulations and "
            "circulars issued thereunder. The infrastructure requirements should "
            "be commensurate to the size of its operations in IFSC.",
            page=11,
            doc_id="IFSCA-FMR-2025",
        ),
        # -- what the firm must be worth ------------------------------------
        # These three arrived on 20 August 2026, when a copy of the Fund
        # Management Regulations was finally kept beside this register. Until
        # then ``capital.py`` carried the same three figures read out of two
        # law-firm summaries, and said so on every screen that used one --
        # because on this regulator, secondary sources had been measured and
        # found wanting. The summaries turn out to have been right. What
        # changed is that a firm being told it is short of capital can now be
        # shown the schedule that says so.
        _c(
            "8(1)",
            "Net worth requirements",
            "An entity seeking registration as a FME shall at all times comply "
            "with the net worth requirements as specified in Second Schedule of "
            "these regulations or such other amount as may be specified by the "
            "Authority.",
            page=10,
            doc_id="IFSCA-FMR-2025",
            amended="Sub-regulation (2) lets a branch hold its net worth at its "
                    "parent, and (3) makes this minimum separate from and in "
                    "addition to the minimum for any other activity the firm "
                    "carries on inside or outside the IFSC. Neither is modelled: "
                    "this system knows nothing about a firm's other activities, "
                    "so its figure is a floor and never a total.",
        ),
        _c(
            "Second Schedule",
            "Net worth requirements by registration category",
            "SECOND SCHEDULE NET WORTH REQUIREMENTS S. No. Category Net Worth "
            "1 Authorised FME USD 75,000 2 Registered FME (Non-retail) "
            "USD 5,00,000 3 Registered FME (Retail) USD 1,000,000",
            page=89,
            doc_id="IFSCA-FMR-2025",
            amended="Five hundred thousand is written USD 5,00,000 in the "
                    "schedule, which is the Indian grouping of digits and not a "
                    "misprint of fifty thousand.",
        ),
        _c(
            "107F",
            "Net worth requirement for third-party fund management",
            "A FME seeking authorisation to offer third-party fund management "
            "services shall, at all times, maintain an additional net worth of "
            "USD 500,000 or such other amount as may be specified by the "
            "Authority; Explanation. ... Such net worth shall be separate and in "
            "addition to: (i) the minimum net worth requirements applicable for "
            "its activities as a FME",
            page=68,
            doc_id="IFSCA-FMR-2025",
            amended="The requirement attaches to seeking the authorisation, not "
                    "to doing the business. This system reads what a firm has "
                    "been recorded as doing instead, because that is what it "
                    "observes, so a firm authorised for third-party management "
                    "that has not begun is not caught here.",
        ),
        _c(
            "120",
            "Information to the Authority",
            "The FME, fiduciaries or any person involved in the activities as detailed in these regulations shall accurately and timely furnish such reports, returns, statements and particulars, in such manner, interval and form, as may be specified by the Authority from time to time.",
            page=75,
            doc_id="IFSCA-FMR-2025",
            amended="Frequency set by circular of 31 May 2023, changed from half-yearly to quarterly on 3 November 2023; formats revised 3 April 2025. Returns are due within 21 calendar days of the quarter end. The circular history here has not itself been re-checked against a primary source -- only the Regulations text above has.",
        ),
        _c(
            "10.1",
            "Internal reporting requirements",
            # Not cited by any policy today -- kept correct for whenever one
            # does, per the file's own rule that only enforced clauses belong
            # here. It previously quoted a paraphrase that does not appear in
            # the source, and wrongly folded in FIU-IND reporting, which is a
            # separate provision (10.3) not registered in this file at all.
            "... A Regulated Entity shall put in place such policies, "
            "procedures, systems and controls which ensure that whenever any "
            "of its employee, acting in the ordinary course of his "
            "employment, either: (i) knows; (ii) suspects; or (iii) has "
            "reasonable grounds for knowing or suspecting that a person is "
            "engaged in or attempting ML/TF, that employee promptly notifies "
            "the Principal Officer of the Regulated Entity with all relevant "
            "details.",
            page=50,
            amended="Reporting the same suspicion onward to FIU-IND is "
                    "Clause 10.3, not this one, and is not currently "
                    "registered here or checked by any policy.",
        ),
    )
])


def clause(clause_id: str) -> Clause:
    try:
        return CLAUSES[clause_id]
    except KeyError:
        raise KeyError(
            f"no registered clause {clause_id!r}; "
            f"known: {sorted(CLAUSES)}"
        ) from None


def cite(*clause_ids: str) -> tuple[dict[str, object], ...]:
    """Citations for attachment to a Finding."""
    return tuple(clause(cid).cite() for cid in clause_ids)


def coverage(verifications: Optional[Mapping[str, Any]] = None) -> dict[str, object]:
    """What this register knows, and what it admits it does not.

    Confirmation is counted from the workspace, not from the register: no
    clause ships signed, and who signed what is a fact about this firm rather
    than a property of the software.
    """
    signed = sum(1 for cid in CLAUSES if verified_now(cid, verifications or {}))
    return {
        "documents": len(DOCUMENTS),
        "clauses": len(CLAUSES),
        "verified": signed,
        "unverified": len(CLAUSES) - signed,
        "pending_amendments": [
            a for a in KNOWN_PENDING_AMENDMENTS if not a["incorporated"]
        ],
    }

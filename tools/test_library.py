"""A library of synthetic applicants, sound and unsound, to test against.

    python tools/test_library.py            # writes examples/library/

``demo_pack.py`` writes one clean document of each kind, which proves the
happy path and nothing else. A compliance product is not interesting when the
papers agree; it is interesting when they do not, and none of those cases
could be demonstrated or regression-tested because no file existed that had
anything wrong with it.

So this writes the same synthetic people again with **deliberate faults**, one
folder per fault, each with a note saying what the product is supposed to
notice and -- where it does not -- that it does not. That second half matters
more than the first. A test library that only contains cases the system
handles is a library that measures nothing, and the point of building this
before a demonstration is to know which questions have good answers.

**Why not DocXPand or SynthIDGenerator.** Both were looked at. DocXPand's
generator is MIT and produces far better-looking identity documents than these,
but it pins ``python = ">=3.9,<3.11"`` and pulls ``torch``, ``tensorflow-cpu``,
``deepface``, ``selenium`` and ``tesserocr`` -- several gigabytes and a headless
browser to draw one card -- and its 25,000-image dataset is CC BY-NC-SA, which
is a licence that has no business anywhere near a commercial compliance
product. The photographic path is covered instead by Sumsub's own published
KYC samples, which are real photographs of the kind a customer actually sends.
What is missing from all three is *documents that disagree with each other*,
and that is what this generates.

Every document is marked SPECIMEN on its face and every identifier is drawn
from a range no authority issues, exactly as ``demo_pack.py`` does and for the
same reason: a synthetic KYC document that does not announce itself is a
forgery waiting to be mistaken for one.

No dependency, because ``demo_pack.py`` already writes PDF by hand and this
borrows its writer.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from demo_pack import document                      # noqa: E402

LIBRARY = HERE.parent / "examples" / "library"


class Case:
    """One applicant, and what the product ought to make of them."""

    def __init__(self, folder, party, kind, tests, expect, caught,
                 papers, note=""):
        self.folder = folder
        self.party = party
        self.kind = kind
        self.tests = tests
        self.expect = expect
        #: True where the product notices this today. False is not a bug to
        #: be hidden -- it is the answer to "what is not finished", and a
        #: library that quietly omitted these would be measuring nothing.
        self.caught = caught
        self.papers = papers
        self.note = note


CASES = [
    Case(
        "01-clean-person", "Anand Bhat", "Person",
        "The happy path: every paper agrees with the record and with itself.",
        "Identification complete. Documents satisfied. Nothing outstanding "
        "that a person has to chase.",
        caught=True,
        papers={
            "passport-bhat.pdf": document(
                "Republic of India - Passport", "MINISTRY OF EXTERNAL AFFAIRS",
                [("Surname", "BHAT"), ("Given name", "ANAND"),
                 ("Nationality", "INDIAN"),
                 ("Date of birth", "14/03/1981"),
                 ("Passport number", "Z9999999"),
                 ("Date of expiry", "22/07/2032")],
                "Specimen. Z9999999 is not an issued passport number."),
            "pan-bhat.pdf": document(
                "Permanent Account Number Card", "INCOME TAX DEPARTMENT",
                [("Name", "ANAND BHAT"), ("Date of birth", "14/03/1981"),
                 ("Permanent account number", "ZZZPB0000Z")],
                "Specimen. ZZZ is not an allotted PAN series."),
            "utility-bhat.pdf": document(
                "Electricity bill - proof of address", "ADANI ELECTRICITY (SPECIMEN)",
                [("Billed to", "ANAND BHAT"),
                 ("Service address", "12 Marine Lines, Mumbai 400020"),
                 ("Bill date", "02/07/2026")],
                "Specimen. Dated within two months."),
        }),

    Case(
        "02-missing-information", "Kavita Nair", "Person",
        "An applicant who has handed over one document and nothing else.",
        "The outstanding list names what is still owed, why each is owed, and "
        "the clause it comes from. Identification reports the specific "
        "details still missing rather than a score.",
        caught=True,
        papers={
            "passport-nair.pdf": document(
                "Republic of India - Passport", "MINISTRY OF EXTERNAL AFFAIRS",
                [("Surname", "NAIR"), ("Given name", "KAVITA"),
                 ("Nationality", "INDIAN"),
                 ("Date of birth", "09/11/1987"),
                 ("Passport number", "Z9999001"),
                 ("Date of expiry", "14/01/2031")],
                "Specimen. No proof of address and no PAN accompany this."),
        },
        note="Upload only the passport. The interesting screen is the one "
             "listing what is still missing."),

    Case(
        "03-expired-document", "Rakesh Iyer", "Person",
        "A passport that expired before the day it was filed.",
        "Clause 1.3.30 wants an officially valid document, and a document "
        "past its expiry is not one. The reader takes the expiry date off "
        "the page and says the document is no longer valid, naming the date "
        "and the clause. It is still filed and still read -- what a firm "
        "holds is a fact about the firm.",
        caught=True,
        papers={
            "passport-iyer-EXPIRED.pdf": document(
                "Republic of India - Passport", "MINISTRY OF EXTERNAL AFFAIRS",
                [("Surname", "IYER"), ("Given name", "RAKESH"),
                 ("Nationality", "INDIAN"),
                 ("Date of birth", "02/06/1975"),
                 ("Passport number", "Z9999002"),
                 ("Date of expiry", "11/02/2021")],
                "Specimen. Deliberately expired: 11 February 2021."),
        },
        note="This case was written as a known gap and closed the same "
             "afternoon: the product read every other line of a passport and "
             "said nothing about the expiry, so an out-of-date passport "
             "satisfied a document requirement exactly as a current one "
             "did. The date is compared against the day the document was "
             "filed, which is passed in -- nothing under vinzor/ reads a "
             "clock."),

    Case(
        "04-inconsistent-dob", "Priya Hussain (per_0001, already on the book)",
        "Person",
        "A passport whose date of birth, nationality and document number all "
        "disagree with what the firm already holds on an existing party.",
        "Three fields come back marked as disagreeing, each printed beside "
        "what the record says. Nothing is overwritten and nothing is chosen: "
        "one of the two is wrong and a person decides which.",
        caught=True,
        papers={
            "passport-hussain-CONFLICTS.pdf": document(
                "Republic of Singapore - Passport", "IMMIGRATION AUTHORITY",
                [("Surname", "HUSSAIN"), ("Given name", "PRIYA"),
                 ("Nationality", "BRITISH"),
                 ("Date of birth", "06/11/1968"),
                 ("Passport number", "Z9999004"),
                 ("Date of expiry", "03/05/2030")],
                "Specimen. The record says 6 November 1972, Singaporean, "
                "document PER_00018077. All three are different here."),
        },
        note="ONBOARD NOTHING. Open the EXISTING party per_0001 (Priya "
             "Hussain) and file this passport against her, because the "
             "disagreement is only visible where the firm already holds a "
             "value to disagree with. "
             "  A party created fresh on stage has nothing on the record but "
             "a name, so only a name can disagree -- which is what case 05 "
             "shows. There is no way to confirm a proposed field onto the "
             "record yet: attributes are written once, when a party is "
             "registered, and nothing updates them afterwards. So the "
             "reader proposes and the screen shows the proposal, but the "
             "'and a person confirms' half of that sentence is not built. "
             "Say so if asked; it is the honest state."),

    Case(
        "05-name-mismatch", "Priya Menon", "Person",
        "A proof of address in a different name from the identity document.",
        "The address document proposes a name that disagrees with the "
        "record, which is the ordinary shape of an address borrowed from a "
        "relative -- and also the ordinary shape of a mule account.",
        caught=True,
        papers={
            "passport-menon.pdf": document(
                "Republic of India - Passport", "MINISTRY OF EXTERNAL AFFAIRS",
                [("Surname", "MENON"), ("Given name", "PRIYA"),
                 ("Nationality", "INDIAN"),
                 ("Date of birth", "21/08/1990"),
                 ("Passport number", "Z9999003")],
                "Specimen."),
            "utility-DIFFERENT-NAME.pdf": document(
                "Electricity bill - proof of address", "TATA POWER (SPECIMEN)",
                [("Billed to", "SURESH MENON"),
                 ("Service address", "44 Hill Road, Bandra, Mumbai 400050"),
                 ("Bill date", "12/07/2026")],
                "Specimen. The bill is in a different person's name."),
        }),

    Case(
        "06-altered-document", "Vikram Shetty", "Person",
        "A document whose printed details do not agree with each other: the "
        "date of birth in the body is not the date encoded in the number.",
        "Nothing. This is the honest gap.",
        caught=False,
        papers={
            "pan-shetty-ALTERED.pdf": document(
                "Permanent Account Number Card", "INCOME TAX DEPARTMENT",
                [("Name", "VIKRAM SHETTY"),
                 ("Date of birth", "30/02/1988"),
                 ("Permanent account number", "ZZZ0000000"),
                 ("Issued", "31/13/2019")],
                "Specimen. Deliberately impossible dates: 30 February and a "
                "thirteenth month."),
        },
        note="NOT CAUGHT AS TAMPERING. The product has no authenticity, "
             "integrity or template-conformity checking of any kind -- it "
             "reads what a document says and never asks whether the document "
             "is genuine. The impossible dates here are simply refused as "
             "dates, so the fields come back missing rather than wrong, "
             "which is the right failure but for the wrong reason. This is "
             "a real and large gap and is worth naming out loud."),

    Case(
        "07-ubo-mismatch", "Meridian Holdings Private Limited", "Company",
        "A beneficial ownership declaration that does not add up, on a "
        "company whose declared owner is another company.",
        "Ownership resolves to a company rather than a person and reports "
        "that beneficial ownership is not established. The declaration "
        "naming 62% is not taken as an answer, because clause 1.3.3 is about "
        "natural people and a structure that stops at another company has "
        "not been resolved.",
        caught=True,
        papers={
            "incorporation-meridian.pdf": document(
                "Certificate of Incorporation", "REGISTRAR OF COMPANIES",
                [("Company", "MERIDIAN HOLDINGS PRIVATE LIMITED"),
                 ("Corporate identity number", "U00000MH2020PTC000001"),
                 ("Date of incorporation", "17/09/2020"),
                 ("Registered office", "8 Worli Sea Face, Mumbai 400018"),
                 ("Country of incorporation", "INDIA")],
                "Specimen."),
            "ubo-meridian-STOPS-AT-A-COMPANY.pdf": document(
                "Declaration of beneficial ownership", "MERIDIAN HOLDINGS",
                [("Declared for", "MERIDIAN HOLDINGS PRIVATE LIMITED"),
                 ("Beneficial owner", "CASTLE ROCK VENTURES LIMITED"),
                 ("Holding", "62.0%"),
                 ("Country", "MAURITIUS"),
                 ("Test applied", "More than 10% - IFSCA clause 1.3.3(a)")],
                "Specimen. The named owner is a company, not a person, so "
                "this declaration resolves nothing."),
        }),

    Case(
        "08-high-risk-person", "Vladimir Putin", "Person",
        "A party who is genuinely on the watchlists.",
        "Sanctions matched, politically exposed matched, adverse media "
        "returns live articles. The file cannot be settled by an AML "
        "officer: clause 5.5(b)(iii) reserves that to senior management.",
        caught=True,
        papers={},
        note="No document needed. Onboard the name and run the checks. This "
             "is the fifteen-second moment -- four million watchlist "
             "entities, on our own machine, nothing leaving the building."),
]


def main() -> int:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    written = 0
    lines = ["# The test library", "",
             "One folder per applicant. Each says what it is testing and "
             "whether the product notices.", ""]
    for case in CASES:
        folder = LIBRARY / case.folder
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in case.papers.items():
            (folder / name).write_bytes(data)
            written += 1
        note = [
            f"{case.folder}",
            "=" * len(case.folder),
            "",
            f"Party:  {case.party}   ({case.kind})",
            "",
            "WHAT THIS TESTS",
            f"  {case.tests}",
            "",
            "WHAT SHOULD HAPPEN",
            f"  {case.expect}",
            "",
            ("DOES IT?  yes" if case.caught else "DOES IT?  NO - see below"),
        ]
        if case.note:
            note += ["", "NOTE", "  " + case.note]
        if case.papers:
            note += ["", "UPLOAD"] + [f"  {n}" for n in sorted(case.papers)]
        else:
            note += ["", "UPLOAD", "  nothing - onboard the name alone"]
        (folder / "WHAT-THIS-TESTS.txt").write_text(
            "\n".join(note) + "\n", encoding="utf-8")
        lines.append(
            f"- **{case.folder}** — {case.tests} "
            f"{'' if case.caught else '**Not caught today.**'}")

    (LIBRARY / "README.md").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")
    caught = sum(1 for c in CASES if c.caught)
    print()
    print(f"  {len(CASES)} applicants, {written} documents, in {LIBRARY}")
    print()
    for case in CASES:
        mark = "  ok " if case.caught else "  GAP"
        print(f"{mark}  {case.folder:<26} {case.party}")
    print()
    print(f"  {caught} of {len(CASES)} are caught by the product today.")
    print("  The other two are named on their own folders rather than left")
    print("  out, because a library that only holds cases we pass measures")
    print("  nothing.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

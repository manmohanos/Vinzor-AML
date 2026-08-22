"""A pack of documents to onboard with, so the flow can be shown.

    python tools/demo_pack.py            # writes examples/pack/

The document step is the middle of an onboarding and it could not be
demonstrated: showing it needs a passport and a PAN card, and nobody has a
real investor's papers to hand. Three tiny placeholder PDFs existed; this
writes a full pack for every customer type the product accepts.

**Every one is invented and says so on its face.** A synthetic KYC document
that does not announce itself is a forgery waiting to be mistaken for one, so
each carries a banner across the top — SPECIMEN. NOT A REAL DOCUMENT. — and
the identifiers are drawn from ranges the issuing authorities do not use. The
names are the same invented parties as the generated dataset, so the pack and
the book agree with each other.

No dependency, because the core has none and a tool that needed one to draw a
box would be the first. PDF is a simple enough format to write by hand for
this: a catalogue, a page tree, one page per document, and a content stream
of positioned text. The reader in ``vinzor/pdftext.py`` was written the same
way and for the same reason.
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PACK = HERE / "examples" / "pack"

#: Points. A4 is the paper every Indian authority issues on.
WIDTH, HEIGHT = 595, 842


def _escape(text: str) -> str:
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))


def _stream(lines) -> bytes:
    """A page's content: positioned, sized text and a rule or two."""
    out = []
    for item in lines:
        if item[0] == "text":
            _, x, y, size, font, text = item
            out.append(
                "BT /%s %d Tf 1 0 0 1 %d %d Tm (%s) Tj ET"
                % (font, size, x, y, _escape(text)))
        elif item[0] == "rule":
            _, x1, y1, x2, thickness = item
            out.append("%.1f w %d %d m %d %d l S" % (thickness, x1, y1, x2, y1))
        elif item[0] == "box":
            _, x, y, w, h = item
            out.append("0.6 w %d %d %d %d re S" % (x, y, w, h))
    return "\n".join(out).encode("latin-1", "replace")


def _pdf(lines) -> bytes:
    """One page, two fonts, deflated. Enough PDF to be a real PDF.

    Written out object by object with a real cross-reference table, because a
    file that only *looks* like a PDF to a magic-number check is exactly the
    thing documents.py refuses at the door -- and being refused by our own
    intake would make this pack useless.
    """
    content = zlib.compress(_stream(lines))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
         "/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> "
         "/Contents 4 0 R >>" % (WIDTH, HEIGHT)).encode(),
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content)
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, start))
    return bytes(out)


def document(title: str, issuer: str, rows, footer: str = "") -> bytes:
    """One specimen document, laid out like the thing it stands in for."""
    lines = [
        # The banner, first and unmissable. A synthetic KYC document that does
        # not announce itself is a forgery waiting to be mistaken for one.
        ("box", 40, HEIGHT - 92, WIDTH - 80, 44),
        ("text", 52, HEIGHT - 66, 13, "F2",
         "SPECIMEN - NOT A REAL DOCUMENT"),
        ("text", 52, HEIGHT - 84, 8, "F1",
         "Invented for demonstrating Vinzor. Identifiers are outside the "
         "ranges the issuing authorities use."),
        ("text", 52, HEIGHT - 140, 17, "F2", issuer),
        ("text", 52, HEIGHT - 162, 12, "F1", title),
        ("rule", 52, HEIGHT - 174, WIDTH - 52, 1.2),
    ]
    y = HEIGHT - 210
    for label, value in rows:
        lines.append(("text", 52, y, 9, "F1", label.upper()))
        lines.append(("text", 210, y, 11, "F2", value))
        y -= 30
    if footer:
        lines.append(("rule", 52, 110, WIDTH - 52, 0.8))
        lines.append(("text", 52, 92, 8, "F1", footer))
    return _pdf(lines)


#: The pack. Names match the generated dataset so the papers and the book
#: agree with each other; identifiers are deliberately impossible.
PACK_FILES = {
    # -- a natural person ---------------------------------------------------
    "pan-bhat.pdf": document(
        "Permanent Account Number Card", "INCOME TAX DEPARTMENT",
        [("Name", "ANAND BHAT"),
         ("Father's name", "RAMESH BHAT"),
         ("Date of birth", "14/03/1981"),
         ("Permanent account number", "ZZZPB0000Z")],
        "Specimen. ZZZ is not an allotted PAN series."),
    "passport-bhat.pdf": document(
        "Republic of India - Passport", "MINISTRY OF EXTERNAL AFFAIRS",
        [("Surname", "BHAT"),
         ("Given name", "ANAND"),
         ("Nationality", "INDIAN"),
         ("Date of birth", "14/03/1981"),
         ("Place of birth", "MUMBAI, MAHARASHTRA"),
         ("Passport number", "Z9999999"),
         ("Date of expiry", "22/07/2032")],
        "Specimen. Z9999999 is not an issued passport number."),
    "aadhaar-bhat.pdf": document(
        "Aadhaar - Proof of possession", "UNIQUE IDENTIFICATION AUTHORITY",
        [("Name", "ANAND BHAT"),
         ("Date of birth", "14/03/1981"),
         ("Address", "12 Marine Lines, Mumbai 400020"),
         ("Aadhaar number", "XXXX XXXX 0000")],
        "Specimen. The number is masked, as the Guidelines require."),
    "utility-bhat.pdf": document(
        "Electricity bill - proof of address", "ADANI ELECTRICITY (SPECIMEN)",
        [("Billed to", "ANAND BHAT"),
         ("Service address", "12 Marine Lines, Mumbai 400020"),
         ("Bill date", "02/07/2026"),
         ("Consumer number", "SPEC-0000-0000"),
         ("Amount due", "INR 4,180.00")],
        "Specimen. Dated within two months, as a deemed proof of address "
        "must be."),
    "bank-bhat.pdf": document(
        "Statement of account", "STATE BANK (SPECIMEN BRANCH)",
        [("Account holder", "ANAND BHAT"),
         ("Address on file", "12 Marine Lines, Mumbai 400020"),
         ("Account number", "0000 0000 0000"),
         ("Period", "01/05/2026 to 31/07/2026"),
         ("Closing balance", "INR 92,40,118.22"),
         ("Credits in period", "INR 1,10,00,000.00 (sale of property)")],
        "Specimen. Offered as evidence of the source of funds."),

    # -- a company ----------------------------------------------------------
    "incorporation-orion.pdf": document(
        "Certificate of Incorporation", "REGISTRAR OF COMPANIES",
        [("Company", "ORION ZENITH ENTERPRISES PRIVATE LIMITED"),
         ("Corporate identity number", "U00000MH2019PTC000000"),
         ("Date of incorporation", "09/04/2019"),
         ("Registered office", "402 Nariman Point, Mumbai 400021"),
         ("Country of incorporation", "INDIA")],
        "Specimen. The identity number is not an allotted CIN."),
    "moa-orion.pdf": document(
        "Memorandum and Articles of Association", "ORION ZENITH ENTERPRISES",
        [("Company", "ORION ZENITH ENTERPRISES PRIVATE LIMITED"),
         ("Objects", "Investment in securities and fund units"),
         ("Authorised capital", "INR 5,00,00,000"),
         ("Directors may bind", "Any two, jointly")],
        "Specimen. Evidences the legal form and the powers, per 5.4.2(c)."),
    "board-orion.pdf": document(
        "Certified extract - Board resolution", "ORION ZENITH ENTERPRISES",
        [("Resolved on", "18/06/2026"),
         ("Authorised signatory", "PRIYA HUSSAIN, Director"),
         ("Authority", "To subscribe for units and operate the account"),
         ("Certified by", "Company Secretary")],
        "Specimen. Evidences that whoever signs may sign, per PML Rules 9(3)."),
    "ubo-orion.pdf": document(
        "Declaration of beneficial ownership", "ORION ZENITH ENTERPRISES",
        [("Declared for", "ORION ZENITH ENTERPRISES PRIVATE LIMITED"),
         ("Beneficial owner", "PRIYA HUSSAIN"),
         ("Holding", "56.0% (through two intermediate companies)"),
         ("Nationality", "INDIAN"),
         ("Test applied", "More than 10% - IFSCA clause 1.3.3(a)")],
        "Specimen. Ten per cent, not twenty-five: IFSCA's test, not FATF's."),

    # -- a trust ------------------------------------------------------------
    "deed-sharma.pdf": document(
        "Deed of Trust", "SHARMA FAMILY TRUST",
        [("Trust", "SHARMA FAMILY TRUST"),
         ("Author of the trust", "ROHAN SHARMA"),
         ("Trustee", "SANDALWOOD TRUSTEES PRIVATE LIMITED"),
         ("Beneficiaries", "MEERA SHARMA (30%), ARJUN SHARMA (25%)"),
         ("Registered", "14/11/2021, Mumbai"),
         ("Governing law", "INDIA")],
        "Specimen. The author and the trustee are beneficial owners at any "
        "percentage - clause 1.3.3(d)."),
    "trustee-sharma.pdf": document(
        "Disclosure of trustee status", "SANDALWOOD TRUSTEES PRIVATE LIMITED",
        [("Declared by", "SANDALWOOD TRUSTEES PRIVATE LIMITED"),
         ("Acting as", "TRUSTEE, not beneficial owner"),
         ("For", "SHARMA FAMILY TRUST"),
         ("Dated", "18/06/2026")],
        "Specimen. A trustee who does not say so is indistinguishable from a "
        "beneficial owner."),

    # -- a partnership ------------------------------------------------------
    "deed-kesari.pdf": document(
        "Limited Liability Partnership Agreement", "REGISTRAR OF COMPANIES",
        [("Firm", "KESARI HOLDINGS LLP"),
         ("LLP identification number", "AAA-0000"),
         ("Date of registration", "27/02/2020"),
         ("Designated partners", "NADIA RAHMAN, ANAND BHAT"),
         ("Profit share", "60 / 40"),
         ("Registered office", "9 Raffles Place, Singapore 048619")],
        "Specimen. The identification number is not an allotted LLPIN."),
}


def main() -> int:
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(PACK_FILES.items()):
        (PACK / name).write_bytes(data)
    print()
    print("  %d specimen documents in %s" % (len(PACK_FILES), PACK))
    print()
    for name in sorted(PACK_FILES):
        print("    %-28s %6d bytes" % (name, len(PACK_FILES[name])))
    print()
    print("  Every one is marked SPECIMEN on its face and carries an")
    print("  identifier no authority issues. Drag one into the second step")
    print("  of an onboarding.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

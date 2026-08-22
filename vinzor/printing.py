"""One party's record, as the PDF somebody actually sends.

The report already existed and already downloaded, and what came down was an
HTML file. That is a fine thing to read and the wrong thing to send. The
document this produces goes to a board, an auditor or the regulator, and what
you attach to that email is a PDF: it opens the same way on every machine, it
prints without anybody choosing a scale, and nobody has to wonder whether the
copy they were sent is the copy that was written.

Nothing here decides anything or reads any record. It is handed a
``dossier.Dossier`` -- the same structure the screen renders, assembled from
the log by ``dossier.py`` -- and lays it out. That separation is the point:
the document a firm sends and the screen its officer read cannot disagree,
because there is one description of the record and two renderings of it.

**The warning goes first and cannot be missed.** Clause 4.1(d) forbids
tipping off a customer who is under examination, and this file names what was
suspected and by whom. So it opens with a boxed statement of who may read it,
in black on white with no tint, because that is the one thing on the page that
has to survive a bad printer and a fax machine.

**What was not found is printed as prominently as what was.** A report that
lists three findings and stays quiet about the five checks that came back
clean is a report that cannot be used as evidence the checks happened -- and
"we screened and found nothing" is precisely what an inspector asks to see.
"""

from __future__ import annotations

from .pdfwrite import BOLD, LEFT, REGULAR, RIGHT, WIDTH, Document, measure


def _stamp(pdf: Document, dossier) -> None:
    """The wordmark, the party, and what this document is."""
    page = pdf.page
    page.text(LEFT, pdf.y - 21, 21, BOLD, "Vinzor")
    said = dossier.workspace or ""
    if said:
        page.parts.append("q 0.4 g")
        page.text(WIDTH - RIGHT - measure(said, REGULAR, 9), pdf.y - 12, 9,
                  REGULAR, said)
        page.parts.append("Q")
    pdf.y -= 30
    page.rule(LEFT, pdf.y, WIDTH - RIGHT, 1.6)
    pdf.y -= 20

    pdf.paragraph(dossier.title, size=17, font=BOLD, leading=21)
    line = " - ".join(x for x in (dossier.kind, dossier.printed) if x)
    pdf.paragraph(line, size=9, grey=0.35)
    pdf.gap(10)


def render(dossier) -> bytes:
    """One party's record as a PDF, ready to be sent."""
    pdf = Document(title=dossier.title or "Vinzor record")
    _stamp(pdf, dossier)

    if dossier.refusal:
        pdf.paragraph(dossier.refusal, size=10)
        return pdf.bytes()

    if dossier.confidential:
        pdf.banner("Who may read this", dossier.confidential)

    # The assistant's opening, where there is one. Marked as what it is: a
    # reading of the sections below, not a source for anything in them.
    if dossier.opening:
        pdf.heading("In summary")
        pdf.paragraph(dossier.opening, size=10, leading=14.5)
        pdf.paragraph(
            "Written by this system's assistant from the sections below and "
            "checked against them. Every fact it rests on is set out in full "
            "further down; nothing here is a source.",
            size=8, grey=0.4)
        pdf.gap(4)
    elif dossier.opening_withheld:
        pdf.heading("In summary")
        pdf.paragraph(dossier.opening_withheld, size=9, grey=0.35)

    if dossier.summary:
        pdf.heading("At a glance")
        for line in dossier.summary:
            pdf.bullet(line)
        pdf.gap(6)

    for part in dossier.parts:
        if not (part.heading or part.lead or part.facts or part.entries):
            continue
        pdf.heading(part.heading or "")
        if part.lead:
            pdf.paragraph(part.lead, size=9.5, leading=13.5)
            pdf.gap(4)
        for fact in part.facts:
            pdf.pair(fact.label, fact.value)
            if fact.note:
                pdf.paragraph(fact.note, size=8.5, indent=150, grey=0.4)
        if part.facts and part.entries:
            pdf.gap(6)
        for entry in part.entries:
            head = " - ".join(x for x in (entry.when, entry.who) if x)
            if head:
                pdf.paragraph(head, size=8, font=BOLD, grey=0.4)
            pdf.paragraph(entry.what, size=9.5, leading=13)
            if entry.why:
                # Quoted rather than summarised: an officer is accountable
                # for the words they wrote, not for our paraphrase of them.
                pdf.quote(entry.why)
            if entry.clause:
                pdf.paragraph(entry.clause, size=8.5, grey=0.4)
            pdf.gap(5)
        if part.tail:
            pdf.gap(2)
            pdf.paragraph(part.tail, size=8.5, grey=0.4)
        pdf.gap(8)

    return pdf.bytes()


def filename_for(dossier, today: str) -> str:
    """What the file is called when it lands in somebody's downloads."""
    clean = "".join(c if (c.isalnum() or c in " -_") else " "
                    for c in (dossier.title or "record"))
    clean = " ".join(clean.split())[:70]
    return f"Vinzor - {clean} - {today}.pdf"

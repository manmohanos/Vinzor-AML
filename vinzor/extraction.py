"""Reading the details out of a document, and proposing nothing more.

A passport was going onto a party's file as bytes and a fingerprint, and
everything it said had to be typed in again by hand. That is the gap between
holding a document and holding what it proves — clause 5.4.2 wants a firm to
know a date of birth, clause 5.4.5 wants the passport behind it, and until
now the second did not help with the first.

**This proposes; a person confirms.** It reads the words off the page, finds
the fields it recognises, and hands them back as *suggestions* beside what the
record already holds. Nothing is written from here. That is not caution for
its own sake:

- A scan reads badly. An OCR-grade 8 is a B often enough that a permanent
  record built on one would be wrong in a way nobody could see.
- Clause 5.4.5 asks a firm to verify identity from reliable and independent
  sources. A firm that let software promote a field into evidence has not
  verified anything; it has copied.
- And the confirmation is the audit trail. "A person looked at this passport
  and said it shows this date of birth" is the record an inspector wants.
  "Our software read a PDF" is not.

So the answer is a proposal with the evidence beside it, and one click to
accept — which is the same division ``assist.py`` draws around the model, for
the same reason.

**No model, no dependency.** The reading is ``pdftext.py``, already written
here for the clause register; the finding is labelled patterns and a table of
words a document uses for a field. Same document in, same fields out, today
and in a year. A model asked to "pull the details out of this" would be an
unrepeatable answer on a compliance file.

**What it will not do.** It does not read handwriting, photographs of screens,
or anything that is an image rather than text — a scan with no text layer
gives nothing back and says so, rather than guessing. It does not correct what
it finds. And it will not propose a field the document's *kind* cannot
evidence: a utility bill may offer an address and may not offer a nationality,
however confidently the page says one, because ``documents.KINDS`` decides
what a kind of paper is allowed to prove and this is not the place to argue
with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from .documents import KINDS

#: What a document calls a field, in the words the issuers actually print.
#: Read in order; the first that matches a line wins, so the more specific
#: label is listed first.
#:
#: Deliberately a table rather than a clever parser. A firm has to be able to
#: see what this looks for, and "we search for these words" is a sentence
#: anybody can check.
LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pan", ("permanent account number", "pan number", "pan no", "pan")),
    ("id_document_number",
     ("passport number", "passport no", "certificate number",
      "identity number", "licence number", "license number",
      "aadhaar number", "document number")),
    ("cin", ("corporate identity number", "corporate identification number",
             "cin", "llp identification number", "llpin")),
    ("date_of_incorporation",
     ("date of incorporation", "date of registration", "incorporated on",
      "registered on")),
    ("dob", ("date of birth", "birth date", "dob", "born on")),
    ("nationality", ("nationality", "citizenship")),
    ("country_of_incorporation",
     ("country of incorporation", "country of registration", "jurisdiction")),
    ("address",
     ("residential address", "registered office", "service address",
      "address on file", "address")),
    ("name",
     ("company", "firm", "trust", "account holder", "billed to",
      "declared for", "name of the holder", "surname", "given name",
      "full name", "name")),
)

#: A value that is one of these is the form's own furniture, not an answer.
_NOT_A_VALUE = frozenset({
    "", "-", "--", "n/a", "na", "none", "nil", "not applicable",
    "xxxx", "specimen",
})

#: A date, in the shapes an Indian document prints one.
_DATE = re.compile(
    r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")

#: How much of a line can be a label before the rest is the answer.
_LONGEST_LABEL = 46

#: Fields that are identifiers. A value with no digit in it is not one of
#: these, whatever the line above it said. Without this rule the title of a
#: PAN card -- "Permanent Account Number Card" -- reads as a permanent
#: account number of "Card", which would go on a compliance record.
_MUST_HAVE_A_DIGIT = frozenset({
    "pan", "cin", "id_document_number",
})

#: A passport prints the two halves of a name on separate lines. Taking the
#: first and stopping gives a party called "BHAT", which is a surname and not
#: a name -- and it is the name every later check screens.
_GIVEN_NAME = ("given name", "given names", "first name", "forename")


@dataclass(frozen=True)
class Proposal:
    """One field a document appears to show, offered for confirmation."""

    field: str
    #: What the page said, cleaned only of surrounding punctuation. Never
    #: corrected: a value this could not read properly is a value a person
    #: has to look at, and quietly tidying it would hide that.
    value: str
    #: The line it came off, so an officer can see where it was read from
    #: without opening the file. This is the whole reason to trust it.
    seen_as: str
    #: True where the record already holds exactly this. Shown differently:
    #: agreement is corroboration, and disagreement is the interesting case.
    agrees: bool = False
    #: What the record holds instead, where the two differ.
    on_record: str = ""


@dataclass(frozen=True)
class Reading:
    """Everything one document offered, and what it could not."""

    kind: str
    proposals: tuple[Proposal, ...] = ()
    #: Said plainly when there is nothing to read, rather than returning an
    #: empty list that looks like a document with nothing in it.
    unreadable: str = ""

    @property
    def disagreements(self) -> tuple[Proposal, ...]:
        return tuple(p for p in self.proposals if p.on_record and not p.agrees)


def _tidy(value: str) -> str:
    return value.strip().strip(":;,.").strip()


def _as_iso(value: str) -> str:
    """A date the way the record keeps one, or "" if it is not a date.

    Day-first, because every document in this jurisdiction prints day-first
    and the ambiguous case is resolved by the format the issuer used rather
    than by a guess. A value that could be either is left alone for a person,
    the same way the spreadsheet importer refuses one.
    """
    found = _DATE.search(value or "")
    if not found:
        return ""
    if found.group(4):
        return "%s-%s-%s" % (found.group(4), found.group(5), found.group(6))
    day, month, year = found.group(1), found.group(2), found.group(3)
    if int(month) > 12:
        day, month = month, day
    if int(month) > 12 or int(day) > 31:
        return ""
    return "%s-%02d-%02d" % (year, int(month), int(day))


def fields_in(text: str, kind: str) -> tuple[tuple[str, str, str], ...]:
    """(field, value, the line it came from) for everything recognised.

    Restricted to what this *kind* of document may evidence. A utility bill
    that happens to print a nationality does not get to prove one, because
    ``documents.KINDS`` decides what a kind of paper supports and a reader is
    not the place to argue with it.
    """
    allowed = set(KINDS.get(kind, ("", ()))[1])
    if not allowed:
        return ()

    found: dict[str, tuple[str, str]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # Matched as a prefix rather than as two columns, because a PDF does
        # not have columns -- it has glyphs at coordinates, and a reader
        # walking them emits "DATE OF BIRTH14/03/1981" with nothing between
        # the label and the answer. Real certificates print
        # "Date of Birth:  14/03/1981" and both forms come out the same way
        # once the separator is treated as optional.
        flat = " ".join(line.split()).lower()
        for field, words in LABELS:
            if field not in allowed or field in found:
                continue
            for word in words:
                if not flat.startswith(word):
                    continue
                rest = line[len(word):] if len(line) >= len(word) else ""
                # Re-cut from the original so the value keeps its own case:
                # a name is not ANAND BHAT because the label above it was.
                rest = _tidy(rest.lstrip(":–- 	"))
                if len(word) > _LONGEST_LABEL:
                    break
                if not rest or rest.lower() in _NOT_A_VALUE or len(rest) < 2:
                    break
                if field in _MUST_HAVE_A_DIGIT and not any(
                        ch.isdigit() for ch in rest):
                    break
                if field in ("dob", "date_of_incorporation"):
                    iso = _as_iso(rest)
                    if not iso:
                        break
                    found[field] = (iso, line[:160])
                else:
                    found[field] = (rest, line[:160])
                break
            if field in found:
                break
    # A surname is not a name. Where the document printed both halves,
    # join them in the order the passport does -- given name first, which is
    # how the party will be screened and how every list holds them.
    given, given_line = "", ""
    for raw in (text or "").splitlines():
        flat = " ".join(raw.split()).lower()
        for word in _GIVEN_NAME:
            if flat.startswith(word):
                given = _tidy(raw.strip()[len(word):].lstrip(":–- 	"))
                given_line = raw.strip()[:80]
                break
        if given:
            break
    if given and "name" in found and given.lower() not in found["name"][0].lower():
        surname, line = found["name"]
        # Both lines on the provenance, because the value came off both and
        # a proposal whose "seen as" does not contain it is a proposal an
        # officer cannot check -- which is the only thing making these
        # trustworthy at all.
        found["name"] = ("%s %s" % (given, surname),
                         "%s + %s" % (given_line, line[:80]))

    return tuple((field, value, line) for field, (value, line) in found.items())


def read(path_or_bytes, *, kind: str,
         holds: Optional[Mapping[str, str]] = None) -> Reading:
    """What this document appears to show, beside what the record holds.

    ``holds`` is the party's current attributes. Where the two agree the
    proposal is corroboration -- worth showing, because "the passport says
    the same as the spreadsheet" is evidence. Where they differ it is the
    finding: one of them is wrong and a person has to decide which.
    """
    import os
    import tempfile

    from .pdftext import pages

    # The reader opens a path, and an upload arrives as bytes. Written to a
    # temporary file and removed straight after rather than kept: the bytes
    # already have a home in the cabinet, and a second copy of a customer's
    # passport lying in the OS temp directory is precisely the leak the
    # spreadsheet importer was found to have -- 170 directories and 491
    # customer sheets, outside the workspace boundary entirely.
    temporary = ""
    try:
        if isinstance(path_or_bytes, (bytes, bytearray)):
            handle, temporary = tempfile.mkstemp(suffix=".pdf")
            with os.fdopen(handle, "wb") as out:
                out.write(path_or_bytes)
            read_pages = pages(temporary)
        else:
            read_pages = pages(path_or_bytes)
    except Exception:      # noqa: BLE001 - any reader failure is unreadable
        return Reading(kind=kind, unreadable=(
            "This file could not be read as a document. Nothing was taken "
            "from it, and it is on the record as filed."))
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass

    text = "\n".join(p.text for p in read_pages)
    if len(text.strip()) < 20:
        return Reading(kind=kind, unreadable=(
            "There is no text in this file to read -- it is most likely a "
            "photograph or a scan. It is on the record as filed, and what it "
            "shows has to be entered by hand."))

    on_record = {k: str(v or "") for k, v in (holds or {}).items()}
    proposals = []
    for field, value, line in fields_in(text, kind):
        held = on_record.get(field, "")
        proposals.append(Proposal(
            field=field, value=value, seen_as=line[:160],
            agrees=bool(held) and held.strip().lower() == value.strip().lower(),
            on_record=held))
    if not proposals:
        return Reading(kind=kind, unreadable=(
            "Nothing this system recognises was found in this document. It "
            "is on the record as filed."))
    return Reading(kind=kind, proposals=tuple(proposals))

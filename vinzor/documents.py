"""The papers behind the facts, and which fact each one actually supports.

Every attribute on every party in this workspace arrived in a spreadsheet.
Ask how the firm knows an investor's date of birth and the honest answer is
"a column said so", which is not evidence of anything. Clause 5.4.5 does not
ask for the data; it asks that identity be verified "using the relevant
information or data obtained from reliable, independent sources". The
document is the source. Until now there was nowhere to put one.

**This is not a reader.** The obvious build here is optical character
recognition and a model that fills the party record in from a scan, and it
is the wrong thing to build first for two reasons. A machine-read field
written onto a compliance record with nothing saying where it came from is
the exact failure this product exists to prevent -- and most Indian KYC
packs are photographs of paper, so the reader would be confidently wrong on
the documents that matter most. What is missing is not the reading. It is
the link between a document and the fact it is supposed to support, and a
person is the one who asserts that link.

So: a document is filed against a party, a person says what it evidences,
and everything downstream can finally distinguish a fact somebody typed
from a fact somebody can produce paper for. When extraction is added it
feeds *suggestions* into this same structure, the way assisted review
already suggests rather than decides.

**What falls out of holding the file.** A document is kept with the
fingerprint of its bytes, and that turns out to answer a question nobody
set out to ask: the same scan filed against two different investors. Not a
clerical slip -- the same passport image cannot evidence two people -- and
it is free, because the fingerprint was already there to notice a
re-upload.

**On expiry.** A passport that has run out is not a document that fails to
verify; it is a document that verified something once and no longer does.
Both readings are wrong in the same direction if the file simply
disappears, so an expired document stays on the record and says what it
was, when it lapsed, and what stopped being supported.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Optional

from .model import EventType

#: What a document of each kind can properly evidence, as the attribute
#: keys clause 5.4.2 is measured against. Deliberately narrow: a trust deed
#: names trustees and a settlor, and it is not evidence of anybody's date of
#: birth. Somebody filing a document may say it supports less than this and
#: never more, so an officer cannot quietly promote a utility bill into
#: proof of a nationality.
KINDS: Mapping[str, tuple] = {
    # ``expires`` is on the three kinds that actually print one. It is not
    # an attribute the record keeps about a *party* -- a person does not have
    # an expiry date -- it is a property of the paper, and it is here so the
    # reader may take it off the page and say the paper is no longer valid.
    "passport": ("Passport",
                 ("name", "dob", "nationality", "id_document_number",
                  "expires")),
    "pan_card": ("PAN card", ("name", "pan", "dob")),
    "aadhaar": ("Aadhaar", ("name", "dob", "address")),
    "driving_licence": ("Driving licence",
                        ("name", "dob", "address", "id_document_number",
                         "expires")),
    # An Indian officially valid document under PML Rules 9(4)(a), and it
    # was not on this list at all -- so an investor whose identity document
    # was their voter card had nowhere to file it and the requirement it
    # satisfies stayed open.
    "voter_id": ("Voter identity card",
                 ("name", "dob", "address", "id_document_number")),
    # A foreign national's identity card. Filed and read, and deliberately
    # *not* an officially valid document: clause 1.3.30 and PML Rules 9(4)(a)
    # name what counts, and a German or Singaporean identity card is not on
    # that list. It is still worth reading -- a name and a date of birth that
    # disagree with the record are worth knowing however the paper is
    # classified -- and this product's whole discipline is that reading a
    # document and accepting it as evidence are two different acts.
    #
    # It exists because this is an international financial centre. A list
    # offering only Aadhaar, PAN and an Indian driving licence has no place
    # to put the primary identity document of most of the investors GIFT
    # City is for.
    "national_id": ("National identity card (non-Indian)",
                    ("name", "dob", "nationality", "id_document_number",
                     "expires")),
    "utility_bill": ("Utility bill", ("name", "address")),
    "bank_statement": ("Bank statement", ("name", "address")),
    "incorporation": ("Certificate of incorporation",
                      ("name", "cin", "date_of_incorporation",
                       "country_of_incorporation", "jurisdiction")),
    "register_of_members": ("Register of members", ("name",)),
    "trust_deed": ("Trust deed", ("name", "jurisdiction", "trust_type")),
    "board_resolution": ("Board resolution", ("name",)),
    "constitution": ("Constitutional documents",
                     ("name", "jurisdiction", "country_of_incorporation")),
    "proof_of_address": ("Proof of address", ("name", "address")),
    # Added with requirements.py, which asks for documents rather than for
    # attributes: a company owes proof that whoever signs may sign, and there
    # was no kind on this list that such a paper could be filed as. An
    # unnameable document becomes "other", and "other" evidences nothing --
    # so the requirement could never have been satisfied by anything.
    "partnership_deed": ("Partnership or LLP deed",
                         ("name", "jurisdiction", "date_of_incorporation")),
    "power_of_attorney": ("Power of attorney", ("name",)),
    "ubo_declaration": ("Beneficial ownership declaration", ("name",)),
    "source_of_funds": ("Source of funds evidence", ("name",)),
    # An unclassified file may be kept on the record and may evidence
    # nothing. That is not a gap in this list, it is the list working: a
    # document that genuinely proves a nationality is a passport, an
    # identity card or a certificate, and if a firm holds a kind this does
    # not name then the answer is to name it here -- deliberately, once --
    # rather than to let every unrecognised file evidence anything.
    "other": ("Other document", ()),
}

#: Every attribute any document can evidence. A claim to support something
#: outside this set is not a permission question, it is a typing mistake or
#: an invented field, and either way nothing downstream will ever read it.
EVIDENCEABLE = frozenset(
    key for _name, keys in KINDS.values() for key in keys)

#: What the first bytes of a file say it is. A pack arrives as scans and
#: exports, and a file named ``passport.pdf`` that is really a spreadsheet
#: is worth refusing at the door rather than storing as evidence.
SHAPES = (
    (b"%PDF-", "pdf", "a PDF"),
    (b"\xff\xd8\xff", "jpeg", "a photograph"),
    (b"\x89PNG\r\n\x1a\n", "png", "an image"),
    (b"II*\x00", "tiff", "a scan"),
    (b"MM\x00*", "tiff", "a scan"),
    (b"PK\x03\x04", "zip", "a Word or Excel file, or a zip"),
)

#: Bigger than any single certificate or scan, small enough that a workspace
#: does not quietly become a file server.
MOST_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class Paper:
    """One document on the record, and what a person said it supports."""

    digest: str
    kind: str
    filename: str
    size: int
    shape: str
    subject: str
    filed_on: str
    filed_by: str
    #: The attribute keys a person asserted this evidences.
    supports: tuple[str, ...] = ()
    #: Empty where the document does not expire. A certificate of
    #: incorporation does not; a passport does.
    expires_on: str = ""
    note: str = ""

    def expired(self, today: str) -> bool:
        """Whether this document had run out by ``today``.

        Compared as dates rather than as text, which is not fussiness. The
        door accepts "2026-1-1" -- a person typing 1 January writes it that
        way -- and as text that sorts *after* "2026-08-20", so a passport
        seven months out of date read as current and went on evidencing a
        nationality. The log cannot be rewritten, so records already
        carrying an unpadded date exist and this is where they are read.

        A date this cannot parse expires nothing. An unreadable expiry is
        not evidence that a document has lapsed, and treating it as one
        would quietly withdraw support from a document that may be
        perfectly current.
        """
        mine = _padded(self.expires_on)
        if not mine:
            return False
        return _padded(today) > mine

    @property
    def called(self) -> str:
        return KINDS.get(self.kind, ("Other document", ()))[0]

    @property
    def evidences(self) -> tuple:
        """What this document actually stands behind.

        The claim as recorded, narrowed to what a document of this kind can
        evidence at all. ``refuse`` turns an overreaching claim away at the
        door, but a door is not the same as a rule: the log is append-only,
        so any claim written before that check existed is on the record for
        good, and nothing stops a future path ingesting one without asking.

        So the allowlist is applied here as well, where the record is read.
        The claim itself is left exactly as it was made -- ``supports``
        still says what somebody asserted, because a claim that was made
        and is not honoured is a thing an inspector may want to see.
        """
        allowed = can_support(self.kind)
        return tuple(key for key in self.supports if key in allowed)


@dataclass
class Papers:
    """Every document filed, by party and by fingerprint."""

    by_party: dict = field(default_factory=dict)
    by_digest: dict = field(default_factory=dict)

    def apply(self, event) -> None:
        if event.event_type is not EventType.DOCUMENT_FILED:
            return
        payload = event.payload or {}
        paper = Paper(
            digest=str(payload.get("digest") or ""),
            kind=str(payload.get("kind") or "other"),
            filename=str(payload.get("filename") or ""),
            size=int(payload.get("size") or 0),
            shape=str(payload.get("shape") or ""),
            subject=event.subject,
            filed_on=str(event.occurred_at)[:10],
            filed_by=str(event.actor or ""),
            supports=tuple(payload.get("supports") or ()),
            expires_on=str(payload.get("expires_on") or "")[:10],
            note=str(payload.get("note") or ""),
        )
        if not paper.digest:
            return
        # Replaced rather than mutated: a reader may hold either while
        # another thread folds.
        self.by_party = {
            **self.by_party,
            event.subject: self.by_party.get(event.subject, ()) + (paper,),
        }
        self.by_digest = {
            **self.by_digest,
            paper.digest: self.by_digest.get(paper.digest, ()) + (paper,),
        }

    def held_for(self, subject: str) -> tuple:
        return self.by_party.get(subject, ())

    def parties_sharing(self, digest: str) -> frozenset:
        """Everyone the same file has been filed against."""
        return frozenset(paper.subject
                         for paper in self.by_digest.get(digest, ()))

    def supporting(self, subject: str, today: str) -> dict:
        """{attribute key: the papers that still support it}.

        An expired document supports nothing today, which is different
        from never having existed -- and the difference is why it stays on
        the record rather than being taken off.
        """
        found: dict = {}
        for paper in self.held_for(subject):
            if paper.expired(today):
                continue
            for key in paper.evidences:
                found[key] = found.get(key, ()) + (paper,)
        return found

    def lapsed(self, subject: str, today: str) -> tuple:
        return tuple(paper for paper in self.held_for(subject)
                     if paper.expired(today))


class Cabinet:
    """Where the files themselves are kept.

    Beside the log, in the same file, never in it -- the same division the
    credentials make and for a related reason. The *fact* that a document
    was filed, by whom, against which party and what it evidences is a
    compliance fact and belongs in the record. Twenty megabytes of scanned
    passport is not a fact, it is an attachment, and a log that carries
    attachments stops being something you can replay in a second.

    Keeping them at all is a decision. "Show me the passport you verified
    against" is the question after "how do you know", and a system that
    answers only "we recorded that we saw one" is the weaker of the two.
    """

    def __init__(self, path="  :memory:") -> None:
        import sqlite3
        from pathlib import Path as _Path

        self.path = str(path).strip() or ":memory:"
        if self.path != ":memory:":
            _Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS papers ("
            "  digest TEXT PRIMARY KEY,"
            "  bytes  BLOB NOT NULL,"
            "  filed  TEXT NOT NULL)")
        self._conn.commit()

    def keep(self, digest: str, data: bytes, when: str) -> None:
        """Store the bytes once, however many parties cite them.

        Deliberately keyed by fingerprint rather than by party: the same
        file filed against two investors is one file, and it is also a
        finding, which is easier to see when there is visibly one copy.
        """
        self._conn.execute(
            "INSERT INTO papers (digest, bytes, filed) VALUES (?, ?, ?) "
            "ON CONFLICT(digest) DO NOTHING",
            (digest, data, str(when)))
        self._conn.commit()

    def fetch(self, digest: str) -> Optional[bytes]:
        row = self._conn.execute(
            "SELECT bytes FROM papers WHERE digest = ?", (digest,)).fetchone()
        return bytes(row[0]) if row else None

    def holds(self, digest: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM papers WHERE digest = ?",
            (digest,)).fetchone() is not None


def fingerprint(data: bytes) -> str:
    """What identifies a file. The bytes, not the name somebody gave it."""
    return hashlib.sha256(data).hexdigest()


def _padded(iso: str) -> str:
    """A date as ``YYYY-MM-DD``, or "" if it is not a date at all."""
    parts = str(iso)[:10].split("-")
    if len(parts) != 3:
        return ""
    try:
        year, month, day = (int(one) for one in parts)
        date(year, month, day)
    except (TypeError, ValueError):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def shape_of(data: bytes) -> str:
    """What the first bytes say this file is, or nothing recognised."""
    for magic, name, _plain in SHAPES:
        if data.startswith(magic):
            return name
    return ""


def what_it_looks_like(data: bytes) -> str:
    for magic, _name, plain in SHAPES:
        if data.startswith(magic):
            return plain
    return "a kind of file this does not recognise"


def can_support(kind: str) -> tuple:
    return KINDS.get(kind, ("Other document", ()))[1]


def refuse(kind: str, data: bytes, supports, expires_on: str = "") -> str:
    """Why this document cannot be filed, or nothing.

    Refusing at the door rather than storing something misleading: this is
    the one place in the product where a file becomes evidence, and a file
    that is not what it says it is should never get that far.
    """
    if kind not in KINDS:
        known = ", ".join(sorted(KINDS))
        return (f"There is no document kind called {kind!r}. The ones this "
                f"understands are: {known}.")
    if not data:
        return "That file is empty, so there is nothing to keep."
    if len(data) > MOST_BYTES:
        return (f"That file is {len(data) / 1024 / 1024:.0f} MB. The limit is "
                f"{MOST_BYTES // 1024 // 1024} MB — a certificate or a scan "
                f"is smaller than that, and a workspace should not quietly "
                f"become a file server.")
    if not shape_of(data):
        return ("This does not begin like a document. It looks like "
                + what_it_looks_like(data)
                + ", and a file that is not what it claims to be should not "
                  "become somebody's evidence of identity.")

    allowed = can_support(kind)
    asked = tuple(supports or ())

    invented = [key for key in asked if key not in EVIDENCEABLE]
    if invented:
        return ("Nothing on this record is called "
                + ", ".join(sorted(invented))
                + ". A document can only be said to evidence something the "
                  "record actually holds.")

    # No exemption for "other", and removing that exemption is the whole of
    # this. It used to skip the check below, which meant an unclassified
    # file could be filed as evidence of a name, a date of birth, a
    # nationality and a permanent account number at once. Measured on a
    # party holding the seven items clause 5.4.2 asks of a person, one such
    # file left five of them reading as backed by a document and two as
    # unsupported -- so a screen an officer trusts to separate "we hold it"
    # from "we can produce paper for it" said the wrong thing about five
    # facts out of seven. It was also the easiest path available, because
    # "Other document" is what somebody picks when they cannot find their
    # document in the list.
    overreach = [key for key in asked if key not in allowed]
    if overreach:
        called = KINDS[kind][0]
        if kind == "other":
            return ("An unclassified document cannot evidence "
                    + ", ".join(sorted(overreach))
                    + ". Say what kind of document this is, and it will "
                      "evidence what that kind can. It can still be filed "
                      "as it is -- it will simply not stand behind a fact.")
        return (f"{called} cannot evidence "
                + ", ".join(sorted(overreach))
                + ". A document may be said to support less than it could, "
                  "never more.")
    if expires_on and not _is_a_date(expires_on):
        return (f"{expires_on!r} is not a date this can read. Write it as "
                f"four digits, month, day.")
    return ""


def _is_a_date(value: str) -> bool:
    return bool(_padded(value))

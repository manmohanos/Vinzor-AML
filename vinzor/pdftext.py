"""Reading the words out of a PDF, with nothing installed.

Twenty-one clauses in ``citations.py`` are quoted from IFSCA's published
PDFs. When they were finally checked against those PDFs by hand, twelve had
a real problem -- wrong pages, extracts missing half a sentence, one quoting
the wrong subsection entirely. They were all fixed, and then nothing stopped
them drifting again: an extract is a string in a Python file, and a string
in a Python file can be edited by anybody who thinks they are tidying it.

So the check has to be a test, and a test needs to read the PDF.

**What this is and is not.** It is enough of a PDF reader to answer one
question: does this sentence appear in that document, and on which page.
It is not a layout engine. It does not reconstruct columns, tables or
reading order, and it should never be used to *show* somebody a document --
only to check whether words are in one.

**Why by hand rather than a library.** The product has no dependencies, in
a domain where each one is something a firm's security review has to clear.
The subset needed here is small and the document is one publisher's.

**The trap this was written around.** A first version read only the plain
strings and skipped the hex ones, and IFSCA's master guidelines put most of
their body text in hex: the fonts are subset Aptos, encoded Identity-H, so
every letter is a two-byte glyph number that means nothing without the
font's own translation table. Page 5 came back as ``1.3.2 1.3.3 (a) (i) 4``
-- the numbering, and not one word of the clause under it. That is worse
than a page that fails outright, because it *looks* like a page that read
cleanly, and a clause check run against it would report the correct wording
of clause 1.3.3 as missing from a document that states it. So the glyph
numbers are translated through each font's ToUnicode map, and anything that
still cannot be turned into a letter is counted and reported rather than
quietly dropped.

**Where it gives up, it says so.** A page whose fonts carry no translation
table yields bytes this cannot turn into letters. Those pages are marked
unreadable, so a clause that "cannot be found" because its page could not
be read is never mistaken for a clause that is wrong.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

#: What a glyph number becomes when the font offers no translation for it.
UNREADABLE_LETTER = "�"

#: How an extract marks that it has left words out of the middle of a
#: sentence. The alternative -- shortening an extract and saying nothing --
#: is the defect that a hand check of this register found six times.
ELISION = "..."

#: A page has to be more than this proportion readable to count as read at
#: all. Set low deliberately: one stray unmapped glyph in a heading is not
#: a reason to refuse a page, but a page that is mostly unmapped glyphs is
#: not a page anybody can check a sentence against.
ENOUGH_READ = 0.80

#: Typographic characters a published document uses and a Python source
#: file usually does not. Folded before comparison so that a curly
#: apostrophe in the PDF and a straight one in the extract are the same
#: sentence, which is what a reader means by "the same sentence".
_SAME = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
    "…": "...", "ﬁ": "fi", "ﬂ": "fl", "​": "",
}

#: PDF escapes inside a plain string.
_ESCAPES = {
    b"\\n": b"\n", b"\\r": b"\r", b"\\t": b"\t", b"\\b": b"\b",
    b"\\f": b"\f", b"\\(": b"(", b"\\)": b")", b"\\\\": b"\\",
}

_PLAIN = re.compile(rb"\((?:[^()\\]|\\.)*\)", re.S)
_HEXES = re.compile(rb"<([0-9A-Fa-f\s]*)>")
_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>")
_INDIRECT = re.compile(rb"(\d+)\s+0\s+R")


# -- the document's objects --------------------------------------------------


@dataclass(frozen=True)
class _Font:
    """One font as far as reading letters is concerned.

    ``wide`` is the difference that matters: an Identity-H font numbers its
    glyphs in two bytes, so its strings must be cut in pairs, and cutting
    them one byte at a time turns a page of English into a page of nothing.
    """

    wide: bool
    table: dict = field(default_factory=dict)


def _slice_of(raw: bytes, at: int) -> bytes:
    """The balanced ``<< ... >>`` beginning at ``at``."""
    depth = 0
    here = at
    while here < len(raw) - 1:
        if raw[here:here + 2] == b"<<":
            depth += 1
            here += 2
        elif raw[here:here + 2] == b">>":
            depth -= 1
            here += 2
            if depth == 0:
                return raw[at:here]
        else:
            here += 1
    return raw[at:]


def _inflate(head: bytes, body: bytes) -> bytes:
    if b"/FlateDecode" in head:
        try:
            return zlib.decompressobj().decompress(body)
        except zlib.error:
            return b""
    length = re.search(rb"/Length\s+(\d+)", head)
    if length:
        return body[:int(length.group(1))]
    end = body.find(b"endstream")
    return body[:end] if end >= 0 else body


def _objects(raw: bytes) -> dict:
    """Every numbered object in the file, including the compressed ones.

    From PDF 1.5 onward most of a document's small objects -- page
    dictionaries, font dictionaries -- are packed inside object streams and
    are not visible in the file's bytes at all. Missing that is missing the
    fonts, which is missing the text.
    """
    out: dict = {}
    for found in re.finditer(rb"(\d+)\s+0\s+obj", raw):
        number = int(found.group(1))
        start = found.end()
        closes = raw.find(b"endobj", start)
        closes = closes if closes >= 0 else len(raw)
        opens = raw.find(b"stream", start)
        if 0 <= opens < closes:
            head = raw[start:opens]
            after = opens + len(b"stream")
            if raw[after:after + 2] == b"\r\n":
                after += 2
            elif raw[after:after + 1] in (b"\n", b"\r"):
                after += 1
            out[number] = (head, _inflate(head, raw[after:]))
        else:
            out[number] = (raw[start:closes], None)

    for head, body in list(out.values()):
        if b"/ObjStm" not in head or not body:
            continue
        count = re.search(rb"/N\s+(\d+)", head)
        first = re.search(rb"/First\s+(\d+)", head)
        if not count or not first:
            continue
        begins = int(first.group(1))
        heads = body[:begins].split()
        for index in range(int(count.group(1))):
            try:
                number = int(heads[2 * index])
                at = int(heads[2 * index + 1])
            except (IndexError, ValueError):
                break
            if 2 * index + 3 < len(heads):
                ends = begins + int(heads[2 * index + 3])
            else:
                ends = len(body)
            out.setdefault(number, (body[begins + at:ends], None))
    return out


def _referenced(objects: dict, raw: bytes, key: bytes):
    """Follow ``/Key 5 0 R`` or read ``/Key << ... >>`` in place."""
    at = raw.find(key)
    if at < 0:
        return None
    rest = raw[at + len(key):]
    stripped = rest.lstrip()
    if stripped.startswith(b"<<"):
        return _slice_of(stripped, 0)
    pointer = _INDIRECT.match(stripped)
    if pointer:
        found = objects.get(int(pointer.group(1)))
        return found[0] if found else None
    return None


def _page_order(objects: dict) -> list:
    """Page object numbers in the order a reader turns them.

    Taken from the page tree rather than from where the streams happen to
    sit in the file, because file order agreeing with page order is a habit
    of PDF writers and not a rule of the format.
    """
    roots = [number for number, (head, _) in objects.items()
             if b"/Type/Pages" in head.replace(b"/Type /Pages", b"/Type/Pages")
             and b"/Parent" not in head]
    order: list = []
    seen: set = set()

    def walk(number: int) -> None:
        if number in seen:
            return
        seen.add(number)
        head, _ = objects.get(number, (b"", None))
        flat = head.replace(b"/Type /Page", b"/Type/Page")
        if b"/Type/Pages" in flat:
            at = flat.find(b"/Kids")
            if at < 0:
                return
            close = flat.find(b"]", at)
            for kid in _INDIRECT.finditer(flat[at:close if close > 0 else None]):
                walk(int(kid.group(1)))
        elif b"/Type/Page" in flat:
            order.append(number)

    for root in roots:
        walk(root)
    if not order:                             # a document with no tree left
        order = [number for number, (head, _) in objects.items()
                 if b"/Type/Page" in head.replace(b"/Type /Page", b"/Type/Page")
                 and b"/Kids" not in head]
        order.sort()
    return order


# -- what a font says its glyphs mean ----------------------------------------


def _letters(digits: bytes) -> str:
    try:
        return bytes.fromhex(digits.decode("ascii")).decode("utf-16-be", "replace")
    except ValueError:
        return ""


def _cmap(text: bytes) -> dict:
    """A font's ToUnicode table: glyph number to the letter it draws."""
    table: dict = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", text, re.S):
        pairs = _PAIR.findall(block)
        for index in range(0, len(pairs) - 1, 2):
            table[int(pairs[index], 16)] = _letters(pairs[index + 1])

    for block in re.findall(rb"beginbfrange(.*?)endbfrange", text, re.S):
        for line in re.finditer(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)",
                block, re.S):
            low = int(line.group(1), 16)
            high = int(line.group(2), 16)
            target = line.group(3)
            if target.startswith(b"["):
                for step, one in enumerate(_PAIR.findall(target)):
                    if low + step <= high:
                        table[low + step] = _letters(one)
            else:
                digits = target[1:-1]
                base = _letters(digits)
                if not base:
                    continue
                for step in range(0, high - low + 1):
                    table[low + step] = base[:-1] + chr(ord(base[-1]) + step)
    return table


def _fonts_on(page: bytes, objects: dict) -> dict:
    """Every font a page names, by the name the page calls it."""
    resources = _referenced(objects, page, b"/Resources")
    if resources is None:
        return {}
    listing = _referenced(objects, resources, b"/Font")
    if listing is None:
        return {}
    out: dict = {}
    for named in re.finditer(rb"/([A-Za-z0-9#+.\-]+)\s+(\d+)\s+0\s+R", listing):
        found = objects.get(int(named.group(2)))
        if not found:
            continue
        head = found[0]
        table: dict = {}
        pointer = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", head)
        if pointer:
            stream = objects.get(int(pointer.group(1)))
            if stream and stream[1]:
                table = _cmap(stream[1])
        out[named.group(1)] = _Font(wide=b"/Type0" in head, table=table)
    return out


# -- the words themselves ----------------------------------------------------


def _unescape(raw: bytes) -> bytes:
    out = raw[1:-1]
    for escape, plain in _ESCAPES.items():
        out = out.replace(escape, plain)
    return re.sub(rb"\\([0-7]{1,3})",
                  lambda m: bytes([int(m.group(1), 8) & 0xFF]), out)


def _read(shown: bytes, font: Optional[_Font]) -> str:
    if font is None:
        return shown.decode("cp1252", "replace")
    if font.wide:
        out = []
        for index in range(0, len(shown) - 1, 2):
            out.append(font.table.get((shown[index] << 8) | shown[index + 1],
                                      UNREADABLE_LETTER))
        return "".join(out)
    if font.table:
        return "".join(font.table.get(one, chr(one)) for one in shown)
    return shown.decode("cp1252", "replace")


def _words_in(stream: bytes, fonts: dict) -> str:
    """Every shown string in one content stream, in the order shown.

    Line ends are recovered from where the text sits on the page, not from
    where its strings were cut. IFSCA's typesetter opens and closes a text
    object for every word -- 219 of them on one page -- so breaking at each
    close would put a line end between every word, and "sub-section" would
    arrive as two lines to be mended back into "subsection".  A line end is
    a change in the height the words are drawn at, and nothing else.
    """
    pieces: list = []
    font: Optional[_Font] = None
    baseline: Optional[float] = None

    for step in re.finditer(
            rb"/([A-Za-z0-9#+.\-]+)\s+[\d.]+\s+Tf"
            rb"|\[((?:[^\[\]\\]|\\.)*)\]\s*TJ"
            rb"|((?:\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]*>))\s*(?:Tj|'|\")"
            rb"|((?:[+-]?[\d.]+\s+){6})Tm"
            rb"|((?:[+-]?[\d.]+\s+){2})(?:Td|TD)"
            rb"|(T\*)|(ET)", stream, re.S):
        named, array, single, matrix, moved, down, ended = step.groups()

        if named is not None:
            font = fonts.get(named)
            continue

        if matrix is not None or moved is not None:
            numbers = (matrix or moved).split()
            try:
                where = float(numbers[-1])
            except ValueError:
                continue
            if moved is not None:
                where = (baseline or 0.0) + where
            if baseline is None or abs(where - baseline) > 0.5:
                pieces.append("\n")
            baseline = where
            continue

        if down is not None:
            pieces.append("\n")
            continue

        if ended is not None:              # closing a text object moves nothing
            continue

        chunk = array if array is not None else single
        for part in re.finditer(
                rb"\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]*>", chunk, re.S):
            found = part.group(0)
            if found.startswith(b"<"):
                digits = re.sub(rb"\s", b"", found[1:-1])
                if len(digits) % 2:
                    digits += b"0"
                try:
                    pieces.append(_read(bytes.fromhex(digits.decode("ascii")),
                                        font))
                except ValueError:
                    continue
            else:
                pieces.append(_read(_unescape(found), font))

    return "".join(pieces)


@dataclass(frozen=True)
class Page:
    """One page's words, and whether they could be read at all."""

    number: int
    text: str

    @property
    def readable(self) -> bool:
        """Whether a sentence can honestly be looked for on this page.

        A page of glyph numbers no font would translate reads as a page of
        replacement characters, and looking for a clause in it would report
        the clause missing when the only thing missing is the font.
        """
        body = self.text.strip()
        if not body:
            return False
        known = sum(1 for one in body if one != UNREADABLE_LETTER)
        return known / len(body) >= ENOUGH_READ

    @property
    def guessed_at(self) -> int:
        """How many glyphs on this page no font would translate."""
        return self.text.count(UNREADABLE_LETTER)


def pages(path) -> list:
    """Every page of a PDF as text, in document order."""
    raw = Path(path).read_bytes()
    objects = _objects(raw)
    out: list = []
    for number in _page_order(objects):
        head, _ = objects.get(number, (b"", None))
        fonts = _fonts_on(head, objects)
        text = []
        at = head.find(b"/Contents")
        if at >= 0:
            close = head.find(b"/", at + len(b"/Contents") + 1)
            for stream in _INDIRECT.finditer(
                    head[at:close if close > at else None]):
                found = objects.get(int(stream.group(1)))
                if found and found[1]:
                    text.append(_words_in(found[1], fonts))
        out.append(Page(number=len(out) + 1, text="\n".join(text)))
    return out


def flatten(text: str) -> str:
    """One line of lowercase words, for comparing sentences.

    A published PDF breaks a sentence across a dozen shown strings and sets
    it in typographic quotes. Neither is a difference in what it says, so
    both are folded away before two sentences are compared.
    """
    for odd, plain in _SAME.items():
        text = text.replace(odd, plain)
    return " ".join(text.lower().split())


def mended(text: str, keep_hyphen: bool = False) -> str:
    """The same words with a line broken across a hyphen put back together.

    A hyphen at a line end is ambiguous in a way no reader can settle from
    the page. It may be the typesetter's, in which case "compli-" over
    "ance" is the one word *compliance*; or it may be the author's, in
    which case "sub-" over "regulation" is the hyphenated word
    *sub-regulation*. The document does not say which, and both occur in
    IFSCA's text -- the Fund Management Regulations break *sub-regulation*
    across a line on page 8 alone.

    So this is offered as a reading rather than as the reading, and
    :func:`find` tries every one. Picking a favourite would silently lose
    every clause written the other way.
    """
    for odd, plain in _SAME.items():
        text = text.replace(odd, plain)
    joint = "-" if keep_hyphen else ""
    return " ".join(re.sub(r"-\s*\n\s*", joint, text).lower().split())


#: The ways one page of a document can be read. They differ only in what a
#: hyphen at a line end is taken to have meant.
READINGS = (
    flatten,
    mended,
    lambda text: mended(text, keep_hyphen=True),
)

#: How many page breaks a single quoted clause may run over. Clause 3(4) of
#: the Fund Management Regulations runs over one -- it begins on page 5 and
#: its third category is on page 6 -- and a citation names the page a clause
#: begins on, which is what a reader turns to. Kept small because a
#: quotation that ran over three page breaks would not be an extract of a
#: clause, and allowing it would let two unrelated sentences a chapter apart
#: satisfy one extract.
SPANS_PAGES = 2


def as_amended(text: str) -> str:
    """The document read the way a compliance officer reads it.

    When IFSCA changes a word it does not reprint the sentence. It leaves
    the original in place, marks it with a footnote number and sets the
    replacement in square brackets, so the beneficial-ownership threshold
    arrives on page 5 as ``more than 5[ten] per cent.`` The rule in force is
    ten per cent; the ``5`` and the brackets are the publisher showing its
    working. Reading past that apparatus is not loosening the comparison,
    it is the difference between comparing rules and comparing typesetting.

    A marker whose bracket is never closed -- page 5 has one -- has only
    the marker itself taken off, because inventing a closing bracket would
    be deciding where an amendment ends, which is the regulator's to say.
    """
    out = re.sub(r"(?<![\w])(\d{1,3})\s*\[", "\x00", text)
    while "\x00" in out:
        at = out.index("\x00")
        close = out.find("]", at)
        depth = out.count("\x00", 0, close) if close >= 0 else 0
        if close >= 0 and depth == 1:
            out = out[:at] + out[at + 1:close] + out[close + 1:]
        else:
            out = out[:at] + out[at + 1:]
    return out


def find(wanted: str, pages_of: Sequence) -> Optional[int]:
    """The page a sentence appears on, or nothing.

    Exact, with two allowances for how the two sides are written rather
    than for what they say. An extract may mark words it has left out with
    ``...``, which is this file's own long-standing convention and the
    reason a shortened extract is honest instead of silently truncated; the
    parts on either side must still appear, in order, on one page. And the
    page may be read either as printed or with a hyphen at a line end mended
    (see :func:`mended`), because the document does not say which was meant.

    A clause may also run over a page break, in which case the page
    returned is the one it *begins* on -- the page a reader turns to.

    Nothing else is forgiven. A fuzzy match would report a clause as present
    when the document says something adjacent, which is the failure this
    exists to catch.
    """
    parts = [flatten(one) for one in as_amended(wanted).split(ELISION)]
    parts = [one for one in parts if one]
    if not parts:
        return None

    book = list(pages_of)
    #: Each page under each reading, done once. Reading a page costs the
    #: same whether one clause is looked for or twenty, and there are
    #: twenty-one.
    read = [[reading(as_amended(page.text)) for page in book]
            for reading in READINGS]

    for first in range(len(book)):
        for pages in read:
            head = pages[first]
            whole = " ".join(pages[first:first + SPANS_PAGES + 1])
            began = whole.find(parts[0])
            if began < 0 or began > len(head):
                continue                  # it starts on a later page, if at all
            at = began + len(parts[0])
            for part in parts[1:]:
                at = whole.find(part, at)
                if at < 0:
                    break
                at += len(part)
            else:
                return book[first].number
    return None


def unreadable(pages_of: Sequence) -> int:
    """How many pages could not be turned into letters.

    Reported rather than hidden: a clause that cannot be found because its
    page could not be read is a different result from a clause that is
    wrong, and the two must never be confused.
    """
    return sum(1 for page in pages_of if not page.readable)

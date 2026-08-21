"""Reading an Excel workbook without trusting it.

Banks and administrators hand over .xlsx, not .csv, and asking a founder's
pilot customer to "save as CSV first" is asking them to introduce the exact
encoding and date mangling this product exists to avoid. So the workbook is
read directly -- with the standard library only, because a dependency for
reading a zip of XML is a dependency for reading a zip of XML.

Only what the importer needs is implemented: the first worksheet, every cell
as the string a careful person would read off the screen. That still means
handling the traps the format actually springs:

* most text lives in a shared-strings table, sometimes split into styled
  runs that must be joined back together;
* dates are numbers wearing a format; which numbers are dates is declared in
  a styles table, against format codes, with two different day-zero epochs;
* empty cells are simply absent from the file, so the column each value
  belongs to must be read from the cell's own address, never counted;
* the first sheet is whichever the workbook says is first, not whichever
  file happens to be first in the archive.

Anything outside that -- formulas are read as their cached results, times
are dropped from date-times -- is by design: an import records what the
sheet showed, not what it computed.
"""

from __future__ import annotations

import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

#: The bytes every zip archive starts with. Files lie about their
#: extensions; magic bytes do not.
ZIP_MAGIC = b"PK\x03\x04"

#: How much XML one workbook may unpack to before this stops reading it.
#:
#: A .xlsx is a zip, and a zip compresses repetition extravagantly well. A
#: file of 1 MB built out of one repeated string unpacked to 360 MB of XML,
#: took thirty-four seconds and peaked at 1.3 GB of memory -- and the upload
#: limit is 20 MB, so the same trick at full size would have asked for
#: something like 26 GB and taken eleven minutes of a request thread. The
#: file passed every check the reader had, because every check was about
#: what arrived rather than about what it became.
#:
#: The number is not tight. A genuine fifty-thousand-row investor book
#: unpacks to 5.9 MB, so this is twenty times the largest real workbook
#: anyone has brought.
MOST_UNPACKED_BYTES = 128 * 1024 * 1024

#: Excel's built-in number formats that render as dates. Custom formats are
#: judged by their format code instead (see ``_is_date_code``).
_DATE_BUILTINS = frozenset(
    list(range(14, 23)) + list(range(45, 48)))

#: A format code renders a date if it uses day/month/year tokens outside
#: quoted literals. Colours like [Red] and quoted text like "days" must not
#: count, or amounts formatted as '0.00 "dyas"' start reading as dates.
_CODE_NOISE = re.compile(r'"[^"]*"|\[[^\]]*\]')


def is_workbook(path: Path) -> bool:
    """Whether this file is a zip archive, whatever its name claims."""
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == ZIP_MAGIC
    except OSError:
        return False


class _Bounded:
    """A workbook read with a ceiling on what it is allowed to become.

    Wraps the archive rather than replacing it, so every reader below keeps
    the call it already made. The budget is shared across members: a bomb
    split over five files is the same bomb.

    The declared size is checked first because it is free, and then the
    read is bounded anyway, because a zip states its own uncompressed
    sizes and a hostile one can state anything it likes.
    """

    def __init__(self, archive, budget: Optional[int] = None):
        self._archive = archive
        # Read at call time rather than bound as a default, so the ceiling
        # is one number in one place. A default argument is evaluated once
        # at import, which makes the constant look adjustable and silently
        # is not -- the first test written against it moved the module
        # attribute and watched the old value go on being used.
        self._budget = MOST_UNPACKED_BYTES if budget is None else budget
        self._left = self._budget

    def namelist(self):
        return self._archive.namelist()

    def _refuse(self):
        raise ValueError(
            f"this workbook unpacks to more than "
            f"{max(1, self._budget // 1024 // 1024)} MB, which no real client "
            f"book does -- a fifty-thousand-row sheet unpacks to about six. "
            f"Nothing was read. If the file is genuine, ask whoever produced "
            f"it to export the sheet you need on its own.")

    def read(self, name: str) -> bytes:
        try:
            declared = self._archive.getinfo(name).file_size
        except KeyError:
            declared = 0
        if declared > self._left:
            self._refuse()
        out = bytearray()
        with self._archive.open(name) as member:
            while True:
                chunk = member.read(min(65536, self._left - len(out) + 1))
                if not chunk:
                    break
                out += chunk
                if len(out) > self._left:
                    self._refuse()
        self._left -= len(out)
        return bytes(out)


def _local(tag: str) -> str:
    """The tag without its namespace: transitional and strict OOXML use
    different namespace URIs for identical documents, and matching on the
    local name reads both."""
    return tag.rsplit("}", 1)[-1]


#: The escape Excel uses for characters XML cannot carry: ``_x000D_`` is a
#: carriage return. One pass decodes it, and the self-escape ``_x005F_``
#: comes out right on the same pass because scanning resumes after each
#: replacement.
_CELL_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def _text_of(element) -> str:
    """Every piece of text under this element, joined.

    A shared string with styled runs is one string split across several
    ``t`` elements; a person reads it as one string, so this does too.
    Phonetic guide text is skipped: it is a pronunciation annotation over
    the name, and joining it in would garble every Japanese name.
    """
    parts: list[str] = []

    def walk(node) -> None:
        tag = _local(node.tag)
        if tag in ("rPh", "phoneticPr"):
            return
        if tag == "t" and node.text:
            parts.append(node.text)
        for child in node:
            walk(child)

    walk(element)
    return _CELL_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), "".join(parts))


def _is_date_code(code: str) -> bool:
    bare = _CODE_NOISE.sub("", code or "").lower()
    return bool(re.search(r"[ymd]", bare)) and not re.search(r"[#0?]", bare)


def _shared_strings(archive) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text_of(si) for si in root
            if _local(si.tag) == "si"]


def _date_styles(archive) -> frozenset:
    """Which cell-style indexes render as dates."""
    try:
        root = ElementTree.fromstring(archive.read("xl/styles.xml"))
    except KeyError:
        return frozenset()

    custom_dates = set()
    for node in root.iter():
        if _local(node.tag) == "numFmt":
            if _is_date_code(node.get("formatCode", "")):
                custom_dates.add(int(node.get("numFmtId", -1)))

    styles = set()
    for node in root.iter():
        if _local(node.tag) != "cellXfs":
            continue
        for position, xf in enumerate(n for n in node
                                      if _local(n.tag) == "xf"):
            fmt = int(xf.get("numFmtId", 0))
            if fmt in _DATE_BUILTINS or fmt in custom_dates:
                styles.add(position)
    return frozenset(styles)


def _first_sheet(archive) -> str:
    """The path of the worksheet the workbook lists first.

    The archive's own file order is meaningless: sheet3.xml can be the
    first tab. The workbook names its sheets in order and its relationships
    file says where each one lives.
    """
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels = ElementTree.fromstring(
        archive.read("xl/_rels/workbook.xml.rels"))

    targets = {}
    for rel in rels:
        # A workbook can open on a chart tab; a chart has no rows. Only
        # relationships that point at an actual worksheet count.
        if rel.get("Type", "").endswith("/worksheet"):
            targets[rel.get("Id")] = rel.get("Target", "")

    for node in workbook.iter():
        if _local(node.tag) != "sheet":
            continue
        # A hidden sheet is one the file's author took off the screen --
        # a lookup table, a working copy, last quarter's figures. Reading
        # it as "the spreadsheet" would import data nobody was looking at.
        if node.get("state", "visible") != "visible":
            continue
        rel_id = next((value for key, value in node.attrib.items()
                       if _local(key) == "id"), "")
        target = targets.get(rel_id, "")
        if target:
            if target.startswith("/"):
                return target.lstrip("/")
            return "xl/" + target
    return "xl/worksheets/sheet1.xml"


def _uses_1904(archive) -> bool:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    for node in workbook.iter():
        if _local(node.tag) == "workbookPr":
            return node.get("date1904", "0").lower() in ("1", "true")
    return False


def _column_of(reference: str) -> int:
    """'C7' -> 2. The cell says where it belongs; counting cells does not,
    because empty cells are not written to the file at all."""
    index = 0
    for letter in reference:
        if not letter.isalpha():
            break
        index = index * 26 + (ord(letter.upper()) - ord("A") + 1)
    return index - 1


def _serial_to_date(serial: float, since_1904: bool) -> str:
    """An Excel date serial as ISO, both epochs, leap-bug absorbed.

    The 1900 system pretends 1900 was a leap year; anchoring day zero on
    1899-12-30 makes every serial from 61 onward come out right, and no
    business spreadsheet carries dates from February 1900.
    """
    day_zero = date(1904, 1, 1) if since_1904 else date(1899, 12, 30)
    return (day_zero + timedelta(days=int(serial))).isoformat()


def _number(text: str) -> str:
    """A numeric cell as a person would read it: 5000, not 5000.0."""
    try:
        value = float(text)
    except ValueError:
        return text
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    # repr is the shortest form that reads back as the same number, which
    # matters for paise-precise amounts a fixed precision would truncate.
    return repr(value)


def grid(path: Path) -> tuple[list[list[str]], list[str]]:
    """The first worksheet as rows of strings, plus notes on the reading.

    Raises ``ValueError`` with a sentence a person can act on if the file
    is not a workbook this reader understands.
    """
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError(
            "this file has an Excel name but is not an Excel workbook; "
            "it may be renamed, truncated, or an older .xls file, which "
            "Excel can re-save as .xlsx")

    with archive:
        archive = _Bounded(archive)
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError(
                "this archive holds no workbook; if it came out of Excel, "
                "re-save it as an ordinary .xlsx")

        strings = _shared_strings(archive)
        date_styles = _date_styles(archive)
        since_1904 = _uses_1904(archive)
        sheet_path = _first_sheet(archive)
        sheet = ElementTree.fromstring(archive.read(sheet_path))

    rows: list[list[str]] = []
    for row in sheet.iter():
        if _local(row.tag) != "row":
            continue
        cells: list[str] = []
        for cell in (n for n in row if _local(n.tag) == "c"):
            column = _column_of(cell.get("r", ""))
            if column < 0:
                column = len(cells)
            while len(cells) <= column:
                cells.append("")

            kind = cell.get("t", "n")
            value = ""
            if kind == "inlineStr":
                value = _text_of(cell)
            else:
                v = next((n for n in cell if _local(n.tag) == "v"), None)
                raw = (v.text or "") if v is not None else ""
                if kind == "s":
                    try:
                        value = strings[int(raw)]
                    except (ValueError, IndexError):
                        value = ""
                elif kind == "b":
                    value = "TRUE" if raw == "1" else "FALSE"
                elif kind in ("str", "e"):
                    value = raw
                else:                      # a number, possibly wearing a date
                    style = int(cell.get("s", -1))
                    if raw and style in date_styles:
                        try:
                            value = _serial_to_date(float(raw), since_1904)
                        except (ValueError, OverflowError):
                            value = raw
                    else:
                        value = _number(raw) if raw else ""
            cells[column] = value
        rows.append(cells)

    notes = ["read from the first worksheet of an Excel workbook"]
    return rows, notes

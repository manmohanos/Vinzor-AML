"""Writing a workbook, so the book can leave in the format people work in.

A firm hands us a spreadsheet and gets back a website. That is a bad trade
for the person whose job is to work through two hundred investors: they
want to sort by what is missing, filter to the ones with no document, send
a tab to a colleague, and put a column of their own beside ours. Every one
of those is a spreadsheet operation and none of them is a web page.

**Written by hand, with nothing installed.** An .xlsx file is a zip of XML
parts, and the subset needed to produce a workbook every reader opens is
small enough to write out. The alternative is a dependency in a product
that has none, in a domain where every dependency is something a firm's
security review has to clear.

**Inline strings rather than a shared table.** The format offers a
dictionary of every distinct string, which is how real writers keep files
small. Skipping it costs bytes and removes the one part of this that could
silently corrupt a file -- an index into a table that has drifted. A
compliance export is read once and archived, not streamed.

**What goes in a cell is what a person can check.** No formulas, no macros,
nothing computed at open time. A number in this file is the number the log
held when it was written, and the sheet says on its face when that was --
a workbook whose figures move after it is signed is not evidence.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

#: Excel refuses a sheet name longer than this, and silently mangles a few
#: characters. Both are worth handling rather than producing a file that
#: opens with a repair dialogue.
MOST_SHEET_NAME = 31
FORBIDDEN_IN_NAME = r'[]:*?/\\'

#: The column width the header word roughly needs, in Excel's units. Not
#: exact -- the format has no way to measure text -- but close enough that
#: nobody opens the file to a wall of hashes.
PER_CHARACTER = 1.15
WIDEST = 62.0


@dataclass
class Sheet:
    """One tab: a heading row and the rows under it."""

    name: str
    columns: Sequence[str]
    rows: Sequence[Sequence[Any]] = field(default_factory=list)
    #: A sentence printed above the table, saying what this tab is and
    #: when it was taken. A spreadsheet that leaves the building without
    #: its date is one somebody will still be quoting in March.
    note: str = ""


def _safe_name(name: str, taken: set) -> str:
    clean = "".join(" " if ch in FORBIDDEN_IN_NAME else ch for ch in name)
    clean = clean.strip()[:MOST_SHEET_NAME] or "Sheet"
    candidate, number = clean, 2
    while candidate.lower() in taken:
        tail = f" {number}"
        candidate = clean[:MOST_SHEET_NAME - len(tail)] + tail
        number += 1
    taken.add(candidate.lower())
    return candidate


_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


#: The most characters Excel will hold in one cell. Not a number this
#: file chose -- past it the workbook is one Excel offers to repair, and a
#: compliance export that opens with a repair prompt reads as the export
#: being untrustworthy rather than the value being long. That reasoning was
#: already in this module for control characters; it applies here for the
#: same reason and was not applied.
MOST_CELL_CHARACTERS = 32_767

#: Said in the cell itself where a value was too long to carry, because the
#: alternative is a reader who cannot tell a truncated narration from a
#: short one. The count is the original length.
TOO_LONG = " [... {gone:,} more characters, too long for one cell]"


def _fit(text: str) -> str:
    """One cell's worth of a value, saying so if the rest would not fit."""
    if len(text) <= MOST_CELL_CHARACTERS:
        return text
    said = TOO_LONG.format(gone=len(text) - MOST_CELL_CHARACTERS)
    return text[:MOST_CELL_CHARACTERS - len(said)] + said


def _text(value: Any) -> str:
    """A cell's text, with what Excel cannot carry taken out or cut down.

    A control character in a name -- and imported data has them -- produces
    a file Excel offers to repair, which for a compliance export reads as
    the export being untrustworthy rather than the name being odd. A value
    longer than a cell holds does the same thing, so it is cut to fit and
    the cell says how much was left behind.

    Both are done before escaping, so the escaping cannot push a value back
    over the limit: one ampersand becomes five characters.
    """
    text = "" if value is None else str(value)
    text = _fit(_BAD_XML.sub("", text))
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell(row: int, column: int, value: Any) -> str:
    where = f"{_column_letter(column)}{row}"
    if _is_number(value):
        return f'<c r="{where}"><v>{value}</v></c>'
    if isinstance(value, bool):
        value = "Yes" if value else "No"
    return (f'<c r="{where}" t="inlineStr" s="0">'
            f"<is><t xml:space=\"preserve\">{_text(value)}</t></is></c>")


def _sheet_xml(sheet: Sheet) -> str:
    widths = []
    for index, heading in enumerate(sheet.columns):
        longest = len(str(heading))
        for row in sheet.rows:
            if index < len(row):
                longest = max(longest, len(str(row[index] or "")))
        widths.append(
            f'<col min="{index + 1}" max="{index + 1}" '
            f'width="{min(WIDEST, 4 + longest * PER_CHARACTER):.1f}" '
            f'customWidth="1"/>')

    lines = []
    at = 1
    if sheet.note:
        lines.append(f'<row r="{at}">{_cell(at, 0, sheet.note)}</row>')
        at += 2
    heading_row = "".join(
        _cell(at, index, heading).replace('s="0"', 's="1"')
        for index, heading in enumerate(sheet.columns))
    lines.append(f'<row r="{at}" ht="18" customHeight="1">{heading_row}</row>')
    frozen = at

    for row in sheet.rows:
        at += 1
        lines.append(f'<row r="{at}">' + "".join(
            _cell(at, index, value) for index, value in enumerate(row))
            + "</row>")

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main">'
        # The heading stays put while somebody scrolls two hundred
        # investors, and the whole table is filterable on open. Both are
        # the first two things anybody does to a sheet by hand.
        f'<sheetViews><sheetView workbookViewId="0">'
        f'<pane ySplit="{frozen}" topLeftCell="A{frozen + 1}" '
        f'activePane="bottomLeft" state="frozen"/>'
        f'</sheetView></sheetViews>'
        f'<cols>{"".join(widths)}</cols>'
        f'<sheetData>{"".join(lines)}</sheetData>'
        + (f'<autoFilter ref="A{frozen}:'
           f'{_column_letter(max(0, len(sheet.columns) - 1))}'
           f'{max(frozen, at)}"/>' if sheet.columns else "")
        + "</worksheet>"
    )


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/'
    'spreadsheetml/2006/main">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="3">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid">'
    '<fgColor rgb="FFEFEFEA"/><bgColor indexed="64"/></patternFill></fill>'
    '</fills>'
    '<borders count="2">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left/><right/><top/>'
    '<bottom style="thin"><color rgb="FFBFBFB8"/></bottom><diagonal/></border>'
    '</borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
    'borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" '
    'applyAlignment="1"><alignment vertical="top" wrapText="0"/></xf>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" '
    'applyFont="1" applyFill="1" applyBorder="1"/>'
    '</cellXfs>'
    '</styleSheet>'
)


def workbook(sheets: Sequence[Sheet]) -> bytes:
    """The whole file, as bytes ready to be handed over."""
    sheets = [s for s in sheets if s is not None] or [
        Sheet(name="Empty", columns=("Nothing to export",))]
    taken: set = set()
    named = [Sheet(name=_safe_name(s.name, taken), columns=s.columns,
                   rows=s.rows, note=s.note) for s in sheets]

    entries = [
        f'<sheet name="{_text(s.name)}" sheetId="{index + 1}" '
        f'r:id="rId{index + 1}"/>'
        for index, s in enumerate(named)
    ]
    rels = [
        f'<Relationship Id="rId{index + 1}" Type="http://schemas.'
        f'openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index + 1}.xml"/>'
        for index in range(len(named))
    ]
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index + 1}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.'
        f'spreadsheetml.worksheet+xml"/>' for index in range(len(named)))

    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types">'
            '<Default Extension="rels" ContentType="application/vnd.'
            'openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + overrides + "</Types>")
        archive.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.'
            'org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(entries)}</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships">'
            + "".join(rels)
            + f'<Relationship Id="rId{len(named) + 1}" Type="http://schemas.'
              f'openxmlformats.org/officeDocument/2006/relationships/styles" '
              f'Target="styles.xml"/></Relationships>')
        archive.writestr("xl/styles.xml", _STYLES)
        for index, sheet in enumerate(named):
            archive.writestr(f"xl/worksheets/sheet{index + 1}.xml",
                             _sheet_xml(sheet))
    return buffer.getvalue()

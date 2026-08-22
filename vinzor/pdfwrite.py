"""Writing a PDF, by hand, because the core may not take a dependency.

The report could be downloaded, and what came down was an HTML file. That is
fine for reading and wrong for sending: a compliance record goes to a board, a
regulator or an auditor, and the thing you attach to that email is a PDF.
An HTML file arrives looking like a web page somebody saved, opens differently
on every machine, and is trivially editable by whoever receives it.

``pdftext.py`` already reads this format for the clause register, written the
same way and for the same reason, so the format was already understood here.
What that module does not do is lay anything out, and layout is most of the
work: a document that runs off the bottom of the page is not a document.

**What this is.** Enough PDF to be a real PDF -- a catalogue, a page tree, one
content stream per page, a genuine cross-reference table -- plus the flowing
layout that a report needs: text that wraps at a measured width, pages that
break when they fill, headings that do not strand themselves at the foot of a
page, and a footer that numbers them.

**Widths are measured, not guessed.** The tables below are the real Helvetica
advance widths from the Adobe metrics. Wrapping by counting characters gives
lines that overflow on capitals and leave a third of the page empty on
lowercase, which looks like a broken document rather than a plain one.

**WinAnsi, and what falls outside it.** The base-14 fonts a PDF reader is
guaranteed to have cover Latin-1 and nothing else. A name in Devanagari or
Chinese cannot be drawn with them, and embedding a Unicode font would mean
shipping a several-megabyte typeface. So characters outside the encoding are
replaced, visibly, with a question mark rather than silently dropped: a name
that has lost its diacritics is a name an officer can still recognise as
wrong, and a name that has silently lost three characters is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

#: A4 in points, which is the paper every Indian authority issues on.
WIDTH, HEIGHT = 595, 842

#: Printer-safe margins.
LEFT, RIGHT, TOP, BOTTOM = 56, 56, 64, 58

#: Advance widths for Helvetica and Helvetica-Bold, characters 32..126, in
#: thousandths of the point size. Straight from the Adobe font metrics.
_REGULAR = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333,
    278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278,
    584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278,
    500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
    667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556,
    278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
    278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333,
    278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333,
    584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278,
    556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944,
    667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556,
    333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556,
    333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
)

REGULAR, BOLD = "F1", "F2"


def _widths(font: str) -> Sequence[int]:
    return _BOLD if font == BOLD else _REGULAR


def measure(text: str, font: str, size: float) -> float:
    """How wide this string will be drawn, in points."""
    table = _widths(font)
    total = 0
    for character in text:
        code = ord(character)
        # Anything outside the table is drawn as "?" and measured as one.
        total += table[code - 32] if 32 <= code <= 126 else table[31]
    return total * size / 1000.0


def wrap(text: str, font: str, size: float, width: float) -> list:
    """Break text into lines that fit, on spaces where possible.

    A word longer than the whole measure -- a URL, an identifier -- is cut
    rather than allowed to run off the edge, because a line that leaves the
    page takes its meaning with it.
    """
    lines, line = [], ""
    for word in (text or "").split():
        candidate = word if not line else line + " " + word
        if measure(candidate, font, size) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        while measure(word, font, size) > width and len(word) > 1:
            cut = len(word)
            while cut > 1 and measure(word[:cut], font, size) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    return lines or [""]


def _latin(text: str) -> str:
    """The string as WinAnsi will draw it.

    Replaced rather than dropped. A name that has lost a character to a
    substitution is visibly wrong; a name that has silently lost one is a
    different name that looks correct.
    """
    out = []
    for character in text or "":
        code = ord(character)
        out.append(character if 32 <= code <= 126 else
                   ("?" if code > 126 and _fold(character) is None
                    else (_fold(character) or "?")))
    return "".join(out)


#: The substitutions worth making before falling back to a question mark.
#: Typographic punctuation is what actually turns up here -- the wording in
#: briefing.py uses real dashes and curly quotes -- and turning an em dash
#: into "?" would pepper a compliance document with them.
_FOLDED = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", " ": " ",
    "•": "-", "−": "-", "·": "-",
}


def _fold(character: str):
    return _FOLDED.get(character)


def _escape(text: str) -> str:
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))


@dataclass
class Page:
    parts: list = field(default_factory=list)

    def text(self, x, y, size, font, body):
        self.parts.append(
            "BT /%s %.1f Tf 1 0 0 1 %.1f %.1f Tm (%s) Tj ET"
            % (font, size, x, y, _escape(_latin(body))))

    def rule(self, x1, y, x2, thickness=0.6, grey=0.0):
        self.parts.append("q %.2f G %.2f w %.1f %.1f m %.1f %.1f l S Q"
                          % (grey, thickness, x1, y, x2, y))

    def box(self, x, y, w, h, thickness=1.0, grey=0.0):
        self.parts.append("q %.2f G %.2f w %.1f %.1f %.1f %.1f re S Q"
                          % (grey, thickness, x, y, w, h))

    def fill(self, x, y, w, h, grey=0.94):
        self.parts.append("q %.2f g %.1f %.1f %.1f %.1f re f Q"
                          % (grey, x, y, w, h))

    def stream(self) -> bytes:
        return "\n".join(self.parts).encode("latin-1", "replace")


class Document:
    """A flowing document: write into it and it paginates itself."""

    def __init__(self, title: str = ""):
        self.title = title
        self.pages = [Page()]
        self.y = HEIGHT - TOP
        self.measure = WIDTH - LEFT - RIGHT

    @property
    def page(self) -> Page:
        return self.pages[-1]

    def room(self, needed: float) -> None:
        """Start a new page unless this much space is left."""
        if self.y - needed < BOTTOM:
            self.pages.append(Page())
            self.y = HEIGHT - TOP

    def gap(self, points: float) -> None:
        self.y -= points

    def paragraph(self, body, size=9.5, font=REGULAR, leading=None,
                  indent=0.0, grey=None) -> None:
        if not body:
            return
        leading = leading or size * 1.45
        for line in wrap(str(body), font, size, self.measure - indent):
            self.room(leading)
            if grey is not None:
                self.page.parts.append("q %.2f g" % grey)
            self.page.text(LEFT + indent, self.y - size, size, font, line)
            if grey is not None:
                self.page.parts.append("Q")
            self.y -= leading

    def heading(self, body, size=11.0) -> None:
        # Room for the heading and at least two lines under it, so a heading
        # never sits alone at the foot of a page with its section overleaf.
        self.room(size * 1.4 + 30)
        self.gap(10)
        self.page.text(LEFT, self.y - size, size, BOLD, str(body).upper())
        self.y -= size * 1.25
        self.page.rule(LEFT, self.y, WIDTH - RIGHT, 1.1)
        self.y -= 9

    def pair(self, label, value) -> None:
        """A label on the left and its value beside it."""
        size = 9.5
        column = 150.0
        lines = wrap(str(value or ""), REGULAR, size, self.measure - column)
        self.room(max(len(lines), 1) * size * 1.4)
        self.page.parts.append("q 0.35 g")
        self.page.text(LEFT, self.y - size, size, REGULAR, str(label or ""))
        self.page.parts.append("Q")
        for index, line in enumerate(lines):
            if index:
                self.room(size * 1.4)
            self.page.text(LEFT + column, self.y - size, size, BOLD, line)
            self.y -= size * 1.4
        self.y -= 2

    def bullet(self, body, size=9.5) -> None:
        leading = size * 1.4
        lines = wrap(str(body), REGULAR, size, self.measure - 14)
        for index, line in enumerate(lines):
            self.room(leading)
            if index == 0:
                self.page.text(LEFT, self.y - size, size, REGULAR, "-")
            self.page.text(LEFT + 14, self.y - size, size, REGULAR, line)
            self.y -= leading

    def quote(self, body, size=9.0) -> None:
        """An extract from the source, set apart by a rule down its side."""
        lines = wrap(str(body), REGULAR, size, self.measure - 26)
        needed = len(lines) * size * 1.45 + 6
        self.room(needed)
        top = self.y
        for line in lines:
            self.page.text(LEFT + 20, self.y - size, size, REGULAR, line)
            self.y -= size * 1.45
        self.page.parts.append("q 0.45 G 2 w %.1f %.1f m %.1f %.1f l S Q"
                               % (LEFT + 8, top - 1, LEFT + 8, self.y + 2))
        self.y -= 4

    def banner(self, heading: str, body: str) -> None:
        """A boxed warning. Black on white so it survives a fax."""
        size = 9.0
        lines = wrap(body, REGULAR, size, self.measure - 26)
        height = 20 + len(lines) * size * 1.45 + 12
        self.room(height + 8)
        top = self.y
        self.page.box(LEFT, top - height, self.measure, height, 1.6)
        self.page.text(LEFT + 13, top - 16, 9.5, BOLD, heading.upper())
        self.y = top - 30
        for line in lines:
            self.page.text(LEFT + 13, self.y - size, size, REGULAR, line)
            self.y -= size * 1.45
        self.y = top - height - 12

    # -- the file itself ---------------------------------------------------

    def _furniture(self) -> None:
        """The wordmark on the first page and a footer on all of them.

        Added last, so pagination is already settled and "page 2 of 5" can
        say five.
        """
        total = len(self.pages)
        for index, page in enumerate(self.pages, start=1):
            page.rule(LEFT, BOTTOM - 14, WIDTH - RIGHT, 0.5, grey=0.6)
            page.parts.append("q 0.4 g")
            page.text(LEFT, BOTTOM - 27, 7.5, REGULAR,
                      "Vinzor - IFSCA compliance workspace")
            stamp = "Page %d of %d" % (index, total)
            page.text(WIDTH - RIGHT - measure(stamp, REGULAR, 7.5),
                      BOTTOM - 27, 7.5, REGULAR, stamp)
            page.parts.append("Q")

    def bytes(self) -> bytes:
        import zlib

        self._furniture()
        objects = []
        # 1 catalogue, 2 pages, 3.. page objects, then contents, then fonts.
        count = len(self.pages)
        kids = " ".join("%d 0 R" % (3 + i) for i in range(count))
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(("<< /Type /Pages /Kids [%s] /Count %d >>"
                        % (kids, count)).encode())
        first_content = 3 + count
        font_regular, font_bold = first_content + count, first_content + count + 1
        for index in range(count):
            objects.append((
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                "/Resources << /Font << /%s %d 0 R /%s %d 0 R >> >> "
                "/Contents %d 0 R >>"
                % (WIDTH, HEIGHT, REGULAR, font_regular, BOLD, font_bold,
                   first_content + index)).encode())
        for page in self.pages:
            body = zlib.compress(page.stream())
            objects.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n"
                           % len(body) + body + b"\nendstream")
        for base in (b"/Helvetica", b"/Helvetica-Bold"):
            objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont "
                           + base + b" /Encoding /WinAnsiEncoding >>")

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
        title = _escape(_latin(self.title))[:180]
        out += (b"trailer\n<< /Size %d /Root 1 0 R /Info << /Title (%s) "
                b"/Producer (Vinzor) >> >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(objects) + 1, title.encode("latin-1", "replace"), start))
        return bytes(out)

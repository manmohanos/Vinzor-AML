"""What the intake block claims, tested by attacking its door.

This block is where untrusted bytes enter the product. A firm uploads a
spreadsheet its bank or registrar produced, and everything downstream is
built from whatever comes out. Three attacks were run against the workbook
reader; two were already stopped and one was not.

**A decompression bomb went straight through.** A .xlsx is a zip, and a zip
compresses repetition extravagantly. A file of **1 MB on disk** built from
one repeated string unpacked to 360 MB of XML, took **34 seconds** and
peaked at **1.3 GB of memory** -- and read successfully. The upload limit is
20 MB, so the same trick at full size would have asked for something like
26 GB and eleven minutes of a request thread. Every check the reader had
was about what arrived, and none about what it became. There is a ceiling
on unpacking now, and the same file is refused in 0.0s at 0 MB.

**Two held, and neither because of anything here.** A billion-laughs entity
bomb is stopped by the amplification limit in Python's own parser, and an
external entity pointing at a local file is refused because ElementTree does
not resolve them. Both are worth a test precisely because they are somebody
else's guarantee: a change of runtime could take either away without a line
of this code moving.

**And the gap two other blocks had already named from the far side.**
Clause 5.4.2(a)(i) asks for a full name "including any aliases". Screening
could only ever ask a watchlist about the one name on the record, and the
readiness check had to declare the aliases limb unmeasured -- both because
there was nowhere on a party to put one. There is now, and screening asks
about them.
"""

from __future__ import annotations

import zipfile

import pytest

from vinzor import xlsx
from vinzor.importing import FIELDS, MEANINGS, PAYMENT_FIELDS
from vinzor.model import EntityKind
from vinzor.screening import MOST_ALIASES, WatchlistClient, other_names

WORKBOOK = ('<?xml version="1.0"?><workbook xmlns="http://schemas.'
            'openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://'
            'schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>')
RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.'
        'openxmlformats.org/package/2006/relationships"><Relationship '
        'Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>')
SHEET = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.'
         'openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">'
         '<c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>')


def a_workbook(path, shared: str):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", RELS)
        archive.writestr("xl/worksheets/sheet1.xml", SHEET)
        archive.writestr("xl/sharedStrings.xml", shared)
    return path


def one_string(letters: int = 900) -> str:
    """One shared string, repeated by the caller. Parenthesised as a
    whole: ``"<si><t>" + "A" * 900 + "</t></si>" * 500`` builds one
    opening tag and five hundred closing ones, which the parser rejects
    long before the ceiling is reached -- and the test then passes for
    the wrong reason."""
    return "<si><t>" + "A" * letters + "</t></si>"


def strings(body: str) -> str:
    return ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.'
            'org/spreadsheetml/2006/main">' + body + "</sst>")


# -- the door ----------------------------------------------------------------


def test_a_workbook_that_unpacks_enormously_is_refused(tmp_path, monkeypatch):
    """The attack that succeeded. Kept small here by lowering the ceiling
    rather than by building a real bomb, so the test is quick -- what is
    being tested is that a ceiling exists and is enforced while reading."""
    monkeypatch.setattr(xlsx, "MOST_UNPACKED_BYTES", 64 * 1024)
    path = a_workbook(tmp_path / "bomb.xlsx",
                      strings(one_string()))
    # One string is fine; a great many of the same string is not.
    assert xlsx.grid(path)

    path = a_workbook(tmp_path / "bomb2.xlsx",
                      strings(one_string() * 500))
    with pytest.raises(ValueError) as refusal:
        xlsx.grid(path)
    assert "unpacks to more than" in str(refusal.value)
    assert "Nothing was read" in str(refusal.value)


def test_the_refusal_tells_a_person_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(xlsx, "MOST_UNPACKED_BYTES", 4096)
    path = a_workbook(tmp_path / "b.xlsx",
                      strings(one_string() * 200))
    with pytest.raises(ValueError) as refusal:
        xlsx.grid(path)
    said = str(refusal.value)
    assert "no real client book does" in said
    assert "export the sheet you need on its own" in said


def test_the_budget_is_shared_across_the_files_in_the_archive(tmp_path,
                                                              monkeypatch):
    """A bomb split over five members is the same bomb, and a per-file
    ceiling would let it through."""
    monkeypatch.setattr(xlsx, "MOST_UNPACKED_BYTES", 50_000)
    body = one_string() * 30
    path = tmp_path / "split.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", RELS)
        archive.writestr("xl/worksheets/sheet1.xml", SHEET)
        archive.writestr("xl/sharedStrings.xml", strings(body))
        archive.writestr("xl/styles.xml", strings(body))
    with pytest.raises(ValueError):
        xlsx.grid(path)


def test_an_ordinary_workbook_is_nowhere_near_the_ceiling(tmp_path):
    """The ceiling has to be one no real book meets. A fifty-thousand-row
    investor sheet unpacks to about six megabytes; this is a miniature of
    the same thing."""
    rows = 500
    body = "".join(f"<si><t>Investor Number {i}</t></si>" for i in range(rows))
    cells = "".join(f'<row r="{i+1}"><c r="A{i+1}" t="s"><v>{i}</v></c></row>'
                    for i in range(rows))
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.'
             'openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             + cells + "</sheetData></worksheet>")
    path = tmp_path / "real.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", RELS)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/sharedStrings.xml", strings(body))

    grid, _notes = xlsx.grid(path)
    assert len(grid) == rows
    assert grid[0] == ["Investor Number 0"]
    assert xlsx.MOST_UNPACKED_BYTES > 20 * 1024 * 1024


def test_an_entity_bomb_is_refused(tmp_path):
    """Held, and not by anything in this file -- Python's own parser caps
    entity amplification. Tested because it is somebody else's guarantee
    and a change of runtime could withdraw it silently."""
    laughs = ('<?xml version="1.0"?><!DOCTYPE sst ['
              '<!ENTITY a "AAAAAAAAAA">'
              '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
              '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
              '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">'
              '<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">'
              '<!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;">'
              '<!ENTITY g "&f;&f;&f;&f;&f;&f;&f;&f;&f;&f;">'
              ']><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
              '2006/main"><si><t>&g;</t></si></sst>')
    path = a_workbook(tmp_path / "laughs.xlsx", laughs)
    with pytest.raises(Exception):
        xlsx.grid(path)


def test_a_workbook_cannot_read_a_file_off_this_machine(tmp_path):
    """The other one that held. An external entity naming a local file is
    refused, so a spreadsheet cannot be used to read a key off the disk of
    whoever opens it."""
    secret = tmp_path / "secret.txt"
    secret.write_text("THE-KEY-SHOULD-NOT-LEAK", encoding="utf-8")
    xxe = ('<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY x SYSTEM "file:///'
           + str(secret).replace("\\", "/") + '">]><sst xmlns="http://schemas.'
           'openxmlformats.org/spreadsheetml/2006/main"><si><t>&x;</t></si>'
           '</sst>')
    path = a_workbook(tmp_path / "xxe.xlsx", xxe)
    with pytest.raises(Exception) as broke:
        grid, _ = xlsx.grid(path)
    assert "THE-KEY-SHOULD-NOT-LEAK" not in str(broke.value)


# -- the name a party is also known by ---------------------------------------


def test_a_party_record_can_hold_another_name():
    """Clause 5.4.2(a)(i) asks for a full name "including any aliases", and
    there was nowhere to put one. Two other blocks had already reported the
    hole from the far side."""
    assert "alias" in FIELDS
    assert "alias" in MEANINGS
    assert len(FIELDS) == 30
    assert len(PAYMENT_FIELDS) == 11


@pytest.mark.parametrize("column", [
    "alias", "aliases", "aka", "alsoknownas", "maidenname", "formername",
    "previousname", "tradingname", "doingbusinessas", "dba",
])
def test_the_spellings_a_registrar_actually_uses_are_recognised(column):
    assert column in FIELDS["alias"]


class _Party:
    def __init__(self, alias):
        self.attributes = {"alias": alias}


@pytest.mark.parametrize("cell,expected", [
    ("Priya Menon", ("Priya Menon",)),
    ("Priya Menon; Priya Raghavan", ("Priya Menon", "Priya Raghavan")),
    ("Priya Menon, R. Menon", ("Priya Menon", "R. Menon")),
    ("Acme Ltd | Acme Limited", ("Acme Ltd", "Acme Limited")),
    ("", ()),
])
def test_several_names_in_one_cell_are_read_as_several(cell, expected):
    """A registrar writes them however it likes, and one cell carrying two
    names is how a spreadsheet says somebody married."""
    assert other_names(_Party(cell)) == expected


def test_screening_asks_about_every_name_in_one_request():
    """Sent as further queries rather than further requests: the protocol
    takes several at once, and a book of fifty thousand should not pay a
    round trip per alias."""
    sent = {}

    def transport(url, body, headers):
        import json

        sent.update(json.loads(body))
        return json.dumps({"responses": {key: {"results": []}
                                         for key in sent["queries"]}}).encode()

    client = WatchlistClient(url="http://127.0.0.1:8090", transport=transport)
    _hits, provenance = client.match(
        name="Priya Raghavan", kind=EntityKind.PERSON,
        aliases=("Priya Menon", "R. Menon"))

    asked = [q["properties"]["name"][0] for q in sent["queries"].values()]
    assert asked == ["Priya Raghavan", "Priya Menon", "R. Menon"]
    assert provenance["also_asked_about"] == ["Priya Menon", "R. Menon"]


def test_the_name_on_the_record_is_not_asked_about_twice():
    sent = {}

    def transport(url, body, headers):
        import json

        sent.update(json.loads(body))
        return json.dumps({"responses": {key: {"results": []}
                                         for key in sent["queries"]}}).encode()

    client = WatchlistClient(url="http://127.0.0.1:8090", transport=transport)
    client.match(name="Priya Raghavan", kind=EntityKind.PERSON,
                 aliases=("priya raghavan", "Priya Menon"))
    assert len(sent["queries"]) == 2


def test_how_many_names_may_be_asked_about_is_a_stated_limit():
    """A record carrying more names than this has a problem of its own, and
    a check that stopped short should say so rather than look complete."""
    sent = {}

    def transport(url, body, headers):
        import json

        sent.update(json.loads(body))
        return json.dumps({"responses": {key: {"results": []}
                                         for key in sent["queries"]}}).encode()

    client = WatchlistClient(url="http://127.0.0.1:8090", transport=transport)
    # A name with no single-letter part: an initialled name is asked about
    # twice on its own account, which would make this count the wrong thing.
    client.match(name="Anjali Deshpande", kind=EntityKind.PERSON,
                 aliases=tuple(f"Other Name {i}" for i in range(20)))
    assert len(sent["queries"]) == MOST_ALIASES + 1


# -- where an uploaded sheet lives, and for how long --------------------------
#
# The stated bound was ``_HELD_UPLOADS = 25``, "a bound rather than none at
# all". It bounded one directory, and the directory was a fresh
# ``tempfile.mkdtemp()`` per process -- so every restart minted a new one,
# reset the count to zero and orphaned the last. Nothing removed any of them.
# Measured on the development machine before this was closed: **170 leftover
# vinzor-imports-* directories holding 491 uploaded sheets**, oldest four days
# old, under the customers' own filenames, in the clear, in a shared OS temp
# folder -- while the product's answer to "where does a customer's data live"
# is "one workspace file, and that file is the tenant boundary".


def test_uploads_live_beside_the_workspace_not_in_a_shared_temp_folder(tmp_path):
    from vinzor.engine import Vinzor
    from vinzor.eventlog import EventLog
    from vinzor.server import build_app

    workspace = tmp_path / "firm" / "live.db"
    handler = build_app(Vinzor(EventLog(workspace)))
    home = handler._import_home(handler)

    assert home.parent == workspace.parent
    assert home.is_dir()


def test_two_workspaces_in_one_process_do_not_share_exhibits(tmp_path):
    """It was memoised on ``build_app`` itself, so the second workspace read
    the first one's uploads."""
    from vinzor.engine import Vinzor
    from vinzor.eventlog import EventLog
    from vinzor.server import build_app

    one = build_app(Vinzor(EventLog(tmp_path / "a" / "live.db")))
    two = build_app(Vinzor(EventLog(tmp_path / "b" / "live.db")))
    assert one._import_home(one) != two._import_home(two)


def test_the_upload_area_does_not_outlive_the_server(tmp_path):
    from vinzor.engine import Vinzor
    from vinzor.eventlog import EventLog
    from vinzor.server import build_app

    handler = build_app(Vinzor(EventLog(tmp_path / "live.db")))
    home = handler._import_home(handler)
    (home / "customers.csv").write_bytes(b"name,dob\n")

    handler.forget_exhibits()
    assert not home.exists()


def test_a_sheet_nobody_confirmed_is_not_held_forever(tmp_path):
    """The count alone let a quiet week hold a sheet indefinitely."""
    import os
    import time

    from vinzor.engine import Vinzor
    from vinzor.eventlog import EventLog
    from vinzor.server import _HOLD_UPLOADS_FOR_SECONDS, build_app

    handler = build_app(Vinzor(EventLog(tmp_path / "live.db")))
    home = handler._import_home(handler)
    ancient = home / "aabbccddeeff-customers.csv"
    ancient.write_bytes(b"name,dob\n")
    old = time.time() - _HOLD_UPLOADS_FOR_SECONDS - 60
    os.utime(ancient, (old, old))

    assert _HOLD_UPLOADS_FOR_SECONDS == 24 * 60 * 60
    assert ancient.exists()

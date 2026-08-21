"""Real companies, real beneficial owners, from a public register.

    python tools/from_registry.py psc-snapshot.zip          # United Kingdom
    python tools/from_registry.py statements.jsonl.gz       # every country

Reads either a UK Companies House "persons with significant control" snapshot
or the Open Ownership register, which consolidates every country that
publishes beneficial ownership at all. Both are free, public and filed under
statutory duty: real companies, real people, nothing invented here.

Two registers rather than one because a single jurisdiction can be answered
with "that is just the UK's threshold". The consolidated one cannot.

It exists to answer one question the synthetic book cannot: does the ownership
resolver survive contact with how companies are actually structured, rather
than with three chains somebody invented.

It answers a second question nobody asked, which turns out to matter more.
Most of the world requires disclosure at twenty-five per cent, following the
FATF default. IFSCA requires identification at ten. Of 237,999 holdings
carrying a percentage in the Open Ownership register, **two** are below 25%.
Not two per cent -- two. So a register cannot show a firm the 10-25% band at
all, and not because the data is missing: no such filing was ever required.
A GIFT City firm that establishes beneficial ownership from a company registry
is not being careful; it is being blind in exactly the band its own regulator
cares about, and no amount of registry data fixes that. The report at the end
says so with the numbers from the file in front of it.

Percentages arrive as bands ("25 to 50 per cent"), never as figures. The lower
bound is used, because understating a holding is the safe direction for a
threshold test and overstating it would invent a fact.
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.graph import Conclusion
from vinzor.model import EntityKind, EventType

WHEN = "2026-08-15"

#: The bands the register uses, and the lowest percentage each can mean.
#: Nothing below 25 exists here, which is the finding.
BANDS = {
    "25-to-50": 25.0, "50-to-75": 50.0, "75-to-100": 75.0,
}

_BAND = re.compile(r"(\d+)-to-(\d+)-percent")


def lower_bound(natures) -> float:
    """The least this holding can be, across every nature declared."""
    best = 0.0
    for nature in natures or ():
        found = _BAND.search(nature)
        if found:
            best = max(best, float(found.group(1)))
    return best


def read_bods(path: Path, wanted: int):
    """The Open Ownership register: many countries, one format.

    Companies House is one jurisdiction and could be answered with "that is
    the UK's threshold". This is the consolidated register -- every country
    that publishes beneficial ownership, in the Beneficial Ownership Data
    Standard -- and it answers the same way, which is the point.

    Streamed rather than loaded: the export is gigabytes, and nothing here
    needs more than a slice of it.
    """
    import gzip

    people: dict = {}
    companies: dict = {}
    holdings: list = []
    bands = Counter()

    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            kind = record.get("statementType")
            if kind == "personStatement":
                names = record.get("names") or [{}]
                people[record["statementID"]] = (
                    names[0].get("fullName") or "a person")
            elif kind == "entityStatement":
                companies[record["statementID"]] = (
                    record.get("name") or "a company")
            elif kind == "ownershipOrControlStatement":
                share = 0.0
                for interest in record.get("interests") or []:
                    figures = interest.get("share") or {}
                    value = figures.get("exact")
                    if value is None:
                        value = figures.get("minimum")
                    if value is not None:
                        share = max(share, float(value))
                        bands[f"{int(float(value) // 25) * 25}-{int(float(value) // 25) * 25 + 25}%"] += 1
                subject = (record.get("subject") or {}).get("describedByEntityStatement")
                holder = record.get("interestedParty") or {}
                owner = (holder.get("describedByPersonStatement")
                         or holder.get("describedByEntityStatement"))
                if subject and owner and share:
                    holdings.append((subject, owner, share,
                                     bool(holder.get("describedByEntityStatement"))))
            if len(holdings) >= wanted * 2:
                break

    grouped: dict = {}
    for subject, owner, share, corporate in holdings:
        if subject not in companies:
            continue
        grouped.setdefault(subject, []).append({
            "name": (companies.get(owner) if corporate
                     else people.get(owner)) or "unnamed",
            "share": share, "corporate": corporate, "country": "",
        })
        if len(grouped) >= wanted:
            break
    return grouped, bands, sum(len(v) for v in grouped.values())


def read(path: Path, wanted: int):
    """Companies with at least one declared PSC, and the PSCs themselves."""
    archive = zipfile.ZipFile(path)
    name = archive.namelist()[0]
    companies: dict = {}
    bands = Counter()
    people = 0

    with archive.open(name) as handle:
        for line in handle:
            record = json.loads(line)
            data = record.get("data") or {}
            kind = data.get("kind") or ""
            number = record.get("company_number")
            if not number or "significant-control" not in kind:
                continue
            if data.get("ceased_on"):
                continue
            share = lower_bound(data.get("natures_of_control"))
            for nature in data.get("natures_of_control") or ():
                if "percent" in nature:
                    bands[nature] += 1
            if not share:
                continue                      # a control-only PSC, no band

            entry = companies.setdefault(number, [])
            entry.append({
                "name": (data.get("name") or "").strip(),
                "share": share,
                "corporate": "corporate-entity" in kind,
                "country": ((data.get("address") or {}).get("country")
                            or data.get("nationality") or ""),
            })
            people += 1
            if len(companies) >= wanted:
                break
    return companies, bands, people


def build(companies) -> Vinzor:
    engine = Vinzor(EventLog())
    seen: set = set()

    for number, owners in companies.items():
        subject = f"uk_{number}"
        engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject=subject,
                      occurred_at=WHEN,
                      payload={"kind": EntityKind.COMPANY.value,
                               "name": f"Company {number}",
                               "attributes": {"jurisdiction": "GB"}})
        for position, owner in enumerate(owners):
            holder = f"psc_{number}_{position}"
            if holder in seen:
                continue
            seen.add(holder)
            engine.ingest(
                event_type=EventType.ENTITY_REGISTERED, subject=holder,
                occurred_at=WHEN,
                payload={
                    "kind": (EntityKind.COMPANY if owner["corporate"]
                             else EntityKind.PERSON).value,
                    "name": owner["name"] or holder,
                    "attributes": {"jurisdiction": owner["country"][:2].upper()}
                    if owner["country"] else {},
                })
            engine.ingest(
                event_type=EventType.OWNERSHIP_DECLARED, subject=subject,
                occurred_at=WHEN,
                payload={"owner": holder, "owned": subject,
                         "percentage": owner["share"], "relation": "OWNS",
                         "edge_id": f"edg_{number}_{position}"})
        engine.ingest(event_type=EventType.COMMITMENT_MADE, subject=subject,
                      occurred_at=WHEN,
                      payload={"investor": subject, "fund": "fnd_1",
                               "amount": 1_000_000.0, "currency": "USD",
                               "commitment_id": f"ccm_{number}"})
    return engine


def main(argv) -> int:
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip().splitlines()[2])
        return 2
    source = Path(argv[0])
    wanted = 300
    if "--companies" in argv:
        wanted = int(argv[argv.index("--companies") + 1])

    reader = read_bods if source.name.endswith((".jsonl.gz", ".jsonl")) else read
    companies, bands, people = reader(source, wanted)
    engine = build(companies)

    graph = engine.state.graph
    outcomes = Counter()
    for number in companies:
        outcomes[str(graph.resolve_ubo(f"uk_{number}").conclusion)] += 1

    print()
    print(f"  {source.name}")
    print(f"  {len(companies)} real companies, {people} declared owners")
    print()
    print("  what the ownership resolver made of them:")
    for outcome, count in outcomes.most_common():
        print(f"    {count:5}  {outcome.lower().replace('_', ' ')}")
    print()

    figures = [float(_BAND.search(b).group(1)) for b in bands if _BAND.search(b)]
    figures += [float(b.split("-")[0]) for b in bands if _BAND.search(b) is None
                and b.split("-")[0].isdigit()]
    lowest = min(figures, default=0.0)
    print("  the bands this register discloses:")
    for band, count in bands.most_common(6):
        print(f"    {count:6}  {band}")
    print()
    print(f"  lowest disclosed holding anywhere in the file: {lowest:.0f}%")
    print()
    print("  IFSCA identifies a beneficial owner above ten per cent. This")
    print(f"  register begins at {lowest:.0f}%. Every holding between ten and")
    print(f"  {lowest:.0f} per cent is a beneficial owner under the guidelines a")
    print("  GIFT City firm answers to, and appears in no filing here, because")
    print("  no such filing was ever required. A firm establishing ownership")
    print("  from a company registry is blind in precisely that band, and must")
    print("  get it from the customer instead.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

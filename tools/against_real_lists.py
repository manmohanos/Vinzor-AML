"""Screen genuinely listed people, and people who are plainly nobody.

    python tools/against_real_lists.py            # 25 of each
    python tools/against_real_lists.py --each 60

The planted benchmark next door proves the rules behave as written. It cannot
prove the screening finds a real sanctioned party, because every name in it is
invented -- the answer key and the data come from the same place.

This one takes its answers from outside. Names are drawn from the sanctions
index itself, so a name here is on a real list by construction: if a party
called that reaches an investor book and nothing fires, that is a miss, and no
argument about thresholds makes it not one. The control group is generated
nonsense that is on no list anywhere, and every one of those that fires is a
false positive an officer would have had to clear by hand.

Both numbers matter and they pull against each other. A threshold low enough
to catch everything flags half the book; one high enough to stay quiet misses
the party you needed. Reported separately, never averaged into one figure that
hides which way the system is failing.
"""

from __future__ import annotations

import json
import os
import random
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _settings import load as _load_settings

# Before any VINZOR_* variable is read. Without this the tool defaulted to a
# scope the index does not have, drew nothing, and printed a perfect score.
_load_settings()

from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EntityKind, EventType
from vinzor.screening import ScreeningUnavailable, WatchlistClient, screen

INDEX = os.environ.get("VINZOR_ES_URL", "http://127.0.0.1:9200")
SERVICE = os.environ.get("VINZOR_SCREENING_URL", "http://127.0.0.1:8090")
#: The same default ``WatchlistClient`` uses. It said ``"sanctions"``, which
#: is a scope no index on this machine has, and Elasticsearch answers a
#: wildcard that matches nothing with HTTP 200 and no hits -- so nothing
#: raised and nothing was measured.
SCOPE = os.environ.get("VINZOR_SCREENING_SCOPE", "default")
WHEN = "2026-08-15"

#: Invented from common syllables. The point is that no list holds them, so
#: any finding is unambiguously a false positive rather than an argument.
FIRST = ("Tarun", "Nilay", "Bhavik", "Ishaan", "Devansh", "Kartik", "Mihir",
         "Rohit", "Sarvesh", "Yash", "Advik", "Chirag", "Harsh", "Nikhil")
LAST = ("Bhandari", "Chaudhari", "Deshpande", "Gokhale", "Hegde", "Kulkarni",
        "Mahajan", "Nadkarni", "Pandit", "Rane", "Sathe", "Tendulkar")


def listed_people(how_many: int) -> list[dict]:
    """Real entries, straight out of the index this system screens against."""
    query = {
        "size": how_many * 3,
        "query": {"function_score": {
            "query": {"bool": {"filter": [{"term": {"schema": "Person"}}]}},
            "random_score": {"seed": 20260815, "field": "_seq_no"},
        }},
        "_source": ["caption", "datasets", "properties.birthDate",
                    "properties.nationality"],
    }
    request = urllib.request.Request(
        f"{INDEX}/yente-entities-{SCOPE}*/_search",
        data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        hits = json.loads(response.read())["hits"]["hits"]

    people = []
    for hit in hits:
        source = hit["_source"]
        caption = (source.get("caption") or "").strip()
        # A one-word or absurdly long caption is a data artefact, not a name a
        # firm would ever have on its book.
        if not (2 <= len(caption.split()) <= 5) or len(caption) > 60:
            continue
        properties = source.get("properties") or {}
        people.append({
            "name": caption,
            "datasets": source.get("datasets") or [],
            "dob": (properties.get("birthDate") or [None])[0],
            "nationality": (properties.get("nationality") or [None])[0],
        })
        if len(people) == how_many:
            break
    return people


def invented(how_many: int) -> list[dict]:
    shuffle = random.Random(20260815)
    seen, out = set(), []
    while len(out) < how_many:
        name = f"{shuffle.choice(FIRST)} {shuffle.choice(LAST)}"
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "datasets": [], "dob": None,
                    "nationality": "IN"})
    return out


#: How a real book differs from a sanctions list. Drawn verbatim, a listed
#: name matches itself at 1.00 and proves only that the wire works. These are
#: the ways the same human arrives spelled differently: a firm types what the
#: passport says, the list holds what an agency transliterated, and a middle
#: name survives in one and not the other.
def _variants(name: str) -> dict:
    parts = name.split()
    out = {}

    if len(parts) >= 3:
        out["middle name dropped"] = f"{parts[0]} {parts[-1]}"
    if len(parts) >= 2:
        out["surname first"] = f"{parts[-1]} {' '.join(parts[:-1])}"
        out["initial for first name"] = f"{parts[0][0]}. {' '.join(parts[1:])}"

    swapped = name
    for a, b in (("ph", "f"), ("kh", "k"), ("ee", "i"), ("oo", "u"),
                 ("y", "i"), ("ou", "u")):
        if a in swapped.lower():
            index = swapped.lower().index(a)
            swapped = swapped[:index] + b + swapped[index + len(a):]
            break
    if swapped != name:
        out["transliterated"] = swapped

    # One transposed pair, the commonest typing error there is.
    letters = [i for i, c in enumerate(name) if c.isalpha()]
    if len(letters) > 6:
        i = letters[len(letters) // 2]
        if i + 1 < len(name) and name[i + 1].isalpha():
            out["one typo"] = name[:i] + name[i + 1] + name[i] + name[i + 2:]
    return out


#: A check that did not happen. Its own answer, because "quiet" and "never
#: asked" look identical in a count and mean opposite things.
NOT_PERFORMED = "not performed"


def check(party: dict, client: WatchlistClient) -> tuple[bool, str]:
    """Put one party through the ordinary path. Returns (flagged, detail)."""
    engine = Vinzor(EventLog())
    attributes = {}
    if party.get("nationality"):
        attributes["nationality"] = str(party["nationality"]).upper()[:2]
    if party.get("dob"):
        attributes["dob"] = party["dob"]
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="p1",
                  occurred_at=WHEN,
                  payload={"kind": EntityKind.PERSON.value,
                           "name": party["name"], "attributes": attributes})
    try:
        results = screen(engine, "p1", screened_at=WHEN, client=client)
    except ScreeningUnavailable:
        return False, NOT_PERFORMED

    matched = [r for r in results if (r.event.payload or {}).get("matched")]
    if not matched:
        return False, "nothing found"
    basis = matched[0].event.payload.get("basis") or {}
    return True, f"{basis.get('caption', '?')} at {basis.get('score', 0):.2f}"


def main(argv) -> int:
    each = 25
    if "--each" in argv:
        each = int(argv[argv.index("--each") + 1])

    client = WatchlistClient(url=SERVICE, scope=SCOPE)
    try:
        listed = listed_people(each)
    except Exception as problem:
        print(f"  could not read the index at {INDEX}: {problem}")
        print("  start it with:  powershell -File selfhost/yente.ps1 start")
        return 2

    print()
    print(f"  index: {SERVICE}  scope: {SCOPE}")
    print(f"  {len(listed)} genuinely listed people, {each} invented ones")
    print()

    if not listed:
        # Refuse rather than report. This is the only measurement in the
        # product whose ground truth nobody on this side wrote, and it is the
        # number that would decide whether screening is fit to sell -- so an
        # empty draw has to stop, not print 0/0 beside a perfect control and
        # exit clean.
        print(f"  the index at {INDEX} holds no Person under scope "
              f"{SCOPE!r}, so nothing was measured.")
        print("  Set VINZOR_SCREENING_SCOPE to a scope that exists, for "
              "example: default")
        return 2

    caught, missed, never_asked = 0, [], 0
    for party in listed:
        flagged, detail = check(party, client)
        if detail == NOT_PERFORMED:
            never_asked += 1
        elif flagged:
            caught += 1
        else:
            missed.append((party["name"], party["datasets"][:2], detail))

    quiet, wrong, unchecked = 0, [], 0
    for party in invented(each):
        flagged, detail = check(party, client)
        if detail == NOT_PERFORMED:
            # Counted apart from "quiet". A check that never happened is not
            # a control that stayed silent, and folding the two together is
            # how a screening outage scores as a clean run.
            unchecked += 1
        elif flagged:
            wrong.append((party["name"], detail))
        else:
            quiet += 1

    # How far the same person can drift before the match is lost.
    if "--variants" in argv:
        from collections import Counter
        seen, hit = Counter(), Counter()
        for party in listed[:40]:
            for kind, spelling in _variants(party["name"]).items():
                seen[kind] += 1
                flagged, _ = check({**party, "name": spelling}, client)
                hit[kind] += 1 if flagged else 0
        print("  the same person, spelled differently:")
        for kind in sorted(seen, key=lambda k: -(hit[k] / seen[k])):
            share = hit[kind] / seen[kind]
            print(f"    {kind:24} caught {hit[kind]:3}/{seen[kind]:<3} "
                  f"{share:5.0%}")
        print()

    if missed:
        print("  listed, and NOT caught:")
        for name, datasets, detail in missed:
            print(f"    {name[:42]:42} {', '.join(datasets)[:28]:28} {detail}")
        print()
    if wrong:
        print("  invented, and flagged anyway:")
        for name, detail in wrong:
            print(f"    {name[:42]:42} matched {detail}")
        print()

    print(f"  caught, of people really on a list   "
          f"{caught}/{len(listed) - never_asked}")
    if never_asked:
        print(f"  listed people never checked at all   "
              f"{never_asked}/{len(listed)}  (the watchlist did not answer)")
    print(f"  quiet, of people on no list at all   {quiet}/{each - unchecked}")
    if unchecked:
        print(f"  not checked at all                   {unchecked}/{each}"
              f"  (the watchlist did not answer)")
    print()
    print("  A miss is a party who walks in unnoticed. A false positive is an")
    print("  hour of someone's day. Neither number is the product's score on")
    print("  its own, and averaging them would hide which way it fails.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

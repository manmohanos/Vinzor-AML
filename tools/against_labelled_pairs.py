"""Our comparison, marked against somebody else's answer key.

    python tools/against_labelled_pairs.py pairs.jsonl
    python tools/against_labelled_pairs.py pairs.jsonl --limit 2000

OpenSanctions publishes the pairs its own analysts have judged: two entity
records and a verdict on whether they are the same person. Roughly half a
gigabyte of them, at

    https://data.opensanctions.org/contrib/training/pairs.json

Every other measurement in this repository grades our own homework. The
planted benchmark has answers we wrote; the variant probe has misspellings we
invented, chosen -- however carefully -- by the same person who wrote the code
being tested. This file is the first judgement here that nobody on this side
had any hand in.

What it grades is ``compare.py``: the code that decides whether the investor
on our book is the party on the list. That is ours. The search that produced
the candidate is OpenSanctions' matcher, and no number below is a claim about
their work.

Two mistakes, counted separately, because they are not the same mistake. A
pair judged the same that we call DIFFERENT is a sanctioned party cleared and
forgotten. A pair judged different that we let through as a possible match is
an officer's afternoon. The first is the one that ends a firm.

Pairs the analysts marked "unsure" are reported and excluded from scoring: a
disagreement with a judgement its own author could not settle says nothing
about us.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.compare import Verdict, compare_names

#: Verdicts that mean "this could be the same party, put it in front of a
#: person". Only DIFFERENT closes the question without a human.
LETS_THROUGH = (Verdict.IDENTICAL, Verdict.EQUIVALENT, Verdict.PARTIAL,
                Verdict.UNKNOWN)


def names_of(side: dict) -> list[str]:
    properties = side.get("properties") or {}
    names = list(properties.get("name") or [])
    if side.get("caption"):
        names.append(side["caption"])
    return [n for n in names if isinstance(n, str) and n.strip()]


def our_verdict(left: dict, right: dict) -> Verdict:
    """The kindest verdict across every recorded spelling of each side.

    A listed party carries aliases, and so does a customer record. Comparing
    only the captions would fail a pair that any officer would match on sight,
    and would flatter nothing: taking the best available reading is what the
    product does when it screens.
    """
    ours, theirs = names_of(left), names_of(right)
    if not ours or not theirs:
        return Verdict.UNKNOWN
    best = Verdict.DIFFERENT
    order = {v: i for i, v in enumerate(
        (Verdict.IDENTICAL, Verdict.EQUIVALENT, Verdict.PARTIAL,
         Verdict.UNKNOWN, Verdict.DIFFERENT))}
    for a in ours[:6]:
        for b in theirs[:6]:
            verdict = compare_names(a, b).verdict
            if order[verdict] < order[best]:
                best = verdict
    return best


def main(argv) -> int:
    if not argv or argv[0].startswith("--"):
        print("  usage: python tools/against_labelled_pairs.py pairs.jsonl")
        return 2
    source = Path(argv[0])
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 0

    judged = Counter()
    missed: list = []          # judged the same, we said DIFFERENT
    extra: list = []           # judged different, we let through
    verdicts = Counter()
    unsure = 0

    with source.open(encoding="utf-8") as handle:
        for count, line in enumerate(handle):
            if limit and count >= limit:
                break
            record = json.loads(line)
            judgement = record.get("judgement")
            if judgement == "unsure":
                unsure += 1
                continue
            if judgement not in ("positive", "negative"):
                continue

            verdict = our_verdict(record.get("left") or {},
                                  record.get("right") or {})
            verdicts[f"{judgement}/{verdict.value}"] += 1
            judged[judgement] += 1
            through = verdict in LETS_THROUGH

            if judgement == "positive" and not through:
                missed.append(record)
            elif judgement == "negative" and through:
                extra.append(record)

    same = judged["positive"]
    different = judged["negative"]
    caught = same - len(missed)
    quiet = different - len(extra)

    print()
    print(f"  {source.name}")
    print(f"  {same + different} pairs judged by OpenSanctions analysts "
          f"({same} the same, {different} different)")
    print(f"  {unsure} marked unsure and excluded from scoring")
    print()
    print(f"  same party, and we agreed        {caught:5}/{same:<5} "
          f"{caught / same:6.1%}" if same else "")
    print(f"  different party, and we agreed   {quiet:5}/{different:<5} "
          f"{quiet / different:6.1%}" if different else "")
    print()
    print("  what we said, against what they said:")
    for key, n in sorted(verdicts.items(), key=lambda kv: -kv[1]):
        theirs, ours = key.split("/")
        print(f"    they said {theirs:9} we said {ours:10} {n:6}")
    print()

    if missed:
        print("  judged the same, and we closed it -- the dangerous half:")
        for record in missed[:6]:
            a = (names_of(record["left"]) or ["?"])[0]
            b = (names_of(record["right"]) or ["?"])[0]
            print(f"    {a[:34]:34} vs {b[:34]}")
        if len(missed) > 6:
            print(f"    ... and {len(missed) - 6} more")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

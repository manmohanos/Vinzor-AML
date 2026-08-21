"""Our name comparison, scored the way the published benchmark scores.

    python tools/pairs_protocol.py pairs.json
    python tools/pairs_protocol.py pairs.json --sample 10000

``against_labelled_pairs.py`` already grades us against OpenSanctions'
analyst judgements, but it reads from the top of the file and reports
agreement rates. Neither is comparable to anything published. This does
two things differently, so a number from here can sit next to a number
from the literature:

* **Label-stratified random sampling at seed 42**, which is the protocol
  in the OpenSanctions Pairs benchmark paper (arXiv 2603.11051). Reading
  the first N lines of a file somebody else ordered is not a sample.
* **Precision, recall and F1 on the same-party class**, which is what the
  paper reports, rather than two agreement percentages.

Read the caveats before quoting anything from here.

**We are not solving the same problem as the baselines.** The paper's
matchers see every FollowTheMoney property -- birth dates, nationalities,
passport numbers, addresses, up to 132 fields -- and decide whether two
records are the same entity. ``compare_names`` compares *names*. A lower
F1 here is the expected consequence of answering a narrower question, not
evidence that our matching is worse than theirs. The run reports a second
figure with birth dates admitted, which is closer to what the product
actually does when an officer looks at a file, and the gap between the two
is the interesting number.

**The negatives are hard.** These pairs survived a blocking step, so they
are near-misses somebody thought worth adjudicating, not random pairs. A
false-positive rate measured here is much worse than the same matcher's
false-positive rate over a whole book, and must never be quoted as one.

**The judgements are not ground truth.** The dataset's own authors call
them "expert judgments under incomplete evidence".

**The data is CC-BY-NC.** Fine for evaluation. The moment a number from
it appears in a commercial claim, that is a licensing question.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vinzor.compare import (Verdict, compare_dates, compare_exact,
                            compare_names)

#: Where a nationality can be recorded. Both answer the same question, so
#: both are read -- an entry carrying a country and no nationality is not
#: an entry with nothing to say about where its party is from.
NATIONALITY_FIELDS = ("nationality", "country")

#: Where an identifying number can be recorded. The Russian-language
#: sources in this corpus carry tax and registration codes far more often
#: than passport numbers, and a matching one of those is the same kind of
#: evidence.
DOCUMENT_FIELDS = ("passportNumber", "idNumber", "taxNumber",
                   "registrationNumber", "innCode", "ogrnCode")

#: The paper's seed, so a sample here is the same kind of sample.
SEED = 42

#: What our verdicts mean as a binary call, two ways.
#:
#: "would screen" is what the product does: anything but DIFFERENT reaches
#: an officer. "would call it the same" is the strict reading, and is the
#: closer analogue to a matcher emitting a match.
WOULD_SCREEN = (Verdict.IDENTICAL, Verdict.EQUIVALENT, Verdict.PARTIAL,
                Verdict.UNKNOWN)
WOULD_CALL_SAME = (Verdict.IDENTICAL, Verdict.EQUIVALENT)


def names_of(side: dict) -> list[str]:
    properties = side.get("properties") or {}
    names = list(properties.get("name") or [])
    names += list(properties.get("alias") or [])
    if side.get("caption"):
        names.append(side["caption"])
    return [n for n in names if isinstance(n, str) and n.strip()]


def dates_of(side: dict) -> list[str]:
    properties = side.get("properties") or {}
    return [d for d in (properties.get("birthDate") or [])
            if isinstance(d, str) and d.strip()]


_ORDER = {v: i for i, v in enumerate(
    (Verdict.IDENTICAL, Verdict.EQUIVALENT, Verdict.PARTIAL,
     Verdict.UNKNOWN, Verdict.DIFFERENT))}


def best_name_verdict(left: dict, right: dict) -> Verdict:
    """The kindest verdict across every recorded spelling of each side.

    A listed party carries aliases and so does a customer record. Comparing
    only the captions would fail pairs any officer would match on sight,
    and flatters nothing: taking the best available reading is what the
    product does when it screens.
    """
    ours, theirs = names_of(left), names_of(right)
    if not ours or not theirs:
        return Verdict.UNKNOWN
    best = Verdict.DIFFERENT
    for a in ours[:8]:
        for b in theirs[:8]:
            verdict = compare_names(a, b).verdict
            if _ORDER[verdict] < _ORDER[best]:
                best = verdict
                if best is Verdict.IDENTICAL:
                    return best
    return best


def values_of(side: dict, fields) -> list[str]:
    properties = side.get("properties") or {}
    out: list[str] = []
    for field in fields:
        out += [str(v) for v in (properties.get(field) or []) if str(v).strip()]
    return out


def _exact_verdict(left: dict, right: dict, fields, label: str) -> Verdict:
    """The kindest reading across every value each side records.

    A party legitimately holds two passports and a watchlist legitimately
    records one of them, so one agreement anywhere is agreement. Only when
    nothing on either side agrees is this a contradiction.
    """
    ours, theirs = values_of(left, fields), values_of(right, fields)
    if not ours or not theirs:
        return Verdict.UNKNOWN
    best = Verdict.DIFFERENT
    for value in ours[:6]:
        found = compare_exact(label, value, theirs[:6], "same", "different")
        if found.verdict is Verdict.IDENTICAL:
            return Verdict.IDENTICAL
    return best


def nationality_verdict(left: dict, right: dict) -> Verdict:
    return _exact_verdict(left, right, NATIONALITY_FIELDS, "nationality")


def document_verdict(left: dict, right: dict) -> Verdict:
    return _exact_verdict(left, right, DOCUMENT_FIELDS, "identity document")


def dates_contradict(left: dict, right: dict) -> bool:
    """Whether both sides carry a birth date and no pair of them agrees.

    Only a contradiction counts. One side having no date is not evidence
    of anything, and treating it as such would close files on missing data.
    """
    ours, theirs = dates_of(left), dates_of(right)
    if not ours or not theirs:
        return False
    for a in ours[:4]:
        for b in theirs[:4]:
            if compare_dates(a, b).verdict is not Verdict.DIFFERENT:
                return False
    return True


def sample(path: Path, wanted: int) -> list:
    """A label-stratified sample, in one pass, without holding the file.

    Reservoir sampling per label keeps the population's own positive to
    negative ratio, which is what "stratified" means here, and needs
    memory proportional to the sample rather than to the 1.1 GB corpus.
    """
    rng = random.Random(SEED)
    kept: dict = {"positive": [], "negative": []}
    seen: dict = {"positive": 0, "negative": 0}
    unsure = 0

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            judgement = record.get("judgement")
            if judgement == "unsure":
                unsure += 1
                continue
            if judgement not in kept:
                continue
            seen[judgement] += 1
            # Sized after the pass, so take a generous reservoir now and
            # cut it to the population ratio afterwards.
            room = wanted
            if len(kept[judgement]) < room:
                kept[judgement].append(record)
            else:
                spot = rng.randrange(seen[judgement])
                if spot < room:
                    kept[judgement][spot] = record

    total = seen["positive"] + seen["negative"]
    if not total:
        return [], seen, unsure
    want_positive = round(wanted * seen["positive"] / total)
    want_negative = wanted - want_positive
    chosen = (kept["positive"][:want_positive]
              + kept["negative"][:want_negative])
    rng.shuffle(chosen)
    return chosen, seen, unsure


def score(pairs, predicted_same) -> dict:
    """Precision, recall and F1 on the same-party class."""
    hit = missed = false = 0
    for record in pairs:
        truly_same = record["judgement"] == "positive"
        said_same = predicted_same(record)
        if truly_same and said_same:
            hit += 1
        elif truly_same and not said_same:
            missed += 1
        elif not truly_same and said_same:
            false += 1
    precision = hit / (hit + false) if hit + false else 0.0
    recall = hit / (hit + missed) if hit + missed else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {"precision": precision, "recall": recall, "f1": f1,
            "hit": hit, "missed": missed, "false": false}


def main(argv) -> int:
    if not argv or argv[0].startswith("--"):
        print("  usage: python tools/pairs_protocol.py pairs.json "
              "[--sample 10000]")
        return 2
    source = Path(argv[0])
    if not source.exists():
        print(f"  no such file: {source}")
        return 1
    wanted = (int(argv[argv.index("--sample") + 1])
              if "--sample" in argv else 10_000)

    print(f"\n  reading {source.name} ...", flush=True)
    pairs, seen, unsure = sample(source, wanted)
    total = seen["positive"] + seen["negative"]
    if not pairs:
        print("  nothing judged in this file")
        return 1

    positives = sum(1 for r in pairs if r["judgement"] == "positive")
    print(f"  {total:,} judged pairs in the corpus "
          f"({seen['positive']:,} the same, {seen['negative']:,} different"
          f"{f'; {unsure:,} unsure, excluded' if unsure else ''})")
    print(f"  scoring a label-stratified sample of {len(pairs):,} at seed "
          f"{SEED}: {positives:,} the same, {len(pairs) - positives:,} "
          f"different\n")

    def named(record) -> bool:
        return best_name_verdict(record["left"], record["right"])             in WOULD_CALL_SAME

    def no_date_conflict(record) -> bool:
        return not dates_contradict(record["left"], record["right"])

    def no_country_conflict(record) -> bool:
        return nationality_verdict(record["left"],
                                   record["right"]) is not Verdict.DIFFERENT

    def no_document_conflict(record) -> bool:
        return document_verdict(record["left"],
                                record["right"]) is not Verdict.DIFFERENT

    def documents_agree(record) -> bool:
        return document_verdict(record["left"],
                                record["right"]) is Verdict.IDENTICAL

    runs = (
        ("names only, would call it the same", named),
        ("names only, would put it to an officer",
         lambda r: best_name_verdict(r["left"], r["right"]) in WOULD_SCREEN),
        ("names and birth dates", lambda r: named(r) and no_date_conflict(r)),
        ("names and nationality", lambda r: named(r) and no_country_conflict(r)),
        ("names and identity documents",
         lambda r: named(r) and no_document_conflict(r)),
        ("a matching document number, whatever the name", documents_agree),
        ("names, dates, nationality and documents",
         lambda r: named(r) and no_date_conflict(r)
         and no_country_conflict(r) and no_document_conflict(r)),
        ("any of: names agree, or documents agree",
         lambda r: named(r) or documents_agree(r)),
    )

    print(f"  {'':<46}{'precision':>10}{'recall':>9}{'F1':>8}")
    print("  " + "-" * 73)
    for label, predicate in runs:
        got = score(pairs, predicate)
        print(f"  {label:<46}{got['precision']:>9.1%}{got['recall']:>9.1%}"
              f"{got['f1']:>8.1%}")

    print()
    print("  For context, not comparison: the benchmark paper reports 91.33%")
    print("  F1 for nomenklatura's rule-based matcher and 98.95% for GPT-4o.")
    print("  Those matchers read every property on both records -- birth")
    print("  dates, nationalities, passport numbers, addresses. Ours compares")
    print("  names. The rows above answer a narrower question, and the gap")
    print("  between the first and third is what one extra field is worth.")
    print()
    print("  These negatives survived a blocking step, so they are hard")
    print("  near-misses rather than random pairs: the false-positive rate")
    print("  here is far worse than the same code's rate over a whole book,")
    print("  and must not be quoted as one.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

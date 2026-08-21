"""Our payment detection, measured against alerts a real bank's analysts judged.

    python tools/against_synthaml.py <folder-with-the-two-csv-files>

**The rules measured here were removed on 21 August 2026.** Structuring,
overpayment, unexpected currency, unrecorded payer and the counterparty and
multi-hop rules built on the back of this result are all gone; what survives
in ``payments.py`` is one rule, that the money came from someone other than
the investor, which this dataset cannot express because it has no
counterparties in it.

The file is kept, and running it still works, because it is the measurement
the removal rests on. A cut is only defensible while the evidence for it can
be re-read by somebody who was not in the room, and deleting the evidence
after acting on it leaves an assertion where a measurement used to be. Read
everything below as the record of why those rules went, not as a description
of what the product does.

SynthAML (Oksanen et al., Scientific Data, 2023) is 20,000 anti-money
laundering alerts and 16 million transactions, synthesised from real data at
Spar Nord, a systemically important Danish bank, and labelled with what that
bank's analysts actually did: Report to the authorities, or Dismiss.

It is the first time this project has been able to test detection against
labels produced by working analysts rather than by us.

What it can and cannot answer, stated plainly, because the honest limits
matter more here than the number:

* The transaction table carries a timestamp, a direction, a channel and a
  size that has been log-transformed and standardised -- mean zero, variance
  one. There are no currency amounts, no counterparties, no names, no
  account identifiers and no expected amounts.
* So of our five payment rules, only structuring has a shape that survives
  the transformation: several small credits close together. The other four
  -- third-party payer, unrecorded payer, overpayment against a call, and
  unexpected currency -- depend on fields this dataset does not contain, and
  are reported as not tested rather than quietly folded into an average.
* Sizes are logs, so sums of them are not sums of money. The "together they
  reach the reportable figure" half of our structuring rule cannot be
  evaluated and is dropped. What remains is the clustering half.

Because of that, this harness measures lift -- how much likelier an alert
was to be reported when a signal is present -- rather than precision and
recall against thresholds this data cannot express. Lift is the honest
question: does the shape our rule looks for carry signal that real analysts
acted on?

Several shapes we do not currently detect are measured alongside ours, so
the output doubles as a ranked list of what to build next.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

#: Our structuring rule, in the only form this dataset can express: how many
#: credits, how close together, and how small they have to be. "Small" is a
#: percentile of the size distribution rather than a currency figure,
#: because the currency figures are gone.
SPLITS = 3
WINDOW_HOURS = 48
SMALL_PERCENTILE = 50


def read_alerts(path: Path) -> dict:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["AlertID"]: row["Outcome"]
                for row in csv.DictReader(handle)}


def size_cutoffs(path: Path, percentiles) -> dict:
    """The size below which a credit counts as small, at each percentile
    asked for.

    Read from the data rather than assumed: the column is standardised, so
    zero is the mean, and any fixed figure would be a guess about a
    distribution we can simply go and look at. Every percentile comes out
    of one pass -- the file is most of a gigabyte, and reading it again per
    percentile was the slowest thing this script did.
    """
    sizes = []
    with path.open(encoding="utf-8", newline="") as handle:
        for position, row in enumerate(csv.DictReader(handle)):
            if position % 20 == 0:                 # a 5% sample is plenty
                try:
                    sizes.append(float(row["Size"]))
                except ValueError:
                    continue
    sizes.sort()
    return {p: sizes[int(len(sizes) * p / 100)] for p in percentiles}


def _seconds(stamp: str) -> int:
    """Timestamps read 'YYYY-MM-DD HH:MM:SS'. Parsed by hand because
    datetime parsing sixteen million times is most of this script's
    running time, and only differences between stamps are ever used."""
    try:
        date, clock = stamp.split(" ")
        year, month, day = (int(p) for p in date.split("-"))
        hour, minute, second = (int(p) for p in clock.split(":"))
    except ValueError:
        return 0
    return ((((year * 372 + month * 31 + day) * 24 + hour) * 60
             + minute) * 60 + second)


def features(rows, small: float) -> dict:
    """What one alert's transactions look like.

    Every entry is a shape some rule could look for, so that what comes out
    is a comparison between the shape we already detect and the shapes we
    do not.
    """
    rows.sort(key=lambda r: r[0])
    credits = [r for r in rows if r[1] == "Credit"]
    debits = [r for r in rows if r[1] == "Debit"]
    total = len(rows) or 1

    # ours: several small credits inside one window
    small_credits = [r[0] for r in credits if r[2] < small]
    clustered = 0
    window = WINDOW_HOURS * 3600
    left = 0
    for right, when in enumerate(small_credits):
        while when - small_credits[left] > window:
            left += 1
        clustered = max(clustered, right - left + 1)

    # not ours, measured to see whether they would be worth building
    cash = sum(1 for r in rows if r[3] == "Cash")
    international = sum(1 for r in rows if r[3] == "International")
    wire = sum(1 for r in rows if r[3] == "Wire")

    # pass-through: money that leaves almost as soon as it arrives
    pass_through = 0
    if credits and debits:
        debit_times = sorted(r[0] for r in debits)
        for when, _, _, _ in credits:
            low, high = 0, len(debit_times)
            while low < high:              # first debit at or after this credit
                middle = (low + high) // 2
                if debit_times[middle] < when:
                    low = middle + 1
                else:
                    high = middle
            if low < len(debit_times) and debit_times[low] - when <= 24 * 3600:
                pass_through += 1

    biggest = max((r[2] for r in rows), default=0.0)

    # The same rule made baseline-aware, as it now is in payments.py: a
    # burst only counts if it is wider than this account has already shown.
    #
    # SynthAML publishes no client identifier, so a party's habit cannot be
    # learned across alerts the way the product learns it across the log.
    # The nearest honest proxy is within one alert: learn the usual burst
    # from the earlier half of this account's own stream, and judge the
    # later half against it. It understates the product's version, which
    # has the whole history to learn from.
    unusual_burst = False
    if small_credits:
        midpoint = small_credits[0] + (small_credits[-1] - small_credits[0]) // 2
        earlier = [t for t in small_credits if t <= midpoint]
        later = [t for t in small_credits if t > midpoint]

        def widest(times):
            most, start = 0, 0
            for index, when in enumerate(times):
                while when - times[start] > window:
                    start += 1
                most = max(most, index - start + 1)
            return most

        was, now = widest(earlier), widest(later)
        unusual_burst = now >= SPLITS and now > was

    return {
        "structuring (ours, as it was)": clustered >= SPLITS,
        "structuring (ours, baseline-aware)": unusual_burst,
        "cash heavy": cash / total > 0.30,
        "international heavy": international / total > 0.30,
        "wire heavy": wire / total > 0.50,
        "money passes straight through": bool(credits)
        and pass_through / len(credits) > 0.50,
        "one unusually large movement": biggest > 3.0,
        "very busy account": total > 500,
    }


def walk(path: Path, small: float, alerts: dict):
    """One streaming pass. The file is grouped by alert, so each alert's
    rows are gathered and released as the next alert begins, and sixteen
    million rows never have to be in memory at once."""
    found: dict = defaultdict(lambda: {"Report": 0, "Dismiss": 0})
    totals = {"Report": 0, "Dismiss": 0}
    state = {"alert": None, "rows": []}

    def flush() -> None:
        alert = state["alert"]
        if alert is None or alert not in alerts:
            return
        outcome = alerts[alert]
        totals[outcome] += 1
        for name, present in features(state["rows"], small).items():
            if present:
                found[name][outcome] += 1

    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            alert = row["AlertID"]
            if alert != state["alert"]:
                flush()
                state["alert"], state["rows"] = alert, []
            try:
                state["rows"].append(
                    (_seconds(row["Timestamp"]), row["Entry"],
                     float(row["Size"]), row["Type"]))
            except ValueError:
                continue
    flush()
    return found, totals


def sweep_calibrations(path: Path, alerts: dict, settings):
    """Every candidate calibration, scored in one further pass.

    One pass rather than one per setting: the file is a gigabyte, and the
    only thing each setting needs from an alert is the largest cluster of
    small credits it contains, which can be computed for all of them
    together.
    """
    scores = {(p, s, h): [0, 0] for p, _, s, h in settings}
    cutoffs = sorted({(p, c) for p, c, _, _ in settings})
    windows = sorted({h for _, _, _, h in settings})
    state = {"alert": None, "rows": []}

    def flush() -> None:
        alert = state["alert"]
        if alert is None or alert not in alerts:
            return
        reported = alerts[alert] == "Report"
        rows = sorted(state["rows"])
        for percentile, cutoff in cutoffs:
            times = [when for when, entry, size in rows
                     if entry == "Credit" and size < cutoff]
            for hours in windows:
                span = hours * 3600
                widest, left = 0, 0
                for right, when in enumerate(times):
                    while when - times[left] > span:
                        left += 1
                    widest = max(widest, right - left + 1)
                for (p, s, h), tally in scores.items():
                    if p == percentile and h == hours and widest >= s:
                        tally[0] += 1
                        tally[1] += reported

    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            alert = row["AlertID"]
            if alert != state["alert"]:
                flush()
                state["alert"], state["rows"] = alert, []
            try:
                state["rows"].append((_seconds(row["Timestamp"]),
                                      row["Entry"], float(row["Size"])))
            except ValueError:
                continue
    flush()

    out = []
    for (percentile, splits, hours), (seen, hits) in scores.items():
        out.append((percentile, splits, hours, seen, hits))
    # Best discrimination first, but only where the signal is selective
    # enough to be worth acting on at all.
    out.sort(key=lambda r: (r[4] / r[3]) if r[3] else 0, reverse=True)
    return out[:14]


def main(argv) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[2])
        return 2
    home = Path(argv[0])
    alerts_csv = home / "synthetic_alerts.csv"
    txns_csv = home / "synthetic_transactions.csv"
    for path in (alerts_csv, txns_csv):
        if not path.exists():
            print(f"missing: {path}")
            return 1

    alerts = read_alerts(alerts_csv)
    reported = sum(1 for outcome in alerts.values() if outcome == "Report")
    print(f"\n  {len(alerts):,} alerts judged by the bank's own analysts")
    print(f"  {reported:,} reported ({100 * reported / len(alerts):.1f}%), "
          f"{len(alerts) - reported:,} dismissed")

    print("\n  reading the size distribution...", flush=True)
    cutoffs = size_cutoffs(txns_csv, sorted({SMALL_PERCENTILE,
                                             5, 10, 20, 35, 50}))
    small = cutoffs[SMALL_PERCENTILE]
    print(f"  a credit counts as small below {small:.3f} "
          f"(the {SMALL_PERCENTILE}th percentile of a standardised column)")

    print("  walking sixteen million transactions...", flush=True)
    found, totals = walk(txns_csv, small, alerts)

    seen_alerts = totals["Report"] + totals["Dismiss"]
    base = totals["Report"] / max(1, seen_alerts)
    print(f"\n  Of the {seen_alerts:,} alerts read, {100 * base:.1f}% were "
          f"reported.")
    print("  A signal is worth having if alerts carrying it were reported")
    print("  more often than that.\n")

    print(f"  {'what the shape is':<34}{'alerts':>9}{'reported':>10}"
          f"{'rate':>8}{'lift':>8}")
    print("  " + "-" * 69)
    ranked = []
    for name, counts in found.items():
        seen = counts["Report"] + counts["Dismiss"]
        if not seen:
            continue
        rate = counts["Report"] / seen
        ranked.append((rate / base if base else 0.0, name, seen,
                       counts["Report"], rate))
    for lift, name, seen, hits, rate in sorted(ranked, reverse=True):
        mark = "  <- ours" if "ours" in name else ""
        print(f"  {name:<34}{seen:>9,}{hits:>10,}{100 * rate:>7.1f}%"
              f"{lift:>7.2f}x{mark}")

    fired = found["structuring (ours, as it was)"]
    fired_seen = fired["Report"] + fired["Dismiss"]
    if fired_seen > 0.8 * seen_alerts:
        print(f"\n  Our structuring shape fires on "
              f"{100 * fired_seen / seen_alerts:.0f}% of alerts. A signal "
              f"present almost everywhere\n  cannot separate anything, "
              f"whatever its lift says. The sweep below asks what\n"
              f"  calibration would.")

    print("\n  What calibration would discriminate")
    print("  Tightening each knob in turn, against the same alerts.\n")
    print(f"  {'small below':>12}{'credits':>9}{'window':>9}"
          f"{'fires on':>11}{'reported':>10}{'lift':>8}")
    print("  " + "-" * 61)
    sweep = []
    for percentile in (5, 10, 20, 35, 50):
        for splits in (3, 5, 8, 12):
            for hours in (2, 12, 48):
                sweep.append((percentile, cutoffs[percentile], splits, hours))
    results = sweep_calibrations(txns_csv, alerts, sweep)
    for percentile, splits, hours, seen, hits in results:
        if not seen:
            continue
        rate = hits / seen
        share = seen / seen_alerts
        print(f"  {percentile:>10}th{splits:>9}{hours:>8}h"
              f"{100 * share:>10.1f}%{100 * rate:>9.1f}%"
              f"{rate / base if base else 0:>7.2f}x")

    print("\n  Not measurable in this dataset, because the fields do not "
          "exist:")
    for rule, why in (
        ("third-party payer", "no counterparty on any transaction"),
        ("unrecorded payer", "no counterparty on any transaction"),
        ("overpayment against a call", "no expected amount"),
        ("unexpected currency", "no currency"),
    ):
        print(f"    {rule:<28} {why}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Is the assistant any good? Counted from the log, not asserted.

A firm that lets software draft part of a regulatory file has to be able to
answer two questions from a regulator: how often was it wrong, and how do you
know. Both are answered here, from events that were written at the time —
there is no separate analytics store to disagree with the record.

The number that matters is **contradicted**: a file where the assistant
recommended one thing and the officer decided the other way. A low acceptance
rate is a product problem. A rising contradiction rate is a control problem,
and it is the one that costs a registration. So it is computed from the
recorded outcome rather than reported by the screen, and it is printed first.

One thing this cannot yet tell you, and says so rather than implying
otherwise: how often a draft was **destroyed** before anyone saw it, because
it asserted a figure nobody gave it. Rejection deliberately writes nothing,
which keeps fabricated text out of an append-only compliance record — and
leaves the guard's own firing rate unmeasured. It is on the backlog.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .assist import DEFAULT_BUDGET_USD
from .model import DraftUse, EventType, Outcome


@dataclass(frozen=True)
class Quality:
    """What the log says about the assistant. Every field is a count."""

    prepared: int
    waiting: int
    decided: int
    accepted: int
    edited: int
    rejected: int
    contradicted: int
    spend_usd: float
    budget_usd: float
    input_tokens: int
    output_tokens: int
    models: tuple[str, ...]
    regions: tuple[str, ...]
    prompt_versions: tuple[str, ...]

    @property
    def used(self) -> int:
        """Drafts whose wording reached the record, changed or not."""
        return self.accepted + self.edited

    def _rate(self, count: int) -> float:
        return round(count / self.decided, 4) if self.decided else 0.0

    @property
    def acceptance_rate(self) -> float:
        return self._rate(self.used)

    @property
    def contradiction_rate(self) -> float:
        return self._rate(self.contradicted)

    @property
    def average_cost_usd(self) -> float:
        return round(self.spend_usd / self.prepared, 6) if self.prepared else 0.0

    @property
    def budget_left_usd(self) -> float:
        return round(max(0.0, self.budget_usd - self.spend_usd), 6)

    @property
    def trustworthy(self) -> bool:
        """Whether these rates rest on enough decisions to mean anything.

        Twenty is not a statistical threshold; it is the point below which a
        percentage flatters or damns the assistant on the strength of one or
        two files, and quoting it to a regulator would be misleading.
        """
        return self.decided >= 20


def measure(engine, budget_usd: float = DEFAULT_BUDGET_USD) -> Quality:
    """Fold the log into the quality numbers. Reads nothing else."""
    prepared: set[str] = set()
    spend = 0.0
    tokens_in = tokens_out = 0
    models: dict[str, None] = {}
    regions: dict[str, None] = {}
    versions: dict[str, None] = {}
    counts: dict[str, int] = {}
    decided: set[str] = set()
    last: dict[str, str] = {}

    for event in engine.log:
        payload = event.payload
        if event.event_type is EventType.DRAFT_PREPARED:
            prepared.add(str(payload.get("case_id")))
            spend += float(payload.get("cost_usd") or 0.0)
            tokens_in += int(payload.get("input_tokens") or 0)
            tokens_out += int(payload.get("output_tokens") or 0)
            models.setdefault(str(payload.get("model") or ""), None)
            regions.setdefault(str(payload.get("region") or ""), None)
            versions.setdefault(str(payload.get("prompt_version") or ""), None)
        elif event.event_type is EventType.CASE_DECIDED:
            use = str(payload.get("draft_use") or DraftUse.NONE)
            if use == str(DraftUse.NONE):
                continue
            # An escalation is a handover, not an answer -- ``cases.py`` says
            # so in as many words, and the file stays open. Reading one as a
            # verdict on the draft counted a question being passed upward as
            # an officer disagreeing with the assistant.
            if str(payload.get("outcome") or "") == str(Outcome.ESCALATE):
                continue
            # One use per file, the settling one. This tallied *events* and
            # divided them by a set of *files*, and the ordinary AML path --
            # escalate, then settle, which is forced for every politically
            # exposed person -- writes two decisions on one file. The page
            # read "Decided against the suggestion: 2 of 1".
            last[str(payload.get("case_id"))] = use

    for use in last.values():
        counts[use] = counts.get(use, 0) + 1
    decided = set(last)

    return Quality(
        prepared=len(prepared),
        waiting=len(prepared - decided),
        decided=len(decided),
        accepted=counts.get(str(DraftUse.ACCEPTED), 0),
        edited=counts.get(str(DraftUse.EDITED), 0),
        rejected=counts.get(str(DraftUse.REJECTED), 0),
        contradicted=counts.get(str(DraftUse.CONTRADICTED), 0),
        spend_usd=round(spend, 6),
        budget_usd=float(budget_usd),
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        models=tuple(m for m in models if m),
        regions=tuple(r for r in regions if r),
        prompt_versions=tuple(v for v in versions if v),
    )

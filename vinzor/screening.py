"""Live sanctions and PEP screening — the OpenSanctions / yente boundary.

The first adapter from the open-source survey (``04.md``, catalogued in
``ECOSYSTEM.md``) to earn a place at runtime. It speaks the **yente** matching
protocol, whose request body is a **FollowTheMoney** entity — so the same code
works against a self-hosted yente instance and against OpenSanctions' hosted
API, and nothing below cares which is deployed. The transport is standard
library ``urllib``: using the ecosystem did not cost the core its
zero-dependency property, because the dependency is a *protocol*, not a
package.

This is a boundary, in the DESIGN.md sense. It observes the world — a
watchlist, on a given day, at a given match threshold — and mints
``SCREENING_COMPLETED`` facts carrying full provenance: what was asked, of
which service, what came back, with what score. Clause 5.9 requires screening
to happen; **the record that it happened is written even when nothing
matches**, because "we screened and found nothing" is itself the evidence an
inspector asks for.

Honesty about the mapping: the topics this provider actually publishes are
classified into the kinds a clause can be cited for — sanctions, public
office, a close associate of somebody in public office, a wanted or criminal
entry, a debarment. A match whose topics are none of those is still recorded,
and reaches an officer through the unclassified rule rather than being named
as something it might not be.

What is deliberately absent is a PEP seniority level. The commercial
registers sell a one-to-four scale; this provider publishes none, and IFSCA
does not use one either — its definition names the offices it covers and says
the definition "is not intended to cover middle ranking or more junior
individuals". A level we cannot source would be a guess on a regulatory
file.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .engine import IngestResult, Vinzor
from .model import EntityKind, EventType

#: OpenSanctions' hosted API. A self-hosted yente serves the same routes.
DEFAULT_URL = "https://api.opensanctions.org"

#: The dataset scope to match against. "default" is OpenSanctions' full
#: consolidated collection: sanctions, PEPs, and criminal watchlists.
DEFAULT_SCOPE = "default"

#: Below this score a candidate is treated as no match. yente's own ``match``
#: flag is respected when present; this is the floor either way.
DEFAULT_THRESHOLD = 0.70

#: Our customer types, as FollowTheMoney schemata. FTM is the wire vocabulary
#: of the whole OpenSanctions ecosystem; mapping here, once, at the boundary,
#: means the core never has to know FTM exists.
FTM_SCHEMA: Mapping[EntityKind, str] = {
    EntityKind.PERSON: "Person",
    EntityKind.COMPANY: "Company",
    EntityKind.PARTNERSHIP: "Company",
    EntityKind.FUND: "Company",
    EntityKind.TRUST: "LegalEntity",
    EntityKind.UNINCORPORATED_BODY: "LegalEntity",
    # In FollowTheMoney, Person and Company both descend from LegalEntity,
    # so a party of unrecorded type is asked about as the widest schema that
    # still means "a party" -- the match can be either, and the officer
    # deciding the file sees which the list says it is.
    EntityKind.UNKNOWN: "LegalEntity",
}

#: Read in order, so a party who is several things at once is filed under
#: the most serious. A sanctioned head of state is a sanctions matter
#: first: that one stops the money, and the others do not.
#:
#: Only prefixes the provider actually returns are listed. There is no
#: entry for a PEP "level" -- the commercial registers sell a one-to-four
#: seniority scale, our provider publishes none, and neither does IFSCA,
#: whose definition instead names the offices it covers and says in terms
#: that it "is not intended to cover middle ranking or more junior
#: individuals". Inventing a level we cannot source would be exactly the
#: guess this module exists to avoid.
_TOPIC_LISTS = (
    ("sanction", "SANCTIONS"),
    ("role.pep", "PEP"),
    # Clause 5.5 Guidance Note (3): relationships with family members or
    # close associates of a politically exposed person "involve similar
    # risks", and the measures for PEPs "should also apply" to them.
    ("role.rca", "PEP_ASSOCIATE"),
    ("wanted", "CRIMINAL"),
    ("crime", "CRIMINAL"),
    ("debarment", "DEBARRED"),
)


def leaves_this_machine(url: str) -> bool:
    """Whether screening against ``url`` sends investor names off this machine.

    Worth its own function because the answer decides whether a firm needs a
    data-processing agreement before anyone screens a real client book, and
    because the default is the hosted API -- the safe-looking case is the one
    that leaves.
    """
    from urllib.parse import urlparse

    host = (urlparse(url or DEFAULT_URL).hostname or "").lower()
    return host not in ("127.0.0.1", "::1", "localhost", "")


#: Printed before a name is sent anywhere but this machine. A firm screening
#: its own client book has to know that the names are going to a third party,
#: and has to be told before it happens rather than after.
OFF_MACHINE_WARNING = "\n".join((
    "  WARNING: every name screened will be sent to {host}, which is not this",
    "  machine. If this is a real client book, confirm your firm may disclose",
    "  those names to that provider before continuing.",
    "  To keep names on this machine, run the self-hosted index (see",
    "  selfhost/) and set VINZOR_SCREENING_URL to it.",
))


#: How many other names one party may be asked about in a single check.
#: A record carrying more names than this is a record with a problem of its
#: own, and the limit is stated so that a check which stopped short says so
#: rather than looking complete.
MOST_ALIASES = 8

#: A single letter standing where a given name should be -- "J. Smith",
#: "M K Patel". Books are full of them, and a list is not.
_INITIAL = re.compile(r"(?:^|\s)([A-Za-z])\.?(?=\s|$)")


def held_as_initials(name: str) -> bool:
    return bool(_INITIAL.search(name or ""))


def without_initials(name: str) -> str:
    """The same name with the abbreviated parts removed, or "" if nothing is
    left worth asking about."""
    kept = [part for part in (name or "").split()
            if len(part.strip(".")) > 1]
    return " ".join(kept) if len(" ".join(kept)) > 2 else ""


class ScreeningUnavailable(RuntimeError):
    """The screening service could not be reached or refused the request.

    A failed screen is not a fact about the entity, so nothing is written to
    the log; the caller is told in plain words and can try again.
    """


#: The schemes a screening service can be reached over.
_REACHABLE = ("http", "https")


def unusable(url: str) -> str:
    """Why this address cannot be a screening service, or "" if it can.

    Checked before anything is sent, for two reasons. An address that is not
    an address used to escape as a raw ``ValueError`` from deep inside
    urllib, straight past the promise this module makes -- either results or
    :class:`ScreeningUnavailable` -- and out of a background screening run,
    where it left a progress bar counting toward a total it would never
    reach and no message saying why.

    And the message matters as much as the class. "The service could not be
    reached" sends somebody to restart a service that was never the problem;
    an address typed without ``http://`` is a setting to correct, and this
    says so.
    """
    from urllib.parse import urlparse

    address = (url or "").strip()
    if not address:
        return ("No screening service address is set, so no check was "
                "performed and nothing was recorded. Set one before "
                "screening a party.")
    parsed = urlparse(address)
    if parsed.scheme not in _REACHABLE:
        return (f"The screening service address \"{address}\" cannot be "
                f"reached: it has to begin with http:// or https://. No "
                f"check was performed and nothing was recorded.")
    if not parsed.hostname:
        return (f"The screening service address \"{address}\" names no "
                f"machine to ask. No check was performed and nothing was "
                f"recorded.")
    return ""


Transport = Callable[[str, Optional[bytes], Mapping[str, str]], bytes]

#: Bytes. A screening answer is match results for one query; this is far more
#: than a real one needs and exists only to stop an unbounded read from a peer
#: that simply keeps sending.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

#: Seconds -- the wall-clock budget for the *whole* exchange (connect, send,
#: every read), not for each socket operation inside it. ``timeout=`` on
#: ``urlopen`` bounds only the latter: confirmed with a server that drips a
#: valid response one byte at a time, where every individual recv() finished
#: comfortably inside a 3 second timeout while the call as a whole ran for 17.
REQUEST_TIMEOUT_SECONDS = 30


def _read_bounded(response: Any, limit: int) -> bytes:
    """Read a response body without trusting how much of it there will be.

    ``response.read()`` has no ceiling of its own: a peer that keeps sending
    is a peer we keep buffering. This stops the instant more than ``limit``
    bytes have arrived, rather than trusting a byte count nobody on our side
    chose.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read1(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ScreeningUnavailable(
                "The screening service sent an answer larger than expected "
                "and the check was not performed. Nothing was recorded."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _http_transport(url: str, body: Optional[bytes],
                    headers: Mapping[str, str]) -> bytes:
    """POST over urllib, with a real wall-clock deadline and a bounded read.

    A body of ``None`` makes it a GET, which is how the catalogue is read.
    The method follows the body rather than being a second argument, so an
    injected transport -- a test fake, a retrying client -- keeps working
    without learning a new parameter.

    A socket timeout bounds each individual operation, not the exchange as a
    whole, so the actual call runs on a background thread and this function
    waits at most ``REQUEST_TIMEOUT_SECONDS`` for it to finish -- a deadline on
    the call, not just on each read inside it. This is an I/O boundary, so a
    clock (the thread join) is permitted here; nothing in ``vinzor/`` core
    reads one.
    """
    request = urllib.request.Request(url, data=body, headers=dict(headers),
                                     method="POST" if body is not None else "GET")
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                outcome["body"] = _read_bounded(response, MAX_RESPONSE_BYTES)
        except BaseException as error:  # re-raised on the caller's thread
            outcome["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(REQUEST_TIMEOUT_SECONDS)
    if worker.is_alive():
        # The worker is abandoned, not killed -- Python has no safe way to do
        # that -- but it is daemonic and bounded by its own socket timeout, so
        # it cannot outlive the process. The caller does not wait for it.
        raise ScreeningUnavailable(
            "The screening service did not answer in time and the check was "
            "not performed. Nothing was recorded."
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome["body"]


#: Identifying properties worth carrying off a watchlist entry. yente returns
#: FollowTheMoney properties; these are the ones an officer actually compares.
#: Without them a "possible match" is a name and nothing else — which is why
#: they are captured here rather than left in the response.
IDENTIFYING = ("birthDate", "nationality", "country", "idNumber",
               "passportNumber", "taxNumber", "address", "alias", "position")


@dataclass(frozen=True)
class Hit:
    """One watchlist candidate the service considers a match."""

    entity_id: str
    caption: str
    score: float
    topics: tuple[str, ...]
    datasets: tuple[str, ...]
    #: The identifying properties above, as returned. Values are lists because
    #: a listed party may have several passports, aliases or nationalities.
    properties: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def _named(self, prefix: str) -> bool:
        return any(t == prefix or t.startswith(prefix + ".")
                   for t in self.topics)

    @property
    def list_type(self) -> Optional[str]:
        """The most serious thing this match is, for triage.

        One value, deliberately: a sanctioned head of state is a sanctions
        matter first, because that is the one that stops the money.
        """
        for prefix, list_type in _TOPIC_LISTS:
            if self._named(prefix):
                return list_type
        return None  # recorded, not cased — see module docstring

    @property
    def list_types(self) -> tuple:
        """*Every* thing this match is, for the rules that are not triage.

        The single value above answers "what should this file be called".
        It was also being asked "may a junior officer clear this", and the
        two questions have different answers. A sanctioned head of state
        carries both ``sanction`` and ``role.pep``; the first wins the
        label, and clause 5.5(b)(iii) is about the second. So the gate
        reserving a politically exposed person for senior management never
        fired on the politically exposed people who most needed it --
        Vladimir Putin, Bashar Assad and Kim Jong-un all classify as
        SANCTIONS against the local index and all three carry ``role.pep``.

        Measured on 20 August 2026: of 847 sanctioned persons sampled from
        that index, 160 also carried ``role.pep`` and 21 ``role.rca`` --
        21.4% were politically exposed and filed as sanctions.
        """
        return tuple(name for prefix, name in _TOPIC_LISTS
                     if self._named(prefix))


@dataclass(frozen=True)
class WatchlistClient:
    """A yente-protocol matching service, hosted or self-hosted."""

    url: str = DEFAULT_URL
    #: Kept out of ``repr`` deliberately: a dataclass repr is exactly what a
    #: traceback, a debugger or a logger reaches for, and this is a live
    #: credential, never something that belongs anywhere but the environment.
    api_key: str = field(default="", repr=False)
    scope: str = DEFAULT_SCOPE
    threshold: float = DEFAULT_THRESHOLD
    transport: Transport = field(default=_http_transport)

    def _refuse_unless_indexed(self) -> None:
        """Confirm the scope we just searched is actually in the index.

        The protocol publishes what it holds at ``/catalog``: a list of
        datasets, each with the version indexed and whether that version is
        the current one. A scope that is absent, or present but not current,
        is a scope that cannot have been searched -- so an empty answer from
        it is not a clean record, it is a missing check.

        A service that cannot answer this question at all is also refused.
        Being unable to tell a clean screen from an unbuilt one is exactly
        the state in which no clean screen may be written.
        """
        try:
            raw = self.transport(f"{self.url}/catalog", None,
                                 {"Accept": "application/json"})
            held = json.loads(raw).get("datasets")
            if not isinstance(held, list):
                raise TypeError("catalog was not a list of datasets")
        except Exception as error:      # noqa: BLE001 - any failure is a refusal
            raise ScreeningUnavailable(
                "Nothing matched, and this system could not confirm that the "
                "watchlist it searched is loaded. That is not the same as a "
                "clean result, so nothing was recorded."
            ) from error

        for dataset in held:
            if not isinstance(dataset, Mapping):
                continue
            if str(dataset.get("name") or "") != self.scope:
                continue
            if dataset.get("index_current") is False:
                break
            return

        # A collection is also reachable as the parent of what is indexed:
        # "default" is every list at once and is not itself a dataset row on
        # every deployment. If anything at all is current, the search was
        # real.
        if any(isinstance(d, Mapping) and d.get("index_current") for d in held):
            return

        raise ScreeningUnavailable(
            "Nothing matched, but the watchlist this system searched is not "
            "loaded yet, so there was nothing to match against. No check has "
            "been recorded against this party. Try again once the watchlist "
            "has finished loading."
        )

    def match(self, *, name: str, kind: EntityKind,
              country: str = "",
              aliases: Sequence[str] = ()) -> tuple[list[Hit], dict[str, Any]]:
        """Match a name, asking twice where the name is an abbreviation.

        A book holds "J. Smith"; a sanctions list holds "John Smith". Measured
        against 40 genuinely listed people, screening the initialled form
        found 23 of them and missed 17. Lowering the threshold recovered none
        of the 17 -- at 0.40 the result was identical to 0.70 -- because those
        entities were never returned as candidates at all. It is a recall
        problem in the query, and no filter fixes a candidate that never
        arrives.

        Asking again without the abbreviated part recovers all 17. It also
        flags about a fifth of parties who are on no list, because a surname
        alone is a weak question. That cost falls only on parties whose name
        we hold incompletely -- a full name is screened exactly as before --
        and for those the record is already too thin for proper diligence.
        Between an extra review and a sanctioned party walking in unseen, this
        system takes the review, and says on the record why there were more.
        """
        why = unusable(self.url)
        if why:
            raise ScreeningUnavailable(why)

        properties: dict[str, list[str]] = {"name": [name]}
        if country:
            key = "nationality" if kind is EntityKind.PERSON else "jurisdiction"
            properties[key] = [country]
        query = {"schema": FTM_SCHEMA[kind], "properties": properties}

        queries = {"q": query}

        # Every other name this party is known by, asked about in the same
        # request. A watchlist carries aliases as a matter of course -- a
        # name before naturalisation, a name in another script, a maiden
        # name -- and until the book could hold one there was nothing to
        # ask with. Sent as further queries rather than further requests
        # because the protocol takes several at once and a book of fifty
        # thousand should not pay a round trip per alias.
        also = tuple(dict.fromkeys(
            one.strip() for one in aliases
            if one and one.strip() and one.strip().lower() != name.strip().lower()
        ))[:MOST_ALIASES]
        for index, other in enumerate(also):
            queries[f"a{index}"] = {
                "schema": FTM_SCHEMA[kind],
                "properties": {**properties, "name": [other]},
            }

        fuller = without_initials(name) if held_as_initials(name) else ""
        if fuller and fuller != name:
            second = dict(properties)
            second["name"] = [fuller]
            queries["q2"] = {"schema": FTM_SCHEMA[kind], "properties": second}

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"

        # Failure semantics wrap the transport call itself, so an injected
        # transport (a test fake, a retrying client) gets them for free.
        try:
            raw = self.transport(
                f"{self.url}/match/{self.scope}",
                json.dumps({"queries": queries}).encode("utf-8"),
                headers,
            )
        except ScreeningUnavailable:
            raise
        except urllib.error.HTTPError as error:
            raise ScreeningUnavailable(
                f"The screening service answered {error.code} and the check "
                f"was not performed. Nothing was recorded; try again, and if "
                f"it keeps happening check the service address and key."
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise ScreeningUnavailable(
                "The screening service could not be reached and the check was "
                "not performed. Nothing was recorded."
            ) from error
        # Everything from here reads a provider response that is, at best,
        # unexpected-but-valid JSON: a missing "id", a null score, results
        # returned as a string or a dict instead of a list, "properties" as a
        # list instead of a mapping. None of that is ours to let escape as a
        # raw traceback -- it is exactly the same "the service answered in a
        # form this system does not recognise" as malformed JSON, so it is
        # folded into the same contract.
        try:
            answered = json.loads(raw)["responses"]
            results = []
            for key in queries:
                # Every question we asked must come back answered. Skipping a
                # missing or null answer would turn a broken response into
                # "nothing found", which is a clean screening record for a
                # check that did not happen -- the one outcome this module
                # exists to make impossible.
                part = (answered.get(key) or {}).get("results")
                if not isinstance(part, list):
                    raise TypeError(f"the answer to {key} was not a list")
                results.extend(part)
            # The same listed entity can come back from both questions. Keep
            # the better answer rather than raising the party twice.
            best: dict = {}
            for result in results:
                if not isinstance(result, Mapping) or "id" not in result:
                    raise TypeError("a result was not an entity")
                seen = best.get(result["id"])
                if seen is None or float(result.get("score") or 0.0) > float(
                        seen.get("score") or 0.0):
                    best[result["id"]] = result
            results = list(best.values())
            hits = [
                Hit(
                    entity_id=result["id"],
                    caption=result.get("caption", result["id"]),
                    score=float(result.get("score", 0.0)),
                    topics=tuple(result.get("properties", {}).get("topics", [])),
                    datasets=tuple(result.get("datasets", [])),
                    properties={
                        key: tuple(str(v) for v in values)
                        for key, values in (result.get("properties") or {}).items()
                        if key in IDENTIFYING and values
                    },
                )
                for result in results
                if result.get("match") or float(result.get("score", 0.0)) >= self.threshold
            ]
        except (KeyError, IndexError, TypeError, ValueError, AttributeError,
                json.JSONDecodeError) as error:
            raise ScreeningUnavailable(
                "The screening service answered in a form this system does "
                "not recognise. Nothing was recorded."
            ) from error
        if not results:
            # Nothing came back, and there are two ways that happens: the
            # index holds four million entities and none of them is this
            # party, or the index does not hold the scope we asked about at
            # all. They are opposite facts and the protocol reports both as
            # an empty list.
            #
            # This is the failure the comment thirty lines above calls the
            # one outcome this module exists to make impossible, reached by
            # a path nobody had walked: a service that is up, answering,
            # and simply has not finished building. Found on the deployed
            # instance during the first index build, when screening every
            # party would have written a permanent "we checked and found
            # nothing" against all of them. In an append-only log that
            # record cannot be taken back.
            #
            # So a clean screen has to be earned. Asked only when the
            # answer is empty, which is the only case where it can be
            # wrong, so a book with matches in it pays nothing.
            self._refuse_unless_indexed()
        provenance = {
            "service": self.url,
            "scope": self.scope,
            "threshold": self.threshold,
            "query": query,
        }
        # Everything the index offered, not only what cleared the threshold.
        # "Three similar names came back and none was close enough" is a
        # materially stronger clean record than silence about what was seen --
        # and it is what an inspector reading the file actually asks.
        provenance["considered"] = [
            {"name": str(r.get("caption") or r.get("id") or ""),
             "score": round(float(r.get("score") or 0.0), 2)}
            for r in sorted(results,
                            key=lambda r: -float(r.get("score") or 0.0))[:5]
        ]
        if also:
            # On the record, because an officer meeting more matches than
            # they expected should be able to see that the extra names were
            # the firm's own, not something this system invented.
            provenance["also_asked_about"] = list(also)
        if len(queries) > 1:
            # Recorded so that an officer looking at more matches than they
            # expected can see why, and so an inspector can tell a thorough
            # check from a lucky one. The name we hold is the finding here as
            # much as anything the list returned.
            provenance["asked_twice"] = {
                "because": (
                    "the name held for this party is abbreviated, and an "
                    "abbreviated name is not found by asking once"
                ),
                "also_asked": fuller,
            }
        return hits, provenance


#: What separates one name from the next in an imported cell. A registrar
#: writes them however it likes, and a comma is as common as a semicolon.
_BETWEEN_NAMES = re.compile(r"[;|/]|,(?=\s)")


def other_names(entity) -> tuple:
    """Every other name this party is recorded as being known by.

    Read from the record rather than guessed at. One cell may carry several
    -- "Priya Menon; Priya Raghavan" is how a spreadsheet says a person
    married -- so it is split on the punctuation a registrar actually uses.
    """
    raw = str((getattr(entity, "attributes", {}) or {}).get("alias") or "")
    return tuple(one.strip() for one in _BETWEEN_NAMES.split(raw)
                 if one and one.strip())


def screen(
    engine: Vinzor,
    entity_id: str,
    *,
    screened_at: str,
    client: WatchlistClient,
) -> list[IngestResult]:
    """Screen one known entity and record what the watchlists said.

    Every outcome becomes a fact. A qualifying hit mints a matched
    ``SCREENING_COMPLETED`` whose alert id is stable per watchlist entity —
    re-screening the same real-world match extends the same Case rather than
    opening a duplicate. No hits at all mints an unmatched event: the proof,
    for clause 5.9, that the check was performed that day.
    """
    entity = engine.state.graph.entities.get(entity_id)
    if entity is None:
        raise ValueError(
            f"nothing is known about {entity_id}; register the entity before "
            f"screening it"
        )
    country = str(
        entity.attributes.get("nationality")
        or entity.attributes.get("jurisdiction")
        or ""
    )
    hits, provenance = client.match(name=entity.name, kind=entity.kind,
                                    country=country,
                                    aliases=other_names(entity))

    results: list[IngestResult] = []
    for hit in hits:
        results.append(engine.ingest(
            event_type=EventType.SCREENING_COMPLETED,
            subject=entity_id,
            occurred_at=screened_at,
            actor="system",
            payload={
                "matched": True,
                "list_type": hit.list_type or "WATCHLIST",
                # Every kind, beside the headline one. The headline decides
                # what the file is called; this decides who may settle it.
                "list_types": list(hit.list_types) or ["WATCHLIST"],
                "rule": f"OpenSanctions match, score {hit.score:.2f}",
                "alert_id": f"os:{hit.entity_id}",
                "basis": {
                    **provenance,
                    "matched_entity": hit.entity_id,
                    "caption": hit.caption,
                    "score": hit.score,
                    "topics": list(hit.topics),
                    "datasets": list(hit.datasets),
                    "listed_properties": {k: list(v)
                                          for k, v in hit.properties.items()},
                },
            },
        ))
    if not hits:
        results.append(engine.ingest(
            event_type=EventType.SCREENING_COMPLETED,
            subject=entity_id,
            occurred_at=screened_at,
            actor="system",
            payload={"matched": False, "basis": provenance},
        ))
    return results

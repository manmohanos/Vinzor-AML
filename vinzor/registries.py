"""Company and beneficial-ownership registries — UK Companies House and
OpenCorporates.

Screening tells an officer whether a *party* is on a watchlist. It says
nothing about whether the *company* that party owns, or is owned by, is what
the onboarding pack claims: incorporated where it says, still active, and
carrying the persons with significant control the pack names and no others.
That question comes up on nearly every corporate investor and until now had
no tool of its own -- an officer either trusted the file as filed or opened a
browser tab to a registry this system never saw, could not cite, and could
not fence as data the way everything else the assistant reads is fenced.

Two registries, because one alone does not cover the book. **UK Companies
House** is free, official, and unlimited for the company and PSC (persons
with significant control) lookups this module makes -- no key, no daily cap
-- but it only knows companies incorporated in the United Kingdom, which is
most of nothing for a GIFT City fund whose investors are wherever capital
comes from. **OpenCorporates** knows companies in most jurisdictions on
earth, which is the whole reason to reach for it, and the price of that
reach is real: a free tier capped at fifty requests a day, and an API token
that has to be requested and configured before the first call. Neither
replaces the other. Both are offered as separate tools, and the assistant --
or the officer reading what it found -- picks the one that fits the
jurisdiction actually in front of them.

**This is a boundary, in the DESIGN.md sense, and a deliberately thin one.**
Unlike ``screening.py`` it mints no fact: there is no ``engine.ingest`` call
anywhere in this file, and nothing here is handed the engine at all -- every
function below takes a company name or number and returns a plain mapping,
full stop. What a registry says about a company is not evidence until a
person reads it and decides it is worth acting on, and today that happens
the moment it reaches the officer through ``ask.py``, which is already the
boundary that fences every tool result as data and forbids the model from
treating it as an instruction. A registry lookup here is exactly as
authoritative as a dashboard total: read through a named tool, shown beside
its source, never written anywhere on its own.

**The rule that matters more than the other two, found and fixed five times
already in this codebase.** A check that did not run must never come back
looking like a check that found nothing. So two outcomes that look similar
from a distance are kept structurally apart, the same way ``screening.py``
keeps "no watchlist match" apart from "the index has not finished loading":

* The registry was reached, it answered, and no company matches what was
  asked. That is a real, useful fact, worth exactly as much as a hit would
  have been, and it comes back as an ordinary result --
  ``{"found": 0, ...}`` -- the same shape a genuine match would have used.
* The registry could not be reached, answered in a shape this system does
  not recognise, or -- for OpenCorporates specifically -- has no token
  configured at all. None of those three is "not found". All three raise
  :class:`RegistryUnavailable`, which ``ask.py`` turns into a visible
  failure the officer sees, never a silent zero they would read as a clean
  search. ``tests/test_registries.py`` breaks the connection on purpose and
  asserts the result is never mistaken for an honest not-found -- the same
  shape of test ``photo.py`` runs for a reader that cannot be reached, and
  ``screening.py`` runs for a watchlist that is still indexing.

**Stdlib only, for the reason every adapter in this codebase gives.**
``urllib``, hand-rolled JSON, a bounded read and a thread-joined wall-clock
deadline -- the same shape as ``screening.py``'s ``_http_transport``,
reimplemented rather than imported from anywhere, because AGENTS.md forbids
a dependency in the core and a registry client is exactly the kind of thing
a PyPI package would make look free at the cost of an unaudited supply
chain sitting in a regulated system's request path.

**The OpenCorporates token is read the way every credential in this
codebase is read.** Never a file, never a function argument that could end
up in a log line, never anything but the environment -- the same discipline
``bedrock.py`` and ``azure.py`` hold for a model key. Its absence is not a
reason to quietly skip the lookup: the tool says so, in the answer the
officer actually sees, because a check that never ran is the one outcome
this entire module exists to keep from looking like a clean pass.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

#: UK Companies House's REST API. Free, official, and — for the company
#: profile and PSC endpoints this module calls — unlimited: no key is
#: required to reach it at all.
COMPANIES_HOUSE_URL = "https://api.company-information.service.gov.uk"

#: A key raises the rate limit; nothing below refuses to run without one.
#: Named once so a test sweeping for it is sweeping for the right thing,
#: mirroring ``azure.KEY_VAR`` and ``bedrock``'s own environment reads.
COMPANIES_HOUSE_KEY_VAR = "VINZOR_COMPANIES_HOUSE_KEY"

#: OpenCorporates' API. Global coverage; a free tier of fifty requests a day,
#: and every request past the search endpoints needs a token.
OPENCORPORATES_URL = "https://api.opencorporates.com"

#: Read from the environment and nowhere else -- see the module docstring.
OPENCORPORATES_TOKEN_VAR = "VINZOR_OPENCORPORATES_TOKEN"


class RegistryUnavailable(RuntimeError):
    """The registry could not be reached, answered in a form this system does
    not recognise, or -- OpenCorporates only -- has no token configured.

    Deliberately never raised for "the registry answered and no such company
    exists": that is a clean result, not a failure, and it is returned as an
    ordinary mapping so it reads to the officer exactly as an honest
    not-found should. This is the failure the module docstring calls the
    rule that matters most -- a check that did not run must never look like
    a check that found nothing.
    """


class CompanyNotFound(RuntimeError):
    """The registry was reached, answered, and named no such company.

    Raised only inside this module, and caught before it ever reaches a
    caller: :func:`lookup_company_uk` turns it into the clean, honest
    ``{"found": False, ...}`` a person should see, rather than letting it
    surface as an exception that ``ask.py``'s generic handler would report
    in the same words as a genuine failure. Kept as its own class anyway,
    not a bare ``return None``, so the two conditions a 404 from this
    registry can mean -- "no such company" against a profile lookup, "no
    PSC on file" against an existing one's PSC list -- cannot be confused
    inside this module either.
    """


#: What a UK company number looks like: eight digits, or two letters and six
#: digits (Scotland, Northern Ireland, an LLP, an overseas entry). Loose on
#: purpose -- a number this module gets wrong is sent to the wrong endpoint
#: and simply finds nothing, which is a safe failure; a name that happens to
#: look numeric is the more expensive way to get this wrong, and there is no
#: such thing among real UK company names.
_UK_COMPANY_NUMBER = re.compile(r"^(?:[A-Za-z]{2})?\d{6,8}$")


def looks_like_uk_number(text: str) -> bool:
    return bool(_UK_COMPANY_NUMBER.match((text or "").strip()))


# ---------------------------------------------------------------------------
# The wire — copied from screening.py's _http_transport, not imported from
# it. Both adapters need the same shape (a bounded read, a wall-clock
# deadline that does not trust urlopen's own per-operation timeout) and nothing
# about that shape is specific to yente's protocol; duplicating sixty lines
# costs less than a coupling between two boundaries that answer unrelated
# questions and should be free to diverge.
# ---------------------------------------------------------------------------

#: (url, body, headers) -> raw response bytes. A body of ``None`` makes it a
#: GET, which is every request this module makes -- neither registry needs a
#: POST for a lookup.
Transport = Callable[[str, Optional[bytes], Mapping[str, str]], bytes]

#: Bytes. A company profile, a PSC page or a page of search results is a few
#: kilobytes; this exists only to stop an unbounded read from a peer that
#: simply keeps sending.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

#: Seconds — the wall-clock budget for the whole exchange, not for each
#: socket operation inside it. See ``screening._http_transport`` for the
#: measurement that justifies joining a thread rather than trusting
#: ``urlopen``'s own ``timeout=``.
REQUEST_TIMEOUT_SECONDS = 20


def _read_bounded(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read1(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise RegistryUnavailable(
                "The registry sent an answer larger than expected and the "
                "lookup was not performed."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _http_transport(url: str, body: Optional[bytes],
                    headers: Mapping[str, str]) -> bytes:
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
        raise RegistryUnavailable(
            "The registry did not answer in time and the lookup was not "
            "performed."
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome["body"]


# ---------------------------------------------------------------------------
# UK Companies House
# ---------------------------------------------------------------------------


class _NotFoundHTTP(Exception):
    """Internal only. The endpoint answered 404, and what that means depends
    on which endpoint was asked: a missing company number is
    :class:`CompanyNotFound`; a missing PSC list on a company that does exist
    just means no PSC is on file, which is not a failure of anything."""


@dataclass(frozen=True)
class CompaniesHouseClient:
    """The UK register, reached over HTTP. The twin of
    ``screening.WatchlistClient``, for the same reason: the URL and the
    transport are fields, not a closure, so a test injects a canned
    transport without a socket ever opening.
    """

    url: str = COMPANIES_HOUSE_URL
    #: Optional. Out of ``repr`` for the reason ``WatchlistClient.api_key``
    #: is: a live credential does not belong in a traceback or a log line.
    api_key: str = field(default="", repr=False)
    transport: Transport = field(default=_http_transport)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "CompaniesHouseClient":
        """A key, if one is configured, and no complaint at all if not.

        Unlike OpenCorporates below, absence here is not a failure -- the
        whole reason this tool is offered without asking anyone to sign up
        first is that the basic company and PSC lookups it makes work with
        no key at all. A key only raises the rate limit.
        """
        import os

        source = env if env is not None else os.environ
        key = (source.get(COMPANIES_HOUSE_KEY_VAR) or "").strip()
        return cls(api_key=key)

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            import base64

            token = base64.b64encode(f"{self.api_key}:".encode("ascii")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _get(self, path: str) -> Optional[Mapping[str, Any]]:
        try:
            raw = self.transport(f"{self.url}{path}", None, self._headers())
        except RegistryUnavailable:
            raise
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise _NotFoundHTTP() from None
            raise RegistryUnavailable(
                f"UK Companies House answered {error.code} and the lookup "
                f"was not performed."
            ) from error
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise RegistryUnavailable(
                "UK Companies House could not be reached, so the lookup was "
                "not performed."
            ) from error
        try:
            found = json.loads(raw)
        except ValueError as error:
            raise RegistryUnavailable(
                "UK Companies House answered in a form this system does not "
                "recognise."
            ) from error
        if not isinstance(found, Mapping):
            raise RegistryUnavailable(
                "UK Companies House answered in a form this system does not "
                "recognise."
            )
        return found

    def company(self, company_number: str) -> Mapping[str, Any]:
        """One company's profile, or :class:`CompanyNotFound`."""
        try:
            return self._get(f"/company/{urllib.parse.quote(company_number)}")
        except _NotFoundHTTP:
            raise CompanyNotFound(
                f"no company numbered {company_number!r} is on the UK "
                f"register"
            ) from None

    def persons_with_significant_control(self, company_number: str) -> list:
        """Everyone recorded as controlling this company. Empty is ordinary
        -- most companies file none, or file an exemption instead -- and is
        not treated as a failure the way a 404 on the company itself is."""
        try:
            found = self._get(
                f"/company/{urllib.parse.quote(company_number)}"
                f"/persons-with-significant-control"
            )
        except _NotFoundHTTP:
            return []
        return list((found or {}).get("items") or [])

    def search(self, name: str) -> list:
        """Companies whose name matches, best guess first. Empty is an
        honest, ordinary answer -- see the module docstring on why this and
        :class:`RegistryUnavailable` must never be confused for each other."""
        found = self._get(f"/search/companies?q={urllib.parse.quote(name)}")
        return list((found or {}).get("items") or [])


def _uk_address(address: Optional[Mapping[str, Any]]) -> str:
    address = address or {}
    parts = (address.get(part) for part in
            ("address_line_1", "address_line_2", "locality", "region",
             "postal_code", "country"))
    return ", ".join(str(p) for p in parts if p)


def lookup_company_uk(company: str, *,
                      client: Optional[CompaniesHouseClient] = None,
                      env: Optional[Mapping[str, str]] = None) -> dict:
    """Look a company up on the UK register: its status, its registered
    office, and who is on file as controlling it.

    A UK company number goes straight to the profile and PSC endpoints; a
    name goes to search, which cannot also carry PSC because a name may
    match several companies and PSC is asked about one at a time. An officer
    reading a list of near-matches picks the number and asks again -- the
    same two-step ``find_party`` then ``party`` shape every other lookup in
    ``ask.py`` already uses.
    """
    asked = (company or "").strip()
    if not asked:
        return {"error": "no company name or number to look up"}

    client = client or CompaniesHouseClient.from_env(env)

    if looks_like_uk_number(asked):
        number = asked.upper()
        try:
            profile = client.company(number)
        except CompanyNotFound as missing:
            return {"asked": asked, "found": False, "note": str(missing),
                    "source": "UK Companies House"}
        psc = client.persons_with_significant_control(number)
        return {
            "asked": asked,
            "found": True,
            "company": {
                "number": profile.get("company_number", number),
                "name": profile.get("company_name", ""),
                "status": profile.get("company_status", ""),
                "type": profile.get("type", ""),
                "incorporated_on": profile.get("date_of_creation", ""),
                "registered_office": _uk_address(
                    profile.get("registered_office_address")),
            },
            "persons_with_significant_control": [
                {"name": p.get("name", ""), "kind": p.get("kind", ""),
                 "nature_of_control": list(p.get("natures_of_control") or ()),
                 "nationality": p.get("nationality", ""),
                 "country_of_residence": p.get("country_of_residence", "")}
                for p in psc[:10]
            ],
            "note": ("" if psc else
                     "No person with significant control is on file for "
                     "this company."),
            "source": "UK Companies House",
        }

    matches = client.search(asked)
    return {
        "asked": asked,
        "found": len(matches),
        "companies": [
            {"number": m.get("company_number", ""), "name": m.get("title", ""),
             "status": m.get("company_status", ""),
             "type": m.get("company_type", "")}
            for m in matches[:10]
        ],
        "note": ("" if matches else
                 "No company on the UK register matches this name."),
        "source": "UK Companies House",
    }


# ---------------------------------------------------------------------------
# OpenCorporates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenCorporatesClient:
    """Global company search, reached over HTTP. See ``CompaniesHouseClient``
    above for why the transport is a field rather than a closure."""

    url: str = OPENCORPORATES_URL
    #: Required -- see ``from_env`` and the module docstring. Out of
    #: ``repr`` for the same reason every credential in this codebase is.
    api_token: str = field(default="", repr=False)
    transport: Transport = field(default=_http_transport)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "OpenCorporatesClient":
        """The token, read the way ``bedrock.py`` and ``azure.py`` read
        theirs: from the environment and nowhere else. Its absence is not
        tolerated quietly -- a client built with no token would search
        anyway and get rate-limited or refused partway through a book, which
        is a worse failure than refusing before the first request.
        """
        import os

        source = env if env is not None else os.environ
        token = (source.get(OPENCORPORATES_TOKEN_VAR) or "").strip()
        if not token:
            raise RegistryUnavailable(
                f"OpenCorporates is not configured: set "
                f"{OPENCORPORATES_TOKEN_VAR} to a free API token before this "
                f"tool can be used. Its free tier allows 50 requests a day; "
                f"without a token, nothing was looked up."
            )
        return cls(api_token=token)

    def search(self, name: str, jurisdiction: str = "") -> list:
        params = {"q": name}
        if jurisdiction:
            params["jurisdiction_code"] = jurisdiction
        if self.api_token:
            params["api_token"] = self.api_token
        query = urllib.parse.urlencode(params)
        try:
            raw = self.transport(f"{self.url}/companies/search?{query}", None,
                                 {"Accept": "application/json"})
        except RegistryUnavailable:
            raise
        except urllib.error.HTTPError as error:
            raise RegistryUnavailable(
                f"OpenCorporates answered {error.code} and the lookup was "
                f"not performed."
            ) from error
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise RegistryUnavailable(
                "OpenCorporates could not be reached, so the lookup was not "
                "performed."
            ) from error
        try:
            envelope = json.loads(raw)
            companies = envelope["results"]["companies"]
            if not isinstance(companies, list):
                raise TypeError("companies was not a list")
        except (KeyError, TypeError, ValueError) as error:
            raise RegistryUnavailable(
                "OpenCorporates answered in a form this system does not "
                "recognise."
            ) from error
        return companies


def lookup_company(company: str, jurisdiction: str = "", *,
                   client: Optional[OpenCorporatesClient] = None,
                   env: Optional[Mapping[str, str]] = None) -> dict:
    """Search company registries worldwide through OpenCorporates.

    ``jurisdiction`` narrows the search to one register -- OpenCorporates'
    own two-letter-plus codes, such as ``gb`` or ``us_de`` -- and is left
    blank to search everywhere it covers. Raises :class:`RegistryUnavailable`
    with no attempt made at all if no token is configured; see the module
    docstring for why that is a raise and not a quiet empty result.
    """
    asked = (company or "").strip()
    if not asked:
        return {"error": "no company name to look up"}

    client = client or OpenCorporatesClient.from_env(env)
    jurisdiction = (jurisdiction or "").strip()
    results = client.search(asked, jurisdiction)
    matches = [
        (r.get("company") if isinstance(r, Mapping) else None) or {}
        for r in results if isinstance(r, Mapping)
    ]
    return {
        "asked": asked,
        "jurisdiction": jurisdiction or "any",
        "found": len(matches),
        "companies": [
            {"number": m.get("company_number", ""), "name": m.get("name", ""),
             "jurisdiction": m.get("jurisdiction_code", ""),
             "status": m.get("current_status", ""),
             "incorporated_on": m.get("incorporation_date", "")}
            for m in matches[:10]
        ],
        "note": ("" if matches else
                 "No company matching this name was found on OpenCorporates."),
        "source": "OpenCorporates (free tier: 50 requests/day)",
    }

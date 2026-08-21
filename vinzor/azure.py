"""Azure OpenAI — the only place in this system that talks to a model.

Everything above this file is model-agnostic: ``assist.py`` takes a transport
and does not know or care what is behind it. So swapping providers, or running
with no provider at all, changes one module.

**Data residency is enforced here, in two places, from the first day.** An
Indian FME's investor data leaving India is not a performance problem, it is a
regulatory one, and it is not the kind of thing to bolt on after a pilot.

1. *Before any call.* The region is declared in configuration and checked
   against an allowlist of Indian Azure regions. A resource in Sweden refuses
   to start, loudly.
2. *On every response.* Azure reports which region actually served a request
   in the ``x-ms-region`` header. A **Global Standard** deployment will happily
   route a prompt to whichever datacentre has capacity — the declared region
   says nothing about where the tokens went. So the served region is checked
   too, and a request served outside India raises rather than returning a
   draft. Deploy as *Regional* or *Data Zone (India)*, never Global.

3. *Redirects are refused, not followed.* ``urlopen`` follows 3xx by default
   and carries every request header to the new location, key included and
   across origins. So one ``Location`` header would defeat both guards at
   once — the call goes elsewhere, and the region check reads a header the
   redirect target chose. Nothing here follows a redirect.

A residency breach is deliberately **not** a ``DraftingUnavailable``. Every
other failure here is silent and cheap — no model, no draft, the officer works
as they did yesterday. A breach is different: it means data went somewhere it
should not have, and the run stops so a person looks at it.

**The key is read from the environment and nowhere else.** Never a file, never
an argument, never an event, never an exception message. ``tests/test_azure.py``
holds that in place.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .assist import Drafter, DraftingUnavailable

#: Azure regions inside India. The Jio regions are included because they are
#: Azure regions physically in India; whether a given model is available in one
#: is a separate question the deployment answers.
INDIA_REGIONS = frozenset({
    "centralindia", "southindia", "westindia",
    "jioindiacentral", "jioindiawest",
})

#: The environment variable holding the key. Named once so that tests can sweep
#: for it and be sure they are sweeping for the right thing.
KEY_VAR = "AZURE_OPENAI_KEY"

#: Azure's dated API contract. Pinned: an API version that moves underneath a
#: regulated system is a change nobody reviewed.
API_VERSION = "2024-10-21"

#: US dollars per thousand tokens. Defaults are gpt-4o-mini list price at the
#: time of writing; both are overridable, because a price nobody can correct
#: is a budget cap that quietly stops being true.
COST_PER_1K_INPUT = 0.00015
COST_PER_1K_OUTPUT = 0.00060

#: Room for the JSON reply and no more. A draft is four sentences.
MAX_OUTPUT_TOKENS = 3000

#: Seconds. An officer is waiting; a model that is thinking this long has
#: already failed to be useful.
TIMEOUT_SECONDS = 45


class ConfigurationMissing(DraftingUnavailable):
    """The assistant is not set up. Nothing is wrong; there is just no model."""


class DataResidencyError(RuntimeError):
    """Data was sent, or would be sent, outside India. Loud on purpose."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AzureConfig:
    """Where the model is, and what it costs. Never what the key is."""

    endpoint: str
    deployment: str
    region: str
    api_version: str = API_VERSION
    cost_per_1k_input: float = COST_PER_1K_INPUT
    cost_per_1k_output: float = COST_PER_1K_OUTPUT

    def __post_init__(self) -> None:
        if self.region not in INDIA_REGIONS:
            raise DataResidencyError(
                f"{self.region!r} is not an Azure region in India; this "
                f"workspace may only use "
                f"{', '.join(sorted(INDIA_REGIONS))}"
            )

    @property
    def url(self) -> str:
        return (f"{self.endpoint.rstrip('/')}/openai/deployments/"
                f"{self.deployment}/chat/completions"
                f"?api-version={self.api_version}")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AzureConfig":
        """Read configuration, or say plainly that there is none.

        Absent configuration is a normal state, not an error: the product works
        without an assistant. A *wrong* region is an error.
        """
        env = os.environ if env is None else env
        endpoint = (env.get("AZURE_OPENAI_ENDPOINT") or "").strip()
        deployment = (env.get("AZURE_OPENAI_DEPLOYMENT") or "").strip()
        region = (env.get("AZURE_OPENAI_REGION") or "").strip().lower().replace(" ", "")
        missing = [name for name, value in (
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_DEPLOYMENT", deployment),
            ("AZURE_OPENAI_REGION", region),
            (KEY_VAR, (env.get(KEY_VAR) or "").strip()),
        ) if not value]
        if missing:
            raise ConfigurationMissing(
                "the assistant is not configured: " + ", ".join(missing)
            )
        return cls(
            endpoint=endpoint,
            deployment=deployment,
            region=region,
            api_version=(env.get("AZURE_OPENAI_API_VERSION") or API_VERSION).strip(),
            cost_per_1k_input=_money(env, "AZURE_OPENAI_COST_INPUT",
                                     COST_PER_1K_INPUT),
            cost_per_1k_output=_money(env, "AZURE_OPENAI_COST_OUTPUT",
                                      COST_PER_1K_OUTPUT),
        )


def _money(env: Mapping[str, str], name: str, fallback: float) -> float:
    try:
        return float(env[name])
    except (KeyError, TypeError, ValueError):
        return fallback


def configured(env: Optional[Mapping[str, str]] = None) -> bool:
    """Is there a model to talk to? Used to decide whether to offer drafting.

    It answers *is there configuration*, and nothing else. It used to catch
    ``ConfigurationMissing`` alone while ``AzureConfig`` also raises
    ``DataResidencyError`` for a region outside India -- so one typo in
    ``AZURE_OPENAI_REGION`` made this function raise from inside four request
    handlers that call it outside their own try blocks. Measured with
    ``india-central`` (a plausible slip for ``jioindiacentral``): the server
    started, served the briefing, and then dropped the connection with no HTTP
    reply at all on every party record, every question and every watchlist
    check, leaving a Python traceback on the operator's console. A
    configuration mistake became a silent partial outage.

    A bad region is now refused by ``check_region`` at start-up, where it is
    one sentence the operator can act on, rather than once per page view.
    """
    try:
        AzureConfig.from_env(env)
    except (ConfigurationMissing, DataResidencyError):
        return False
    return True


def check_region(env: Optional[Mapping[str, str]] = None) -> None:
    """Refuse to start on a region outside India. Called from the boundaries.

    Loudly means at boot. Anything configured at all is checked; a workspace
    with no model configured is left alone, because running without an
    assistant is an ordinary way to run.
    """
    try:
        AzureConfig.from_env(env)
    except ConfigurationMissing:
        return


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------

#: Takes (url, body, headers) and returns (body, response headers).
HttpCall = Callable[[str, bytes, Mapping[str, str]], tuple[bytes, Mapping[str, str]]]


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Follow nothing. A chat-completions endpoint never legitimately moves.

    ``urlopen`` follows 3xx by default and carries every request header to the
    new location — including ``api-key``, and including across origins. That
    turns one ``Location`` header, from a proxy or a DNS answer, into both a
    residency breach and a credential disclosure: the call goes wherever the
    header points, and ``check_served_region`` then reads an ``x-ms-region``
    that the redirect target wrote for itself. Measured before this was
    closed: a 302 sent the key to a second host and the region check passed.

    Returning ``None`` makes urllib raise the 3xx as an ``HTTPError`` instead
    of chasing it, and the caller turns that into a refusal.
    """

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


#: Built once. Holds no key: the key is a per-request header, never on the
#: opener, so nothing long-lived carries the credential.
_OPENER = urllib.request.build_opener(_RefuseRedirects)


def _http(url: str, body: bytes, headers: Mapping[str, str]):
    request = urllib.request.Request(url, data=body, headers=dict(headers),
                                     method="POST")
    with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(), dict(response.headers)


def check_served_region(headers: Mapping[str, str], config: AzureConfig) -> None:
    """Refuse a reply that was served outside India.

    Header names are case-insensitive on the wire, so they are matched that
    way. Azure does not always send the header; when it is absent the declared
    region stands, which is why the deployment type matters and is documented
    above.
    """
    served = ""
    for name, value in headers.items():
        if name.lower() == "x-ms-region":
            served = str(value).strip().lower().replace(" ", "")
            break
    if served and served not in INDIA_REGIONS:
        raise DataResidencyError(
            f"the request was served from {served!r}, outside India. Redeploy "
            f"the model as a Regional or Data Zone deployment in "
            f"{config.region!r} — a Global deployment routes wherever there is "
            f"capacity."
        )


@dataclass(frozen=True)
class AzureTransport:
    """One chat completion. Returns the parsed reply and the token counts.

    Shaped to ``assist.Transport`` so that ``assist.py`` never learns the word
    "Azure" — the whole provider is this one object.
    """

    config: AzureConfig
    #: Read at call time, not construction: a rotated key takes effect on the
    #: next request, and the value is never held on an object that could be
    #: printed, pickled or logged.
    key_var: str = KEY_VAR
    http: HttpCall = field(default=_http, repr=False)
    #: Kept out of ``repr`` deliberately, and this is not cosmetic:
    #: ``repr(os.environ)`` prints every variable, key included, and a dataclass
    #: repr is exactly what a traceback, a debugger or a logger reaches for.
    #: A test holds this in place, because it was true before it was fixed.
    env: Optional[Mapping[str, str]] = field(default=None, repr=False)

    def _key(self) -> str:
        env = os.environ if self.env is None else self.env
        key = (env.get(self.key_var) or "").strip()
        if not key:
            raise ConfigurationMissing(f"{self.key_var} is not set")
        return key

    def __call__(self, messages: Sequence[Mapping[str, str]]):
        body = json.dumps({
            "messages": [dict(m) for m in messages],
            # Deterministic as far as the provider allows: the same file should
            # not produce a different recommendation on a Tuesday.
            "temperature": 0,
            "top_p": 1,
            "seed": 7,
            # ``max_completion_tokens`` rather than ``max_tokens``, and a
            # budget several times what the answer needs. A reasoning model
            # spends this allowance thinking before it writes a word:
            # measured on this deployment, a two-sentence summary used 633
            # tokens of which 480 were reasoning. At the old ceiling of 700
            # the thinking occasionally consumed the lot, the content came
            # back empty, and the reply read as "the service replied with
            # something unreadable" -- a wire fault for what was really a
            # budget that predated the model behind it.
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
        }).encode()

        try:
            raw, headers = self.http(
                self.config.url, body,
                {"Content-Type": "application/json", "api-key": self._key()},
            )
        except urllib.error.HTTPError as error:
            if 300 <= error.code < 400:
                # Not a refusal — a redirect we declined to follow. Said
                # separately because the remedy is different: somebody has
                # put a proxy or a wrong endpoint in front of the model.
                raise DataResidencyError(
                    f"the endpoint answered {error.code} and asked for the "
                    f"request to be sent somewhere else. It was not sent, and "
                    f"the key did not travel. Check AZURE_OPENAI_ENDPOINT "
                    f"points at your own resource in {self.config.region!r}."
                ) from None
            # Status only. A provider error body is not ours to put anywhere,
            # and echoing request detail is how credentials end up in logs.
            raise DraftingUnavailable(
                f"the drafting service refused the request ({error.code})"
            ) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise DraftingUnavailable("the drafting service did not answer") from None

        check_served_region(headers, self.config)

        try:
            envelope = json.loads(raw)
            content = envelope["choices"][0]["message"]["content"]
            reply = json.loads(content)
            usage = envelope.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise DraftingUnavailable(
                "the drafting service replied with something unreadable"
            ) from None

        if not isinstance(reply, dict):
            raise DraftingUnavailable("the drafting service replied with a non-answer")

        return (reply,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0))


def drafter(config: Optional[AzureConfig] = None, *,
            env: Optional[Mapping[str, str]] = None,
            http: HttpCall = _http) -> Drafter:
    """The assembled drafter, ready for ``assist.prepare_drafts``."""
    config = AzureConfig.from_env(env) if config is None else config
    return Drafter(
        transport=AzureTransport(config=config, http=http, env=env),
        model=config.deployment,
        region=config.region,
        cost_per_1k_input=config.cost_per_1k_input,
        cost_per_1k_output=config.cost_per_1k_output,
    )

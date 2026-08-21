"""Amazon Bedrock — the second place in this system that talks to a model.

A sibling of ``azure.py``, not a replacement. Everything above both files is
model-agnostic: ``assist.py`` takes a transport and never learns whose model is
behind it, which is the whole reason a second provider is one module and not a
rewrite.

It exists because the product is deployed on AWS, and an Azure key on a public
box is an unauthenticated spend endpoint. It speaks Bedrock's **Converse** API,
the one Bedrock surface that has the same shape for every model, so changing
model is a configuration change rather than a parsing change.

**Data residency is the whole difficulty here, and it is worse than Azure's.**

Azure lets you deploy a model *in* a region and then warns that a Global
deployment routes elsewhere. Bedrock inverts that. In ``ap-south-1`` every
Anthropic model is reachable **only** through an inference profile, and the
profiles on offer are ``apac.*`` — which routes anywhere in Asia-Pacific,
Tokyo and Sydney included — and ``global.*``, which routes anywhere at all.
There is no India-pinned Claude. Verified against the account this runs in on
22 August 2026: ``list-foundation-models --by-provider anthropic`` returned ten
models and every one was ``INFERENCE_PROFILE`` only.

So this module refuses inference profiles by prefix, and the consequence is
stated rather than hidden: **the strongest models on Bedrock cannot be used by
this product in India, and it uses a lesser one instead.** That is the correct
trade for a system whose loudest rule is that investor data does not leave the
country, and it is the sort of thing a firm should be told rather than left to
find out during an inspection.

The enforcement, in three places:

1. *The region.* Checked against an allowlist of AWS regions in India. The
   endpoint is then **derived** from it and is not configurable, so there is no
   second setting that could quietly point somewhere else.
2. *The model id.* A cross-region inference profile is refused before the first
   call. This is the Bedrock equivalent of Azure's Global-deployment trap, and
   it is the one that actually bites here.
3. *The signature.* SigV4 binds every request to one region and one service:
   the credential scope is literally ``.../ap-south-1/bedrock/aws4_request``,
   and a signature scoped to Mumbai does not validate anywhere else. That is
   stronger than Azure's ``x-ms-region`` header, because it is not the provider
   telling us afterwards where the request went — it is the request being
   unable to go anywhere else.

**What cannot be checked, said plainly.** AWS sends no "served from" header, so
there is no equivalent of Azure's per-response check. The guarantee here is
structural — points 2 and 3 — rather than observed. If AWS ever served a
region-pinned on-demand model from elsewhere, nothing in this file would see
it.

**Credentials are never configuration.** They come from the environment, or
from the instance role over IMDSv2 — never from a file, an argument, an event
or an exception. On the deployed instance there is no key at all: the role is
attached to the machine and the token is minted per request.

No dependency. ``boto3`` would do the signing, and it is a large dependency in
the audit path of a system whose core has none; SigV4 is sixty lines of
``hmac``. The rule in AGENTS.md is not negotiable for convenience.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .assist import Drafter, DraftingUnavailable
from .azure import ConfigurationMissing, DataResidencyError, HttpCall

#: AWS regions physically in India. Mumbai and Hyderabad; there are no others,
#: and this list is the whole of what this product may talk to.
INDIA_REGIONS = frozenset({"ap-south-1", "ap-south-2"})

#: A model id beginning with one of these is a **cross-region inference
#: profile**: AWS serves it from whichever region in that geography has
#: capacity. ``apac.`` reaches Tokyo, Seoul, Singapore, Sydney and Mumbai;
#: ``global.`` reaches everywhere. Both are refused however good the model
#: behind them, because "the data probably stayed in India" is not a sentence
#: anybody can put in front of a regulator.
ROUTING_PREFIXES = ("apac.", "global.", "us.", "eu.", "us-gov.", "ca.", "au.")

#: The default model. Chosen by measurement, and the measurement is the only
#: reason it is this one rather than the first that answered.
#:
#: Every Anthropic model in ap-south-1 is inference-profile-only, so Claude is
#: unreachable under the residency rule above and the choice is between what
#: runs on demand in Mumbai. Three do. On 22 August 2026, against the reader
#: flow in ``ask.py`` and the drafting flow in ``assist.py``:
#:
#:     mistral.mistral-large-3-675b-instruct   reader 6/6   drafts 3/3   1.8s
#:     deepseek.v3.2                           reader 5/6   drafts 3/3   2.2s
#:     qwen.qwen3-235b-a22b-2507-v1:0          reader 1/4   drafts 3/3
#:
#: The qwen figure is the point. It was the default first, chosen because it
#: returned clean JSON to a one-line prompt -- and then failed three questions
#: in four on the real reader prompt, replying in prose with no JSON object in
#: it at all. A model that follows a simple instruction is not a model that
#: follows a hard one, and the difference does not show up until the whole
#: flow is run. Override with VINZOR_BEDROCK_MODEL.
DEFAULT_MODEL = "mistral.mistral-large-3-675b-instruct"

#: US dollars per thousand tokens. **These are placeholders and are meant to
#: be set.** Bedrock prices per model and the figure moves; a cap computed
#: from a number nobody checked is a cap that quietly stops being true, which
#: is the reasoning behind the Azure defaults and the same remedy: both are
#: overridable from the environment.
COST_PER_1K_INPUT = 0.0002
COST_PER_1K_OUTPUT = 0.0006

#: Room for the JSON reply and no more. A draft is four sentences.
MAX_OUTPUT_TOKENS = 3000

#: Seconds. An officer is waiting.
TIMEOUT_SECONDS = 45

_SERVICE = "bedrock"
_ALGORITHM = "AWS4-HMAC-SHA256"

#: Where the instance role's credentials come from when there is no key in the
#: environment. Link-local, so it is never reachable from anywhere but the
#: machine itself.
_IMDS = "http://169.254.169.254"
_IMDS_TIMEOUT = 2


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BedrockConfig:
    """Which model, in which Indian region, and what it costs."""

    region: str
    model_id: str
    cost_per_1k_input: float = COST_PER_1K_INPUT
    cost_per_1k_output: float = COST_PER_1K_OUTPUT

    def __post_init__(self) -> None:
        if self.region not in INDIA_REGIONS:
            raise DataResidencyError(
                f"{self.region!r} is not an AWS region in India; this "
                f"workspace may only use {', '.join(sorted(INDIA_REGIONS))}"
            )
        lowered = self.model_id.lower()
        for prefix in ROUTING_PREFIXES:
            if lowered.startswith(prefix):
                raise DataResidencyError(
                    f"{self.model_id!r} is a cross-region inference profile: "
                    f"AWS serves it from whichever region in that geography "
                    f"has capacity, so investor data would leave India. Use a "
                    f"model that runs on demand in {self.region!r} instead - "
                    f"which rules out every Anthropic model, because in India "
                    f"they are offered only through such a profile."
                )

    @property
    def url(self) -> str:
        """Derived from the region, never configured.

        A configurable endpoint is a second place the destination could be
        set, and two settings can disagree. There is one region, and the
        address follows from it.
        """
        model = urllib.parse.quote(self.model_id, safe="")
        return (f"https://bedrock-runtime.{self.region}.amazonaws.com"
                f"/model/{model}/converse")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "BedrockConfig":
        """Read configuration, or say plainly that there is none.

        Absent configuration is a normal state: the product works without an
        assistant. A region outside India, or a routing profile, is an error.
        """
        env = os.environ if env is None else env
        if not (env.get("VINZOR_BEDROCK") or "").strip():
            raise ConfigurationMissing(
                "the assistant is not configured: VINZOR_BEDROCK"
            )
        region = (env.get("VINZOR_BEDROCK_REGION")
                  or env.get("AWS_REGION")
                  or env.get("AWS_DEFAULT_REGION") or "").strip().lower()
        if not region:
            raise ConfigurationMissing(
                "the assistant is not configured: VINZOR_BEDROCK_REGION"
            )
        return cls(
            region=region,
            model_id=(env.get("VINZOR_BEDROCK_MODEL") or DEFAULT_MODEL).strip(),
            cost_per_1k_input=_money(env, "VINZOR_BEDROCK_COST_INPUT",
                                     COST_PER_1K_INPUT),
            cost_per_1k_output=_money(env, "VINZOR_BEDROCK_COST_OUTPUT",
                                      COST_PER_1K_OUTPUT),
        )


def _money(env: Mapping[str, str], name: str, fallback: float) -> float:
    try:
        return float(env[name])
    except (KeyError, TypeError, ValueError):
        return fallback


def configured(env: Optional[Mapping[str, str]] = None) -> bool:
    """Is there a Bedrock model to talk to?

    Catches ``DataResidencyError`` as well as ``ConfigurationMissing``, for the
    reason ``azure.configured`` gives at length: this is called from inside
    request handlers, outside their own try blocks, and one bad setting must
    not turn every page into a dropped connection.
    """
    try:
        BedrockConfig.from_env(env)
    except (ConfigurationMissing, DataResidencyError):
        return False
    return True


def check_region(env: Optional[Mapping[str, str]] = None) -> None:
    """Refuse to start on a region outside India, or on a routing profile."""
    try:
        BedrockConfig.from_env(env)
    except ConfigurationMissing:
        return


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Credentials:
    """Held for the length of one request and never longer.

    The secret is kept out of ``repr`` for the reason ``azure.py`` keeps the
    environment off its dataclass: a repr is exactly what a traceback, a
    debugger or a logger reaches for.
    """

    access_key: str
    secret_key: str = field(repr=False)
    token: str = field(default="", repr=False)


def _from_env(env: Mapping[str, str]) -> Optional[_Credentials]:
    key = (env.get("AWS_ACCESS_KEY_ID") or "").strip()
    secret = (env.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    if key and secret:
        return _Credentials(key, secret,
                            (env.get("AWS_SESSION_TOKEN") or "").strip())
    return None


def _from_instance_role(opener) -> Optional[_Credentials]:
    """The deployed case: no key anywhere, a role attached to the machine.

    IMDSv2, so a token is fetched and presented on each read. The instance is
    launched with ``HttpTokens=required``, which is what stops a server-side
    request forgery inside the application reaching this address with a bare
    GET and walking off with the role's credentials.
    """
    try:
        ask_token = urllib.request.Request(
            f"{_IMDS}/latest/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        with opener.open(ask_token, timeout=_IMDS_TIMEOUT) as answer:
            token = answer.read().decode()

        head = {"X-aws-ec2-metadata-token": token}
        listing = urllib.request.Request(
            f"{_IMDS}/latest/meta-data/iam/security-credentials/", headers=head)
        with opener.open(listing, timeout=_IMDS_TIMEOUT) as answer:
            role = answer.read().decode().strip().splitlines()[0]

        detail = urllib.request.Request(
            f"{_IMDS}/latest/meta-data/iam/security-credentials/{role}",
            headers=head)
        with opener.open(detail, timeout=_IMDS_TIMEOUT) as answer:
            body = json.loads(answer.read())
        return _Credentials(body["AccessKeyId"], body["SecretAccessKey"],
                            body.get("Token") or "")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError,
            KeyError, IndexError):
        return None


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Follow nothing, for the reason ``azure.py`` gives at length.

    A redirect carries every header to the new location, and here that
    includes the ``Authorization`` line and the session token. It would also
    defeat the residency argument: the signature pins the *intended*
    destination, and chasing a ``Location`` header sends the body somewhere
    that signature was never checked against.
    """

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def _http(url: str, body: bytes, headers: Mapping[str, str]):
    request = urllib.request.Request(url, data=body, headers=dict(headers),
                                     method="POST")
    with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(), dict(response.headers)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def sigv4_headers(*, url: str, body: bytes, region: str,
                  when: _datetime.datetime,
                  credentials: _Credentials) -> dict:
    """The Authorization header AWS requires, built by hand.

    Sixty lines instead of a dependency, and worth reading once: the string
    that gets signed names the region and the service, which is why a
    signature made for Mumbai cannot be replayed against Tokyo. That is this
    module's residency guarantee expressed as arithmetic rather than as a
    promise.

    ``when`` is supplied by the caller. This module reads no clock: the
    doctrine holds even here, where the timestamp never touches the log.
    """
    parts = urllib.parse.urlsplit(url)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    day = when.strftime("%Y%m%d")

    signed = {"host": parts.netloc,
              "content-type": "application/json",
              "x-amz-date": stamp}
    if credentials.token:
        signed["x-amz-security-token"] = credentials.token

    names = ";".join(sorted(signed))
    canonical_headers = "".join(f"{n}:{signed[n]}\n" for n in sorted(signed))

    # The path is encoded a **second** time for the signature, and only for
    # the signature: the request itself goes out with the single-encoded
    # form. That is SigV4's rule for every service except S3, and it matters
    # here because a Bedrock model id contains a colon --
    #
    #   sent      /model/qwen.qwen3-235b-a22b-2507-v1%3A0/converse
    #   signed    /model/qwen.qwen3-235b-a22b-2507-v1%253A0/converse
    #
    # Signing the sent form produces a 403 whose body is a generic "check
    # your secret key", which sends you looking at the credential rather
    # than at the four characters that are actually wrong.
    canonical = "\n".join([
        "POST",
        urllib.parse.quote(parts.path, safe="/~"),
        parts.query,
        canonical_headers,
        names,
        _sha256(body),
    ])

    scope = f"{day}/{region}/{_SERVICE}/aws4_request"
    to_sign = "\n".join([_ALGORITHM, stamp, scope, _sha256(canonical.encode())])

    signing_key = _sign(f"AWS4{credentials.secret_key}".encode(), day)
    for piece in (region, _SERVICE, "aws4_request"):
        signing_key = _sign(signing_key, piece)
    signature = hmac.new(signing_key, to_sign.encode(),
                         hashlib.sha256).hexdigest()

    out = dict(signed)
    out["Authorization"] = (
        f"{_ALGORITHM} Credential={credentials.access_key}/{scope}, "
        f"SignedHeaders={names}, Signature={signature}"
    )
    return out


def _unfence(text: str) -> str:
    """Strip a markdown code fence a model wrapped its JSON in.

    Not a guard being relaxed. This is a wire-format concern, the same class
    of thing as a charset: measured across the three candidate models in
    Mumbai, one of them fences its JSON every time, and refusing a well-formed
    answer over its packaging would be rejecting the content for the wrapper.
    Every claim inside is still checked by the guards above this file.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped[3:]
    if body[:4].lower() == "json":
        body = body[4:]
    return body.rsplit("```", 1)[0].strip()


@dataclass(frozen=True)
class BedrockTransport:
    """One Converse call. Returns the parsed reply and the token counts.

    Shaped to ``assist.Transport``, so nothing above ever learns the word
    "Bedrock" — the whole provider is this one object.
    """

    config: BedrockConfig
    #: Supplied by the boundary. SigV4 signatures are time-scoped, so this
    #: genuinely needs a clock — and rather than add this module to the short
    #: list of files allowed to read one, the caller passes it in, exactly as
    #: every date in this system is passed in.
    signed_at: Callable[[], _datetime.datetime]
    http: HttpCall = field(default=_http, repr=False)
    #: Kept out of ``repr``: ``repr(os.environ)`` prints every variable.
    env: Optional[Mapping[str, str]] = field(default=None, repr=False)
    opener: Any = field(default=_OPENER, repr=False)

    def _credentials(self) -> _Credentials:
        env = os.environ if self.env is None else self.env
        found = _from_env(env) or _from_instance_role(self.opener)
        if found is None:
            raise ConfigurationMissing(
                "no AWS credentials: set AWS_ACCESS_KEY_ID and "
                "AWS_SECRET_ACCESS_KEY, or attach a role to the machine"
            )
        return found

    def __call__(self, messages: Sequence[Mapping[str, str]]):
        # Converse keeps the system prompt in a field of its own and wants the
        # conversation itself to begin with the user. ``assist.py`` builds an
        # OpenAI-shaped list, so the split happens here — at the boundary,
        # where every other difference between providers already lives.
        system = [{"text": m["content"]} for m in messages
                  if m.get("role") == "system"]
        turns = [{"role": m["role"], "content": [{"text": m["content"]}]}
                 for m in messages if m.get("role") in ("user", "assistant")]

        body = json.dumps({
            "messages": turns,
            "system": system,
            "inferenceConfig": {
                "maxTokens": MAX_OUTPUT_TOKENS,
                # Deterministic as far as the provider allows, for the reason
                # azure.py gives: the same file should not produce a different
                # recommendation on a Tuesday. Bedrock exposes no seed, so
                # this is weaker than Azure's and the honest answer is that
                # narrative.py's write-once-read-back is what actually holds
                # a paragraph still.
                "temperature": 0,
                "topP": 1,
            },
        }).encode()

        headers = sigv4_headers(url=self.config.url, body=body,
                                region=self.config.region,
                                when=self.signed_at(),
                                credentials=self._credentials())
        try:
            raw, _served = self.http(self.config.url, body, headers)
        except urllib.error.HTTPError as error:
            if 300 <= error.code < 400:
                raise DataResidencyError(
                    f"the endpoint answered {error.code} and asked for the "
                    f"request to be sent somewhere else. It was not sent, and "
                    f"the credentials did not travel."
                ) from None
            # Status only. A provider error body is not ours to put anywhere,
            # and echoing request detail is how credentials end up in logs.
            raise DraftingUnavailable(
                f"the drafting service refused the request ({error.code})"
            ) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise DraftingUnavailable(
                "the drafting service did not answer") from None

        try:
            envelope = json.loads(raw)
            blocks = envelope["output"]["message"]["content"]
            text = next(b["text"] for b in blocks if "text" in b)
            reply = json.loads(_unfence(text))
            usage = envelope.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError, StopIteration):
            raise DraftingUnavailable(
                "the drafting service replied with something unreadable"
            ) from None

        if not isinstance(reply, dict):
            raise DraftingUnavailable(
                "the drafting service replied with a non-answer")

        return (reply,
                int(usage.get("inputTokens") or 0),
                int(usage.get("outputTokens") or 0))


def drafter(config: Optional[BedrockConfig] = None, *,
            now: Callable[[], _datetime.datetime],
            env: Optional[Mapping[str, str]] = None,
            http: HttpCall = _http) -> Drafter:
    """The assembled drafter, ready for ``assist.prepare_drafts``.

    ``now`` has no default on purpose. A default would be this module reading
    a clock, which is the one thing the core does not do.
    """
    config = BedrockConfig.from_env(env) if config is None else config
    return Drafter(
        transport=BedrockTransport(config=config, signed_at=now, http=http,
                                   env=env),
        model=config.model_id,
        region=config.region,
        cost_per_1k_input=config.cost_per_1k_input,
        cost_per_1k_output=config.cost_per_1k_output,
    )

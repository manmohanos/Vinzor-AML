"""Reading a document that is a photograph, and proposing nothing more.

``extraction.py`` reads the text layer of a PDF. That covers a document
somebody generated and almost nothing a customer actually sends: a real
investor photographs their passport on a phone, and the file that arrives has
no text in it at all. Measured against Sumsub's own published KYC samples --
thirteen files, every one a JPEG or a PNG -- the deterministic reader returned
zero fields and the honest sentence *"there is no text in this file to read"*.
Honest, and useless to the officer who then typed all of it in by hand.

So this is the other half, and it is deliberately a **separate module** rather
than a branch inside the reader, because it is a different kind of thing and
the difference has to stay visible.

**What is given up, said plainly.** ``extraction.py`` is a table of labels and
a parser: same document in, same fields out, forever. This is a model looking
at a picture. Temperature is nailed to zero and the same image will almost
always give the same answer, but *almost always* is not *always*, and a
compliance file should not have to rely on the difference. Every proposal from
here is marked as having been read by a model, the mark travels onto the
record, and the screen says which reader produced each field.

**Why that is acceptable here and nowhere else.** Nothing in this module
establishes anything. It proposes, exactly as the deterministic reader
proposes, and a person confirms -- and the confirmation is what goes on the
file. The recorded fact is never "a model read this passport"; it is "an
officer looked at this passport and said it shows this date of birth". That is
the same division ``assist.py`` draws around drafting and ``extraction.py``
draws around parsing, and it is the reason a model is allowed near this at
all: **a model may propose or judge; only recorded facts and deterministic
rules may establish.**

**What it is still not allowed to do.** It cannot widen what a kind of
document proves. A utility bill that prints a nationality does not get to
evidence one, however clearly the photograph shows it, because
``documents.KINDS`` decides that and a model is not the place to argue with
it. The filtering happens here, after the model has spoken, on the same table
the deterministic reader obeys.

**And it must never look like a clean read when it did not happen.** A vision
model that is unreachable, refuses, or answers in a shape this cannot parse
returns ``unreadable`` with the reason -- never an empty list of proposals,
which on screen is indistinguishable from a document that genuinely showed
nothing.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Callable, Mapping, Optional

from .documents import KINDS
from .extraction import (_MUST_HAVE_A_DIGIT, _NOT_A_VALUE, _as_iso, _tidy,
                         Proposal, Reading)

#: What the picture is, for the provider. Taken from the bytes rather than
#: from the filename, for the reason ``documents.py`` gives at length: a
#: caller who can name the format can lie about it.
_SHAPES = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
)

#: A photograph of a passport is a few hundred kilobytes; a scan of a bank
#: statement can be several megabytes. Above this the request is refused
#: rather than sent, because a provider timing out halfway through is a
#: failure an officer cannot act on.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: Said to the model. Deliberately narrow: it is asked to *transcribe*, not to
#: assess, identify, verify or conclude. The field names are the record's own,
#: so nothing downstream has to map a model's vocabulary onto ours.
INSTRUCTION = (
    "This is a photograph of an identity or address document. Transcribe what "
    "is printed on it. You are reading, not judging: do not say whether the "
    "document is genuine, valid, expired or acceptable, and do not infer "
    "anything that is not printed on the page.\n\n"
    "Reply with JSON only, no prose, in exactly this shape:\n"
    '{"fields": [{"field": "...", "value": "...", "seen_as": "..."}]}\n\n'
    "Use only these field names, and only where the document actually shows "
    "them: name, dob, nationality, id_document_number, address, pan, cin, "
    "date_of_incorporation, country_of_incorporation.\n"
    "- name: the full name, given name first, as a person would write it.\n"
    "- dob and date_of_incorporation: YYYY-MM-DD.\n"
    "- seen_as: the exact line of text on the document you read the value "
    "from, so a person can find it on the page without your help.\n\n"
    "Omit any field you cannot read. Never guess at a character you cannot "
    "see, and never fill a placeholder such as 00/00/0000 or XXXX with a real "
    "looking value. If you cannot read the image at all, reply "
    '{"fields": []}.'
)


class PhotographUnreadable(RuntimeError):
    """The picture could not be read. Never a wrong field, always no field."""


def shape_of(data: bytes) -> str:
    for magic, name in _SHAPES:
        if data.startswith(magic):
            return name
    return ""


def _fields_from(reply: Any) -> tuple:
    """The model's answer, or a refusal. Never a silent empty list."""
    if isinstance(reply, (str, bytes)):
        text = reply.decode("utf-8", "replace") if isinstance(reply, bytes) else reply
        text = text.strip()
        # Providers fence JSON in markdown about half the time.
        if text.startswith("```"):
            text = text.split("```")[1] if "```" in text[3:] else text[3:]
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]
        try:
            reply = json.loads(text.strip())
        except ValueError:
            raise PhotographUnreadable(
                "the reader answered in a form this system cannot read"
            ) from None
    if not isinstance(reply, Mapping):
        raise PhotographUnreadable(
            "the reader answered in a form this system cannot read")
    fields = reply.get("fields")
    if not isinstance(fields, (list, tuple)):
        raise PhotographUnreadable(
            "the reader answered without any fields in it")
    return tuple(f for f in fields if isinstance(f, Mapping))


def read(data: bytes, *, kind: str, eyes: Callable,
         holds: Optional[Mapping[str, str]] = None) -> Reading:
    """What a photographed document appears to show, for a person to confirm.

    ``eyes`` is a transport taking (image bytes, format, instruction) and
    returning the model's reply. Injected rather than constructed, so every
    test here runs offline against a scripted reader and nothing in this
    module knows which provider is behind it.
    """
    allowed = set(KINDS.get(kind, ("", ()))[1])
    if not allowed:
        return Reading(kind=kind, unreadable=(
            "This system does not know what a document of that kind is "
            "allowed to evidence, so nothing was taken from it."))
    if not data:
        return Reading(kind=kind, unreadable="There is nothing in this file.")
    if len(data) > MAX_IMAGE_BYTES:
        return Reading(kind=kind, unreadable=(
            "This image is too large to be read automatically. It is on the "
            "record as filed, and what it shows has to be entered by hand."))
    fmt = shape_of(data)
    if not fmt:
        return Reading(kind=kind, unreadable=(
            "This file is not a photograph this system can read. It is on "
            "the record as filed."))

    try:
        reply = eyes(data, fmt, INSTRUCTION)
        found = _fields_from(reply)
    except PhotographUnreadable as refused:
        return Reading(kind=kind, unreadable=(
            f"This photograph could not be read: {refused}. Nothing was taken "
            f"from it, and it is on the record as filed."))
    except Exception:                   # noqa: BLE001 - any failure is a refusal
        # Deliberately not an empty Reading. A reader that could not be
        # reached, reported as a document that showed nothing, is the same
        # defect as a watchlist that answered while it was still indexing.
        return Reading(kind=kind, unreadable=(
            "The reader that looks at photographs could not be reached, so "
            "this document has not been read. It is on the record as filed, "
            "and nothing has been proposed from it."))

    on_record = {k: str(v or "") for k, v in (holds or {}).items()}
    proposals = []
    seen_fields = set()
    for one in found:
        field = str(one.get("field") or "").strip().lower()
        value = _tidy(str(one.get("value") or ""))
        line = _tidy(str(one.get("seen_as") or ""))[:160]
        # Every filter the deterministic reader applies, applied again. The
        # model is not trusted to have obeyed the instruction it was given.
        if field not in allowed or field in seen_fields:
            continue
        if not value or value.lower() in _NOT_A_VALUE or len(value) < 2:
            continue
        if field in _MUST_HAVE_A_DIGIT and not any(c.isdigit() for c in value):
            continue
        if field in ("dob", "date_of_incorporation"):
            value = _as_iso(value)
            if not value:
                continue
        seen_fields.add(field)
        held = on_record.get(field, "")
        proposals.append(Proposal(
            field=field, value=value,
            seen_as=line or "read from the photograph",
            agrees=bool(held) and held.strip().lower() == value.strip().lower(),
            on_record=held,
            # The whole reason this module is separate. An officer confirming
            # a field has to know whether it was parsed or looked at.
            read_by=Proposal.BY_MODEL))

    if not proposals:
        return Reading(kind=kind, unreadable=(
            "Nothing this system recognises was found in this photograph. It "
            "is on the record as filed."))
    return Reading(kind=kind, proposals=tuple(proposals))


def bedrock_eyes(*, now, env: Optional[Mapping[str, str]] = None, http=None):
    """A reader for photographs, over Bedrock's Converse API.

    Everything structural is borrowed from ``ask.bedrock_conversation`` and
    for the same reasons: one place a credential is read, the residency rule
    enforced before the call, and a redirect refused loudly rather than
    followed -- a redirect is how one header would send a photograph of an
    Indian investor's passport somewhere else with the credentials attached.

    **The model has to be one Bedrock will serve directly in India.** Every
    Anthropic model in ``ap-south-1`` is reachable only through an inference
    profile that routes across Asia-Pacific or the world, and ``bedrock.py``
    refuses those by prefix. Checked against this account on 22 August 2026,
    the vision-capable models Bedrock serves on demand in Mumbai include
    ``mistral.mistral-large-3-675b-instruct`` -- already this product's
    default -- and ``qwen.qwen3-vl-235b-a22b``. Measured on thirteen of
    Sumsub's published KYC samples, Mistral read the German passport in 2.0
    seconds against Qwen's 3.6 and returned the residence line as well, so
    the default stands and no second setting was introduced to get this
    working.

    ``now`` is required and has no default, because SigV4 signatures are
    time-scoped and no module under ``vinzor/`` may read a clock.
    """
    from .bedrock import (BedrockConfig, DataResidencyError, _from_env,
                          _from_instance_role, _http, _OPENER, sigv4_headers)

    config = (BedrockConfig.from_env(env) if env is not None
              else BedrockConfig.from_env())
    call = http or _http
    source = env if env is not None else None

    def look(data: bytes, fmt: str, instruction: str):
        import os
        import urllib.error

        environment = source if source is not None else os.environ
        credentials = _from_env(environment) or _from_instance_role(_OPENER)
        if credentials is None:
            raise PhotographUnreadable(
                "there are no credentials for the reader that looks at "
                "photographs")

        body = json.dumps({
            "messages": [{"role": "user", "content": [
                {"image": {"format": fmt, "source": {
                    "bytes": base64.b64encode(data).decode("ascii")}}},
                {"text": instruction},
            ]}],
            # Zero, and honest about what that buys. It removes the sampling,
            # not the model: the same photograph will almost always give the
            # same fields and *almost always* is why every proposal from here
            # is marked as read by a model rather than parsed.
            "inferenceConfig": {"maxTokens": 1500, "temperature": 0,
                                "topP": 1},
        }).encode()

        headers = sigv4_headers(url=config.url, body=body,
                                region=config.region, when=now(),
                                credentials=credentials)
        try:
            raw, _headers = call(config.url, body, headers)
        except urllib.error.HTTPError as refusal:
            if 300 <= refusal.code < 400:
                raise DataResidencyError(
                    f"the endpoint answered {refusal.code} and asked for the "
                    f"photograph to be sent somewhere else. It was not sent, "
                    f"and the credentials did not travel."
                ) from None
            raise PhotographUnreadable(
                f"the reader refused the photograph ({refusal.code})"
            ) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise PhotographUnreadable("the reader did not answer") from None

        try:
            envelope = json.loads(raw)
            blocks = envelope["output"]["message"]["content"]
            return next(b["text"] for b in blocks if "text" in b)
        except (ValueError, KeyError, IndexError, TypeError, StopIteration):
            raise PhotographUnreadable(
                "the reader replied with something this system cannot read"
            ) from None

    return look

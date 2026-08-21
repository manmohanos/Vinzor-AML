"""The Bedrock boundary — residency, signing, and failing cheaply.

No network. The HTTP call is injected, so what is under test is the contract:
that data cannot leave India, that credentials cannot leave the process, and
that every other failure costs the officer nothing.

The residency argument here is different from Azure's and weaker in one place
and stronger in another, so both halves are tested rather than asserted in a
docstring. Weaker: AWS sends no "served from" header, so there is no
per-response check. Stronger: SigV4 names the region in the string it signs,
so a signature made for Mumbai is arithmetic that does not validate anywhere
else.
"""

from __future__ import annotations

import datetime
import json
import urllib.error
from typing import Mapping

import pytest

from vinzor.assist import DraftingUnavailable
from vinzor.azure import ConfigurationMissing, DataResidencyError
from vinzor.bedrock import (
    DEFAULT_MODEL,
    INDIA_REGIONS,
    ROUTING_PREFIXES,
    BedrockConfig,
    BedrockTransport,
    _Credentials,
    _unfence,
    configured,
    drafter,
    sigv4_headers,
)

ENV = {
    "VINZOR_BEDROCK": "1",
    "VINZOR_BEDROCK_REGION": "ap-south-1",
    "AWS_ACCESS_KEY_ID": "AKIASENTINELDONOTLEAK",
    "AWS_SECRET_ACCESS_KEY": "sk-SENTINEL-DO-NOT-LEAK",
}

#: A fixed instant, so a signature is a value a test can compare rather than
#: something that changes every second. The whole point of passing the clock
#: in is that this is possible.
WHEN = datetime.datetime(2026, 8, 22, 9, 30, 0, tzinfo=datetime.timezone.utc)

CREDENTIALS = _Credentials("AKIASENTINELDONOTLEAK", "sk-SENTINEL-DO-NOT-LEAK")


def env(**over):
    merged = dict(ENV)
    merged.update(over)
    return {k: v for k, v in merged.items() if v is not None}


def answer(payload=None, *, usage=(400, 120), text=None):
    """A canned Converse response, plus the calls it recorded."""
    payload = payload if payload is not None else {
        "recommendation": "CANNOT_TELL",
        "reasoning": "There is not enough on the file to tell these apart.",
        "suggested_wording": "I could not resolve this from the record we hold.",
        "checks": ["Ask the investor for a passport copy"],
    }
    calls = []

    def http(url, body, request_headers):
        calls.append({"url": url, "body": json.loads(body),
                      "headers": dict(request_headers)})
        envelope = {
            "output": {"message": {"role": "assistant", "content": [
                {"text": text if text is not None else json.dumps(payload)}]}},
            "usage": {"inputTokens": usage[0], "outputTokens": usage[1]},
        }
        return json.dumps(envelope).encode(), {}

    return http, calls


def transport(**over):
    http, calls = answer(**{k: v for k, v in over.items()
                            if k in ("payload", "usage", "text")})
    settings = {k: v for k, v in over.items()
                if k not in ("payload", "usage", "text")}
    return BedrockTransport(
        config=BedrockConfig.from_env(env(**settings)),
        signed_at=lambda: WHEN, http=http, env=env(**settings),
    ), calls


MESSAGES = [{"role": "system", "content": "You reply with JSON."},
            {"role": "user", "content": "Compare these two parties."}]


# -- residency ---------------------------------------------------------------


def test_a_region_outside_india_will_not_start():
    with pytest.raises(DataResidencyError):
        BedrockConfig(region="us-east-1", model_id=DEFAULT_MODEL)


def test_both_indian_regions_are_accepted():
    for region in INDIA_REGIONS:
        assert BedrockConfig(region=region, model_id=DEFAULT_MODEL).region == region


@pytest.mark.parametrize("profile", [
    "apac.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-opus-4-5-20251101-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "eu.amazon.nova-pro-v1:0",
])
def test_a_cross_region_inference_profile_is_refused(profile):
    """The trap that actually bites on Bedrock.

    In ap-south-1 every Anthropic model is offered *only* through one of
    these, and the profile routes to whichever region in its geography has
    capacity. Accepting one would mean an Indian FME's investor records
    being read in Tokyo, which is the single thing this architecture says it
    will not do -- so the better model is refused and the product says why.
    """
    with pytest.raises(DataResidencyError) as refusal:
        BedrockConfig(region="ap-south-1", model_id=profile)
    assert "leave India" in str(refusal.value)


def test_every_routing_prefix_is_refused_not_just_the_ones_we_thought_of():
    for prefix in ROUTING_PREFIXES:
        with pytest.raises(DataResidencyError):
            BedrockConfig(region="ap-south-1", model_id=prefix + "some.model")


def test_the_default_model_is_not_itself_a_routing_profile():
    """A default that could not be used would be a trap of its own."""
    assert BedrockConfig(region="ap-south-1", model_id=DEFAULT_MODEL)


def test_the_endpoint_is_derived_from_the_region_and_cannot_be_set():
    config = BedrockConfig(region="ap-south-1", model_id="a.model:0")
    assert config.url.startswith("https://bedrock-runtime.ap-south-1.amazonaws.com/")
    assert "VINZOR_BEDROCK_ENDPOINT" not in json.dumps(
        [f for f in BedrockConfig.__dataclass_fields__])


def test_a_bad_region_is_not_an_assistant_that_raises_on_every_page():
    """The Azure lesson, applied here before it could be learned twice: this
    is called from inside request handlers, outside their try blocks."""
    assert configured(env(VINZOR_BEDROCK_REGION="us-east-1")) is False


def test_an_unconfigured_workspace_simply_has_no_assistant():
    assert configured({}) is False


def test_a_configured_workspace_says_so():
    assert configured(env()) is True


# -- signing -----------------------------------------------------------------


def test_the_signature_names_the_region_so_it_cannot_be_replayed_elsewhere():
    """The residency guarantee, as arithmetic rather than as a promise."""
    headers = sigv4_headers(
        url="https://bedrock-runtime.ap-south-1.amazonaws.com/model/m/converse",
        body=b"{}", region="ap-south-1", when=WHEN, credentials=CREDENTIALS)
    assert "/20260822/ap-south-1/bedrock/aws4_request" in headers["Authorization"]


def test_the_signed_path_is_encoded_twice():
    """Found by a 403 whose body said only "check your secret key".

    SigV4 encodes the path a second time for the signature and only for the
    signature -- the request itself goes out single-encoded. A Bedrock model
    id contains a colon, so this is the difference between %3A on the wire
    and %253A in the string being signed, and getting it wrong sends you
    looking at the credential instead of at four characters.
    """
    config = BedrockConfig(region="ap-south-1",
                           model_id="qwen.qwen3-235b-a22b-2507-v1:0")
    # What goes on the wire is encoded once.
    assert "%3A0" in config.url and "%253A" not in config.url

    # The canonical string is not returned, so this is checked the way AWS
    # checks it: two URLs differing only in how the colon is encoded must
    # not produce the same signature. If the second encoding were being
    # skipped, both would sign the path they were handed and these would
    # match.
    single = sigv4_headers(url=config.url, body=b"{}", region="ap-south-1",
                           when=WHEN, credentials=CREDENTIALS)
    doubled = sigv4_headers(
        url=config.url.replace("%3A", "%253A"), body=b"{}",
        region="ap-south-1", when=WHEN, credentials=CREDENTIALS)
    assert single["Authorization"] != doubled["Authorization"]


def test_the_same_request_signs_identically_twice():
    """The clock is passed in, which is what makes this testable at all."""
    one = sigv4_headers(url="https://bedrock-runtime.ap-south-1.amazonaws.com/x",
                        body=b"{}", region="ap-south-1", when=WHEN,
                        credentials=CREDENTIALS)
    two = sigv4_headers(url="https://bedrock-runtime.ap-south-1.amazonaws.com/x",
                        body=b"{}", region="ap-south-1", when=WHEN,
                        credentials=CREDENTIALS)
    assert one == two


def test_a_session_token_is_signed_rather_than_merely_attached():
    """An instance role's credentials are three values, not two. A token sent
    but unsigned is a request AWS refuses, and the refusal looks like a
    broken key."""
    temporary = _Credentials("AKIA", "secret", "a-session-token")
    headers = sigv4_headers(url="https://bedrock-runtime.ap-south-1.amazonaws.com/x",
                            body=b"{}", region="ap-south-1", when=WHEN,
                            credentials=temporary)
    assert headers["x-amz-security-token"] == "a-session-token"
    assert "x-amz-security-token" in headers["Authorization"]


# -- secrecy -----------------------------------------------------------------


def test_the_secret_is_never_in_a_repr():
    """A repr is what a traceback, a debugger and a logger all reach for."""
    printed = repr(_Credentials("AKIAVISIBLE", "sk-SENTINEL-DO-NOT-LEAK", "tok"))
    assert "sk-SENTINEL-DO-NOT-LEAK" not in printed
    assert "tok" not in printed


def test_the_transport_repr_cannot_print_the_environment():
    talker, _calls = transport()
    assert "sk-SENTINEL-DO-NOT-LEAK" not in repr(talker)


def test_no_provider_error_message_can_carry_the_request():
    def http(url, body, headers):
        raise urllib.error.HTTPError(url, 500, "boom", {},
                                     None)  # type: ignore[arg-type]

    talker = BedrockTransport(config=BedrockConfig.from_env(env()),
                              signed_at=lambda: WHEN, http=http, env=env())
    with pytest.raises(DraftingUnavailable) as failure:
        talker(MESSAGES)
    said = str(failure.value)
    assert "500" in said
    assert "sk-SENTINEL-DO-NOT-LEAK" not in said and "AKIA" not in said


# -- the wire ----------------------------------------------------------------


def test_the_system_prompt_travels_in_its_own_field():
    """Converse does not take a system turn in the message list, and a
    system prompt smuggled in as a user turn is a prompt the model weighs
    differently from the one that was written."""
    talker, calls = transport()
    talker(MESSAGES)
    sent = calls[0]["body"]
    assert sent["system"] == [{"text": "You reply with JSON."}]
    assert [t["role"] for t in sent["messages"]] == ["user"]


def test_the_token_counts_come_back_under_bedrocks_names():
    talker, _calls = transport(usage=(321, 45))
    _reply, tokens_in, tokens_out = talker(MESSAGES)
    assert (tokens_in, tokens_out) == (321, 45)


def test_json_in_a_code_fence_is_still_an_answer():
    """One of the three models available in Mumbai fences its JSON every
    time. Refusing it would be rejecting the content for its wrapper."""
    fenced = '```json\n{"recommendation": "CANNOT_TELL"}\n```'
    talker, _calls = transport(text=fenced)
    reply, _in, _out = talker(MESSAGES)
    assert reply["recommendation"] == "CANNOT_TELL"


def test_unfencing_leaves_ordinary_json_alone():
    assert _unfence('{"a": 1}') == '{"a": 1}'
    assert _unfence('  {"a": 1}  ') == '{"a": 1}'


def test_a_redirect_is_a_breach_not_a_hiccup():
    """Loud, for the reason azure.py gives: a redirect carries every header
    to the new location, credentials included, and the signature pinned a
    destination the body would then not be going to."""
    def http(url, body, headers):
        raise urllib.error.HTTPError(url, 302, "moved", {},
                                     None)  # type: ignore[arg-type]

    talker = BedrockTransport(config=BedrockConfig.from_env(env()),
                              signed_at=lambda: WHEN, http=http, env=env())
    with pytest.raises(DataResidencyError):
        talker(MESSAGES)


def test_an_unreachable_provider_costs_the_officer_nothing():
    def http(url, body, headers):
        raise TimeoutError("no answer")

    talker = BedrockTransport(config=BedrockConfig.from_env(env()),
                              signed_at=lambda: WHEN, http=http, env=env())
    with pytest.raises(DraftingUnavailable):
        talker(MESSAGES)


def test_an_unreadable_reply_is_refused_rather_than_guessed_at():
    def http(url, body, headers):
        return b"not json at all", {}

    talker = BedrockTransport(config=BedrockConfig.from_env(env()),
                              signed_at=lambda: WHEN, http=http, env=env())
    with pytest.raises(DraftingUnavailable):
        talker(MESSAGES)


def test_missing_credentials_are_a_missing_assistant_not_a_crash():
    bare = {"VINZOR_BEDROCK": "1", "VINZOR_BEDROCK_REGION": "ap-south-1"}
    http, _calls = answer()

    def no_imds(*_args, **_kwargs):
        raise OSError("no metadata service here")

    class Dead:
        open = staticmethod(no_imds)

    talker = BedrockTransport(config=BedrockConfig.from_env(bare),
                              signed_at=lambda: WHEN, http=http, env=bare,
                              opener=Dead())
    with pytest.raises(ConfigurationMissing):
        talker(MESSAGES)


# -- assembly ----------------------------------------------------------------


def test_the_drafter_reports_the_model_and_region_it_used():
    http, _calls = answer()
    made = drafter(now=lambda: WHEN, env=env(), http=http)
    assert made.region == "ap-south-1"
    assert made.model == DEFAULT_MODEL


def test_prices_can_be_corrected_without_a_code_change():
    made = drafter(now=lambda: WHEN,
                   env=env(VINZOR_BEDROCK_COST_INPUT="0.004",
                           VINZOR_BEDROCK_COST_OUTPUT="0.016"),
                   http=answer()[0])
    assert made.cost_per_1k_input == 0.004
    assert made.cost_per_1k_output == 0.016


def test_the_clock_has_no_default_because_this_module_may_not_read_one():
    """If a default ever appears, the doctrine has been quietly dropped."""
    with pytest.raises(TypeError):
        drafter(env=env(), http=answer()[0])  # type: ignore[call-arg]


# -- against the deployed model ----------------------------------------------
#
# Kept out of the ordinary run behind `pytest -m live`, for the reason
# pyproject.toml gives: a suite that needs a credential and a working
# connection fails for reasons the code did not cause.


@pytest.mark.live
def test_the_configured_model_can_actually_follow_the_reader_prompt():
    """The one thing the offline tests cannot tell you.

    The first default was picked because it returned clean JSON to a
    one-line prompt, and it then failed three questions in four on the real
    reader prompt -- replying in prose, with no JSON object in it at all.
    A model that follows a simple instruction is not a model that follows a
    hard one, and nothing above the transport can rescue a reply that has no
    object in it to parse.

    So the check is the whole flow against the model actually configured,
    not a canned response: whatever is set in VINZOR_BEDROCK_MODEL has to
    answer the shape ``ask.py`` asks for.
    """
    from vinzor.__main__ import _load_dotenv

    _load_dotenv()
    if not configured():
        pytest.skip("Bedrock is not configured in this environment")

    import datetime as _dt

    from vinzor.ask import bedrock_conversation

    talk = bedrock_conversation(now=lambda: _dt.datetime.now(_dt.timezone.utc))
    spoken = talk([
        {"role": "system",
         "content": 'Reply with one JSON object and nothing else, shaped '
                    '{"answer": "<a sentence>", "used": []}.'},
        {"role": "user", "content": "Say that two files are open."},
    ])
    assert isinstance(spoken.reply, Mapping)
    assert "answer" in spoken.reply
    assert spoken.tokens_in > 0 and spoken.tokens_out > 0
    assert spoken.region in INDIA_REGIONS

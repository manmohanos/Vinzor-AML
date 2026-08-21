"""The Azure boundary — residency, secrecy, and failing cheaply.

No network. The HTTP call is injected, so what is under test is the contract:
that data cannot leave India, that the key cannot leave the process, and that
every other failure costs the officer nothing.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from vinzor.assist import DraftingUnavailable
from vinzor.azure import (
    API_VERSION,
    INDIA_REGIONS,
    KEY_VAR,
    AzureConfig,
    AzureTransport,
    ConfigurationMissing,
    DataResidencyError,
    check_served_region,
    configured,
    drafter,
)

KEY = "sk-SENTINEL-DO-NOT-LEAK"

ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://vinzor-india.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "vinzor-review",
    "AZURE_OPENAI_REGION": "centralindia",
    KEY_VAR: KEY,
}


def env(**over):
    merged = dict(ENV)
    merged.update(over)
    return {k: v for k, v in merged.items() if v is not None}


def answer(payload=None, *, headers=None, usage=(400, 120)):
    """A canned Azure chat-completion response, plus the calls it recorded."""
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
            "choices": [{"message": {"content": json.dumps(payload)}}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
        }
        return json.dumps(envelope).encode(), dict(headers or {})

    return http, calls


def transport_with(http, **over):
    return AzureTransport(config=AzureConfig.from_env(env(**over)), http=http,
                          env=env(**over))


MESSAGES = [{"role": "system", "content": "rules"},
            {"role": "user", "content": "a comparison"}]


# -- residency ---------------------------------------------------------------


def test_a_region_outside_india_will_not_start():
    with pytest.raises(DataResidencyError) as raised:
        AzureConfig(endpoint="https://x.openai.azure.com", deployment="d",
                    region="swedencentral")
    assert "not an Azure region in India" in str(raised.value)


def test_every_indian_region_is_accepted():
    for region in INDIA_REGIONS:
        AzureConfig(endpoint="https://x.openai.azure.com", deployment="d",
                    region=region)


def test_the_region_is_read_case_and_space_insensitively():
    config = AzureConfig.from_env(env(AZURE_OPENAI_REGION="Central India"))
    assert config.region == "centralindia"


def test_a_reply_served_outside_india_is_a_breach_not_a_hiccup():
    """A Global deployment routes wherever there is capacity. The declared
    region proves nothing; the served region does."""
    http, _ = answer(headers={"x-ms-region": "eastus"})
    with pytest.raises(DataResidencyError) as raised:
        transport_with(http)(MESSAGES)
    assert "outside India" in str(raised.value)


def test_a_breach_is_not_swallowed_as_an_unavailable_model():
    """Silent degradation is right for every other failure and wrong for this
    one: it would mean data left India and nobody was told."""
    http, _ = answer(headers={"x-ms-region": "eastus"})
    with pytest.raises(DataResidencyError):
        transport_with(http)(MESSAGES)
    assert not issubclass(DataResidencyError, DraftingUnavailable)


def test_a_reply_served_inside_india_is_accepted():
    http, _ = answer(headers={"X-MS-Region": "Central India"})
    reply, _, _ = transport_with(http)(MESSAGES)
    assert reply["recommendation"] == "CANNOT_TELL"


def test_an_absent_region_header_leaves_the_declared_region_standing():
    http, _ = answer(headers={})
    reply, _, _ = transport_with(http)(MESSAGES)
    assert reply["recommendation"] == "CANNOT_TELL"


def test_the_check_is_a_function_anyone_can_call():
    config = AzureConfig(endpoint="https://x.openai.azure.com", deployment="d",
                         region="centralindia")
    check_served_region({"x-ms-region": "southindia"}, config)
    with pytest.raises(DataResidencyError):
        check_served_region({"x-ms-region": "westeurope"}, config)


# -- the key -----------------------------------------------------------------


def test_the_key_is_never_held_on_the_configuration():
    config = AzureConfig.from_env(env())
    assert KEY not in json.dumps(config.__dict__)
    assert KEY not in repr(config)


def test_the_key_is_read_from_the_environment_at_call_time():
    """A rotated key takes effect on the next request, not the next restart."""
    live = env()
    http, calls = answer()
    transport = AzureTransport(config=AzureConfig.from_env(live), http=http,
                               env=live)
    transport(MESSAGES)
    live[KEY_VAR] = "sk-ROTATED"
    transport(MESSAGES)

    assert calls[0]["headers"]["api-key"] == KEY
    assert calls[1]["headers"]["api-key"] == "sk-ROTATED"


def test_the_key_appears_in_the_header_and_absolutely_nowhere_else():
    http, calls = answer()
    transport = transport_with(http)
    transport(MESSAGES)

    call = calls[0]
    assert call["headers"]["api-key"] == KEY
    assert KEY not in call["url"]
    assert KEY not in json.dumps(call["body"])
    assert KEY not in repr(transport)


def test_the_transport_repr_cannot_print_the_environment():
    """It could, once. ``repr(os.environ)`` prints every variable, and a
    dataclass repr is what a traceback or a logger reaches for first."""
    import os

    os.environ["VINZOR_REPR_SENTINEL"] = "sk-SENTINEL-DO-NOT-LEAK"
    try:
        transport = AzureTransport(config=AzureConfig.from_env(env()))
        assert "SENTINEL" not in repr(transport)
        assert "VINZOR_REPR_SENTINEL" not in repr(transport)
    finally:
        del os.environ["VINZOR_REPR_SENTINEL"]


def test_a_missing_key_is_a_missing_assistant_not_a_crash():
    with pytest.raises(ConfigurationMissing) as raised:
        AzureConfig.from_env(env(**{KEY_VAR: None}))
    assert KEY_VAR in str(raised.value)


def test_no_provider_error_message_can_carry_the_request():
    """Echoing a failed request back into a log is how credentials escape."""
    def http(url, body, headers):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    transport = AzureTransport(config=AzureConfig.from_env(env()), http=http,
                               env=env())
    with pytest.raises(DraftingUnavailable) as raised:
        transport(MESSAGES)
    message = str(raised.value)
    assert "401" in message
    assert KEY not in message and "api-key" not in message


# -- configuration -----------------------------------------------------------


def test_an_unconfigured_workspace_simply_has_no_assistant():
    assert configured({}) is False
    with pytest.raises(ConfigurationMissing):
        AzureConfig.from_env({})


def test_a_configured_workspace_says_so():
    assert configured(env()) is True


def test_every_missing_piece_is_named_at_once():
    with pytest.raises(ConfigurationMissing) as raised:
        AzureConfig.from_env({"AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com"})
    message = str(raised.value)
    for name in ("AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_REGION", KEY_VAR):
        assert name in message


def test_the_api_version_is_pinned():
    assert AzureConfig.from_env(env()).api_version == API_VERSION
    assert "api-version=" in AzureConfig.from_env(env()).url


def test_the_url_is_the_azure_chat_completions_route():
    assert AzureConfig.from_env(env()).url == (
        "https://vinzor-india.openai.azure.com/openai/deployments/"
        f"vinzor-review/chat/completions?api-version={API_VERSION}"
    )


def test_prices_can_be_corrected_without_a_code_change():
    config = AzureConfig.from_env(env(AZURE_OPENAI_COST_INPUT="0.005",
                                      AZURE_OPENAI_COST_OUTPUT="0.02"))
    assert (config.cost_per_1k_input, config.cost_per_1k_output) == (0.005, 0.02)


def test_an_unreadable_price_falls_back_rather_than_failing():
    config = AzureConfig.from_env(env(AZURE_OPENAI_COST_INPUT="free"))
    assert config.cost_per_1k_input > 0


# -- the request -------------------------------------------------------------


def test_the_request_asks_for_json_and_no_creativity():
    http, calls = answer()
    transport_with(http)(MESSAGES)
    body = calls[0]["body"]

    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == MESSAGES
    # ``max_completion_tokens``, not ``max_tokens``. A reasoning model
    # spends the allowance thinking before it writes: measured on this
    # deployment a two-sentence summary used 633 tokens of which 480 were
    # reasoning, so at the old ceiling of 700 the thinking occasionally
    # consumed the lot and the content came back empty. That surfaced as
    # "the service replied with something unreadable" -- a wire fault for
    # what was really a budget older than the model behind it.
    assert body["max_completion_tokens"] > 1000
    assert "max_tokens" not in body


def test_token_counts_come_back_for_the_budget():
    http, _ = answer(usage=(1234, 567))
    _, tokens_in, tokens_out = transport_with(http)(MESSAGES)
    assert (tokens_in, tokens_out) == (1234, 567)


# -- failing cheaply ---------------------------------------------------------


def test_an_unreachable_service_is_an_unavailable_assistant():
    def http(url, body, headers):
        raise urllib.error.URLError("no route to host")

    with pytest.raises(DraftingUnavailable):
        transport_with(http)(MESSAGES)


def test_a_reply_that_is_not_json_is_an_unavailable_assistant():
    def http(url, body, headers):
        return b"<html>gateway timeout</html>", {}

    with pytest.raises(DraftingUnavailable):
        transport_with(http)(MESSAGES)


def test_a_reply_whose_content_is_not_json_is_refused():
    def http(url, body, headers):
        envelope = {"choices": [{"message": {"content": "I think they match!"}}],
                    "usage": {}}
        return json.dumps(envelope).encode(), {}

    with pytest.raises(DraftingUnavailable):
        transport_with(http)(MESSAGES)


def test_an_empty_choices_list_is_refused():
    def http(url, body, headers):
        return json.dumps({"choices": [], "usage": {}}).encode(), {}

    with pytest.raises(DraftingUnavailable):
        transport_with(http)(MESSAGES)


# -- assembled ---------------------------------------------------------------


def test_the_assembled_drafter_carries_the_deployment_and_the_region():
    http, _ = answer()
    made = drafter(env=env(), http=http)
    assert made.model == "vinzor-review"
    assert made.region == "centralindia"
    assert made.cost_per_1k_input > 0

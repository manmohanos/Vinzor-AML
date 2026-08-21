"""The Azure boundary, attacked at the three places its docstring promises.

All three promises were written down and none of the three held.

* **"Data residency is enforced here, in two places."** One ``Location``
  header defeated both at once. ``urlopen`` follows a redirect by default and
  carries every request header to the new address, ``api-key`` included and
  across origins. So the call went where the header pointed, and the second
  guard -- which reads ``x-ms-region`` off the reply -- read a header the
  redirect target had written for itself. Measured before this was closed: a
  throwaway server sent a 302 for the chat-completions POST and received
  ``api-key: sk-SENTINEL-REDIRECT``, and the region check passed.

* **"A spend ceiling across the whole workspace, summed from the log."** It
  summed one event type. Four questions typed into the ask box made eleven
  model calls and 22,848 input tokens; ``spent_so_far`` afterwards read 0.00
  of 50.00, because the transport threw the ``usage`` block away and the
  ASSISTANT_ASKED payload carried no model, no tokens and no cost.

* **"Identical inputs produce identical logs -- no clock in the core."**
  ``ask.py`` read ``date.today()`` on a write path. Two engines built from
  identical events, asked the identical question, given the identical answer,
  came out with different chain heads.
"""

from __future__ import annotations

import ast
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from vinzor import azure
from vinzor.ask import PROMPT_VERSION, AskingUnavailable, Spoken, ask
from vinzor.assist import spent_so_far
from vinzor.engine import Vinzor
from vinzor.eventlog import EventLog
from vinzor.model import EventType, Role

WHEN = "2026-08-20"


# -- residency ---------------------------------------------------------------


class _Redirects(BaseHTTPRequestHandler):
    """The shape a residency breach takes: a proxy, or a wrong endpoint."""

    keys_seen: list = []

    def log_message(self, *rest):
        pass

    def _drain(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

    def do_POST(self):
        self._drain()
        type(self).keys_seen.append(("POST", self.headers.get("api-key")))
        self.send_response(302)
        self.send_header("Location", "/elsewhere")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._drain()
        type(self).keys_seen.append(("GET", self.headers.get("api-key")))
        body = json.dumps({
            "choices": [{"message": {"content": '{"ok": "yes"}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        # The header the second guard reads -- written by whoever the redirect
        # points at, which is the whole of the problem.
        self.send_header("x-ms-region", "centralindia")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def redirecting_endpoint():
    _Redirects.keys_seen = []
    server = HTTPServer(("127.0.0.1", 0), _Redirects)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1], _Redirects
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _env(endpoint):
    return {"AZURE_OPENAI_ENDPOINT": endpoint,
            "AZURE_OPENAI_KEY": "sk-SENTINEL-REDIRECT",
            "AZURE_OPENAI_DEPLOYMENT": "d",
            "AZURE_OPENAI_REGION": "centralindia"}


def test_a_redirect_is_refused_and_the_key_does_not_travel(redirecting_endpoint):
    """The defect. Before this the call succeeded, the reply came from the
    second address, and the sentinel key was in its request headers."""
    endpoint, handler = redirecting_endpoint
    env = _env(endpoint)
    transport = azure.AzureTransport(config=azure.AzureConfig.from_env(env),
                                     env=env)

    with pytest.raises(azure.DataResidencyError):
        transport([{"role": "user", "content": "hello"}])

    assert [verb for verb, _key in handler.keys_seen] == ["POST"], (
        "the redirect was followed")


def test_the_ask_boundary_refuses_the_same_redirect(redirecting_endpoint):
    """Both halves of the assistant share ``_http``, and a residency breach on
    the half an officer types into is not a quieter kind of breach."""
    from vinzor.ask import azure_conversation

    endpoint, handler = redirecting_endpoint
    talk = azure_conversation(env=_env(endpoint))

    with pytest.raises(azure.DataResidencyError):
        talk([{"role": "user", "content": "hello"}])
    assert [verb for verb, _key in handler.keys_seen] == ["POST"]


def test_a_refused_redirect_is_not_a_quiet_unavailable():
    """``DraftingUnavailable`` means "no draft today, carry on". A redirect
    means somebody put something in front of the model, and the run stops."""
    assert not issubclass(azure.DataResidencyError, azure.DraftingUnavailable)


def test_the_opener_carries_no_credential():
    """A key on a long-lived opener is a key in every traceback that prints
    one. It stays a per-request header."""
    assert "sk-" not in repr(azure._OPENER)
    for handler in azure._OPENER.handlers:
        assert azure.KEY_VAR not in repr(handler)


# -- the bill ----------------------------------------------------------------


def a_workspace():
    engine = Vinzor(EventLog())
    engine.enroll(name="Meera Nair", role=Role.AML_OFFICER, enrolled_at=WHEN)
    return engine


def priced(tokens_in=1000, tokens_out=500, cost=0.25):
    """A transport that answers once and says what it cost."""

    def talk(_messages):
        return Spoken(reply={"answer": "Two files are open.", "used": []},
                      tokens_in=tokens_in, tokens_out=tokens_out,
                      cost_usd=cost, model="model-router",
                      region="southindia")

    return talk


def test_what_a_question_cost_reaches_the_permanent_record():
    engine = a_workspace()
    ask(engine, "What is open?", transport=priced(), person="Meera Nair",
        asked_at=WHEN)

    asked = [e for e in engine.log if e.event_type is EventType.ASSISTANT_ASKED]
    assert len(asked) == 1
    payload = asked[0].payload
    assert payload["input_tokens"] == 1000
    assert payload["output_tokens"] == 500
    assert payload["cost_usd"] == 0.25
    assert payload["model"] == "model-router"
    assert payload["region"] == "southindia"
    assert payload["prompt_version"] == PROMPT_VERSION
    assert payload["model_calls"] == 1


def test_the_workspace_total_counts_questions_as_well_as_drafts():
    """It summed drafting alone, so the half of the assistant a person drives
    all day was invisible to the ceiling said to cover the workspace."""
    engine = a_workspace()
    assert spent_so_far(engine) == 0.0
    ask(engine, "What is open?", transport=priced(cost=0.25),
        person="Meera Nair", asked_at=WHEN)
    assert spent_so_far(engine) == 0.25


def test_a_workspace_over_its_ceiling_stops_asking_before_it_spends():
    engine = a_workspace()
    ask(engine, "What is open?", transport=priced(cost=4.0),
        person="Meera Nair", asked_at=WHEN)

    def must_not_be_called(_messages):
        raise AssertionError("a model was called after the ceiling was reached")

    with pytest.raises(AskingUnavailable) as refusal:
        ask(engine, "And now?", transport=must_not_be_called,
            person="Meera Nair", asked_at=WHEN, budget_usd=1.0)
    assert "allowance" in str(refusal.value)
    assert "Every screen still works" in str(refusal.value)


def test_a_scripted_answer_claims_no_model_it_never_talked_to():
    """The tests run offline. A canned reply must not record a model name, a
    token count or a cost -- an invented zero is still an invented fact."""
    engine = a_workspace()
    ask(engine, "What is open?",
        transport=lambda _m: {"answer": "Two files are open.", "used": []},
        person="Meera Nair", asked_at=WHEN)

    payload = [e for e in engine.log
               if e.event_type is EventType.ASSISTANT_ASKED][0].payload
    assert "model" not in payload
    assert "cost_usd" not in payload


def test_every_turn_of_one_question_is_counted_not_just_the_last():
    """A question is up to six model calls, each resending the whole
    conversation. Counting the last alone understates the bill most for the
    questions that cost the most."""
    engine = a_workspace()
    turns = iter([
        Spoken(reply={"tool": "brief", "arguments": {}, "why": "looking"},
               tokens_in=1000, tokens_out=50, cost_usd=0.10,
               model="model-router", region="southindia"),
        Spoken(reply={"answer": "Two files are open.", "used": ["brief"]},
               tokens_in=3000, tokens_out=100, cost_usd=0.30,
               model="model-router", region="southindia"),
    ])
    ask(engine, "What is open?", transport=lambda _m: next(turns),
        person="Meera Nair", asked_at=WHEN)

    payload = [e for e in engine.log
               if e.event_type is EventType.ASSISTANT_ASKED][0].payload
    assert payload["model_calls"] == 2
    assert payload["input_tokens"] == 4000
    assert payload["cost_usd"] == 0.40


# -- the clock ---------------------------------------------------------------


def test_identical_inputs_produce_an_identical_log_through_the_ask_box():
    """The one guarantee the Ledger rests on. ``ask.py`` used to fall through
    to ``date.today()``, so the same question answered the same way on two
    machines produced two different chain heads."""
    heads = []
    for _ in range(2):
        engine = a_workspace()
        ask(engine, "What is open?",
            transport=lambda _m: {"answer": "Two files are open.", "used": []},
            person="Meera Nair", asked_at=WHEN)
        heads.append(list(engine.log)[-1].event_hash)
    assert heads[0] == heads[1]


def test_asking_without_a_date_is_refused_rather_than_guessed():
    engine = a_workspace()
    with pytest.raises(ValueError) as refusal:
        ask(engine, "What is open?",
            transport=lambda _m: {"answer": "Two.", "used": []},
            person="Meera Nair")
    assert "does not read" in str(refusal.value)


def test_nothing_in_the_core_reads_a_clock():
    """The doctrine is absolute and was unenforced, which is how one slipped
    in. ``server.py`` and ``__main__.py`` are boundaries and supply dates to
    everything below them; ``briefing.py``'s two are read-side presentation
    defaults that touch no event."""
    allowed = {"server.py", "__main__.py", "briefing.py"}
    clocks = {"date.today", "datetime.now", "datetime.utcnow", "time.time",
              "datetime.today", "time.monotonic"}
    offences = []
    for path in sorted(pathlib.Path("vinzor").glob("*.py")):
        if path.name in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # Parsed, not grepped: half these modules explain in prose why
            # they may not call a clock, and a text sweep reads the warning
            # as the offence.
            if isinstance(node, ast.Call) and ast.unparse(node.func) in clocks:
                offences.append("%s:%d %s" % (path.name, node.lineno,
                                              ast.unparse(node.func)))
    assert offences == [], "a clock inside the core: " + "; ".join(offences)


# -- the words the assistant uses --------------------------------------------
#
# Rule 5 of the prompt already forbade identifiers and field names. Three of
# six live answers broke it:
#
#     Q  What is the exact identifier of the first file in my queue?
#     A  The first file in your queue is case_2027b6adf581.
#     Q  Tell me about the party with the largest unmatched payment.
#     A  ...I tried open_files, but it did not provide the required amounts.
#
# Nothing checked. The jargon sweep is a static test over sentences written
# into briefing.py; these are written at runtime and then onto a permanent
# event. The figures guard did not help either: every run of digits in
# case_2027b6adf581 is under a hundred. The tool-name half was required by
# the prompt itself -- rule 1 said "say which tool you tried" and the tools
# had only snake_case internal names to give.


def _a_party_and_a_file():
    from vinzor.model import EntityKind

    engine = a_workspace()
    engine.ingest(event_type=EventType.ENTITY_REGISTERED, subject="per_0002",
                  occurred_at=WHEN, actor="system",
                  payload={"kind": EntityKind.PERSON.value,
                           "name": "Rohan Desai", "attributes": {}})
    engine.ingest(event_type=EventType.SCREENING_COMPLETED, subject="per_0002",
                  occurred_at=WHEN, actor="system",
                  payload={"matched": True, "list_type": "SANCTIONS",
                           "list_types": ["SANCTIONS"], "rule": "match",
                           "alert_id": "os:x", "basis": {}})
    return engine, engine.queue()[0].case_id


def test_a_file_identifier_is_said_as_the_file_it_names():
    from vinzor.ask import plainer

    engine, case_id = _a_party_and_a_file()
    said, changed = plainer(engine, f"The first file in your queue is {case_id}.")

    assert said == "The first file in your queue is the name check on Rohan Desai."
    assert changed == [case_id]


def test_a_party_identifier_is_said_as_the_party_it_names():
    from vinzor.ask import plainer

    engine, _case_id = _a_party_and_a_file()
    said, changed = plainer(engine, "per_0002 has an unmatched payment.")
    assert said == "Rohan Desai has an unmatched payment."
    assert changed == ["per_0002"]


def test_a_tool_is_named_the_way_a_person_would_name_it():
    from vinzor.ask import plainer

    engine, _case_id = _a_party_and_a_file()
    said, changed = plainer(
        engine, "I tried open_files, but it did not provide the amounts.")
    assert said.startswith("I tried the open files,")
    assert changed == ["open_files"]


def test_an_ordinary_english_word_is_not_rewritten():
    """Four of the nine tools are called ``party``, ``file``, ``rule`` and
    ``screening``. A single English word is not jargon because a function
    happens to share its name, and rewriting those would turn every honest
    sentence into nonsense."""
    from vinzor.ask import plainer

    engine, _case_id = _a_party_and_a_file()
    plain = "Two files are open. One is a name check on a party under rule 5.9."
    said, changed = plainer(engine, plain)
    assert said == plain
    assert changed == []


def test_what_was_said_plainly_is_on_the_record():
    """A guard that fires silently is a guard nobody can audit."""
    engine, case_id = _a_party_and_a_file()
    ask(engine, "Which file is first?",
        transport=lambda _m: {"answer": f"It is {case_id}.", "used": []},
        person="Meera Nair", asked_at=WHEN)

    payload = [e for e in engine.log
               if e.event_type is EventType.ASSISTANT_ASKED][-1].payload
    assert payload["said_plainly"] == [case_id]
    assert case_id not in payload["answer"]


def test_every_tool_has_a_name_a_person_would_use():
    """Rule 1 makes the model name the tool it tried. Without this there is
    nothing to name but the function."""
    from vinzor.ask import TOOLS

    missing = [name for name, tool in TOOLS.items() if not tool.shown]
    assert missing == []
    assert all("_" not in tool.shown for tool in TOOLS.values())


def test_the_prompt_tells_the_model_which_name_to_use():
    from vinzor.ask import INSTRUCTIONS, _catalogue

    assert "never by its short name" in INSTRUCTIONS
    assert 'call it "the open files" when you mention it' in _catalogue()

"""The command line's own small concerns: reading ``.env``, and bad flags.

``_load_dotenv`` exists for one reason -- a founder with no terminal habits
should be able to paste a key into a file once, rather than export it in every
new shell. It is stdlib, ten lines, and deliberately not a general parser.
"""

from __future__ import annotations

import os

import pytest

from vinzor.__main__ import Misused, _flag, _load_dotenv, _value


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with none of the variables these tests use set."""
    for key in ("VINZOR_TEST_A", "VINZOR_TEST_B", "AZURE_OPENAI_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_a_pasted_key_reaches_the_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("VINZOR_TEST_A=sk-example-1234\n", encoding="utf-8")

    _load_dotenv()

    assert os.environ["VINZOR_TEST_A"] == "sk-example-1234"


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _load_dotenv()  # no .env in tmp_path -- must not raise


def test_comments_and_blank_lines_are_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "# a comment\n\nVINZOR_TEST_A=one\n   # indented comment\nVINZOR_TEST_B=two\n",
        encoding="utf-8",
    )

    _load_dotenv()

    assert os.environ["VINZOR_TEST_A"] == "one"
    assert os.environ["VINZOR_TEST_B"] == "two"


def test_surrounding_quotes_are_stripped():
    """A value pasted from somewhere that quoted it should still work."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".env"
        path.write_text('VINZOR_TEST_A="quoted value"\n', encoding="utf-8")
        _load_dotenv(path)

    assert os.environ["VINZOR_TEST_A"] == "quoted value"


def test_a_real_environment_variable_is_never_overwritten_by_the_file(
    tmp_path, monkeypatch
):
    """The file is a convenience default, not an authority over a session
    someone configured on purpose -- a real export must win."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VINZOR_TEST_A", "from-the-real-shell")
    (tmp_path / ".env").write_text("VINZOR_TEST_A=from-the-file\n", encoding="utf-8")

    _load_dotenv()

    assert os.environ["VINZOR_TEST_A"] == "from-the-real-shell"


def test_a_line_with_no_equals_sign_is_ignored_not_fatal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("this is not a valid line\nVINZOR_TEST_A=fine\n",
                                   encoding="utf-8")

    _load_dotenv()  # must not raise

    assert os.environ["VINZOR_TEST_A"] == "fine"


def test_a_value_with_an_equals_sign_in_it_keeps_the_rest():
    """A key or endpoint can legitimately contain '=' (base64, a query
    string) -- only the FIRST '=' splits key from value."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".env"
        path.write_text("VINZOR_TEST_A=abc=def=ghi\n", encoding="utf-8")
        _load_dotenv(path)

    assert os.environ["VINZOR_TEST_A"] == "abc=def=ghi"


def test_the_loader_never_prints_a_value(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AZURE_OPENAI_KEY=sk-SENTINEL-DO-NOT-LEAK\n",
                                   encoding="utf-8")

    _load_dotenv()

    assert "SENTINEL" not in capsys.readouterr().out


# -- flags, already covered indirectly elsewhere, pinned here directly -------


def test_a_trailing_flag_with_no_value_explains_itself_instead_of_crashing():
    with pytest.raises(Misused) as raised:
        _value(["--workspace"], "--workspace")
    assert "needs a value" in str(raised.value)


def test_a_flag_followed_by_another_flag_is_treated_as_missing():
    with pytest.raises(Misused):
        _value(["--port", "--workspace", "fund.db"], "--port")


def test_a_bad_number_explains_itself_instead_of_a_raw_valueerror():
    with pytest.raises(Misused) as raised:
        _flag(["--port", "abc"], "--port", 8000)
    assert "whole number" in str(raised.value)

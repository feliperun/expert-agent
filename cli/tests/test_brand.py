"""Smoke tests for the ASCII brand + the ``expert brand`` / ``--version`` paths."""

from expert.main import app
from typer.testing import CliRunner


def test_brand_command_prints_wordmark_and_tagline() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["brand"])
    assert result.exit_code == 0, result.output
    # Wordmark: one row of the ANSI-shadow figlet should always be present.
    assert "███████╗" in result.output
    # Tagline + knowledge glyph box.
    assert "ground a model on your docs" in result.output
    assert "╭───╮" in result.output
    # Version footer.
    assert "MIT" in result.output
    assert "github.com/feliperbroering/expert-agent" in result.output


def test_version_flag_renders_brand() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert "expert" in result.output
    assert "███████╗" in result.output


def test_brand_command_is_hidden_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    # `brand` is a hidden easter-egg command; it must not pollute --help output.
    assert "brand" not in result.output.split("Commands")[-1]

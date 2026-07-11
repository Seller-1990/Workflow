# -*- coding: utf-8 -*-
"""script_arg_utils / introspection unit tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from script_arg_introspection import inspect_script_source
from script_arg_utils import (
    CliArgsParseError,
    format_cli_args_for_log,
    merge_step_args,
    parse_cli_args_text,
    redact_cli_args,
    resolve_effective_args,
)


def test_parse_year():
    assert parse_cli_args_text("--year 2025") == ["--year", "2025"]


def test_parse_quoted():
    assert parse_cli_args_text('--name "North Region"') == ["--name", "North Region"]


def test_parse_json_array():
    assert parse_cli_args_text('["--year", "2025"]') == ["--year", "2025"]


def test_parse_empty():
    assert parse_cli_args_text("") == []
    assert parse_cli_args_text("   ") == []
    assert parse_cli_args_text(None) == []


def test_parse_unclosed_quote():
    with pytest.raises(CliArgsParseError):
        parse_cli_args_text('--name "North')


def test_parse_null_char():
    with pytest.raises(CliArgsParseError):
        parse_cli_args_text("--x a\x00b")


def test_merge_order():
    assert merge_step_args(["--mode", "prod"], ["--year", "2025"]) == [
        "--mode", "prod", "--year", "2025"
    ]


def test_merge_empty_temp_keeps_fixed():
    assert merge_step_args(["--mode", "prod"], []) == ["--mode", "prod"]


def test_resolve_by_uid():
    fixed = ["--mode", "prod"]
    overrides = {"step-a": ["--year", "2025"]}
    assert resolve_effective_args("step-a", fixed, overrides) == [
        "--mode", "prod", "--year", "2025"
    ]
    assert resolve_effective_args("step-b", fixed, overrides) == ["--mode", "prod"]


def test_redact_token():
    assert redact_cli_args(["--token", "abc", "--year", "2025"]) == [
        "--token", "****", "--year", "2025"
    ]


def test_redact_access_token_value():
    assert redact_cli_args(["url=access_token=xyz"]) == ["****"]


def test_format_for_log():
    text = format_cli_args_for_log(["--password", "secret", "--x", "1"])
    assert "****" in text
    assert "secret" not in text


def test_inspect_import_argparse():
    src = (
        "import argparse\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--year', type=int, help='year only')\n"
        "parser.add_argument('--mode', choices=['full', 'incremental'], default='full')\n"
        "parser.add_argument('--verbose', action='store_true')\n"
    )
    spec = inspect_script_source(src)
    assert spec.detected is True
    dests = {a.dest for a in spec.arguments}
    assert "year" in dests
    assert "mode" in dests
    assert "verbose" in dests
    mode = next(a for a in spec.arguments if a.dest == "mode")
    assert mode.choices == ("full", "incremental")
    verbose = next(a for a in spec.arguments if a.dest == "verbose")
    assert verbose.action == "store_true"


def test_inspect_from_import():
    src = (
        "from argparse import ArgumentParser\n"
        "parser = ArgumentParser()\n"
        "parser.add_argument('--year', type=int)\n"
    )
    spec = inspect_script_source(src)
    assert spec.detected is True
    assert any(a.dest == "year" for a in spec.arguments)


def test_inspect_fallback_no_parser():
    src = "print('hi')\n"
    spec = inspect_script_source(src)
    assert spec.detected is False



def test_parse_windows_path_preserved_on_win32(monkeypatch):
    monkeypatch.setattr("script_arg_utils.sys.platform", "win32")
    assert parse_cli_args_text(r"--input C:\Data\2025") == ["--input", r"C:\Data\2025"]


def test_parse_windows_quoted_path(monkeypatch):
    monkeypatch.setattr("script_arg_utils.sys.platform", "win32")
    assert parse_cli_args_text(r'--input "C:\My Data\file.txt"') == [
        "--input",
        r"C:\My Data\file.txt",
    ]


def test_redact_token_equals_form():
    assert redact_cli_args(["--token=abc", "--year", "2025"]) == [
        "--token=****",
        "--year",
        "2025",
    ]


def test_redact_password_equals_form():
    assert redact_cli_args(["--password=secret"]) == ["--password=****"]

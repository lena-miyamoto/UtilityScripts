"""Smoke tests for the .claude/scripts CLI stack.

Give the ``uv run test`` entry point (and the pre-commit pytest hook)
something to collect, and assert the modules load and wire together.
"""

import entrypoints
import utils


def test_lint_md_entry_point():
    assert callable(entrypoints.lint_md)


def test_lint_entry_point():
    assert callable(entrypoints.lint)


def test_format_entry_point():
    assert callable(entrypoints.format)


def test_test_entry_point():
    assert callable(entrypoints.test)


def test_run_cli_helper():
    assert callable(utils.run_cli)


def test_atomic_write_helper():
    assert callable(utils.atomic_write)


def test_lint_source_md_helper():
    assert callable(utils.lint_source_md)

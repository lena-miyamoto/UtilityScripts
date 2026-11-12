"""Smoke tests for the csv-tool console entry point."""

import shutil
import subprocess

CSV_TOOL = shutil.which("csv-tool")


def _run(*args):
    assert CSV_TOOL is not None, "csv-tool console script not found on PATH"
    return subprocess.run([CSV_TOOL, *args], capture_output=True, text=True)


def test_check_missing_file_exits_1(tmp_path):
    result = _run("check", str(tmp_path / "missing.csv"))
    assert result.returncode == 1, result.stderr


def test_help_exits_0():
    result = _run("--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout

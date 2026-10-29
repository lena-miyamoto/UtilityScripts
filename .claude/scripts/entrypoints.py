import subprocess
import sys

import utils


def lint_md():
    """Run rumdl on repo markdown files.

    Delegates to utils.lint_source_md when --check-source-md or --fix-source-md
    is passed.  Otherwise scans README.md, CLAUDE.md, and .claude by
    default.  Pass --fix to auto-fix violations.  rumdl reads
    its rule set from .rumdl.toml.
    """
    args = list(sys.argv[1:])
    source_md_result = utils.lint_source_md(args)
    if source_md_result != -1:
        return source_md_result

    fix_mode = False
    if "--fix" in args:
        fix_mode = True
        args = [a for a in args if a != "--fix"]

    if not args:
        args = [
            "README.md",
            "CLAUDE.md",
            ".claude",
        ]

    if fix_mode:
        subprocess.run(["rumdl", "fmt", *args], check=False)

    # Always check afterward so remaining violations are visible even when
    # --fix rewrote files: `check` reports them and sets the exit code.
    return subprocess.run(["rumdl", "check", *args], check=False).returncode


def test():
    try:
        from pytest import main as pytest_main
    except ModuleNotFoundError:
        print(
            "pytest is not installed; run 'uv sync' to install the dev dependencies",
            file=sys.stderr,
        )
        return 1

    args = sys.argv[1:] or [".claude/scripts", "-v"]
    return pytest_main(args)


def lint():
    """Run ruff check and ruff format --check on repo Python code.

    Targets .claude/scripts by default.  Pass --fix to apply
    safe autofixes before checking, or pass explicit paths to override
    the defaults.
    """
    args = list(sys.argv[1:])
    fix_mode = "--fix" in args
    if fix_mode:
        args = [a for a in args if a != "--fix"]

    targets = [a for a in args if not a.startswith("-")] or [".claude/scripts"]

    if fix_mode:
        subprocess.run(["ruff", "check", "--fix", *targets], check=False)

    status = 0
    status |= subprocess.run(["ruff", "check", *targets], check=False).returncode
    status |= subprocess.run(["ruff", "format", "--check", *targets], check=False).returncode
    return status


def format():
    """Format repo Python code with ruff format.

    Targets .claude/scripts by default; pass paths to override.
    """
    args = sys.argv[1:]
    flags = [a for a in args if a.startswith("-")]
    targets = [a for a in args if not a.startswith("-")] or [".claude/scripts"]
    return subprocess.run(["ruff", "format", *flags, *targets], check=False).returncode

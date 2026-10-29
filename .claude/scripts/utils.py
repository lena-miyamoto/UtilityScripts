"""Shared utilities for the .claude/scripts CLI stack.

CLI entry-point wrapper, atomic file writes, and source-MD line-length
checking/normalisation.
"""

import sys as _sys
import textwrap as _textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


def atomic_write(path, content):
    """Write *content* to *path* atomically via a temporary file + rename.

    On POSIX ``Path.replace`` is atomic when the source and destination are
    on the same filesystem.  This prevents corruption if the process crashes
    mid-write.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# run_cli — canonical CLI entry-point wrapper
# ---------------------------------------------------------------------------


def run_cli(main_func):
    """Run *main_func* as a CLI entry point with KeyboardInterrupt handling.

    Usage::

        if __name__ == "__main__":
            utils.run_cli(main)
    """
    try:
        raise SystemExit(main_func())
    except KeyboardInterrupt:
        print("cancelled", file=_sys.stderr)
        raise SystemExit(130) from None


# =============================================================================
# Source-MD line-length checking and normalisation
# =============================================================================
#
# These functions are used by lint-md --check-source-md and --fix-source-md
# to wrap long lines in archived Marxists source files.  They were moved here
# from entrypoints.py to keep the entrypoint module thin.

SOURCE_LINE_LENGTH = 120


def _archive_md_files(paths):
    """Collect markdown files from a list of paths (files or directories)."""
    markdown_files = []
    for path_arg in paths:
        path = Path(path_arg)
        if path.is_dir():
            markdown_files.extend(sorted(path.rglob("*.md")))
        elif path.is_file() and path.suffix == ".md":
            markdown_files.append(path)
        else:
            print(f"not a markdown file or directory: {path}", file=_sys.stderr)
    return markdown_files


def _frontmatter_line_numbers(lines):
    """Return a set of 0-based line indices that belong to YAML frontmatter."""
    if not lines or lines[0].rstrip("\n") != "---":
        return set()
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\n") == "---":
            return set(range(index + 1))
    return set()


def _wrap_source_line(line, width=SOURCE_LINE_LENGTH):
    """Wrap a single source line to *width*, preserving indentation."""
    newline = "\n" if line.endswith("\n") else ""
    text = line[:-1] if newline else line
    if len(text) <= width or not text.strip():
        return [line]
    indent = text[: len(text) - len(text.lstrip())]
    wrapped = _textwrap.wrap(
        text,
        width=width,
        expand_tabs=False,
        replace_whitespace=False,
        drop_whitespace=True,
        break_long_words=False,
        break_on_hyphens=False,
        subsequent_indent=indent,
    )
    if not wrapped:
        return [line]
    return [f"{wrapped_line}\n" for wrapped_line in wrapped[:-1]] + [f"{wrapped[-1]}{newline}"]


def _source_line_violations(path, width=SOURCE_LINE_LENGTH):
    """Return list of ``(line_number, length)`` tuples for lines exceeding *width*."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    frontmatter_lines = _frontmatter_line_numbers(lines)
    violations = []
    for line_number, line in enumerate(lines, start=1):
        if line_number - 1 in frontmatter_lines:
            continue
        length = len(line.rstrip("\n"))
        if length > width:
            violations.append((line_number, length))
    return violations


def _normalize_source_md(path, width=SOURCE_LINE_LENGTH):
    """Normalize source markdown line lengths in-place.  Returns True if changed."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    frontmatter_lines = _frontmatter_line_numbers(lines)
    normalized_lines = []
    for line_number, line in enumerate(lines):
        if line_number in frontmatter_lines:
            normalized_lines.append(line)
        else:
            normalized_lines.extend(_wrap_source_line(line, width))
    normalized_text = "".join(normalized_lines)
    original_text = "".join(lines)
    if normalized_text == original_text:
        return False
    atomic_write(path, normalized_text)
    return True


def lint_source_md(args):
    """Handle --check-source-md and --fix-source-md flags.

    Returns the CLI exit code, or -1 when *args* does not start with a
    recognised source-MD flag (caller should fall back to rumdl).
    """
    if not args or args[0] not in {"--check-source-md", "--fix-source-md"}:
        return -1

    should_fix = args[0] == "--fix-source-md"
    source_args = args[1:]
    if not source_args:
        print(
            f"usage: lint-md {args[0]} <archive-md-or-directory> [...]",
            file=_sys.stderr,
        )
        return 2

    markdown_files = _archive_md_files(source_args)
    if not markdown_files:
        return 2

    if should_fix:
        changed = [_normalize_source_md(path) for path in markdown_files]
        changed_count = sum(1 for was_changed in changed if was_changed)
        print(f"normalized {changed_count} of {len(markdown_files)} archive markdown file(s)")

    violation_count = 0
    for path in markdown_files:
        for line_number, length in _source_line_violations(path):
            violation_count += 1
            print(f"{path}:{line_number}: line length {length} > {SOURCE_LINE_LENGTH}")

    return 1 if violation_count else 0

"""CSV/TSV inspection and transform utility for the repo.

Run as ``python3 csv-util.py <command> ...``. The first row of every input
file is treated as the header row.

Handles the CSV features this repo actually relies on: CRLF line endings,
UTF-8, quoted fields with embedded commas/newlines/escaped quotes, and
``QUOTE_MINIMAL`` output. Output is written without a trailing newline,
matching the round-trip behaviour of the glossary workflow.

Subcommands:

- ``stats``       — row/column counts, per-column empty counts, placeholder rows.
- ``check``       — validate field-count consistency and required columns.
- ``cut``         — select a subset of columns.
- ``head``        — preview the first N data rows.
- ``drop-empty``  — remove blank/placeholder rows.
- ``dedupe``      — remove duplicate rows (full-row or by key column).
- ``fill``        — fill columns from a ``{key: {column: value}}`` JSON map.
"""

import argparse
import csv
import io
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

NAMED_DELIMITERS = {"comma": ",", "tab": "\t", "semicolon": ";", "pipe": "|"}


def atomic_write(path, content):
    """Write *content* to *path* atomically via a temporary file + rename.

    On POSIX ``Path.replace`` is atomic when the source and destination are
    on the same filesystem.  This prevents corruption if the process crashes
    mid-write.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    mode = path.stat().st_mode if path.exists() else None
    tmp.write_text(content, encoding="utf-8")
    if mode is not None:
        tmp.chmod(mode)
    tmp.replace(path)


def run_cli(main_func):
    """Run *main_func* as a CLI entry point with KeyboardInterrupt handling."""
    try:
        raise SystemExit(main_func())
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        raise SystemExit(130) from None


# ---------------------------------------------------------------------------
# Parsing / serialisation
# ---------------------------------------------------------------------------


def parse_delimiter(value):
    """Resolve a delimiter name or literal character to a one-char string."""
    named = NAMED_DELIMITERS.get(value.lower())
    if named is not None:
        return named
    if len(value) != 1:
        raise ValueError(
            f"delimiter must be a name ({', '.join(NAMED_DELIMITERS)}) "
            f"or a single character, got {value!r}"
        )
    return value


def detect_line_ending(path):
    """Return ``\\r\\n`` if any CRLF appears in the first 4096 bytes, else ``\\n``."""
    with open(path, "rb") as handle:
        sample = handle.read(4096)
    return "\r\n" if b"\r\n" in sample else "\n"


def resolve_newline(path, choice):
    """Map a ``--newline`` choice to a concrete line-ending string."""
    if choice == "auto":
        return detect_line_ending(path)
    return "\r\n" if choice == "crlf" else "\n"


def read_rows(path, delimiter):
    """Read *path* as CSV, returning a list of row lists (including header)."""
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle, delimiter=delimiter))


def render_csv(rows, delimiter, newline):
    """Render *rows* to CSV text using QUOTE_MINIMAL, with no trailing newline."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator=newline)
    writer.writerows(rows)
    text = buf.getvalue()
    if text.endswith(newline):
        text = text[: -len(newline)]
    return text


def write_output(path, rows, delimiter, newline):
    """Write *rows* as CSV to *path* (or stdout when *path* is None)."""
    text = render_csv(rows, delimiter, newline)
    if path is None:
        sys.stdout.write(text)
    else:
        atomic_write(path, text)


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------


def cell(row, index):
    """Return ``row[index]`` or ``""`` when *index* is past the row's end."""
    return row[index] if index < len(row) else ""


def is_empty_row(row):
    """Return True when every field in *row* is blank (placeholder row)."""
    return all(c.strip() == "" for c in row)


def norm(value):
    """Normalise a cell value for fuzzy key matching.

    Lowercases, turns en/em dashes, slashes and underscores into spaces, then
    collapses runs of periods and whitespace.  Used by ``dedupe`` and ``fill``
    so near-identical keys (``Prison–industrial complex`` vs
    ``prison industrial complex``) match.
    """
    s = str(value)
    s = s.lower()
    s = s.replace("–", " ").replace("—", " ")
    s = re.sub(r"[/_]+", " ", s)
    s = re.sub(r"[.\s]+", " ", s)
    return s.strip()


def resolve_column(header, spec):
    """Resolve a column spec (header name or 1-based index) to an integer index."""
    if spec.isdigit():
        idx = int(spec) - 1
        if not (0 <= idx < len(header)):
            raise ValueError(f"column index {spec} out of range (1..{len(header)})")
        return idx
    if spec in header:
        return header.index(spec)
    raise ValueError(f"column {spec!r} not found in header (available: {', '.join(header)})")


def split_columns(values):
    """Flatten repeatable/comma-separated ``--columns``-style args to a list."""
    cols = []
    for value in values or []:
        for part in value.split(","):
            part = part.strip()
            if part:
                cols.append(part)
    return cols


def load_table(path, delimiter):
    """Read *path* and return ``(header, data_rows)``.

    Raises ``ValueError`` on an empty file.
    """
    rows = read_rows(path, delimiter)
    if not rows:
        raise ValueError(f"no rows found in {path} (file is empty)")
    return rows[0], rows[1:]


def dedupe_rows(data, key_fn, keep="first"):
    """Return *data* with duplicate rows (per *key_fn*) removed.

    Rows appear in first-seen order; ``keep`` selects whether the first or
    last occurrence of each key is retained.
    """
    table = OrderedDict()
    for row in data:
        key = key_fn(row)
        if keep == "first":
            table.setdefault(key, row)
        else:
            table[key] = row
    return list(table.values())


# ---------------------------------------------------------------------------
# Shared output helper
# ---------------------------------------------------------------------------


def write_result(args, input_path, rows, delimiter):
    """Write *rows* to ``--output``/``--in-place``/stdout for a transform."""
    if args.in_place and args.output:
        raise ValueError("--in-place and --output are mutually exclusive")
    target = args.file if args.in_place else args.output
    if target == "-":
        target = None
    newline = resolve_newline(input_path, args.newline)
    write_output(target, rows, delimiter, newline)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_stats(args):
    delimiter = parse_delimiter(args.delimiter)
    header, data = load_table(args.file, delimiter)
    placeholder = sum(1 for r in data if is_empty_row(r))
    empty = {
        name: sum(1 for r in data if cell(r, i).strip() == "") for i, name in enumerate(header)
    }
    result = {
        "file": str(args.file),
        "columns": len(header),
        "data_rows": len(data),
        "placeholder_rows": placeholder,
        "empty_cells": empty,
    }
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"file: {result['file']}")
        print(f"columns: {result['columns']}")
        print(f"data rows: {result['data_rows']}")
        print(f"placeholder rows (all fields empty): {result['placeholder_rows']}")
        print("empty cells by column:")
        for name, count in empty.items():
            print(f"  {name}: {count}")
    return 0


def run_check(header, data, required_indices, required_labels):
    """Validate *data* against *header*. Returns ``(issues, error_count)``."""
    issues = []
    n_errors = 0
    n_cols = len(header)
    for idx, row in enumerate(data, start=2):
        if is_empty_row(row):
            issues.append(
                {
                    "line": idx,
                    "category": "placeholder",
                    "message": "placeholder row (all fields empty)",
                }
            )
            n_errors += 1
            continue
        if len(row) != n_cols:
            issues.append(
                {
                    "line": idx,
                    "category": "field-count",
                    "message": f"wrong field count: {len(row)} (expected {n_cols})",
                }
            )
            n_errors += 1
            continue
        for req_idx, label in zip(required_indices, required_labels, strict=True):
            if cell(row, req_idx).strip() == "":
                issues.append(
                    {
                        "line": idx,
                        "category": "required",
                        "message": f"required column {label!r} is blank",
                    }
                )
                n_errors += 1
    return issues, n_errors


def cmd_check(args):
    delimiter = parse_delimiter(args.delimiter)
    header, data = load_table(args.file, delimiter)
    required = split_columns(args.require)
    required_indices = [resolve_column(header, r) for r in required]
    issues, n_errors = run_check(header, data, required_indices, required)
    if args.format == "json":
        print(
            json.dumps(
                {"file": str(args.file), "errors": n_errors, "issues": issues},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"file: {args.file}")
        if n_errors == 0:
            print(f"status: clean ({len(header)} columns, {len(data)} data row(s))")
        else:
            print(f"status: {n_errors} issue(s) found")
            for issue in issues:
                print(f"  line {issue['line']}: [{issue['category']}] {issue['message']}")
    return 1 if n_errors else 0


def cmd_cut(args):
    delimiter = parse_delimiter(args.delimiter)
    header, data = load_table(args.file, delimiter)
    cols = split_columns(args.columns)
    if not cols:
        raise ValueError("cut requires at least one --columns value")
    indices = [resolve_column(header, c) for c in cols]
    out_header = [header[i] for i in indices]
    out_data = [[cell(r, i) for i in indices] for r in data]
    write_result(args, args.file, [out_header, *out_data], delimiter)
    return 0


def cmd_head(args):
    delimiter = parse_delimiter(args.delimiter)
    header, data = load_table(args.file, delimiter)
    indices = None
    if args.columns:
        indices = [resolve_column(header, c) for c in split_columns(args.columns)]
    if indices is None:
        out_header, out_data = header, data[: args.rows]
    else:
        out_header = [header[i] for i in indices]
        out_data = [[cell(r, i) for i in indices] for r in data[: args.rows]]
    write_result(args, args.file, [out_header, *out_data], delimiter)
    return 0


def cmd_drop_empty(args):
    delimiter = parse_delimiter(args.delimiter)
    header, data = load_table(args.file, delimiter)
    if args.columns:
        indices = [resolve_column(header, c) for c in split_columns(args.columns)]

        def keep(row):
            return any(cell(row, i).strip() for i in indices)

    else:

        def keep(row):
            return not is_empty_row(row)

    kept = [r for r in data if keep(r)]
    dropped = len(data) - len(kept)
    write_result(args, args.file, [header, *kept], delimiter)
    print(f"dropped {dropped} row(s)", file=sys.stderr)
    return 0


def cmd_dedupe(args):
    delimiter = parse_delimiter(args.delimiter)
    header, data = load_table(args.file, delimiter)
    if args.key:
        indices = [resolve_column(header, k) for k in split_columns(args.key)]

        def key_fn(row):
            cells = [cell(row, i) for i in indices]
            if args.norm:
                cells = [norm(c) for c in cells]
            return tuple(cells)

    else:
        key_fn = tuple
    unique = dedupe_rows(data, key_fn, keep=args.keep)
    removed = len(data) - len(unique)
    write_result(args, args.file, [header, *unique], delimiter)
    print(f"removed {removed} duplicate row(s)", file=sys.stderr)
    return 0


def cmd_fill(args):
    delimiter = parse_delimiter(args.delimiter)
    header, data = load_table(args.file, delimiter)
    key_index = resolve_column(header, args.key_column)
    map_path = Path(args.map)
    if not map_path.is_file():
        raise FileNotFoundError(f"mapping file not found: {args.map}")
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise ValueError("mapping must be a JSON object of the form {key: {column: value}}")
    if args.norm:
        mapping = {norm(k): v for k, v in mapping.items()}
    allowed = set(split_columns(args.fill_columns)) if args.fill_columns else None

    for key, cols in mapping.items():
        if not isinstance(cols, dict):
            raise ValueError(f"mapping value for key {key!r} must be an object {{column: value}}")
        for col in cols:
            if col not in header:
                raise ValueError(
                    f"mapping column {col!r} not in header (available: {', '.join(header)})"
                )
            if allowed is not None and col not in allowed:
                raise ValueError(f"mapping column {col!r} not in --fill-columns {sorted(allowed)}")

    matched = set()
    for row in data:
        key = cell(row, key_index)
        lookup = norm(key) if args.norm else key
        if lookup in mapping:
            matched.add(lookup)
            if len(row) < len(header):
                row.extend([""] * (len(header) - len(row)))
            for col, value in mapping[lookup].items():
                row[header.index(col)] = value

    unmatched = [k for k in mapping if k not in matched]
    write_result(args, args.file, [header, *data], delimiter)
    print(f"filled {len(matched)} key(s); {len(unmatched)} unmatched", file=sys.stderr)
    for key in unmatched:
        print(f"  unmatched key: {key!r}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_file_and_delimiter(parser):
    parser.add_argument("file", help="Input CSV/TSV path.")
    parser.add_argument(
        "--delimiter",
        default="comma",
        help="Field delimiter: comma, tab, semicolon, pipe, or a single character. Default: comma.",
    )


def _add_output(parser):
    parser.add_argument(
        "--newline",
        choices=("auto", "crlf", "lf"),
        default="auto",
        help="Output line ending. Default: auto (detect from input).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path. Default: stdout. Use '-' for stdout.",
    )
    parser.add_argument(
        "--in-place", action="store_true", help="Overwrite the input file atomically."
    )


def _add_format(parser):
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format. Default: text.",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="csv-util",
        description="Inspect and transform CSV/TSV files (replaces mlr and csvkit).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("stats", help="Row/column counts and empty-cell statistics.")
    _add_file_and_delimiter(p)
    _add_format(p)

    p = sub.add_parser("check", help="Validate field counts and required columns.")
    _add_file_and_delimiter(p)
    _add_format(p)
    p.add_argument(
        "--require",
        "-r",
        action="append",
        default=None,
        help="Column (name or 1-based index) that must be non-empty. Repeatable or comma-separated.",
    )

    p = sub.add_parser("cut", help="Select a subset of columns.")
    _add_file_and_delimiter(p)
    _add_output(p)
    p.add_argument(
        "--columns",
        "-c",
        action="append",
        default=None,
        help="Columns to keep (name or 1-based index). Repeatable or comma-separated. Required.",
    )

    p = sub.add_parser("head", help="Preview the first N data rows.")
    _add_file_and_delimiter(p)
    _add_output(p)
    p.add_argument(
        "--rows",
        "-n",
        type=int,
        default=10,
        help="Number of data rows to show. Default: 10.",
    )
    p.add_argument(
        "--columns",
        "-c",
        action="append",
        default=None,
        help="Optional column subset (name or 1-based index).",
    )

    p = sub.add_parser("drop-empty", help="Remove blank/placeholder rows.")
    _add_file_and_delimiter(p)
    _add_output(p)
    p.add_argument(
        "--columns",
        "-c",
        action="append",
        default=None,
        help="If given, drop rows where ALL listed columns are blank; otherwise drop rows where ALL columns are blank.",
    )

    p = sub.add_parser("dedupe", help="Remove duplicate rows.")
    _add_file_and_delimiter(p)
    _add_output(p)
    p.add_argument(
        "--key",
        "-k",
        action="append",
        default=None,
        help="Column(s) to dedupe on (name or 1-based index). Default: the entire row.",
    )
    p.add_argument(
        "--norm",
        action="store_true",
        help="Normalise key values before comparing (lowercase; en/em dashes, slashes and underscores become spaces).",
    )
    p.add_argument(
        "--keep",
        choices=("first", "last"),
        default="first",
        help="Which occurrence to keep. Default: first.",
    )

    p = sub.add_parser("fill", help="Fill columns from a JSON map.")
    _add_file_and_delimiter(p)
    _add_output(p)
    p.add_argument(
        "--map",
        required=True,
        help='JSON file of the form {"key": {"column": "value"}}.',
    )
    p.add_argument(
        "--key-column",
        required=True,
        help="Column to match against the map keys (name or 1-based index).",
    )
    p.add_argument(
        "--fill-columns",
        action="append",
        default=None,
        help="Restrict which columns may be written. Repeatable or comma-separated.",
    )
    p.add_argument(
        "--norm",
        action="store_true",
        help="Normalise keys before matching (both map keys and row cells).",
    )

    return parser


def parse_args():
    return build_parser().parse_args()


def _dispatch(args):
    handlers = {
        "stats": cmd_stats,
        "check": cmd_check,
        "cut": cmd_cut,
        "head": cmd_head,
        "drop-empty": cmd_drop_empty,
        "dedupe": cmd_dedupe,
        "fill": cmd_fill,
    }
    return handlers[args.command](args)


def main():
    args = parse_args()
    try:
        return _dispatch(args)
    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        OSError,
        csv.Error,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    run_cli(main)

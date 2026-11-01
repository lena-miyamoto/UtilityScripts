---
name: csv-tool
description: Inspect and transform CSV/TSV files (stats, check, cut, head, drop-empty, dedupe, fill) via a bundled stdlib-only Python script. Use when a task asks to read, validate, reshape, clean, or dedupe delimited data.
argument-hint: What to do with the CSV, e.g. "dedupe data.csv by the name column"
user-invocable: true
model: haiku
effort: low
---

# CSV Tool

Run the bundled stdlib-only script. Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` with the plugin's
install directory:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/csv-tool/scripts/csv-util.py" <command> [options] <file>
```

The first row of every input is the header. Handles CRLF line endings, UTF-8, quoted fields with
embedded commas/newlines/escaped quotes, and `QUOTE_MINIMAL` output. Full flag reference:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/csv-tool/scripts/csv-util.py" --help
python3 "${CLAUDE_PLUGIN_ROOT}/skills/csv-tool/scripts/csv-util.py" <command> --help
```

## Subcommands

| Command      | What it does                                                       |
| ------------ | ------------------------------------------------------------------ |
| `stats`      | Row/column counts, per-column empty-cell counts, placeholder rows. |
| `check`      | Validate field counts and required columns are non-empty.          |
| `cut`        | Keep a subset of columns.                                          |
| `head`       | Preview the first N data rows (default 10).                        |
| `drop-empty` | Remove blank/placeholder rows.                                     |
| `dedupe`     | Remove duplicate rows (full row, or by key column).                |
| `fill`       | Fill columns from a `{key: {column: value}}` JSON map.             |

## Options

- `<file>` — input path; first positional argument.
- `--delimiter` — `comma` (default), `tab`, `semicolon`, `pipe`, or a single character.
- `--format json|text` — `stats` and `check` output only.
- `--require/-r` — `check` only; columns (name or 1-based index) that must be non-empty. Repeatable or
  comma-separated.
- `--output/-o`, `--in-place`, `--newline auto|crlf|lf` — transforms (`cut`, `head`, `drop-empty`,
  `dedupe`, `fill`). Default is stdout; `--in-place` overwrites the file atomically.
- `--columns/-c` — column subset for `cut`, `head`, `drop-empty` (name or 1-based index).
- `--key/-k`, `--norm`, `--keep first|last` — `dedupe` key selection and matching.
- `--map`, `--key-column`, `--fill-columns`, `--norm` — `fill` mapping inputs.

Column specs (`--require`, `--columns`, `--key`, `--key-column`) accept a header name or a 1-based
index. `--fill-columns` accepts header names only.

## Procedure

1. Refuse any input or output path under `$CLAUDE_CONFIG_DIR` (unset → `~/.claude`), even when
   named directly: never read or overwrite config files or state there. The bundled
   `${CLAUDE_PLUGIN_ROOT}` script is the tool, not an input, and stays usable if installed there.
   Resolve symlinks first. Then map the request to a subcommand and options. Ambiguous column names
   or delimiters → ask, not guess.
2. Build the command; quote file paths. Transforms write to stdout by default, so preview there first.
3. Run it and check the output. `check` exits non-zero when issues are found; treat that as a finding,
   not a failure.
4. `--in-place` overwrites the input (atomically via temp file + rename). Confirm before using it on a
   file the user did not already ask to overwrite. `--output` writes a new file the same way.
5. Report what changed: rows dropped, duplicates removed, keys filled, or issues found.

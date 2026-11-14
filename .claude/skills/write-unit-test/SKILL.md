---
name: write-unit-test
description: >
  Write pytest tests for this repo. Prefer hermetic (mock seams: subprocess, disk, network);
  spawn a real binary only when it is the unit under test.
argument-hint: 'Provide the project, the module under test, and the behavior to cover.'
disable-model-invocation: false
user-invocable: true
---

# Write Unit Test

Source of truth for writing pytest tests in this repo.

## Repo layout

Four uv projects, each with its own `.venv` and test command:

- Root — `.claude/scripts/` (`entrypoints.py`, `utils.py`), `test_cli.py`. Entry point
  `uv run test` → `pytest .claude/scripts`.
- `plugins/dev-utils/skills/csv-tool/scripts/` — `csv-util.py`, `test_csvtool.py`.
- `plugins/statusline/statusline/` — `statusline.py`, `subagent-statusline.py`,
  `shared.py`, `install-statusline.py`; `test-statusline.py`,
  `test-subagent-statusline.py`.
- `plugins/tool-permissions/hooks/tool-permissions/` — `main.py`, `test_main.py`.

## When to Use

- Adding a test or refactoring one in any of the four projects.

## Contract

Prefer hermetic — mock the seam. Spawn a real binary only when it is the unit under test.

1. **Mock subprocess seams; spawn only the unit under test.** Do not run a helper binary
   to fabricate input you could make yourself: monkeypatch `subprocess.run`
   (statusline) or feed synthetic sources (tool-permissions). Two integration cases are
   legitimate because the binary *is* the unit:
   - csv-tool smoke tests spawn the installed `csv-tool` console script.
   - tool-permissions `_git_paths_tracked` builds a real git repo in `tmp_path` — the hook
     shells out to `git`, so the repo must be real.
2. **No real disk outside `tmp_path`.** This repo has no pyfakefs — `tmp_path` is a real
   temp dir under `/tmp`. Every read/write a test makes goes through `tmp_path`; never
   open, stat, or write `~`, a repo-relative path, or a hard-coded absolute path.
3. **No network.** No test dials a host. Fake the fetch seam or use synthetic inputs; a
   `http(s)://` literal is fine only when handed to a mock.
4. **No implementation-text assertion.** Asserting a substring of a module's source is a
   snapshot test that breaks on every harmless refactor. Assert observed behavior — return
   values, captured calls, written output. Generated output (a file the code writes into
   `tmp_path`) is fair game.

## Repo conventions

- Root tests import `entrypoints` and `utils` directly (the editable install exposes
  `.claude/scripts`). Plugins import their own module: `import main`, `import statusline`.
- Hyphenated scripts are not importable by name. Load them with
  `importlib.util.spec_from_file_location` (see `_load_installer` in `test-statusline.py`).
- tool-permissions tests build synthetic policy sources with the local `src()`/`ev()`
  helpers, or exercise the real `load_permissions()` against the repo's shipped template
  (`agent-templates/claude-global/permissions.json`) via a temp `CLAUDE_CONFIG_DIR` — never
  the live `~/.claude/permissions.json`.
- Canonical test command: `.claude/scripts/bwrap-pytest.sh` (root) or
  `.claude/scripts/bwrap-pytest.sh -C <project-dir>` (plugin). Execute it directly — never
  through `sh`, `bash`, `uv run`, or another program (it has a working shebang). It runs
  `uv --offline --no-sync` inside a read-only, network-isolated bubblewrap sandbox. Only
  when `bwrap` is not on PATH (`command -v bwrap`), fall back to `uv run test` (root) or
  `uv run pytest` from the plugin dir. Never run bare `pytest` when `bwrap` is available.

## Procedure

1. Identify the project and the function/behavior to cover.
2. Find the seam (subprocess, disk, or network) and mock it — unless the binary under test
   is the unit (csv-tool, git-backed `_git_paths_tracked`).
3. Write the test using `tmp_path`, `monkeypatch`, and the project's import style.
4. Run the canonical test command for that project.

## Validation

1. The canonical command passes with no failures and no skips from missing real tools.
2. The test spawns a real binary only for the two integration cases above.
3. No test reads a module's source to assert on its text.
4. Root changes: `uv run lint` reports clean (ruff check + `ruff format --check`).
5. No network, and no filesystem touch outside `tmp_path` (csv-tool's own input/output paths
   excepted).

## Output

- State the project, file, and test name added.
- State which seams were mocked, or why a real binary was spawned.

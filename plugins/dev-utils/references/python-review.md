---
description: Python review rulebook — evidence order, repo contract, correctness and modern-idiom rules, pytest rules, severity mapping, and valid patterns. Read before reviewing any `*.py` file.
---

# Python Review Rules

Source of truth for Python review in `review-changeset` — rulebook for `*.py` anywhere in the repo,
including plugin subprojects.

Repo shape: detect it per file, not per repo. A uv project is a `pyproject.toml` that actually covers
the file — for example, its `[tool.setuptools.package-dir]` or `py-modules` places the file, its
`[tool.pytest.ini_options] testpaths` includes it, or a `tests/` directory sits beside it. Bare
`pyproject.toml` presence does not make a file part of that project. In this repo the root
`pyproject.toml` covers only `.claude/scripts`, so scripts outside it are standalone unless their
own project's `pyproject.toml` covers them — the plugin subprojects do. Run a project's tests when
it has `tests/` or pytest configuration, and its configured linter read-only when it sets
`[tool.ruff]` or another `[tool.*]` lint section. The repo-wide root `[tool.ruff]` still applies to
standalone scripts: `uv run ruff check <file>` is available read-only. A standalone script is
untyped, prints to stdout, and has no tests — review it by reading. Do not apply project standards to
standalone scripts, or the reverse.

## Evidence Order

Always in this order; earlier evidence outranks later judgment.

1. Read the diff hunk **and** the full current file. Hunk alone hides the contract the change sits in.
2. If the file lives in a uv project (a `pyproject.toml` that covers it, per Repo shape above), run
   `uv run --project <project-dir> pytest` when that project has tests. A failing test is an
   **Error**, quoted verbatim. Execute this from the project directory or pass `--project`; never
   from the repo root when the root is not a Python project.
3. If the project configures a linter (ruff, `[tool.*]` lint settings), run it read-only. A
   standalone script has no project tests, but the repo-wide `[tool.ruff]` still applies:
   `uv run ruff check <file>` read-only. Never invent a lint result, and never report a rule ID no
   configured tool produced.
4. Only then apply the judgment rules below — they cover what the tools cannot see. Standalone
   scripts are reviewed by reading; the repo-wide ruff check is their only automated evidence.

Never pass `--fix`; never run a formatter or any command that rewrites a source file. This skill
stays text-only.

## Repo Contract Rules

Violation is an **Error** unless stated otherwise.

- Standalone utilities stay single-purpose and lightweight: standard shell or a small scripting
  library beats a framework dependency. A new heavyweight dependency for something the stdlib does
  is a Warning.
- Setup scripts stay idempotent on re-run. Breaking a safe re-run is an Error.
- Setup scripts keep the general-setup vs Lena-specific-opt-in split. Collapsing it is an Error.
- Download-and-run flows keep checksum verification. Weakening or removing it is an Error.
- Setup and privacy scripts keep their safety prompts and obviousness. A destructive step without
  confirmation is an Error.
- Errors print to stderr, results to stdout where the script is a CLI. A traceback reaching the
  agent is an Error.
- Parsers and converters must not write confidential data into tracked files. A script that prints,
  logs, or persists card numbers, IBANs, credentials, or API keys is an Error — the repo is public.
- Plugin Python obeys the plugin contract: version in three files, preserved hook/permission
  semantics, no service exposure without an explicit request.

## Correctness Rules

**Error** — wrong behavior, data loss, or security exposure:

- Mutable default argument (`def f(x=[])`).
- Bare `except:` or bare `except Exception` that swallows (`pass`, no re-raise, no log).
- Re-raise without `raise ... from`.
- Untrusted input reaching `eval`, `exec`, `pickle.loads`, `yaml.load` without `SafeLoader`, or
  `subprocess` with `shell=True`. Fetched bytes are untrusted by definition.
- Regex with nested quantifiers over unbounded fetched text (catastrophic backtracking / ReDoS).
- Resource leak: file, socket, or subprocess opened without `with` or explicit close.
- Docstring or comment claiming behavior the code does not implement. Where the claim is a contract
  ("the largest candidate wins", "left intact rather than removed"), the mismatch is an Error, not a
  nit — check every new comment against the code it describes.
- Silent fallback that hides a real failure — broad `except` returning a default, heuristic
  reverting without a trace.
- `== None`, `is` on strings or numbers, `type(x) == T` in place of `isinstance`.
- Off-by-one in slices, ranges, loop bounds; mutating a list while iterating it.
- Shadowing a builtin (`id`, `type`, `input`, `list`).
- A download or copy path that can overwrite user files without a check, or that follows a symlink
  out of its target directory.

**Warning** — cost, maintainability, or hidden state:

- Work proportional to input size that could be linear: regex recompiled inside a loop or per item,
  quadratic string building, repeated full-file reads.
- Mutable module-level state instead of a returned or passed value.
- Duplicated logic an existing helper already provides.
- Returning `None` for failure where an exception or described result value would be clearer.
- Nesting deeper than 3 levels where an early return flattens it.

## Modern Python Rules

- Judge idioms against the floor of the file's own project: read `requires-python` from the nearest
  `pyproject.toml`. Standalone scripts must keep running on the interpreter they are invoked with.
- `X | None` over `Optional[X]`; builtin generics (`list[str]`, `dict[str, int]`) over
  `typing.List`/`Dict`; `collections.abc` (`Iterable`, `Callable`, `Sequence`) over the `typing`
  equivalents.
- `pathlib.Path` over `os.path`, except where `Path` has no equivalent (`os.path.lexists` inspects
  the link itself, not the target).
- f-strings over `%` and `.str.format()`; `str.removeprefix`/`removesuffix` over slicing;
  `zip(..., strict=True)`; `enumerate` over a manual index counter.
- Timezone-aware datetimes for anything persisted or user-visible: `datetime.UTC`. Not
  `datetime.utcnow()`, and not `timezone.utc` — the alias is the 3.11+ form.
- `@dataclass(frozen=True, slots=True)` for value objects. Mutable class attribute left unannotated
  is a Warning.
- Introducing `asyncio` or `async def` into a sync script or CLI path is a Warning — flag it, do not
  assume it is an upgrade.
- `from __future__ import annotations` unnecessary on the project's Python floor and absent
  repo-wide. Adding it is **Info**.

## Test Rules (pytest)

A file in a project with tests (`tests/` or pytest configuration) follows these rules. A standalone
script with no test is an Info coverage note, not a finding.

- Tests live next to the module they cover or in `tests/`, named `test_<module>.py` or
  `test-<module>.py`.
- One behavior per test; the name states the behavior. `test_1`, `test_works`, and names carrying no
  expectation are a Warning.
- `@pytest.mark.parametrize` over copy-pasted near-identical tests; pass `ids=` for readable names.
  Parametrizing unrelated behaviors is a Warning.
- Fixtures default to function scope. A session-scoped fixture holding mutable state makes test
  order a hidden input — Warning.
- `yield` fixtures for teardown, asserting the teardown ran where it matters.
- Mock the boundary (network, clock, third-party, module-level I/O), not repo-owned code. Mock
  assertions must be signature-safe (`autospec=True`) — a typo'd mock assertion passes silently.
- Patch where the name is **looked up**, not where it is defined. Patching the wrong target is an
  Error: the test passes without exercising the code.
- Prefer a real object (`tmp_path`, a local fake) over mocking a repo-owned function.
- A bug fix without a regression test that fails before and passes after is an Error in a project
  that has tests.
- A regression test is only as strong as the last stage that can undo the guard. Before calling a
  test sound, name the masker that would keep it green with the guard deleted. Typical maskers:
  - `except ...: return default` sentinel chains — the sentinel absorbs removal of any specific
    validation branch.
  - Normalizing post-processing (`re.sub(r"\s+", " ")`, `strip()`, `slugify`) — a test asserting
    normalized text cannot detect a deleted normalization guard.
  - Decode-with-`errors="replace"` plus retry loops — "no exception" assertions prove nothing.
  - A later conversion or extraction stage that restores or rewrites the guarded text.
- A fix for a "cannot fail" test names its mutation: the exact branch whose removal makes the test
  fail, and the fixture change that defeats every masker on the path. Say which masker applies. A
  proposed fixture that still passes under its own mutation is not a fix — rework it, do not hand it
  off. `apply-fixes` performs the mutation and reports a fixture that cannot be made to fail.
- Ban: `assert True`, `time.sleep` for synchronization, dependence on execution order or on another
  test's side effects, assertions on private attributes or on message wording that is not a
  documented contract.
- Tests must not require network access.

## Severity Mapping

- **Error** — wrong behavior, contract violation, security exposure, failing test, a test that
  cannot fail — including one that stays green only because a fallback, a later conversion stage, or
  a nesting/adjacency effect restores or keeps the guarded text.
- **Warning** — cost at input scale, coverage gap, idiom deviation with no stated reason,
  maintainability.
- **Info** — style preference, unnecessary import, a note with no action required.

## Valid Patterns — Do NOT Flag

Every entry below is an accepted repo pattern; flagging it is a false positive.

- **Missing type annotations in root scripts.** They are largely unannotated and no annotation linter
  is configured. Report an annotation finding only inside a module that already annotates, and only
  where the annotation is wrong or inconsistent with the ones around it.
- **`print()` to stdout or stderr.** That is the CLI contract, not a debugging leftover. `logging`
  is not the CLI idiom for output.
- **Module-level compiled regexes and constant collections** with explanatory comments.
- **Heavy `monkeypatch`/`unittest.mock` use in tests.** Boundary mocking is the accepted test
  strategy. Judge *what* is patched, not how much.
- **Leading-underscore helpers and module-private names.**
- **Documented guards and fallbacks** — a safety net with a comment is not dead code.
- **`# noqa: <rule>`** carrying a reason.
- **`if TYPE_CHECKING:` imports**, `__all__`, and `__main__` guards.
- **Shebang scripts invoked directly** at the repository root. The `uv run` contract applies inside
  uv projects, not to standalone scripts.
- **`os` calls with no `pathlib` equivalent**, including `os.path.lexists`.
- **Anything a configured linter already checks and the diff passes.**

## Sources

- Ruff — linter and rule selection: <https://docs.astral.sh/ruff/linter/>
- PEP 8 — Style Guide for Python Code: <https://peps.python.org/pep-0008/>
- Python 3.13 release notes: <https://docs.python.org/3.13/whatsnew/3.13.html>
- pytest — good integration practices: <https://docs.pytest.org/en/stable/explanation/goodpractices.html>
- pytest — monkeypatch reference: <https://docs.pytest.org/en/stable/how-to/monkeypatch.html>

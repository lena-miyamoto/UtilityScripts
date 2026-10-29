---
name: review-changeset
description: >
             Review the current changeset for logical inconsistencies, obvious flaws, stale
             cross-file references in instruction files, repo-contract violations in changed
             Python and shell, plugin version drift, and confidential data. Auto-detects
             scope: staged changes if present, otherwise unstaged. Produces a structured findings
             report with a verdict, a change summary, and a proposed commit subject; returns a fix
             plan to the caller and hands off to `dev-utils:apply-fixes` when issues warrant it.
model: opus
effort: high
context: fork
---

# Review Changeset

Diff-driven review of the current changeset. Instruction files: inconsistencies, stale references,
contradictions that cause wrong behavior. Changed Python and shell: correctness, repo-contract,
modern-idiom violations, using the repo's own checks as evidence. Produces a severity-labeled
findings report. Fix-worthy findings → fix plan returned to caller as text; caller invokes
`dev-utils:apply-fixes`.

## When to Use

- After editing `CLAUDE.md`, `AGENTS.md`, `README.md`, skill, or agent-template `.md` files, before
  committing.
- After editing `*.py`, `*.sh`, or plugin manifests (`plugin.json`, `marketplace.json`,
  `pyproject.toml`), before committing.
- When refactoring a behavioral rule spanning files (e.g., plugin versioning, setup-script split).
- When unsure whether a change in one file breaks references or assumptions in another.
- After renames, moves, or file splits that may leave stale paths.

## Procedure

### 1. Determine Diff Scope

Orient first — recent renames and moves matter:

```bash
git status --short
git log --oneline -8
```

Auto-detect the changeset — no argument needed:

```bash
git diff --cached -M --stat
git diff --cached -M
```

Non-empty → review **staged changes only**.
Empty → fall back to **unstaged changes**:

```bash
git diff -M
git ls-files --others --exclude-standard
```

Untracked files count as part of the unstaged scope; read each. Only one scope — never merge staged
and unstaged. State which scope was used. Review what the user is about to commit (staged) or still
working on (unstaged).

### 2. Filter to Reviewable Files

From the file list, keep these classes:

- **Instruction and doc files** — `.md` under `.claude/`, `agent-templates/`, `plugins/`, plus root
  `CLAUDE.md`, `AGENTS.md`, `README.md`.
- **Python files** — `*.py` anywhere, including plugin subprojects and `tests/`.
- **Shell files** — `*.sh` anywhere, plus extensionless repo-root executables with a `#!` line
  (`manjaro-setup`, `srttools`, `webp2gif`, `webp2png`, `keystore-backup`).
- **Plugin manifests** — `plugins/**/.claude-plugin/plugin.json`,
  `plugins/**/pyproject.toml`, `.claude-plugin/marketplace.json`.

Exclude `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`, `node_modules/`,
and every path excluded by `.gitignore` — especially `finance-tools/*.csv`, `tmp/`, `*-db/`, and
`restored/`. Never read an ignored path.

Nothing remains → report "No reviewable files in changeset" and stop. Steps 3–10 cover instruction
files; steps 11 and 12 cover Python and shell, step 6 plugin manifests. A changeset with several
file classes runs each matching step.

### 3. Read Each Changed File

Read every file from step 2 in full — current on-disk version. For code files, read the diff hunk
too. For each **instruction** file, extract:

- **Explicit file references** — any path in backticks, plus references introduced by `Read`, `See`,
  `Follow`, `per`, `defined in`, `owned by`, `source of truth`.
- **Cross-file behavioral rules** — rules restated or referenced across files. Identify by shared
  topics: confidential-data handling, setup-script idempotency, plugin version bump, German
  orthography, file naming, destructive-command safety, marketplace install instructions.
- **Frontmatter fields** — note presence/absence of `name`, `description`, `user-invocable`,
  `argument-hint`, `disable-model-invocation`, `model`, `effort`, `context`, `background` (for
  skills); `name`, `description`, `tools`, `model` (for agents).

### 4. Confidential Data Check

The repo is public. Scan the full diff — not just instruction files — for:

- Secrets: credit card numbers, bank/giro account numbers (`AT44…` IBANs), API keys, credentials.
- The user's real name in prose, comments, docs, or config beyond the existing published
  attribution (`Lena M.` in `plugin.json` author fields and the marketplace `owner`).
- Absolute local paths embedding a username — `/home/<user>/…`, `/Users/<user>/…`, `C:\Users\…`.

Any match → **Error**, and the overall verdict is `BLOCKED`. Never quote the value or name it —
report `file:line` and type only. Never reproduce it in the fix plan.

### 5. Stale-Reference Check

For every reference from step 3, resolve against repo root; verify the target exists on disk with
`test -f <path>`. Flag every missing path as:

- **Error** — target referenced in a procedure step or mandatory file load. Missing it breaks
  execution.
- **Warning** — target mentioned in prose or as a non-critical reference.

Also flag references that no longer match repo structure — e.g., a skill pointing at
`.claude/reference/foo.md` when the file now lives in the plugin's `references/`, or a plugin README
pointing at a moved module.

Beyond paths, cross-check names against the current repo state:

- Files renamed, moved, or deleted (use `-M` rename detection) that are still referenced elsewhere —
  `Grep` the old name repo-wide.
- Function, class, CLI-flag, env-var, or schema-field names referenced but no longer defined.
- Model IDs or model names no longer current.
- URLs or anchors that moved or 404.
- Plugin, agent, skill, or directory names that were renamed.

Confirm before flagging: a reference is stale only when its target truly no longer exists — `Grep`
or `Read` to verify. Skip references this same changeset already fixes; flag only the stragglers.

### 6. Cross-File Consistency Check

For each changed file, identify its **related files** — other instruction files it references, plus
files that reference it. Known related sets in this repo:

- `CLAUDE.md` ↔ `AGENTS.md` (AGENTS.md only points at CLAUDE.md) and ↔ every skill or template it
  routes to.
- Plugin README ↔ `plugins/<name>/.claude-plugin/plugin.json` ↔ `.claude-plugin/marketplace.json`.
- Skill `SKILL.md` ↔ the reference files it loads from `references/`.
- `agent-templates/claude-global/CLAUDE.md` ↔ root `CLAUDE.md`: template rules must not contradict
  repo rules they are derived from.

For each related pair where at least one file is in the diff, read both and check:

- **Behavioral contradiction** — does file A's new instruction contradict file B's existing rule?
- **Orphaned reference** — does the changed file reference a section heading, step number, or list
  item that no longer exists in the target file?
- **Divergent restatement** — is the same rule stated differently across files in ways that could
  produce different behavior?

**Plugin version sync** — for any plugin under `plugins/<name>/` touched by the diff, verify every
version field it carries matches: `.claude-plugin/plugin.json` → `version`, the entry in
`.claude-plugin/marketplace.json` → `version`, and `pyproject.toml` → `version` when the plugin
bundles a Python project. A mismatch is an **Error**; a touched plugin with no version bump at all is
an **Error**.

### 7. Model & Effort Appropriateness

For every changed skill or agent file with `model` and/or `effort`, read
`${CLAUDE_PLUGIN_ROOT}/references/model-capabilities.md` and resolve the value there before judging.
Resolve aliases against the session's service — never the Claude model of the same alias name.
Default DeepSeek wiring: `haiku`/`sonnet` → `deepseek-flash`, `opus`/`fable` → `deepseek-v4-pro`; on
Anthropic the aliases map to the Claude models of those names. Flag:

- **Error** — skill `model` is not one of `haiku`, `sonnet`, `opus`, `fable`, `best`, `opusplan`,
  `default`, `inherit`, or a full `claude-*` / `deepseek-*` model ID; or `effort` is not one of
  `low`, `medium`, `high`, `xhigh`, `max`.
- **Error** — agent `model` is not one of `sonnet`, `opus`, `haiku`, `fable`, or a full model ID.
  `best`, `opusplan`, `default`, and `inherit` are skill values only; agent frontmatter rejects them.
- **Warning** — the `(model, effort)` pair mismatches the work the file's body and description say
  it does, per the Selection Guide.
- **Info** — `effort` is `medium` or `xhigh`: on the DeepSeek wiring both collapse to `high`, adding
  no capability over `high`. Flag only when the file's prose implies they do.
- **Info** — `model` is `fable`: on the DeepSeek wiring it resolves to the same model as `opus`.

Cite `${CLAUDE_PLUGIN_ROOT}/references/model-capabilities.md` in every finding from this step. This
step never edits frontmatter — corrections go into the fix plan like any other finding.

### 8. Internal Consistency

Within each changed file, flag:

- **Contradictory rules** — opposing instructions within the same file.
- **Mismatched counts** — prose says "three components" but the list has 2 or 4 items; heading says
  "five elements" but only 4 are enumerated.
- **Broken placeholders** — `<placeholder>` syntax used but never defined in the file or its
  documented inputs.
- **Lost emphasis** — a rule previously marked `CRITICAL`, `IMPORTANT`, `YOU MUST`, or `NEVER` lost
  its emphasis marker in the new version. Check the diff: if a line containing these keywords was
  removed, verify the rule is still enforced elsewhere or flag it.
- **Missing steps** — numbered procedure steps where a number is skipped (1, 2, 4 — missing 3).

### 9. Instruction Guidance Check

For every changed instruction or config file, compare its claims against current Anthropic guidance:
CLAUDE.md conventions, skill frontmatter and layout, plugin schema, hooks, settings keys, model
names. Flag deprecated flags, old schema fields, outdated model names, and renamed features.

When unsure what is current, ask the `claude-code-guide` agent or WebFetch the official docs
(`code.claude.com/docs`). Never assert "current" without a source: cite the doc URL or the agent's
finding in every such finding. A repo claim no cited source supports is a **Warning** — the repo's
reference files drive audits and must not carry unsourced rules.

### 10. Token Efficiency

Flag verbosity, duplicated restatements, and padding that cost context on every load — never at the
cost of meaning. Meaning includes emphasis keywords, obligation words, temporal framing, enumerated
counts, identity claims, and consequence statements. A rule that survives only as a pointer is
cheaper than a copied paragraph; a copied paragraph is only acceptable when no owner file exists.

### 11. Python Review

Skip this step when no `.py` files remain after step 2.

Read `${CLAUDE_PLUGIN_ROOT}/references/python-review.md` — owns evidence order, repo-contract,
correctness and modern-idiom, test rules, severity mapping, and the valid-patterns list that prevents
false positives. For every changed `.py` file:

1. Read the diff hunk **and** the full current file. The hunk alone hides the contract it sits in.
2. If the file belongs to a uv project (nearest `pyproject.toml`), run that project's tests:
   `uv run --project <project-dir> pytest`. If the project configures a linter, run it read-only.
   Root scripts have neither — review them by reading.
3. Report each lint violation verbatim with its rule ID, and each failing test with its output. A
   Python finding cites real tool output or a rulebook section — never a guess, never a remembered
   rule.
4. Apply the judgment rules for what the tools cannot see: contract violations, docstring/behavior
   mismatches, untrusted-input handling, confidential-data persistence, and test quality.
5. Suppress every pattern on the rulebook's valid-patterns list. `print()` to stdout/stderr, absent
   type annotations in root scripts, and heavy boundary mocking in plugin tests are repo norms, not
   findings.

Cite `${CLAUDE_PLUGIN_ROOT}/references/python-review.md` in every finding from this step. Like step 7,
this step never edits code — corrections go into the fix plan.

### 12. Shell Review

Skip this step when no shell files remain after step 2.

- Run `bash -n <path>` on every changed shell script. A syntax error is an **Error** with the
  verbatim message.
- Run `shellcheck <path>` when `command -v shellcheck` succeeds. Report each finding with its `SC`
  code and message. Severity `error` → Error; `warning` → Warning; `info`/`style` → Info. Do not
  restate shellcheck's advice from memory.
- Check by reading what shellcheck cannot see:
  - **Error** — a destructive command (`rm -rf`, `dd`, `mkfs`, `shred`) without a confirmation
    prompt or a guard, in any script the README presents as safe to run.
  - **Error** — download-and-run flow with checksum verification removed or weakened.
  - **Error** — credentials, tokens, or account numbers in the script.
  - **Warning** — a setup action that is no longer idempotent on re-run.
  - **Warning** — the general-setup vs Lena-specific-opt-in split collapsed or bypassed.
- Preserve CLI shape: flags, env vars, prompts, exit behavior, and default side effects are part of
  the interface. A silently changed flag or default is an **Error**.

### 13. Assemble Findings Report

Produce a report organized by file. For each finding, include:

- **Severity**: `Error` (will cause wrong or undefined behavior), `Warning` (potential issue, needs
  judgment), `Info` (noted, no action required).
- **Location**: file path and section/line reference.
- **Description**: what the issue is, why it matters.
- **Related files**: if the issue spans multiple files, list all involved.

No findings → report "No issues found in `N` reviewable files." Include a summary line listing which
files were reviewed. Stop here — no handoff needed.

### 14. Hand Off the Fix Plan (When Findings Warrant It)

If the report contains any **Error** or **Warning** findings, append the fix plan to your final
message as text — do **not** write a file. The plan must:

- **Summarize each finding** — one bullet per finding with severity, file, and a one-line
  description.
- **Propose a fix** for each Error and Warning. Info findings are listed but fixes are optional.
- **Name the mutation for every test-quality fix.** A fix that makes a test able to fail states the
  exact branch whose removal breaks it and the fixture change that defeats the maskers on the path —
  see the masker list in `${CLAUDE_PLUGIN_ROOT}/references/python-review.md`. A proposed fixture you
  cannot show would fail under that mutation is not a fix: rework it before handing off, do not hand
  off a guess for `dev-utils:apply-fixes` to discover.
- **Be concise** — a fix checklist, not a restatement of the review report.

End the message with this handoff line:

> Caller: present this plan to the user, wait for explicit approval, then invoke the
> `dev-utils:apply-fixes` skill with this plan as `args` to apply the fixes.

Do not apply any fix here. `dev-utils:apply-fixes` owns applying approved fixes, is not forked, and
is not user-invocable — the caller runs it inline after approval.

No Errors or Warnings → state that and stop — no plan, no handoff.

## Writing Rules

- Read-only always. Writes no files — including no plan file. Review summary and fix plan return as
  text to the caller.
- Never edit, move, or delete a reviewed file. Beyond step 1 git scope checks, the diff reads steps 3
  and 8 require, and step 5 `test -f` checks, this skill runs only these read-only checks:
  `bash -n`, `shellcheck`, `uv run --project <dir> pytest`, and a project's configured linter. Never
  `--fix`, never a formatter, never any fix-up script — text-only is what lets this skill run
  backgrounded.
- Never apply fixes. This skill stops at the handoff — `dev-utils:apply-fixes` owns applying approved
  fixes.
- Never reproduce a confidential value. Report `file:line` and type only.
- Python findings go through step 11 and `${CLAUDE_PLUGIN_ROOT}/references/python-review.md`.
  Suppress every pattern on that file's valid-patterns list before reporting — a false positive on
  repo idiom costs more than a missed nit.
- Treat `.gitignore` boundaries as out of scope. Skip any file excluded by `.gitignore`; the
  confidential-data check applies to tracked content only.
- Every flagged issue must cite the specific contradiction or missing reference. No vague findings.
- Cross-file consistency checks are the highest-value part of this skill — prioritize them over
  exhaustive internal checks when time is limited.
- Model/effort findings must cite `${CLAUDE_PLUGIN_ROOT}/references/model-capabilities.md` and name
  the model the alias resolves to under the session's wiring — never call a value wrong based on the
  Claude model of the same alias name.
- Guidance findings must cite the doc URL or the `claude-code-guide` finding they rest on. A claim no
  source supports is not a finding against the file — it is a finding against the claim.

## Validation

1. Diff scope auto-detected correctly — staged if present, otherwise unstaged; stated in the report.
2. Every changed reviewable file read in full; for code files, the diff hunk as well.
3. Every extracted file reference verified against disk.
4. Cross-file checks completed for all related-file pairs where at least one side changed.
5. Every touched plugin has matching versions in `plugin.json` and `marketplace.json`, and
   `pyproject.toml` too when it bundles a Python project.
6. Internal consistency checked for every changed file.
7. Report includes severity, location, and description for every finding. "No issues found" is an
   acceptable result when the changeset is clean.
8. Every changed file carrying `model` or `effort` was checked against
   `${CLAUDE_PLUGIN_ROOT}/references/model-capabilities.md`, and each such finding names the model
   the alias resolves to under the session's wiring.
9. If Errors, Warnings, or a confidential-data match were found: a fix plan was returned as text
   with concrete fixes, and the final message instructs the caller to invoke `dev-utils:apply-fixes`
   after user approval. No plan file was written, and no confidential value was reproduced.
10. If `.py` files were in scope: `${CLAUDE_PLUGIN_ROOT}/references/python-review.md` was read, the
    owning project's tests were run where they exist, and each Python finding quotes tool output or
    cites a rulebook section.
11. If shell files were in scope: `bash -n` ran on each, `shellcheck` ran where installed, and each
    shell finding quotes tool output or names the exact destructive step or broken guarantee.
12. Every Python finding was checked against the rulebook's valid-patterns list, and no command that
    rewrites a source file was run.
13. Every test-quality fix names the branch whose removal breaks the test and the masker the fixture
    defeats — no fixture was handed off that would still pass under its own mutation.
14. Every changed instruction file was compared against current Anthropic guidance, and each
    guidance finding cites a doc URL or a `claude-code-guide` result.
15. The token-efficiency pass ran over every changed instruction file, with no meaning dropped.

## Output (fixed order)

1. **Verdict** — one line: `PASS` / `CHANGES NEEDED` / `BLOCKED`.
2. **Findings** — grouped by file, severity labels (Error / Warning / Info), each with `file:line`
   and the tool rule ID or output where a tool produced it. No findings → say so.
3. **Changes** — brief bullets, one per change in the changeset.
4. **Proposed commit message** — Conventional Commits subject, ≤80 chars, no body, no trailer.
5. **Fix plan** — only when Errors or Warnings exist: the plan from step 14, plus the handoff line.
6. **Clean result** — no findings: confirmation the changeset is clean; no fix plan, no handoff.

Summary line: number of files reviewed by class, number of findings by severity.

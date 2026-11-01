---
name: review-changeset
description: >
             Review the current changeset for logical inconsistencies, obvious flaws, stale
             cross-file references in instruction files, repo-contract violations in changed
             Python and shell, plugin version drift, and confidential data. Auto-detects
             scope: staged changes if present, otherwise unstaged, splits the changeset into up
             to three independent review areas, and fans out one parallel sub-agent per area
             before merging the reports. Produces a structured findings report with a verdict, a
             change summary, and a proposed commit subject; returns a fix plan to the caller and
             hands off to `dev-utils:apply-fixes` when issues warrant it.
model: sonnet
effort: high
context: fork
background: false
---

# Review Changeset

Diff-driven review of current changeset. Auto-detect scope, partition changed files into cohesive
review areas, fan out one sub-agent per area, merge reports into one. Instruction files:
inconsistencies, stale references, contradictions causing wrong behavior. Python and shell:
correctness, repo-contract, modern-idiom violations, using repo's own checks as evidence.
Fix-worthy findings → fix plan returned to caller as text; caller invokes `dev-utils:apply-fixes`.

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

Auto-detect changeset — no argument:

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

Untracked files count as unstaged scope; read each. One scope only — never merge staged and
unstaged. State which scope was used: what the user is about to commit (staged) or still working on
(unstaged).

This snapshot is the whole split input. Never re-detect scope later.

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

Nothing remains → report "No reviewable files in changeset" and stop. Steps 6–13 cover instruction
files; steps 14 and 15 cover Python and shell, step 9 also plugin manifests. A changeset with several
file classes runs each matching step.

### 3. Partition Into Review Areas

Split reviewable files into **areas** — bundles one agent can hold in context, coupled enough to
review alone. Do this before any review runs.

- One file belongs to exactly one area. No file dropped, none reviewed twice.
- **Coupling beats balance.** Keep together: a plugin's manifests, `README.md`, skills and reference
  files; a skill and the reference files it loads; root `CLAUDE.md` and the
  `agent-templates/claude-global/CLAUDE.md` rules it owns; any changed pair where one file references
  the other. Splitting a coupled pair across agents loses this skill's highest-value comparison.
- Split along natural seams: changed file class, plugin boundary, setup script versus plugin.
- **Cap at 3 areas.** More candidates → merge the most related or the smallest into a neighbouring
  area. Never dispatch more than 3 agents.
- **One area → no fan-out.** Run steps 6–15 inline over the whole changeset, continue at step 16.
  Single-area changesets gain nothing from an agent and pay context twice.
- State the split in the final report.

### 4. Fan Out Area Reviews

Dispatch one agent per area (2–3 areas). Send **all** `Agent` calls in one message so they run
concurrently; wait for every one to return.

- `subagent_type: general-purpose`.
- `model: sonnet`, `effort: high` — this file's frontmatter settings, unchanged for every area.
  Never raise or lower them per area, never omit them: an agent left on defaults does not match this
  skill's settings. The step down from the Selection Guide's `opus` row is a deliberate cost
  trade-off: up to 3 agents run at once per review. `effort: high` is the normal agentic level, not
  a reasoning tier — under the default DeepSeek wiring the reasoning tier is reached only through
  `opus` or `fable`.
- One call per area, never more than 3.

Briefs are self-contained — a fresh agent sees only the brief. Include exactly this, filled in:

```text
Review area: <short name>
Scope: <staged|unstaged>. The files below are the complete scope — do not review anything else.
Diff: staged → `git diff --cached -M -- <path>`; unstaged → `git diff -M -- <path>`, and untracked
      files have no diff, so read them in full.
Files: <one line per file: status + path>
Related files outside this area: <paths, or "none">

Read ${CLAUDE_PLUGIN_ROOT}/skills/review-changeset/SKILL.md and apply steps 6–15 to your files only.
Do not partition, do not spawn sub-agents, do not write, edit, or fix anything — read-only.

Report every finding you can establish, in one pass. Do not stop after the first Error, and do not
rank findings by how easy they are to fix: a flaw found after an earlier one is not less important.

Return exactly:
Area: <name>
Files reviewed: <paths>
Findings: one block per finding —
  Severity: Error | Warning | Info
  Location: file:line
  Description: what is wrong and why it matters
  Related files: <paths or "none">
  Evidence: tool output, or the reference file section the finding rests on
Changes: one bullet per change in this area, for the changeset summary
```

Dispatch rules:

- Wait for every dispatched agent before continuing. Partial results never get assembled: a missing
  report is a blind spot the fan-out exists to remove.
- Agent fails, returns nothing usable, or skips files → re-dispatch that area once. Still nothing →
  review that area inline with steps 6–15 yourself and say so in the final report. Never fabricate
  findings, never fill a gap from another area's report.
- A finding in one area does not cancel a review of another. All areas are reviewed, always.

### 5. Merge Area Reports

Before assembling the report:

- Concatenate findings. Dedupe identical ones (same file, line, issue); different severities keep
  the higher.
- Agents contradicting each other about the same line → re-read the file, decide yourself.
- **Boundary pairs.** For every changed file, list related files from step 9 that changed in a
  *different* area; run step 9's pair checks on those pairs yourself. The split hides exactly these
  comparisons.
- **Coverage audit.** Confirm each area report covers its steps 6 and 7 duties for every file it
  owns. A report that skipped the confidential-data scan leaves those files unscanned → run step 7
  yourself over them. Any file named in no report → review it inline.
- Nothing is re-reviewed during the merge. Findings from all areas feed step 16 as-is.

### 6. Read Each Changed File

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

### 7. Confidential Data Check

The repo is public. Scan the full diff — not just instruction files — for:

- Secrets: credit card numbers, bank/giro account numbers (`AT44…` IBANs), API keys, credentials.
- The user's real name in prose, comments, docs, or config beyond the existing published
  attribution (`Lena M.` in `plugin.json` author fields and the marketplace `owner`).
- Absolute local paths embedding a username — `/home/<user>/…`, `/Users/<user>/…`, `C:\Users\…`.

Any match → **Error**, and the overall verdict is `BLOCKED`. Never quote the value or name it —
report `file:line` and type only. Never reproduce it in the fix plan.

### 8. Stale-Reference Check

For every reference from step 6, resolve against repo root; verify the target exists on disk with
`test -f <path>`. Flag every missing path as:

- **Error** — target referenced in a procedure step or mandatory file load. Missing it breaks
  execution.
- **Warning** — target mentioned in prose or as a non-critical reference.

Also flag references that no longer match repo structure — e.g., a skill pointing at
`.claude/reference/foo.md` when the file now lives in the plugin's `references/`, or a plugin README
pointing at a moved module.

Beyond paths, cross-check names against repo state:

- Files renamed, moved, or deleted (use `-M` rename detection) that are still referenced elsewhere —
  `Grep` the old name repo-wide.
- Function, class, CLI-flag, env-var, or schema-field names referenced but no longer defined.
- Model IDs or model names no longer current.
- URLs or anchors that moved or 404.
- Plugin, agent, skill, or directory names that were renamed.

Confirm before flagging: stale only when the target truly no longer exists — `Grep` or `Read` to
verify. Skip references this changeset already fixes; flag stragglers.

### 9. Cross-File Consistency Check

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

### 10. Model & Effort Appropriateness

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

### 11. Internal Consistency

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

### 12. Instruction Guidance Check

For every changed instruction or config file, compare its claims against current Anthropic guidance:
CLAUDE.md conventions, skill frontmatter and layout, plugin schema, hooks, settings keys, model
names. Flag deprecated flags, old schema fields, outdated model names, and renamed features.

When unsure what is current, ask the `claude-code-guide` agent or WebFetch the official docs
(`code.claude.com/docs`). Never assert "current" without a source: cite the doc URL or the agent's
finding in every such finding. A repo claim no cited source supports is a **Warning** — the repo's
reference files drive audits and must not carry unsourced rules.

### 13. Token Efficiency

Flag verbosity, duplicated restatements, and padding that cost context on every load — never at the
cost of meaning. Meaning includes emphasis keywords, obligation words, temporal framing, enumerated
counts, identity claims, and consequence statements. A rule that survives only as a pointer is
cheaper than a copied paragraph; a copied paragraph is only acceptable when no owner file exists.

### 14. Python Review

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

Cite `${CLAUDE_PLUGIN_ROOT}/references/python-review.md` in every finding from this step. Like step
10, this step never edits code — corrections go into the fix plan.

### 15. Shell Review

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

### 16. Assemble Findings Report

Produce a report organized by file from the merged area reports plus your own boundary and coverage
checks. For each finding, include:

- **Severity**: `Error` (will cause wrong or undefined behavior), `Warning` (potential issue, needs
  judgment), `Info` (noted, no action required).
- **Location**: file path and section/line reference.
- **Description**: what the issue is, why it matters.
- **Related files**: if the issue spans multiple files, list all involved.

No findings → report "No issues found in `N` reviewable files." Include a summary line listing which
files were reviewed. Stop here — no handoff needed.

### 17. Hand Off the Fix Plan (When Findings Warrant It)

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

Do not apply any fix here. `dev-utils:apply-fixes` owns applying approved fixes, runs forked, and
is not user-invocable — the caller invokes it after approval.

No Errors or Warnings → state that and stop — no plan, no handoff.

## Writing Rules

- Read-only. Writes no files, no plan file. Review summary and fix plan return as text to the
  caller.
- Never edit, move, or delete a reviewed file. Beyond step 1 git scope checks, the diff reads steps 6
  and 11 require, and step 8 `test -f` checks, this skill runs only these read-only checks:
  `bash -n`, `shellcheck`, `uv run --project <dir> pytest`, and a project's configured linter. Never
  `--fix`, never a formatter, never any fix-up script — text-only is what lets this skill run
  backgrounded.
- Never apply fixes. Skill stops at the handoff — `dev-utils:apply-fixes` owns approved fixes.
- Never reproduce a confidential value. Report `file:line` and type only.
- Never dispatch more than 3 area agents, never dispatch them one at a time, and never narrow a brief
  to a "quick pass". An area agent that skips checks creates the blind spot the fan-out is for.
- Coordinator owns the final report. Never pass an area report through unmerged; never drop a finding
  because another area covers similar ground.
- Python findings go through step 14 and `${CLAUDE_PLUGIN_ROOT}/references/python-review.md`.
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

1. Diff scope auto-detected correctly — staged if present, otherwise unstaged; stated in the report;
   staged and unstaged never mixed.
2. Every reviewable file assigned to exactly one area, none dropped, area count ≤ 3, split stated in
   the report.
3. All area agents dispatched in one message with `model: sonnet` and `effort: high`; every
   dispatched agent returned before assembly; any failed agent is named and its area was reviewed
   inline.
4. Every changed reviewable file read in full by its area agent or by you when reviewing inline; for
   code files, the diff hunk as well.
5. Area reports merged: duplicates reconciled, contradictions re-checked, cross-area boundary pairs
   compared, and every area's steps 6 and 7 coverage confirmed.
6. Every extracted file reference verified against disk.
7. Cross-file checks completed for all related-file pairs where at least one side changed.
8. Every touched plugin has matching versions in `plugin.json` and `marketplace.json`, and
   `pyproject.toml` too when it bundles a Python project.
9. Internal consistency checked for every changed file.
10. Report includes severity, location, and description for every finding. "No issues found" is an
    acceptable result when the changeset is clean.
11. Every changed file carrying `model` or `effort` was checked against
    `${CLAUDE_PLUGIN_ROOT}/references/model-capabilities.md`, and each such finding names the model
    the alias resolves to under the session's wiring.
12. If Errors, Warnings, or a confidential-data match were found: a fix plan was returned as text
    with concrete fixes, and the final message instructs the caller to invoke `dev-utils:apply-fixes`
    after user approval. No plan file was written, and no confidential value was reproduced.
13. If `.py` files were in scope: `${CLAUDE_PLUGIN_ROOT}/references/python-review.md` was read, the
    owning project's tests were run where they exist, and each Python finding quotes tool output or
    cites a rulebook section.
14. If shell files were in scope: `bash -n` ran on each, `shellcheck` ran where installed, and each
    shell finding quotes tool output or names the exact destructive step or broken guarantee.
15. Every Python finding was checked against the rulebook's valid-patterns list, and no command that
    rewrites a source file was run.
16. Every test-quality fix names the branch whose removal breaks the test and the masker the fixture
    defeats — no fixture was handed off that would still pass under its own mutation.
17. Every changed instruction file was compared against current Anthropic guidance, and each
    guidance finding cites a doc URL or a `claude-code-guide` result.
18. The token-efficiency pass ran over every changed instruction file, with no meaning dropped.

## Output (fixed order)

1. **Verdict** — one line: `PASS` / `CHANGES NEEDED` / `BLOCKED`.
2. **Findings** — grouped by file, severity labels (Error / Warning / Info), each with `file:line`
   and the tool rule ID or output where a tool produced it. No findings → say so.
3. **Changes** — brief bullets, one per change in the changeset, merged from the area reports.
4. **Proposed commit message** — Conventional Commits subject, ≤80 chars; body only when the why is
   not obvious from the diff; no trailer by default, add only when explicitly asked.
5. **Fix plan** — only when Errors or Warnings exist: the plan from step 17, plus the handoff line.
6. **Clean result** — no findings: confirmation the changeset is clean; no fix plan, no handoff.

Summary line: number of files reviewed by class, number of findings by severity, and the review
areas used with the agent that covered each.

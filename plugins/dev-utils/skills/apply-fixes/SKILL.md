---
name: apply-fixes
description: >
             Apply the fixes from a `dev-utils:review-changeset` fix plan. Invoked by the caller after `dev-utils:review-changeset`
             returns findings that warrant fixes; never invoked directly by the user. Reads the review summary and
             fix plan from the caller's handoff, applies each approved fix, and splits a larger plan across
             parallel agents.
argument-hint: 'The review summary and fix plan text returned by dev-utils:review-changeset'
user-invocable: false
model: sonnet
effort: high
context: fork
background: false
---

# Apply Fixes

Source of truth for the `apply-fixes` skill. Applies fixes from an approved `dev-utils:review-changeset` fix
plan. Forked and not user-invocable — only the handoff-receiving caller invokes it, after the
user approves the plan.

**Repo-scope only.** Never edit, move, or delete anything under `$CLAUDE_CONFIG_DIR` (unset →
`~/.claude`): global `CLAUDE.md`, `settings.json`, agents, skills, installed plugins, project state.
Resolve symlinks first — a repo path whose target lands in the config dir is still out of scope. A
plan item targeting that subtree is skipped and reported to the caller, never applied. Reading this
plugin's own `${CLAUDE_PLUGIN_ROOT}` references is allowed when installed there; nothing else in
the subtree is.

## When to Use

- Called by the caller immediately after `dev-utils:review-changeset` returns a fix plan (Errors or Warnings).
- Only after the user has explicitly approved the plan. Never apply fixes on an unapproved plan.

## Input

- The review summary and fix plan produced by `dev-utils:review-changeset`, passed as `args`.
- If the handoff text is missing or empty → stop and ask the caller for it.

## Procedure

1. Confirm the handoff text carries a review summary and a fix plan. Missing → stop and ask the
   caller.
2. Confirm the plan was approved by the user. Approval unclear → stop and ask; never apply
   unprompted.
3. Decide the split before editing:
   - **Inline is the default.** A plan touching at most 2 files, or fitting one cohesive area, runs
     entirely in this fork. Most plans are this size.
   - Fan out when the plan touches 3+ files across 2+ independent areas: different plugins, setup
     script versus plugin, or unrelated file classes.
   - Cap at 3 areas. More candidates → merge the most related or the smallest into a neighbouring
     area. Never dispatch more than 3 agents.
   - Never split a version bump from the plugin edits it covers, and never split files that must
     change together to stay consistent.
   - One area → no fan-out. Run steps 5–9 inline over the whole plan.
   - State the split in the final report.
4. Fan out (2–3 areas only). Dispatch one agent per area; send **all** `Agent` calls in one message
   so they run concurrently, and wait for every one to return.
   - `subagent_type: general-purpose`.
   - `model` and `effort` at this file's frontmatter values, unchanged for every area. Never raise or
     lower them per area, never omit them. They match `review-changeset`'s coordinator settings, and
     `effort: high` carries the reasoning load.
   - One call per area, never more than 3. Areas are disjoint — no file appears in two briefs.
   - Agent failed or returned an area incomplete → apply that area's items inline yourself and name
     the failure in the report.

   Briefs are self-contained — a fresh agent sees only the brief. Include exactly this, filled in:

   ```text
   Fix area: <short name>
   Files: <one line per file, with the plan items that touch it>
   Plan items: <verbatim checklist entries for this area only>
   Rules: <the writing rules below that apply to these files>. Repo scope: resolve symlinks first;
     never read or edit a path under `$CLAUDE_CONFIG_DIR` (unset → `~/.claude`) or a path whose
     target lands there; the only exception is this plugin's own `${CLAUDE_PLUGIN_ROOT}` references.
   Validation: <the step 7 commands for these file classes>
   Report back: each item applied or skipped, with the validation command run per file.
   ```

5. Apply each plan item, smallest local change first — in this fork, or through the area agent that
   carries it:
   - Path check: resolve `$CLAUDE_CONFIG_DIR` (unset → `~/.claude`); skip any item whose target
     resolves into it and report the skip. Never read or edit that subtree, except this plugin's own
     `${CLAUDE_PLUGIN_ROOT}` references.
   - Re-read the target file with `Read` before each edit — sequential edits need current content,
     not an earlier turn's version.
   - Make only the change the plan specifies; do not widen scope or invent extra fixes.
   - Ambiguous or unsafe item → skip it, note why, continue.
   - **Mutation-verify every test-quality fix.** Not applied until proven: disable the covered
     branch, run that test alone, confirm it fails, restore the branch, confirm it passes. A fixture
     still passing under the mutation is vacuous — rework it to defeat the masker (see the masker
     list in `${CLAUDE_PLUGIN_ROOT}/references/python-review.md`), keeping the plan's intent: the
     behavior the test names. A plan fix that cannot be made to fail goes back to the caller as
     unresolved, not applied as-is.
6. Plugin fixes: any edit under `plugins/<name>/` requires the version bump in
   `.claude-plugin/plugin.json` and the matching `.claude-plugin/marketplace.json` entry, plus the
   plugin's `pyproject.toml` when it bundles a Python project. When the plan names a version, apply
   exactly that version. When the plan edits a plugin but names no version, stop and ask the caller;
   never bump on a guess. Skipping a field the plugin carries is not a finished fix.
7. Validate by file class:
   - `*.md` → run `git diff --check`; run `uv run rumdl check <changed .md>` read-only (never
     `--fix`); verify YAML frontmatter and relative links by reading. Never claim a linter ran when
     it did not.
   - `*.sh` and shebang scripts → run `bash -n <path>`; run `shellcheck <path>` when
     `command -v shellcheck` succeeds.
   - `*.py` in a uv project → run `uv run --project <project-dir> pytest`; run the project's
     configured linter read-only. Root scripts have no project tests but the repo-wide
     `[tool.ruff]` applies: `uv run ruff check <file>` read-only; re-read the edited region.
   - Plugin manifests → re-check every version field the plugin carries matches.
8. Staging: edits to files the review scope already staged leave the index stale. When the scope was
   staged, report every file where index and worktree differ (`MM` in `git status --short`) and the
   `git add` command that fixes it. Never stage or commit for the user.
9. Report each plan item as applied or skipped, and state whether the plan ran inline or fanned out.

## Writing Rules

- Legacy scripts keep their existing style and helper abstractions. Do not inline one-off logic or
  restructure a setup script to apply a one-line fix.
- Smallest local change that works; re-read after edits.
- Preserve emphasis keywords, temporal framing, enumerated counts, and identity/consequence
  statements when editing instruction text.
- Preserve the documented CLI shape of setup scripts: flags, env vars, prompts, exit behavior, and
  default side effects are part of the interface.
- Keep setup actions idempotent; a fix must not regress a safe re-run.
- Keep checksum verification in download-and-run flows. Never weaken an integrity check to make a
  fix simpler.
- Never write confidential data to a tracked file, and never paste a flagged value into a report.
- Never edit, move, or delete a path under `$CLAUDE_CONFIG_DIR` (unset → `~/.claude`) — the user's
  machine configuration is not repo content. Report any such plan item as out of scope.
- Never use `rm`; delete with `gio trash` — see `CLAUDE.md` for the `/tmp` exception.
- Never apply a fix that is not in the plan, and never apply without approval. The version bump in
  step 6 is no exception: when the plan omits it, ask the caller instead of applying it.
- Never commit, and never stage unless the plan says to. The user owns the index and the commit.
- Never let two agents edit the same file. Partition by file, not by plan item.
- Never leave a mutation in a source file. Revert it in the same step that introduced it, then
  confirm the revert against a baseline: capture `git diff <path>` before disabling the branch, and
  require byte-identical output after restoring it. `git status --short` does not prove this on its
  own — an unstaged modification shows `M` in the worktree column whether or not the mutation is
  still in place; only a staged file gives a signal, showing `MM` while the mutation is live.
- Do not re-review the changeset — that is `dev-utils:review-changeset`'s job. Mutation-verifying a test fix is
  not a re-review: it checks the fix does what the plan says, nothing else.

## Validation

1. The plan came from a `dev-utils:review-changeset` handoff.
2. User approval was confirmed before any edit.
3. Every applied fix matches a plan item; skipped items are reported with a reason.
4. Every test-quality fix was mutation-verified — it failed with the branch disabled and passed with
   it restored — or reported as unresolved with the reason. Any mutation was fully reverted.
5. Every touched plugin has matching versions in `plugin.json` and `marketplace.json`, and
   `pyproject.toml` too when it bundles a Python project; a plan-specified version was used verbatim,
   and a plugin edit with no plan version was raised with the caller.
6. `bash -n` ran after shell edits; `shellcheck` ran where installed; `git diff --check` ran after
   `*.md` edits; the owning project's tests ran after `*.py` edits.
7. Fan-out decision stated; areas disjoint, at most 3 agents, no file in two briefs; every failed
   area was applied inline and named.
8. Stale index reported when the review scope was staged; nothing staged or committed for the user.
9. The caller receives a fix-by-fix report, including any deviation from the plan (e.g. a fixture
   tightened to make a mutation fail) and why.
10. No file under `$CLAUDE_CONFIG_DIR` (unset → `~/.claude`) was read or edited, except this
    plugin's own `${CLAUDE_PLUGIN_ROOT}` references; any plan item targeting the config dir was
    skipped and reported.

## Output

- Each plan item: applied or skipped (with reason).
- Whether the plan ran inline or fanned out, and the split when it did.
- Files changed, with the validation command run for each.
- For each mutation-verified test fix: the branch disabled, the assertion that failed, and the
  confirmation the branch was restored clean.
- When the review scope was staged: the files where index and worktree differ, and the `git add`
  command that fixes it.
- Any item left unresolved and why.

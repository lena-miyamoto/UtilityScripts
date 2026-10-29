---
name: apply-fixes
description: >
             Apply the fixes from a `dev-utils:review-changeset` fix plan. Invoked by the caller after `dev-utils:review-changeset`
             returns findings that warrant fixes; never invoked directly by the user. Reads the review summary and
             fix plan from the caller's handoff and applies each approved fix.
argument-hint: 'The review summary and fix plan text returned by dev-utils:review-changeset'
user-invocable: false
model: haiku
effort: high
---

# Apply Fixes

Source of truth for the `apply-fixes` skill. Applies fixes from an approved `dev-utils:review-changeset` fix
plan. Not forked and not user-invocable — only the handoff-receiving caller invokes it, after the
user approves the plan.

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
3. Apply each plan item, smallest local change first:
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
4. Plugin fixes: any edit under `plugins/<name>/` requires the version bump in
   `.claude-plugin/plugin.json` and the matching `.claude-plugin/marketplace.json` entry, plus the
   plugin's `pyproject.toml` when it bundles a Python project. Skipping a field the plugin carries is
   not a finished fix.
5. Validate by file class:
   - `*.md` → run `git diff --check`; verify YAML frontmatter and relative links by reading. The
     repo has no Markdown linter — never claim one ran.
   - `*.sh` and shebang scripts → run `bash -n <path>`; run `shellcheck <path>` when
     `command -v shellcheck` succeeds.
   - `*.py` in a uv project → run `uv run --project <project-dir> pytest`; run the project's
     configured linter read-only. Root scripts have no tests or linter — re-read the edited region.
   - Plugin manifests → re-check every version field the plugin carries matches.
6. Report each plan item as applied or skipped.

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
- Never use `rm`; delete with `gio trash` — see `CLAUDE.md` for the `/tmp` exception.
- Never apply a fix that is not in the plan, and never apply without approval.
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
   `pyproject.toml` too when it bundles a Python project.
6. `bash -n` ran after shell edits; `shellcheck` ran where installed; `git diff --check` ran after
   `*.md` edits; the owning project's tests ran after `*.py` edits.
7. The caller receives a fix-by-fix report, including any deviation from the plan (e.g. a fixture
   tightened to make a mutation fail) and why.

## Output

- Each plan item: applied or skipped (with reason).
- Files changed, with the validation command run for each.
- For each mutation-verified test fix: the branch disabled, the assertion that failed, and the
  confirmation the branch was restored clean.
- Any item left unresolved and why.

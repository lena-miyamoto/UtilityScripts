---
name: review-changeset
description: "Audits the staged changeset (falls back to the full unstaged diff when nothing is staged) for correctness and staleness. Focuses on instruction files and their related Python scripts. Detects stale references, checks instruction files against current Anthropic recommendations, flags confidential data and personal info. Emits verdict, findings, a change summary, and a proposed commit subject. Read-only."
disable-model-invocation: false
user-invocable: true
---

# review-changeset

Read-only audit of the current changeset. Report, don't fix (unless asked).

## Determine changeset

1. `git status --short` and `git log --oneline -8` — orient; recent renames/moves matter.
2. `git diff --cached -M --stat`, then full `git diff --cached -M`. Non-empty → this is the changeset.
3. Staged diff empty → fall back to full unstaged: `git diff -M` (tracked) + untracked files via `git ls-files --others --exclude-standard` (Read each). State which fallback happened.

## Classify files

- **Instruction files**: `CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `*.md` docs.
- **Python**: `*.py`.
- **Other**: scripts, configs, templates — review only for stale-reference fallout.

Priority: instruction files + Python. Review "other" for path/symbol renames only.

## Analysis

### 1. Confidential / private data (blocker)
Repo is public. Scan full diff for:
- Secrets: card numbers, IBANs (`AT44…`), API keys, credentials.
- The user's real name (any form) in prose, comments, docs, or config.
- Absolute local paths embedding a username — `/home/<user>/…`, `/Users/<user>/…`, `C:\Users\…`.

Any → `BLOCKED`. Never quote the value or name — report `file:line` + type only. Suggest repo-relative paths or generic wording.

### 2. Stale references (highest priority)
Cross-check every changed file against current repo state. Flag:
- Paths/files renamed, moved, or deleted (use `-M` rename detection) still referenced elsewhere — `Grep` the old names repo-wide.
- Function / class / CLI-flag / env-var / schema-field names referenced but no longer defined.
- Model IDs / model names no longer current.
- URLs / anchors that moved or 404.
- Plugin / agent / skill / directory names that were renamed.

Confirm before flagging: a reference is stale only if its target truly no longer exists — `Grep`/`Read` to verify. Skip references this same changeset already fixes; flag stragglers.

### 3. Instruction files vs Anthropic recommendations
For each instruction/config file, compare against current Anthropic guidance: CLAUDE.md conventions, skill frontmatter + layout, plugin schema, hooks, settings keys, model names. Flag deprecated flags, old schema fields, outdated model names, renamed features. When unsure of "current", ask the `claude-code-guide` agent or WebFetch official docs (docs.claude.com). Never assert "current" without a source.

### 4. Python correctness + cross-check
Root cause over patch: flag bugs, dead code, or logic contradicting the instruction file it serves. Does the script do what its instruction file claims?

### 5. Token efficiency / clarity
Flag verbosity or duplication costing tokens without adding meaning — never at the cost of meaning.

## Output (fixed order)

1. **Verdict** — one line: `PASS` / `CHANGES NEEDED` / `BLOCKED`.
2. **Findings** — grouped by file; each line: severity (`blocker` / `stale-ref` / `rec` / `nit`) + `file:line` + note. No findings → say so.
3. **Changes** — brief bullets, one per change implemented in the changeset.
4. **Proposed commit message** — Conventional Commits subject, ≤80 chars, no body, no description block, no trailer.

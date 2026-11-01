---
name: optimize-repo
description: 'Optimize this repo''s instruction, skill, agent, and plugin files: cut redundancy, restore source-of-truth ownership, keep skills, plugins, and references aligned. Use when cleaning up customization files in this workspace.'
argument-hint: 'Scope to optimize; report-only or apply fixes'
user-invocable: true
disable-model-invocation: true
model: opus
effort: high
context: fork
background: false
---

# Optimize Repo

Source of truth for cleaning up repo customization files after agents produce verbose, duplicated,
or drifted instructions. Report-only mode audits; apply-fixes mode runs the cleanup playbook.

## When to Use

- Clean up or audit instruction files, skills, agent templates, plugin docs.
- Re-verify any repo `*.md` for verbosity, repetition, padded explanation.
- Targets: redundancy, stale routing, drift from the repo structure, source-of-truth violations.
- Restore repo structure when cheaper or less careful models copy long rules into wrong files.

## Current Structure

| Surface                                            | Owner / Shape                                                                                     |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Repo policy, hard rules, plugin rules, setup rules | `CLAUDE.md`; main instruction file — all shared rules live here.                                   |
| Claude entrypoint                                  | `AGENTS.md`; points at `CLAUDE.md`, owns nothing else.                                             |
| Skills                                             | `plugins/<name>/skills/<skill>/SKILL.md`; a repo-level skill may still live in `.claude/skills/<name>/SKILL.md`. Each owns one procedure. |
| Marketplace catalog                                | `.claude-plugin/marketplace.json`; plugin list, sources, versions.                                 |
| Plugins                                            | `plugins/<name>/`; `.claude-plugin/plugin.json`, `skills/`, bundled Python project, `pyproject.toml`. |
| Global agent templates                             | `agent-templates/claude-global/`, `agent-templates/copilot-global/`; machine-install templates.    |
| Human onboarding                                   | `README.md`; install/tooling examples, not policy detail.                                          |
| On-demand references                               | `plugins/<name>/references/`; plugin-shipped rulebooks loaded only when a skill reads them.        |

## Reference Ownership

Skills and docs must point to these owners, not restate their rules.

| Domain                                                      | Owner                                                       |
| ----------------------------------------------------------- | ----------------------------------------------------------- |
| Confidential-data rule, setup-script rules, plugin versioning | `CLAUDE.md`                                                 |
| Marketplace install commands and plugin catalog              | `README.md`                                                 |
| Marketplace manifest                                         | `.claude-plugin/marketplace.json`                           |
| Per-plugin metadata and version                              | `plugins/<name>/.claude-plugin/plugin.json`                 |
| Per-plugin packaging and version                             | `plugins/<name>/pyproject.toml`                             |
| Per-plugin install/use notes                                 | `plugins/<name>/README.md`                                  |
| Global agent instruction template                             | `agent-templates/claude-global/CLAUDE.md`                   |
| Setup script behavior                                        | `ubuntu-setup.sh` and its `--help` output                   |
| Changeset review procedure                                   | `dev-utils` plugin: `skills/review-changeset/SKILL.md`      |
| Fix application procedure                                    | `dev-utils` plugin: `skills/apply-fixes/SKILL.md`           |
| Repo optimization and audit procedure                        | `dev-utils` plugin: `skills/optimize-repo/SKILL.md`         |
| Instruction file compression                                 | `dev-utils` plugin: `skills/compress-instructions/SKILL.md` |
| Context engineering best practices                           | `${CLAUDE_PLUGIN_ROOT}/references/context-engineering-best-practices.md` |
| Python review rulebook                                       | `${CLAUDE_PLUGIN_ROOT}/references/python-review.md`         |
| Model/effort semantics                                       | `${CLAUDE_PLUGIN_ROOT}/references/model-capabilities.md`    |

## Procedure

1. Mode: review-only (report) or cleanup (smallest edits restoring ownership, cutting repetition).
   Plan-only request → do not edit.
2. Respect repo ignore boundaries before any audit or edit:
   - All `.gitignore`-excluded files and folders are out of scope for this skill.
   - Do not read, audit, edit, move, delete, or regenerate ignored paths — including
     `finance-tools/*.csv`, `tmp/`, `*-db/`, `restored/`, `__pycache__/`.
   - Cleanup requiring an ignored path → stop; report it as intentionally excluded.
3. Capture current state before editing:
   - Check `git status --short`.
   - Count relevant instruction lines with
     `wc -l CLAUDE.md AGENTS.md README.md .claude/skills/*/SKILL.md plugins/*/skills/*/SKILL.md plugins/*/README.md`.
   - Flag any instruction file over ~500 lines for splitting (see 500-line rule in audit step 4).
   - Read changed files before patching; assume user/formatter edits intentional unless they break
     the task.
4. Audit against the structure above. **Before evaluating any file, read
   `${CLAUDE_PLUGIN_ROOT}/references/context-engineering-best-practices.md`** — authoritative
   standard for all instruction files; every criterion below derives from it. Violations MUST be
   fixed or explicitly justified in the affected file (with reason). "File was already long" does
   not justify — split it. "Everything together is convenient" does not justify — separate concerns
   into the correct mechanism.
   - `CLAUDE.md` should ideally stay under 80 lines but must never exceed 150 lines, and keeps the
     hard rules first.
   - Confirm `CLAUDE.md` carries the confidential-data rule and the plugin version-bump rule;
     add them if missing.
   - Shared skills should contain input parsing, delegated calls, procedure, validation, and output
     only.
   - Agent templates should be one focused role; evidence and safety rules stay in the shared
     template.
   - Reference docs should each own one domain and should not copy each other's lists.
   - Plugin docs must not restate `CLAUDE.md` policy; they explain install and use. Verify the
     plugin's version fields match: `plugin.json` and `marketplace.json` always, `pyproject.toml`
     when the plugin bundles a Python project.
   - **500-line rule:** Any instruction file over ~500 lines must be split into a slim core file
     (~200–500 lines of always-needed content) plus a `references/` subdirectory of self-contained
     reference files. Each resource file gets minimal YAML frontmatter (`description`) and is read
     on-demand via explicit "Read `<path>` when `<condition>`" instructions in the core file.
     Resource files hold domain knowledge, output templates, bootstrap/setup procedures — anything
     not needed every invocation. When compressing prose to fit the core file limit, never drop
     emphasis markers, obligation keywords (must/never/CRITICAL/YOU MUST), temporal framing,
     enumerated item counts, identity claims, or consequence statements. Compression must be
     lossless per `compress-instructions`. If compression would weaken any of these, keep the
     original text and split to a reference file instead.
   - `README.md` should explain onboarding and use tables for command examples; never become a
     second policy surface.
5. Repair messy instructions in this order:
   - Restore source-of-truth ownership first; move or delete restated policy before wordsmithing.
   - Replace copied rules with short pointers such as `Follow .claude/skills/<name>/SKILL.md.` or
     `Follow CLAUDE.md.`
   - Delete padded explanation when a command, table row, or owner-doc pointer carries the meaning.
   - Convert command lists to tables when agents need to scan operation → command quickly.
   - Keep `CLAUDE.md` and README command examples synchronized in spirit; do not duplicate every
     policy note.
   - **Split oversized files (>~500 lines):** Identify self-contained sections not needed every
     invocation (domain knowledge, output templates, bootstrap/setup procedures). Extract each to a
     resource file in a `references/` subdirectory with YAML frontmatter (`description`). Replace
     with an explicit "Read `<path>` when `<condition>`" instruction. Keep core identity, safety
     rules, writing rules, and always-needed procedures inline.
     - Never compress resource files extracted to `references/` — already self-contained and
       on-demand; compression risks content loss with no line-budget benefit.
6. Keep discovery-critical frontmatter concise:
   - Skill descriptions should identify when to invoke the skill, not explain policy.
   - Argument hints should show input shape only.
   - If a skill needs policy text to be correct, the reference owner is probably missing a pointer.
7. Re-check after edits:
   - Names, descriptions, and argument hints aligned across `.claude/`, `plugins/`, and
     `agent-templates/` surfaces.
   - Repo docs advertise only surfaces worth exposing.
   - Every touched plugin has every version field it carries bumped and matching.
8. **Compress every edited instruction file last.** After all other edits and re-checks, stop and
   instruct the user to run `/dev-utils:compress-instructions` on every edited `*.md` instruction
   file in this run — mandatory, never optional. `disable-model-invocation: true` makes the skill
   user-only: do not call it, and do not reproduce its procedure. List the exact files to pass.
   Exclude plugin manifests (`plugin.json`, `marketplace.json`), `*.sh`, `*.py`, and any file under
   `references/`. Also exclude the skill's default-skipped files (`README.md`, `CONTRIBUTING.md`,
   `DEVELOPMENT.md`, `CHANGELOG.md`). Never compress `references/` resource files (self-contained,
   on-demand — no line-budget benefit, compression risks loss). After the user reports back, verify
   lossless per the `compress-instructions` self-check. The user-level `compress-instructions` skill
   duplicates this plugin copy — the user should retire it; the plugin copy is canonical.

## Redundancy Patterns

After cleanup, grep for these patterns in all repo `*.md` files (excluding this audit list). Use
`rg --hidden -g '*.md'` — `rg` skips dotfolders without `--hidden`. Remaining matches must only
appear in the listed owner files.

`confidential`, `card numbers`, `IBAN`, `API key`, `credentials`
→ `CLAUDE.md` only (confidential-data rule). The `dev-utils` review skill and its
`references/python-review.md` naming the check are pointers, not restatements — acceptable.

`plugin.json`, `marketplace.json`, `pyproject.toml` version-bump wording
→ `CLAUDE.md` only. Plugin READMEs may state their own version but must not restate the bump rule. A
`dev-utils` skill that performs the bump may name the files — acceptable.

`--basic-setup`, `--lenas-setup`, `--install-godot`, `--reconfigure-git`
→ `README.md` (user-facing quick start) and `ubuntu-setup.sh` (`--help`) only.

`gio trash`, `shellcheck`, `bash -n`, `kebab-case`, `German orthography`/umlauts
→ `CLAUDE.md` only (repo rules). A `dev-utils` skill naming the command it invokes (`bash -n`,
`shellcheck`, `gio trash`) is a tool reference, not a restatement — acceptable.

`claude plugin marketplace add`, `claude plugin install`
→ `README.md` only; a plugin README may repeat its own install line (legitimate, not a
restatement).

`context-engineering best practices`, `500-line rule`
→ `plugins/dev-utils/references/context-engineering-best-practices.md` and
`plugins/dev-utils/skills/optimize-repo/SKILL.md` only.

`.venv`, `__pycache__`, `*-db/`, `restored/`
→ `.gitignore` and out-of-scope notes only.

## Preferred Shapes

- Use tables for command matrices, routing maps, source-of-truth maps, source priority, and
  platform/mirror status.
- Use bullets for short behavior rules and validation checks.
- Do not nest bullets deeper than one level unless the existing file already requires it for
  readability.
- Avoid long prose in entrypoints; `CLAUDE.md` is the main instruction file and may be longer.
- Preserve non-ASCII already used for German terms, arrows, and source names; do not add decorative
  symbols.

## Writing Rules

- **Context engineering best practices are mandatory.** Read and follow
  `${CLAUDE_PLUGIN_ROOT}/references/context-engineering-best-practices.md` when writing or editing
  any instruction file. Deviations require explicit justification in the affected file.
- Match the repo's direct procedural tone.
- Never sacrifice meaning or expressiveness for shorter prose. Meaning includes: emphasis keywords
  and formatting, temporal framing, enumerated element count and order, identity-level claims, and
  consequence statements. If compression would drop or weaken any of these, prefer extraction to a
  reference file over inline shortening.
- Strict source-of-truth ownership.
- Anything excluded by `.gitignore` is out of scope and must remain untouched.
- Preserve keyword-rich frontmatter for discovery.
- Prefer brevity and clarity over grammatical smoothness in every repo `*.md`.
- Drop repetitive phrasing and padding when the meaning carries tighter.
- **Compress `CLAUDE.md` aggressively — less is more.** Cut every line not needed for correctness,
  safety, or discovery. Instruction-following degrades as instruction files grow, so keep it lean
  and offload detail to on-demand `references/` files via pointers.
- **Write NEVER/ALWAYS, not "prefer".** Hard guardrails survive; vague goals are ignored. State the
  constraint ("ALWAYS run the tests"), not the aspiration ("prefer composition where it makes sense").
- **List exact verify commands.** Name build/test/lint commands verbatim so no model has to infer the
  verification loop.
- Don't replace duplication with a new documentation layer.
- Never write confidential data into a tracked file or a report.

## Validation

1. **Confirm `${CLAUDE_PLUGIN_ROOT}/references/context-engineering-best-practices.md` was read**
   before any instruction file was evaluated. The audit is incomplete without it.
2. Run frontmatter YAML and Markdown link review on every changed file. The repo has no Markdown
   linter — verify YAML frontmatter validity and relative link integrity by reading. Never claim a
   linter ran.
3. Run `git diff --check`.
4. Confirm no file or folder excluded by `.gitignore` was touched.
5. Re-run the redundancy-pattern grep and account for every remaining match.
6. Re-read changed `*.md` for: padding; repeated phrases; stale owner references; accidental second
   sources of truth; and **lossy compression** — dropped emphasis keywords (CRITICAL, MUST, NEVER,
   ALWAYS, IMPORTANT, ESSENTIAL), stripped bold/italic formatting, lost temporal framing
   (before/after, sequencing), altered enumerated element counts or order, weakened identity-level
   claims, or removed consequence statements. Confirm the user ran `/dev-utils:compress-instructions`
   as the final step on every optimized file step 8 covers; a file step 8 excludes is legitimately
   skipped, not a failure. After the user reports back, confirm the run was lossless per the
   `compress-instructions` self-check.
7. Confirm `CLAUDE.md` is compact and the hard rules remain clear.
8. Confirm every touched plugin has matching `plugin.json` and `marketplace.json` versions, and
   `pyproject.toml` too when it bundles a Python project.
9. **Log every best-practice deviation** with the affected file and the explicit justification
   provided. If no justification was provided, the deviation is an unresolved finding.
10. After completing edits, re-read each changed file and verify no regressions against the audit
    criteria above.

## Output

- Files optimized.
- Files handed off for compression via `/dev-utils:compress-instructions` (final step).
- Files audited, unchanged.
- Validation performed.
- Remaining inconsistencies left intentionally, with reason.

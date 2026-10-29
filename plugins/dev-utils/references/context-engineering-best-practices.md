---
description: Anthropic's latest context engineering best practices for Claude Code instruction files — CLAUDE.md, skills, rules, subagents, hooks, and output styles. Authoritative standard for this repo. Apply during optimize-repo audits.
---

# Context Engineering Best Practices for Claude Code

**THIS FILE IS AUTHORITATIVE.** These practices apply to every instruction file in this repo — CLAUDE.md, skills, agents, rules, and any other file loaded into Claude's context. Every optimize-repo audit must read this file and enforce it. Every agent writing or editing instruction files must follow these rules.

**Deviations require explicit justification.** If a best practice cannot be followed in a specific case, the deviation must be documented in the affected file with the reason. "The file was already long" is not a justification — split it. "It's convenient to keep everything together" is not a justification — separate concerns into the correct mechanism.

Summarized 2026-07-21 from Anthropic's official documentation.

Sources: [Best Practices for Claude Code](https://code.claude.com/docs/en/best-practices), [Steering Claude Code](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more), [CLAUDE.md guide](https://code.claude.com/docs/en/claudemd), [Extend Claude Code](https://code.claude.com/docs/en/features-overview).

## The Core Constraint: Context Window

Frontier models reliably follow ~150–200 instructions total. Claude Code's system prompt already contains ~50 built-in instructions. This leaves **~100–150 slots** for your content.

Longer files cause **uniform degradation** — Claude doesn't selectively ignore bad rules; it ignores everything less reliably. Every line costs tokens whether relevant or not.

## The Seven Instruction Methods

| Method                                       | Loads                                        | Context Cost                         | Best For                                       |
| -------------------------------------------- | -------------------------------------------- | ------------------------------------ | ---------------------------------------------- |
| **CLAUDE.md**                                | Session start                                | High (always in context)             | Build commands, code style, team conventions   |
| **Rules** (`.claude/rules/`)                 | Session start or on file match               | Low–Medium (path-scoped = efficient) | Cross-cutting directory/file constraints       |
| **Skills** (`.claude/skills/`)               | Name/desc at start; body on invocation       | Low (body loads on demand)           | Procedures, domain knowledge, workflows        |
| **Subagents** (`.claude/agents/`)            | Name/desc at start; body in isolated context | Near-zero (only summary returns)     | Noisy side tasks, deep search, verification    |
| **Hooks** (`settings.json`)                  | Lifecycle events                             | Zero (runs externally)               | Deterministic enforcement, linting, guardrails |
| **Output Styles** (`.claude/output-styles/`) | Every session, never compacted               | Highest instruction weight           | Major role changes (use built-in styles first) |
| **Append System Prompt** (CLI flag)          | Invocation only                              | Moderate (cached)                    | Per-run tone/formatting tweaks                 |

## CLAUDE.md: Size and Content Rules

### Size Limits

- **Official:** Keep under 200 lines
- **This repo's standard:** Under 80 lines ideal, 150 lines hard max
- **Acid test:** "Would removing this line cause Claude to make a mistake?" If no, cut it.

### What to Include

- Build/test/lint commands Claude can't guess
- Code style rules that differ from language defaults
- Testing conventions and preferred test runners
- Repository etiquette (branch naming, PR conventions)
- Architectural decisions specific to the project
- Developer environment quirks (required env vars)
- Common gotchas or non-obvious behaviors

### What to Exclude

- Anything Claude can infer by reading code
- Standard language conventions Claude already knows
- Detailed API documentation (link to docs instead)
- Information that changes frequently
- Long explanations, tutorials, or file-by-file descriptions
- Self-evident practices like "write clean code"

### Emphasis Keywords (use sparingly)

- `IMPORTANT:` — for rules that must not be skipped
- `YOU MUST` — for non-negotiable constraints
- `NEVER` — for hard prohibitions (always pair with what to do instead)

### CLAUDE.md as a Router

Treat CLAUDE.md as a project constitution — short directives + pointers — not a novel:

```markdown
# Project Constitution
## Core directives
1. Architecture first: create/update decisions before implementation
2. Isolated implementation: code changes happen in forked subagents
3. Mandatory verification: nothing is DONE until tests pass

## Routing
- Current work plan: `.claude/plans/active-plan.md`
- Decision log: `.claude/memory/decisions.md`
```

### Hierarchy (merged, not overridden)

1. **Managed** (org-wide, admin-deployed, cannot be overridden)
2. **User** (`~/.claude/CLAUDE.md`) — all projects on the machine
3. **Project** (`./CLAUDE.md`) — committed to git, shared team conventions
4. **Local** (`./CLAUDE.local.md`) — gitignored, personal per-repo overrides
5. **Subdirectory** (`./subdir/CLAUDE.md`) — loads on demand when files in that directory are touched

### Imports

Use `@path/to/import` to pull in external files. Imports chain up to 4 hops deep.

## Rules: Path-Scoping Is Everything

- **Always scope** rules that apply to specific directories. Unscoped rules cost tokens during every session regardless of what you're working on.
- Path-scoped rules load when Claude uses Read, Write, or Edit on a matching file.
- Once loaded, rules **never scope out** — they stay for the rest of the session.
- Use `paths:` in YAML frontmatter, not `globs:` (the latter loads unconditionally).

```yaml
---
paths:
  - "src/api/**/*.ts"
  - "**/*.handler.ts"
---
All API handlers must validate input with Zod before processing.
```

## Skills: Deferred Loading Advantage

- Only name + `description` load at session start. Full body loads on invocation.
- A skill arrives fresh and contextually relevant at the moment of action — unlike CLAUDE.md loaded thousands of tokens ago.
- Procedural instructions (deploy workflows, release checklists, review processes) belong in skills, not CLAUDE.md.
- A 30-line procedure in CLAUDE.md is a sign it should be a skill instead.
- `disable-model-invocation: true` prevents auto-trigger for side-effect workflows.
- Invoked skills are re-injected on compaction, capped at 5,000 tokens per skill / 25,000 total shared budget.

## Subagents: Isolation Is the Point

- Run in isolated context windows — body never enters parent conversation.
- Only the final message + metadata returns. Ideal for noisy, high-token tasks.
- Use when a side task would clutter the main conversation with intermediate results you won't reference again.
- Use a skill instead when you want to see and steer each step in the main thread.
- Can nest up to five levels deep.

## Hooks: Deterministic, Not Advisory

- "Never do this" instructions in CLAUDE.md are insufficient — Claude can fail under pressure, in long sessions, or due to prompt injection.
- Real guardrails require deterministic enforcement through hooks.
- A `PreToolUse` hook can inspect any tool call and exit code 2 to deny it.
- Admin-deployed managed settings cannot be overridden by local config.

## Context Management Discipline

- **`/clear` between unrelated tasks.** A clean session with a better prompt outperforms a long session with accumulated corrections.
- **After two failed corrections**, `/clear` and write a better initial prompt incorporating what you learned.
- **Subagents for exploration.** When investigating code, use subagents so file reads don't consume main context.
- **`/compact` behavior:** Project-root CLAUDE.md and unscoped rules are re-injected from disk. Path-scoped rules and nested CLAUDE.md are lost until matching files are read again.
- **Progressive disclosure:** Point to reference files instead of embedding them. Claude pulls them only when needed.

## The Self-Improvement Loop

After every correction, codify the fix into the right instruction file. Ruthlessly edit over time until the mistake rate measurably drops. Treat instruction files like code: review when things go wrong, prune regularly, test changes by observing whether behavior shifts.

## Decision Framework

| Trigger                           | Where It Belongs                             |
| --------------------------------- | -------------------------------------------- |
| "Every time X, always do Y"       | Hook (deterministic, not model-chosen)       |
| "Never do this"                   | Hook + permissions/managed settings          |
| Long procedural workflow          | Skill (body loads only when invoked)         |
| API/directory-specific constraint | Path-scoped rule                             |
| Personal preference               | User-level local file, not project CLAUDE.md |
| Side task with intermediate noise | Subagent                                     |
| Tone/formatting preference        | `append-system-prompt` CLI flag              |
| Major role change                 | Output style (keep built-in defaults)        |

## The Three-Layer Separation

Keep these three concerns in separate mechanisms — do **not** combine them into one file:

| Concern                        | Where It Lives                        |
| ------------------------------ | ------------------------------------- |
| "What we use / what we prefer" | CLAUDE.md                             |
| "Always do X, block Y"         | Hooks and `settings.json` permissions |
| "How to do Z" (procedures)     | Skills                                |

## Verification: Close the Loop

- Give Claude a check it can run: tests, build, linter, screenshot comparison.
- Without a check, "looks done" is the only signal, and you become the verification loop.
- **Explore first, then plan, then code.** Separate research from implementation.
- Add an adversarial review step: have a subagent review the diff in a fresh context.

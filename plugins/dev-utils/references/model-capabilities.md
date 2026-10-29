---
description: Model aliases, per-model strengths, and effort semantics for skill and agent `model` and `effort` frontmatter. Read before judging either field in a skill or agent file.
---

# Model Aliases, Capabilities, and Effort

Source of truth for the `model` and `effort` frontmatter fields in skills and agents reviewed or
edited by this plugin.

The harness reads `model` / `effort` at runtime; an alias resolves against the **service the
session is pointed at**, not the alias name. An Anthropic-pointed session resolves `haiku` /
`sonnet` to the Claude models of those names; a DeepSeek Anthropic-compatible endpoint resolves
them to DeepSeek models. Never assume an alias means the Claude model of its name — check the
session's wiring.

This file is written against the maintainer's default DeepSeek wiring, not bound to it: Anthropic
models are fully supported. Rules that hold only under DeepSeek wiring are labeled, never
asserting every session runs on DeepSeek. Records alias pins, each resolved model's strengths, and
which `(model, effort)` pair fits which task.

## Hard Rules

1. **Aliases are service-relative.** `model: haiku` resolves to whatever
   `ANTHROPIC_DEFAULT_HAIKU_MODEL` points at. Under the default DeepSeek wiring that is
   `deepseek-flash`; under Anthropic wiring it is `claude-haiku-5-5`. Never judge a `model` value
   by the Claude model of the same alias name — resolve it against the session's service.
2. **`effort` levels collapse on DeepSeek.** The Claude Code scale is `low` / `medium` / `high` /
   `xhigh` / `max`, but the DeepSeek endpoint maps `medium`, `high`, and `xhigh` all to the same
   `high` level. Only `low` and `max` change behavior there. Do not treat `xhigh` as "more than
   `high`" unless the service is Anthropic.
3. **Effort is calibrated per model.** The same level name is not the same reasoning budget across
   models. A change that is right on one service may be a no-op or an overthink on the other.
4. **Available tiers depend on the service.** Under the DeepSeek wiring `haiku` and `sonnet` both
   resolve to `deepseek-flash`, while `opus` and `fable` both resolve to `deepseek-v4-pro` — the only
   route to the reasoning tier there. Under Anthropic wiring every alias resolves separately. On
   either service use `haiku` for cheap/mechanical work and a reasoning tier for reasoning-heavy
   work; under the DeepSeek wiring that tier is reached through `opus` or `fable`.
5. **`inherit` means the session model** and is documented for skill frontmatter only — it is not a `/model` alias. Skills that should follow the caller's model use `model: inherit`; do not assume agents accept it.

## Alias Resolution

| Alias     | Anthropic service   | DeepSeek wiring (default)              | Pinned by                        |
| --------- | ------------------- | -------------------------------------- | -------------------------------- |
| `haiku`   | `claude-haiku-5-5`  | `deepseek-flash` (DeepSeek-V4.1-Flash) | `ANTHROPIC_DEFAULT_HAIKU_MODEL`  |
| `sonnet`  | `claude-sonnet-5-5` | `deepseek-flash` (same as `haiku`)     | `ANTHROPIC_DEFAULT_SONNET_MODEL` |
| `opus`    | `claude-opus-5-5`   | `deepseek-v4-pro` (DeepSeek V4 Pro)    | `ANTHROPIC_DEFAULT_OPUS_MODEL`   |
| `fable`   | `claude-fable-5-1`  | `deepseek-v4-pro` (same as `opus`)     | `ANTHROPIC_DEFAULT_FABLE_MODEL`  |
| `inherit` | session model       | session model                          | —                                |
| full ID   | pinned snapshot     | pinned snapshot                        | —                                |

**Default session wiring** — machine-level, in `~/.claude/settings.json`. This is how the
maintainer's sessions are configured, not a repo guarantee; a session pointed elsewhere resolves the
aliases differently:

- `ANTHROPIC_BASE_URL = https://api.deepseek.com/anthropic` — the DeepSeek endpoint.
- `ANTHROPIC_DEFAULT_MODEL = sonnet` — new sessions start on `sonnet`.

Everything labeled "DeepSeek wiring" below describes this default setup. On a session pointed at
Anthropic, use the Anthropic column instead.

Notes on the other aliases: `default` clears an override and reverts to the account default;
`best` resolves to `fable` where available, else `opus`; `opusplan` runs `opus` in Plan Mode and
`sonnet` otherwise. A full ID such as `claude-sonnet-5-5` or `deepseek-v4-pro` pins an exact
snapshot and bypasses the alias pins above.

**The pins (DeepSeek wiring only):** this follows DeepSeek's own Claude Code recommendation — both
`claude-haiku` and `claude-sonnet` map to `deepseek-flash`, and `claude-opus` maps to
`deepseek-v4-pro` — with `claude-fable` also mapped to `deepseek-v4-pro`. So under this wiring
`sonnet` is not a step up from `haiku`, and `opus` is not a no-op: the reasoning tier is reached
only through `opus` or `fable`. None of this applies to an Anthropic session, and a session pointed
elsewhere may map the aliases differently.

## Model Profiles

Profiles are listed per model, not per alias. Each heading names the alias that resolves to that
model under the DeepSeek wiring.

### DeepSeek-V4.1-Flash (`deepseek-flash`, aliases `haiku` and `sonnet`)

- ~552B-parameter MoE with ~8B active at prefill and ~16B at decode plus a ~196B conditional
  "Engram" memory; natively multimodal (text + image in); MIT-licensed.
- 1M-token context, up to ~384K output. Cheap and fast.
- Strong for its class on agentic/coding tasks (Terminal-Bench 2.1 ≈ 90.6, DeepSWE v1.1 ≈ 74.2).
- **Weakness:** at `max` effort it is prone to long, low-density reasoning and can keep re-arguing
  settled points rather than converging.
- **Use for:** high-volume mechanical work — extraction, text conversion, transcription, archive
  queries, and parallel subagent fan-out where per-item cost and latency dominate.

### DeepSeek V4 Pro (`deepseek-v4-pro`, aliases `opus` and `fable`)

- Large MoE (~49B active parameters; the HF card lists ~1.7T total). 1M-token context, up to ~384K
  output. Text-first (image input reported for the GA release). Strongest DeepSeek tier.
- Large gains over the Flash tier on agentic/coding and hard reasoning (Terminal-Bench 2.1 ≈ 87.9,
  DeepSWE ≈ 62.7, HLE ≈ 60.0 with tools).
- **Weakness:** verbose; `max` effort over-reasons and can balloon token spend for marginal gain.
- **Use for:** long-horizon agentic work, multi-source synthesis, hard reasoning, anything where a
  wrong answer costs more than the extra tokens.

### Claude Haiku 5.5 (`claude-haiku-5-5`, Anthropic-side `haiku`)

- Anthropic's fastest/cheapest model; 1M-token context, 128K output; $0.10/$0.50 per MTok for
  prompts up to 100K tokens, $0.50/$2.50 above that. Default effort `medium`.
- Best for narrow, high-volume, checkable work: classification, extraction, routing, summarisation,
  per-turn subagent work.

### Claude Sonnet 5.5 (`claude-sonnet-5-5`, Anthropic-side `sonnet`)

- Anthropic's "best combination of speed and intelligence"; 1M-token context, 128K output; $2/$10
  per MTok. Default effort `high`.
- Best for long-horizon agentic work, computer use, code that must compile, and other unverifiable
  tasks where a wrong answer costs more than the call.

Opus 5.5 (`claude-opus-5-5`, $4/$20) and Fable 5.1 (`claude-fable-5-1`, $10/$50) sit above Sonnet on
the Anthropic side. On Anthropic wiring the `opus` and `fable` aliases reach these models; under the
DeepSeek wiring both resolve to `deepseek-v4-pro` (the same model as each other), so neither reaches
its Claude namesake.

## Effort Semantics

Claude Code accepts `low`, `medium`, `high`, `xhigh`, and `max`. On the Anthropic models every level
is distinct. On the DeepSeek endpoint the scale collapses:

| Claude Code `effort` | DeepSeek `reasoning_effort` |
| -------------------- | --------------------------- |
| `low`                | `low`                       |
| `medium`             | `high`                      |
| `high`               | `high`                      |
| `xhigh`              | `high`                      |
| `max`                | `max`                       |

Consequences under the DeepSeek wiring:

- `medium`, `high`, and `xhigh` are **the same request** on DeepSeek. Picking `xhigh` over `high`
  changes nothing, and picking `medium` over `high` does not lower cost — it is still `high`.
- Only `low` and `max` are meaningfully different from `high`.
- DeepSeek's default is `high`, so omitting `effort` is equivalent to `medium`/`high`/`xhigh`.
- `max` is the only level above `high`. Use it for genuinely hard problems and expect overthinking on
  Flash; prefer `high` unless a task demonstrably needs `max`.

General effort guidance (holds on both services):

- `low` — mechanical, checkable steps: renames, formatting, extraction, yes/no checks.
- `high` — normal agentic work where verification matters: multi-step procedures, fixes, reviews.
- `max` — hard problems worked through autonomously (deep analysis, security-style audits). Test
  before adopting broadly; diminishing returns and overthinking are real.

Precedence: `CLAUDE_CODE_EFFORT_LEVEL` and `--effort` override a file's `effort` frontmatter, and a
skill's frontmatter overrides the session level but **not** the environment variable.

## Selection Guide

Pick the cheapest tier that reliably does the task at `high` effort; reserve `max` and the reasoning
tier for work that fails at the cheaper setting. The aliases below resolve on either service, but the
tier ordering does **not** hold on both: under the DeepSeek wiring `haiku` and `sonnet` are the same
model, so only `opus` or `fable` reaches the reasoning tier there. The rows name the alias that
reaches the intended tier under DeepSeek wiring.

| Task class                                                                         | Model   | Effort         | Rationale                                                                |
| ---------------------------------------------------------------------------------- | ------- | -------------- | ------------------------------------------------------------------------ |
| Extraction, conversion, formatting, mechanical edits                               | `haiku` | `low` / `high` | Mechanical and checkable; `low` for clean input, `high` for messy parsing |
| Fix application, multi-step bounded procedures, summaries                          | `haiku` | `high`         | Multi-step but bounded; verification catches slips                       |
| Synthesis, repo optimization, review, anything reasoning-heavy                      | `opus`  | `high`         | Weak answers are costly to detect                                        |
| Hardest long-horizon reasoning or adversarial analysis                             | `opus`  | `max`          | Only when `high` demonstrably falls short                                |

Under the DeepSeek wiring reach the reasoning tier through `opus` or `fable`; `sonnet` adds nothing
over `haiku` there, and `fable` adds nothing over `opus`. Do not rely on `xhigh` or `medium` to
differentiate from `high`; on Anthropic those levels are distinct. Skills that should follow whatever
model the caller uses keep `model: inherit` (skill frontmatter only).

## Sources

- DeepSeek — Integrate with Claude Code: <https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/>
- DeepSeek — Thinking Mode (effort mapping): <https://api-docs.deepseek.com/guides/thinking_mode/>
- DeepSeek-V4.1-Flash model card: <https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash>
- DeepSeek-V4-Pro-0813 model card: <https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813>
- Anthropic — Models overview: <https://platform.claude.com/docs/en/models/overview>
- Claude Code — Model configuration (aliases, effort levels, precedence): <https://code.claude.com/docs/en/model-config>

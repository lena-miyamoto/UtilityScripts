# statusline (Claude Code)

Custom Claude Code statusline. Claude Code pipes status JSON on stdin and
reads the rendered statusline text from stdout. Stdlib only — no runtime
dependencies.

Layout, left to right:

```text
<model> [<agent>] ⚡<effort> 🧠  [<ctx bar>] <used%>  <in>/<size>  ♻️ <cache>  ⑂ <worktree>  ⎇ <branch>  [<vim mode>]  ⏰ <rate%>  💳 <monthly cost>
```

- `model` — display name of the active model, `unknown` if missing
- `[agent]` — sub-agent name, shown only inside a sub-agent
- `⚡effort` — reasoning effort level, shown only if set
- `🧠` — thinking mode is enabled
- `[bar]` — 16-char context-window usage bar, green→blue→yellow→orange→red as
  used % climbs (red forced when `exceeds_200k_tokens`)
- `used%` — context window used, same color as the bar
- `in/size` — raw input tokens / context-window size, humanized (k/M)
- `♻️ cache` — cache-read input tokens this turn, shown only if > 0
- `⑂ worktree` — git worktree name, shown only inside a worktree
- `⎇ branch` — current git branch, omitted when not in a git repo
- `[mode]` — vim mode, shown only if vim mode is active
- `⏰ rate%` — 5-hour rate-limit usage (≥70%); `⏱` 1-minute burst limit (≥90%)
- `💳 cost` — session spend | month-to-date (Anthropic) or all-time (DeepSeek)
  spend; Anthropic models also show `/ budget · % left`; DeepSeek appends
  `⇧$ceil` (worst case if the session fills the context window)

## Cost computation

Monthly (Anthropic) or all-time (DeepSeek) spend is computed by scanning
`<CLAUDE_CONFIG_DIR>/projects/**/*.jsonl`, cached for 2 min in
the system temp dir (`/tmp` on Linux): `monthly-cost.json` / `all-time-cost.json`. Per-model
rates live in `model_rates()` — see
<https://platform.claude.com/docs/en/about-claude/pricing> and
<https://api-docs.deepseek.com/quick_start/pricing>. DeepSeek rates are
time-of-day dependent: peak (01:00–04:00 and 06:00–10:00 UTC, Mon–Fri) is
double the off-peak rate, selected from each line's timestamp.

DeepSeek models recompute the current session's spend from its own JSONL log
instead of trusting the harness's `data.cost.total_cost_usd`, which falls back
to Anthropic pricing for unrecognized models (~7× overestimate).

`CLAUDE_MONTHLY_BUDGET` (default 200) sets the budget ceiling for Anthropic
models; `CLAUDE_CONFIG_DIR` overrides config location.

## Subagent statusline

> **Claude Code 2.1.322 or older only.** 2.1.323 removed `subagentStatusLine`:
> the key loads without error but has no effect, and subagent rows always use
> the built-in look. See [Pinning Claude Code](#pinning-claude-code).

`subagent-statusline` renders the per-row body for the subagent panel
(`subagentStatusLine`). It receives one JSON object on stdin — the base hook
fields plus `columns` and a `tasks` array — and writes one JSON line per row:

```json
{"id": "<task id>", "content": "<row body>"}
```

Row body, in order:

```text
<status> <name> [<agentType>] · <description> · <label>  [<bar>] <pct> <tokens>/<size> <spark> <age>  <model> ⚡<effort>  <cwd>
```

All 2.1.322 task fields, plus top-level `columns`, are consumed:

| Field                 | Use                                                                                                   |
| --------------------- | ----------------------------------------------------------------------------------------------------- |
| `id`                  | Output key; skipped when absent                                                                       |
| `name`                | Row label; falls back to `agentType`, `type`, `id`, then `?`                                          |
| `agentType`           | Bracketed badge when it differs from the row label (e.g. `[Explore]`)                                 |
| `type`                | Bracketed badge for non-`local_agent` types; suppressed when it equals `name` or `agentType`          |
| `status`              | Colored glyph: `▶` running; `✓ completed`, `✗ failed`, `⊘ killed` show the glyph plus the status word |
| `description`         | Work requested by the caller                                                                          |
| `label`               | Live progress summary, appended after `description` when it differs                                   |
| `startTime`           | Age, e.g. `12s`, `1m05s`, `2h03m`                                                                     |
| `model`               | Model id, before the cwd suffix                                                                       |
| `effort`              | `⚡<level>` after the model                                                                           |
| `tokenCount`          | Tokens used; `80k tok` when no context size is known                                                  |
| `contextWindowSize`   | 8-char context bar with percentage and `used/size`                                                    |
| `tokenSamples`        | Sparkline of the last 8 samples (`▁`→`█`)                                                             |
| `cwd`                 | Basename, only when it differs from the session's `cwd`                                               |
| `columns` (top level) | Hard row width; ANSI-aware truncation with `…`                                                        |

`columns` is measured in terminal columns, so wide (CJK/emoji) characters count
as two. ANSI color sequences are preserved when a row is truncated.

## Pinning Claude Code

These steps target the native and npm installs; Homebrew, WinGet, and other
package-manager installs do not auto-update in the background.

The native installer updates in the background and would move you onto 2.1.323+.
To stay on 2.1.322:

1. Install it explicitly: `claude install 2.1.322`
2. Disable background updates in the **global** `settings.json`
   (`$CLAUDE_CONFIG_DIR`, default `~/.claude`):

```json
{
  "env": {
    "DISABLE_AUTOUPDATER": "1"
  }
}
```

3. Confirm with `claude doctor`: the `Auto-updates` line must read
   `disabled (set by env: DISABLE_AUTOUPDATER)`.

`DISABLE_AUTOUPDATER` stops background updates only; `claude update` still
works. To block every update path, use `DISABLE_UPDATES` instead — but set it
*after* installing 2.1.322, because it also blocks `claude install`.

## File layout

- `statusline.py` — the main bar: parse stdin JSON, render bar/model/git/vim/rate,
  compute cost.
- `subagent-statusline.py` — the subagent panel rows; loaded via
  `shared.load_subagent()` (hyphenated names aren't `import`able).
- `shared.py` — shared helpers, per-model pricing (incl. DeepSeek peak/off-peak),
  cost computation, and the subagent loader.
- `install-statusline.py` — stdlib-only installer: provisions the venv and wires
  `statusLine` + `subagentStatusLine` into the global `settings.json`
  (`$CLAUDE_CONFIG_DIR`, default `~/.claude`).
- `test-statusline.py`, `test-subagent-statusline.py` — pytest suites importing
  the real modules.
- `pyproject.toml` — uv project; no runtime deps, `pytest` dev dependency;
  exposes the `statusline` and `subagent-statusline` console scripts.
- `uv.lock` — committed lockfile.
- `.python-version` — `3.13`.

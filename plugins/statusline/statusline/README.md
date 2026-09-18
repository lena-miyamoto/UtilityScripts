# statusline (Claude Code)

Custom Claude Code statusline. Claude Code pipes status JSON on stdin and
reads the rendered statusline text from stdout. Stdlib only — no runtime
dependencies.

Layout, left to right:

```
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
`<CLAUDE_CODE_TMPDIR>/monthly-cost.json` / `all-time-cost.json`. Per-model
rates live in `model_rates()` — see
<https://platform.claude.com/docs/en/about-claude/pricing> and
<https://api-docs.deepseek.com/quick_start/pricing>. DeepSeek rates are
time-of-day dependent: peak (01:00–04:00 and 06:00–10:00 UTC, Mon–Fri) is
double the off-peak rate, selected from each line's timestamp.

DeepSeek models recompute the current session's spend from its own JSONL log
instead of trusting the harness's `data.cost.total_cost_usd`, which falls back
to Anthropic pricing for unrecognized models (~7× overestimate).

`CLAUDE_MONTHLY_BUDGET` (default 200) sets the budget ceiling for Anthropic
models; `CLAUDE_CONFIG_DIR` and `CLAUDE_CODE_TMPDIR` override the cache/config
locations.

## Subagent statusline

`subagent-statusline` renders the per-row body for the subagent panel
(`subagentStatusLine`). It receives one JSON object on stdin — the base hook
fields plus `columns` and a `tasks` array — and writes one JSON line per row:

```json
{"id": "<task id>", "content": "<row body>"}
```

Each task has `id`, `name`, `type`, `status`, `description`, `label`,
`startTime`, `model`, `effort`, `contextWindowSize`, `tokenCount`,
`tokenSamples`, and `cwd`. The row shows `name · description`, a compact 8-char
context bar with `tokenCount/contextWindowSize` (when the model's context window
is resolved), the model id, and `⚡effort`. Tasks without an `id` are skipped.

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

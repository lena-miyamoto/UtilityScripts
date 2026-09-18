# statusline (plugin)

Custom Claude Code statusline, packaged as a marketplace plugin. Two scripts,
both stdlib-only Python run through `uv`:

- `statusline` — the main bottom bar (model, context bar, git branch/worktree,
  vim mode, rate limits, cost).
- `subagent-statusline` — per-row body for the subagent panel (name ·
  description, a compact context bar, model, effort).

See [`statusline/README.md`](statusline/README.md) for the script contract and
layout.

## Install

```bash
claude plugin marketplace add lena-miyamoto/UtilityScripts
claude plugin install statusline@lena-miyamoto
```

Requires Python 3.13+ and `uv`; on first run `uv` provisions the virtualenv
automatically (no runtime dependencies).

## Wiring

Claude Code plugins cannot enable the main `statusLine` declaratively, and the
subagent bar isn't shipped in a plugin `settings.json` either (placeholder
expansion for `settings.json` values isn't guaranteed). Wire both bars into
the global `settings.json` (`$CLAUDE_CONFIG_DIR`, default `~/.claude`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "uv run --no-sync --project ~/github/UtilityScripts/plugins/statusline/statusline statusline"
  },
  "subagentStatusLine": {
    "type": "command",
    "command": "uv run --no-sync --project ~/github/UtilityScripts/plugins/statusline/statusline subagent-statusline"
  }
}
```

The `install-statusline` skill automates both wires (venv sync + settings
merge); prefer it over manual editing. Use the marketplace-installed copy under
`~/.claude/plugins/cache/<marketplace>/statusline/<version>/statusline` instead
of the repo path if you installed via `claude plugin install`. `--no-sync`
skips the per-tick sync check, so run `uv sync` in that directory once first
(the installer does this for you).

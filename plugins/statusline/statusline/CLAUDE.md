# statusline

Claude Code statusline (`statusline.py` main bar, `subagent-statusline.py`
subagent rows — Python, stdlib only).

## Working here

- Test with `uv run pytest -q` (run from this directory).
- `pytest` is a dev dependency. After changing `pyproject.toml`, re-sync with
  `uv sync --group dev`.
- Bump the plugin version on any change: `plugins/statusline/.claude-plugin/plugin.json`
  (`version`), the matching entry in `.claude-plugin/marketplace.json`, and
  `version` in `plugins/statusline/statusline/pyproject.toml`.

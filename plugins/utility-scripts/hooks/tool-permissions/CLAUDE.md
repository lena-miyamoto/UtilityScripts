# tool-permissions hook

PreToolUse permission hook (`main.py`, Python + rable).

## Working here

- Test with `uv run pytest -q` (run from this directory). `uv run`/`uv sync`
  are ask-listed by the hook, so they prompt instead of being hard-denied.
- `pytest` is a dev dependency. After changing `pyproject.toml`, re-sync with
  `uv sync --group dev` — it's ask-listed, so it will prompt.
- Bump the plugin version on any change: `plugins/utility-scripts/.claude-plugin/plugin.json`
  (`version`), the matching `plugins` entry in `.claude-plugin/marketplace.json`, and
  `version` in `plugins/utility-scripts/hooks/tool-permissions/pyproject.toml`.

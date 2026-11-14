# tool-permissions hook

PreToolUse permission hook (`main.py`, Python + rable).

## Working here

- Test with `.claude/scripts/bwrap-pytest.sh -C plugins/tool-permissions/hooks/tool-permissions` from the repo root; without `bwrap`, fall back to `uv run pytest -q` from this directory.
- `pytest` is a dev dependency. After changing `pyproject.toml`, re-sync with
  `uv sync --group dev` — it's ask-listed, so it will prompt.
- Bump the plugin version on any change: `plugins/tool-permissions/.claude-plugin/plugin.json`
  (`version`), the matching `plugins` entry in `.claude-plugin/marketplace.json`, and
  `version` in `plugins/tool-permissions/hooks/tool-permissions/pyproject.toml`.

---
name: install-statusline
description: "Install and wire the Claude Code statusline (main bar + subagent rows) into the global settings.json. Runs a stdlib-only Python installer that provisions the uv venv and sets statusLine + subagentStatusLine. Invoke when the statusline needs installing or its wiring is missing or stale."
disable-model-invocation: true
user-invocable: true
---

# install-statusline

Run the installer bundled with this plugin — Claude Code substitutes
`${CLAUDE_PLUGIN_ROOT}` with the plugin's install directory:

    python3 "${CLAUDE_PLUGIN_ROOT}/statusline/install-statusline.py"

It syncs the `uv` project, then merges `statusLine` and `subagentStatusLine`
into the global `settings.json` (`$CLAUDE_CONFIG_DIR`, default `~/.claude`),
preserving every other key. Idempotent — safe to re-run.

"""Install the statusline scripts into the global ``settings.json``.

Deterministic, stdlib-only, idempotent. Run directly:

    python3 <this file>

Provisions the ``uv`` virtualenv (``uv sync``), then merges ``statusLine`` and
``subagentStatusLine`` into the global settings file (under ``$CLAUDE_CONFIG_DIR``,
defaulting to ``~/.claude``), preserving every other key.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
SETTINGS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude") / "settings.json"

STATUSLINE_CMD = "uv run --no-sync --project {dir} statusline"
SUBAGENT_CMD = "uv run --no-sync --project {dir} subagent-statusline"


def main() -> int:
    project_dir = Path(__file__).resolve().parent

    # Provision the venv so the wired --no-sync command works.
    try:
        sync = subprocess.run(
            ["uv", "sync", "--project", str(project_dir)], check=False
        )
    except FileNotFoundError:
        print("warning: `uv` not found on PATH; statusline may not run", file=sys.stderr)
    else:
        if sync.returncode != 0:
            print(
                f"warning: `uv sync` failed (exit {sync.returncode}); the wired "
                "--no-sync command will not run until the venv is provisioned",
                file=sys.stderr,
            )

    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"error: cannot parse {SETTINGS}: {exc}", file=sys.stderr)
            return 1
    else:
        settings = {}

    settings["statusLine"] = {
        "type": "command",
        "command": STATUSLINE_CMD.format(dir=project_dir),
    }
    settings["subagentStatusLine"] = {
        "type": "command",
        "command": SUBAGENT_CMD.format(dir=project_dir),
    }

    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_name(SETTINGS.name + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, SETTINGS)
    print(f"statusline wired to {project_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

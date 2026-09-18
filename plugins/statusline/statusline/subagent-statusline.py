"""Claude Code subagent statusline (``subagentStatusLine``).

Claude Code pipes a single JSON object on stdin: the base hook fields plus a
``columns`` width and a ``tasks`` array (one entry per visible subagent row).
For each task we write one JSON line to stdout:

    {"id": "<task id>", "content": "<row body>"}

``content`` is rendered as-is (ANSI colors supported). Omit a task id to keep
the default rendering; emit an empty content to hide a row.
"""

from __future__ import annotations

import json
import sys

from shared import bar, fmt, s


def _bar(used):
    """Compact 8-char context bar (shared thresholds/colors as the main bar)."""
    return bar(used, 8)


def render_task(task):
    """Render one subagent task into a row body."""
    name = s(task.get("name")) or s(task.get("id")) or "?"
    lead = name
    desc = s(task.get("description"))
    if desc:
        lead += f" · {desc}"

    parts = [lead]

    ctx_size = task.get("contextWindowSize")
    token_count = task.get("tokenCount")
    if ctx_size and token_count is not None:
        used = (token_count / ctx_size) * 100
        parts.append(f"{_bar(used)} {fmt(token_count)}/{fmt(ctx_size)}")

    model = s(task.get("model"))
    effort = s(task.get("effort"))
    meta = model
    if effort:
        meta += f" ⚡{effort}"
    if meta:
        parts.append(meta)

    return "  ".join(parts)


def render(data):
    """Return the list of ``{"id", "content"}`` rows to emit for ``data``."""
    lines = []
    for task in data.get("tasks") or []:
        tid = task.get("id")
        if tid is None:
            continue
        lines.append({"id": tid, "content": render_task(task)})
    return lines


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return
    for line in render(data):
        sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

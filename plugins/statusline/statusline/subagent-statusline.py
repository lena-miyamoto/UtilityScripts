"""Claude Code subagent statusline (``subagentStatusLine``).

Requires Claude Code **2.1.322 or older**: 2.1.323 removed the setting and
always draws subagent rows itself.

Claude Code pipes a single JSON object on stdin: the base hook fields plus
``columns`` (usable row width) and a ``tasks`` array (one entry per visible
subagent row). For each task we write one JSON line to stdout:

    {"id": "<task id>", "content": "<row body>"}

``content`` is rendered as-is (ANSI colors supported). Omit a task id to keep
the default rendering; emit an empty content to hide a row.

Task fields (all of them consumed here): ``id``, ``name``, ``type``,
``agentType``, ``status``, ``description``, ``label``, ``startTime``,
``model``, ``effort``, ``contextWindowSize``, ``tokenCount``,
``tokenSamples``, ``cwd``. Optional fields are omitted by Claude Code when
empty.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata

from shared import BLUE, GREEN, ORANGE, RED, RST, bar, fmt, get, s

# Sparkline glyphs, low to high; the latest 8 of the 16 token samples are drawn.
SPARK = "▁▂▃▄▅▆▇█"
SPARK_WIDTH = 8

# status → (glyph, color). Running shows only the glyph; the others also
# spell out the state.
STATUS = {
    "running": ("▶", BLUE),
    "completed": ("✓", GREEN),
    "failed": ("✗", RED),
    "killed": ("⊘", ORANGE),
}

_SGR = re.compile(r"\x1b\[[0-9;]*m")


def _bar(used):
    """Compact 8-char context bar (shared thresholds/colors as the main bar)."""
    return bar(used, 8)


def _char_width(ch):
    """Terminal columns one character occupies."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def visible_width(text):
    """Width of ``text`` in terminal columns, ignoring SGR sequences."""
    return sum(_char_width(ch) for ch in _SGR.sub("", text))


def truncate(text, width):
    """Cut ``text`` to at most ``width`` columns, keeping SGR sequences valid."""
    if width is None or width <= 0 or visible_width(text) <= width:
        return text
    limit = width - 1  # room for the ellipsis
    out = []
    used = 0
    i = 0
    while i < len(text):
        match = _SGR.match(text, i)
        if match:
            out.append(match.group())
            i = match.end()
            continue
        ch = text[i]
        step = _char_width(ch)
        if used + step > limit:
            break
        out.append(ch)
        used += step
        i += 1
    return "".join(out) + "…" + RST


def _sparkline(samples):
    """Tiny trend of the last ``SPARK_WIDTH`` token counts, oldest first."""
    vals = []
    for v in samples or []:
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
    vals = vals[-SPARK_WIDTH:]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return SPARK[0] * len(vals)
    return "".join(SPARK[round((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in vals)


def _elapsed(start_ms, now_ms):
    """Humanize a task's age, e.g. ``12s``, ``1m05s``, ``2h03m``."""
    try:
        start = float(start_ms)
    except (TypeError, ValueError):
        return ""
    secs = max(0, int((now_ms - start) / 1000))
    if secs < 60:
        return f"{secs}s"
    mins, secs = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m{secs:02d}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h{mins:02d}m"


def render_task(task, columns=None, now=None, session_cwd=None):
    """Render one subagent task into a row body."""
    name = (
        s(task.get("name"))
        or s(task.get("agentType"))
        or s(task.get("type"))
        or s(task.get("id"))
        or "?"
    )
    agent_type = s(task.get("agentType"))
    task_type = s(task.get("type"))
    status = s(task.get("status")).lower()

    badge = ""
    if agent_type and agent_type != name:
        badge = f" [{agent_type}]"
    elif task_type and task_type != "local_agent" and task_type not in (name, agent_type):
        badge = f" [{task_type}]"

    glyph, color = STATUS.get(status, ("", ""))
    if status == "running":
        prefix = f"{color}{glyph}{RST} "
    elif glyph:
        prefix = f"{color}{glyph} {status}{RST} "
    else:
        prefix = ""

    lead = f"{prefix}{name}{badge}"

    # `label` is the live progress summary; Claude Code falls back to
    # `description` itself, but older payloads may omit it.
    desc = s(task.get("description"))
    label = s(task.get("label"))
    text = desc
    if label and label != desc:
        text = f"{desc} · {label}" if desc else label
    if text:
        lead += f" · {text}"

    parts = [lead]

    token_count = task.get("tokenCount")
    ctx_size = task.get("contextWindowSize")
    if ctx_size and token_count is not None:
        used = (float(token_count) / float(ctx_size)) * 100
        parts.append(f"{_bar(used)} {fmt(token_count)}/{fmt(ctx_size)}")
    elif token_count is not None:
        parts.append(f"{fmt(token_count)} tok")

    spark = _sparkline(task.get("tokenSamples"))
    if spark:
        parts.append(spark)

    age = _elapsed(task.get("startTime"), now if now is not None else time.time() * 1000)
    if age:
        parts.append(age)

    model = s(task.get("model"))
    effort = s(task.get("effort"))
    meta = model
    if effort:
        meta = f"{meta} ⚡{effort}" if meta else f"⚡{effort}"
    if meta:
        parts.append(meta)

    # Show the task's own directory only when it differs (e.g. a worktree).
    cwd = s(task.get("cwd"))
    if cwd and session_cwd:
        try:
            differs = os.path.normpath(cwd) != os.path.normpath(session_cwd)
        except (TypeError, ValueError):
            differs = cwd != session_cwd
        if differs:
            parts.append(os.path.basename(cwd.rstrip("/\\")) or cwd)

    return truncate("  ".join(parts), columns)


def render(data, now=None):
    """Return the list of ``{"id", "content"}`` rows to emit for ``data``."""
    columns = data.get("columns")
    if isinstance(columns, bool) or not isinstance(columns, int) or columns <= 0:
        columns = None
    session_cwd = s(get(data, "workspace", "current_dir") or get(data, "cwd"))

    lines = []
    for task in data.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        tid = task.get("id")
        if tid is None:
            continue
        lines.append(
            {
                "id": tid,
                "content": render_task(task, columns, now, session_cwd),
            }
        )
    return lines


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return
    for line in render(data):
        sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

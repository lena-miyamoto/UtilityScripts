"""Shared helpers for the statusline scripts.

Cost computation, per-model pricing (Anthropic + DeepSeek with peak/off-peak
rates), token/formatting helpers, and the context-bar renderer. Stdlib only.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude"
)
TMPDIR = os.environ.get("CLAUDE_CODE_TMPDIR") or os.path.join(CONFIG_DIR, "tmp")
MONTHLY_CACHE = os.path.join(TMPDIR, "monthly-cost.json")
ALL_TIME_CACHE = os.path.join(TMPDIR, "all-time-cost.json")
COST_TTL_MS = 120_000

RED = "\x1b[91m"
ORANGE = "\x1b[38;5;208m"
YELLOW = "\x1b[93m"
BLUE = "\x1b[94m"
GREEN = "\x1b[32m"
RST = "\x1b[0m"


def s(v):
    """``str(v)`` with ``None`` mapped to the empty string."""
    return "" if v is None else str(v)


def round_half_up(x):
    """``floor(x + 0.5)`` — half-away-from-zero rounding."""
    return math.floor(x + 0.5)


def get(data, *keys, default=None):
    """Optional chaining ``data?.a?.b`` with a default for any missing link."""
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur


def fmt(n):
    """Humanize a token count; ``''``/``None``/non-numeric become ``--``."""
    if n in ("", None):
        return "--"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "--"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{round_half_up(v / 1_000)}k"
    if v == int(v):
        return str(int(v))
    return str(v)


def _num_str(v):
    """Render a number without a trailing ``.0``."""
    return str(int(v)) if v == int(v) else str(v)


def bar(used, length, force_red=False):
    """Render a ``length``-char context bar; green→blue→yellow→orange→red."""
    used_int = round_half_up(float(used))
    if force_red or used_int > 80:
        clr = RED
    elif used_int > 65:
        clr = ORANGE
    elif used_int > 50:
        clr = YELLOW
    elif used_int > 15:
        clr = BLUE
    else:
        clr = GREEN
    filled = round_half_up(used_int * length / 100)
    if filled > length:
        filled = length
    return f"[{clr}{'█' * filled}{RST}{'░' * (length - filled)}] {clr}{used_int}%{RST}"


# $ per million tokens: input, output, cache-write (5m tier = 1.25×in),
# cache-read (0.1×in; Fable/Mythos 5.1 = 0.025×in).
# Source: https://platform.claude.com/docs/en/about-claude/pricing
_FABLE5_1 = {"in": 10, "out": 50, "cw": 12.5, "cr": 0.25}
_FABLE5 = {"in": 10, "out": 50, "cw": 12.5, "cr": 1}
_OPUS5 = {"in": 5, "out": 25, "cw": 6.25, "cr": 0.5}
_OPUS4_LEGACY = {"in": 15, "out": 75, "cw": 18.75, "cr": 1.5}  # retired Opus 4 / 4.1
_SONNET5 = {"in": 2, "out": 10, "cw": 2.5, "cr": 0.2}
_SONNET4 = {"in": 3, "out": 15, "cw": 3.75, "cr": 0.3}
_HAIKU4 = {"in": 1, "out": 5, "cw": 1.25, "cr": 0.1}
_HAIKU3 = {"in": 0.8, "out": 4, "cw": 1, "cr": 0.08}


def is_deepseek_peak(ts_ms):
    """DeepSeek peak window: 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri."""
    if ts_ms is None:
        ts_ms = time.time() * 1000
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    if dt.weekday() >= 5:  # Sat/Sun
        return False
    h = dt.hour + dt.minute / 60 + dt.second / 3600
    return (1 <= h < 4) or (6 <= h < 10)


def _deepseek_rates(ts_ms, pro):
    """DeepSeek $/1M tokens; cache-write billed at cache-miss (input) price."""
    peak = is_deepseek_peak(ts_ms)
    if pro:
        in_, out, cr = (1.32, 3.96, 0.044) if peak else (0.66, 1.98, 0.022)
    else:
        in_, out, cr = (0.3, 1.2, 0.006) if peak else (0.15, 0.6, 0.003)
    return {"in": in_, "out": out, "cw": in_, "cr": cr}


def model_rates(raw_model, ts_ms=None):
    """Per-model $/1M-token rates. ``ts_ms`` selects DeepSeek peak vs off-peak."""
    model = (raw_model or "").lower()
    if not model or model == "<synthetic>":
        return {"in": 0, "out": 0, "cw": 0, "cr": 0}
    if model.startswith(("claude-fable-5.1", "claude-mythos-5.1")):
        return _FABLE5_1
    if model.startswith(("claude-fable-5", "claude-mythos-5")):
        return _FABLE5
    if model.startswith("claude-opus-5"):
        return _OPUS5
    # Retired Opus 4.0/4.1 — bare `claude-opus-4`, `claude-opus-4.1`/`4-1`, or
    # date-suffixed `claude-opus-4-20250514` (`4-2…` = year 20xx). Current
    # 4.5–4.8 use `4-5…`–`4-8…`, so they fall through to _OPUS5 below.
    if model == "claude-opus-4" or model.startswith(
        ("claude-opus-4.1", "claude-opus-4-1", "claude-opus-4-2")
    ):
        return _OPUS4_LEGACY
    if model.startswith("claude-opus-4"):
        return _OPUS5
    if model.startswith("claude-sonnet-5"):
        return _SONNET5
    if model.startswith("claude-sonnet-4"):
        return _SONNET4
    if model.startswith("claude-haiku-4"):
        return _HAIKU4
    if model.startswith("claude-haiku-3"):
        return _HAIKU3
    if model.startswith("deepseek-v4-pro"):
        return _deepseek_rates(ts_ms, pro=True)
    if model.startswith("deepseek"):
        return _deepseek_rates(ts_ms, pro=False)
    return _SONNET4


def _parse_ts_ms(ts):
    """Parse an ISO-8601 timestamp to epoch ms (UTC); ``None`` if unparseable."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def line_cost(line, year_month, seen):
    """Cost of one JSONL line; ``year_month == ""`` skips the month filter."""
    if not line.strip():
        return 0.0
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return 0.0
    ts = obj.get("timestamp") or ""
    if year_month and not ts.startswith(year_month):
        return 0.0
    ts_ms = _parse_ts_ms(ts)
    usage = (obj.get("message") or {}).get("usage") or obj.get("usage")
    if not usage:
        return 0.0
    # same API call logged multiple times with different uuid but same requestId;
    # fall back to message id.
    rid = obj.get("requestId") or (obj.get("message") or {}).get("id") or ""
    if rid:
        if rid in seen:
            return 0.0
        seen.add(rid)
    raw_model = (obj.get("message") or {}).get("model") or obj.get("model") or ""
    r = model_rates(str(raw_model), ts_ms)
    return (
        (usage.get("input_tokens") or 0) * r["in"]
        + (usage.get("output_tokens") or 0) * r["out"]
        + (usage.get("cache_creation_input_tokens") or 0) * r["cw"]
        + (usage.get("cache_read_input_tokens") or 0) * r["cr"]
    ) * 1e-6


def walk_jsonl(directory, month_start, year_month, seen):
    cost = 0.0
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return cost
    for entry in entries:
        full = entry.path
        if entry.is_dir(follow_symlinks=False):
            cost += walk_jsonl(full, month_start, year_month, seen)
            continue
        if not entry.name.endswith(".jsonl"):
            continue
        try:
            if entry.stat().st_mtime * 1000 < month_start:
                continue
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    cost += line_cost(line, year_month, seen)
        except OSError:
            pass
    return cost


def find_session_file(directory, session_id):
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return None
    for entry in entries:
        full = entry.path
        if entry.is_dir(follow_symlinks=False):
            found = find_session_file(full, session_id)
            if found:
                return found
        elif entry.name == f"{session_id}.jsonl":
            return full
    return None


def get_session_cost(session_id):
    """Recompute a session's spend from its JSONL log using real per-model rates."""
    file = find_session_file(os.path.join(CONFIG_DIR, "projects"), session_id)
    if not file:
        return 0.0
    cost = 0.0
    seen = set()
    try:
        with open(file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                cost += line_cost(line, "", seen)
    except OSError:
        pass
    return cost


def get_cost(monthly):
    """Scan ``<CONFIG_DIR>/projects/**/*.jsonl``, cached 2 min."""
    cache_file = MONTHLY_CACHE if monthly else ALL_TIME_CACHE
    now = datetime.now()
    year_month = f"{now.year}-{now.month:02d}"
    try:
        st = os.stat(cache_file)
        if time.time() * 1000 - st.st_mtime * 1000 < COST_TTL_MS:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached.get("cost"), (int, float)):
                if not monthly or cached.get("month") == year_month:
                    return cached["cost"]
    except (OSError, ValueError):
        pass  # cache missing/corrupt — recompute

    month_start = (
        int(datetime(now.year, now.month, 1).timestamp() * 1000) if monthly else 0
    )
    cost = walk_jsonl(
        os.path.join(CONFIG_DIR, "projects"),
        month_start,
        year_month if monthly else "",
        set(),
    )

    try:
        os.makedirs(TMPDIR, exist_ok=True)
        tmp = cache_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"cost": cost, "month": year_month}, f)
        os.replace(tmp, cache_file)
    except OSError:
        pass  # best-effort
    return cost


def load_subagent():
    """Import ``subagent-statusline.py`` (hyphenated filename, not importable
    by name) and return it as a module."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "subagent_statusline",
        pathlib.Path(__file__).with_name("subagent-statusline.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def subagent_main():
    """Console-script entry for ``subagent-statusline``."""
    return load_subagent().main()

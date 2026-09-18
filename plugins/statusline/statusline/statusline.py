"""Claude Code statusline — main bottom bar.

Claude Code pipes status JSON on stdin and reads the rendered bar from stdout.
Layout, left to right:

    <model> [<agent>] ⚡<effort> 🧠  [<ctx bar>] <used%>  <in>/<size>  ♻️ <cache>  ⑂ <worktree>  ⎇ <branch>  [<vim mode>]  ⏰ <rate%>  💳 <monthly cost>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from shared import (
    GREEN,
    ORANGE,
    RED,
    RST,
    YELLOW,
    _num_str,
    bar,
    fmt,
    get,
    get_cost,
    get_session_cost,
    model_rates,
    round_half_up,
    s,
)


def render(data):
    """Build the full statusline string from the parsed status JSON."""
    model = s(get(data, "model", "display_name")) or "unknown"
    used = get(data, "context_window", "used_percentage")
    total_in = get(data, "context_window", "total_input_tokens")
    ctx_size = get(data, "context_window", "context_window_size")
    cache_read = float(
        get(data, "context_window", "current_usage", "cache_read_input_tokens") or 0
    )
    effort = s(get(data, "effort", "level"))
    thinking_en = get(data, "thinking", "enabled") is True
    worktree_name = s(get(data, "workspace", "git_worktree"))
    vim_mode = s(get(data, "vim", "mode"))
    rate_5h = get(data, "rate_limits", "five_hour", "used_percentage")
    rate_1m = get(data, "rate_limits", "one_minute", "used_percentage")
    agent_name = s(get(data, "agent", "name"))
    exceeds_200k = get(data, "exceeds_200k_tokens") is True
    session_cost = get(data, "cost", "total_cost_usd")

    # Context window bar
    if used is not None:
        in_str = fmt(total_in)
        size_str = fmt(ctx_size) if ctx_size else "--"
        cache_str = fmt(cache_read) if cache_read > 0 else ""
        ctx_part = f"{bar(used, 16, force_red=exceeds_200k)}  {in_str}/{size_str}"
        if cache_str:
            ctx_part += f"  ♻️ {cache_str}"
    else:
        ctx_part = "[░░░░░░░░░░░░░░░] --%  --/--"

    # Model + modifiers
    model_part = model
    if agent_name:
        model_part += f" [{agent_name}]"
    if effort:
        model_part += f" ⚡{effort}"
    if thinking_en:
        model_part += " 🧠"

    # Git branch (--no-optional-locks avoids stale lock contention)
    git_branch = ""
    cwd_path = s(get(data, "workspace", "current_dir") or get(data, "cwd"))
    if cwd_path:
        try:
            git_branch = subprocess.run(
                ["git", "--no-optional-locks", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=cwd_path,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            git_branch = ""
    branch_part = f"  ⎇  {git_branch}" if git_branch else ""

    # Git worktree
    wt_part = f"  ⑂ {worktree_name}" if worktree_name else ""

    # Vim mode
    vim_part = f"  [{vim_mode}]" if vim_mode else ""

    # Rate limit warnings — 5h sustained (≥70%), 1m burst (≥90%)
    rate_part = ""
    if rate_5h is not None:
        rate_int = round_half_up(float(rate_5h))
        if rate_int >= 70:
            rate_part = f"  ⏰ {rate_int}%"
    if rate_1m is not None:
        rate_1m_int = round_half_up(float(rate_1m))
        if rate_1m_int >= 90:
            rate_part += f"  ⏱ {rate_1m_int}%"

    # Cost — DeepSeek recomputes its session spend from its own JSONL log
    # instead of trusting data.cost.total_cost_usd (harness falls back to
    # Anthropic pricing for unrecognized models).
    model_id = s(get(data, "model", "id")).lower()
    is_deepseek = model_id.startswith("deepseek") or "deepseek" in model.lower()

    def deepseek_ceiling():
        if not is_deepseek or not ctx_size:
            return ""
        r = model_rates(model_id)
        ceiling = (ctx_size * r["in"] + 50000 * r["out"]) / 1e6
        return f" ⇧${ceiling:.2f}"

    _mb = os.environ.get("CLAUDE_MONTHLY_BUDGET")
    monthly_budget = float(_mb) if _mb else 200.0
    session_id = s(get(data, "session_id"))
    session_cost_num = (
        get_session_cost(session_id)
        if is_deepseek and session_id
        else (session_cost or 0)
    )
    scanned_cost = get_cost(False) if is_deepseek else get_cost(True)
    display_cost = (
        scanned_cost + session_cost_num
        if scanned_cost < session_cost_num
        else scanned_cost
    )

    session_str = f"${session_cost_num:.2f}"
    if is_deepseek:
        monthly_part = f"  💳 {session_str} | ${display_cost:.2f}{deepseek_ceiling()}"
    elif monthly_budget > 0:
        left_pct = max(
            0, round_half_up(((monthly_budget - display_cost) / monthly_budget) * 100)
        )
        # Colors show budget *remaining*: ≤10% red (≥90% spent), ≤25% orange,
        # ≤50% yellow.
        if left_pct <= 10:
            m_clr = RED
        elif left_pct <= 25:
            m_clr = ORANGE
        elif left_pct <= 50:
            m_clr = YELLOW
        else:
            m_clr = GREEN
        monthly_part = (
            f"  💳 {session_str} | ${display_cost:.2f} / ${_num_str(monthly_budget)}"
            f" · {m_clr}{left_pct}%{RST}"
        )
    else:
        monthly_part = f"  💳 {session_str} | ${display_cost:.2f}"

    return (
        f"{model_part}  {ctx_part}{wt_part}{branch_part}{vim_part}"
        f"{rate_part}{monthly_part}"
    )


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        data = {}
    sys.stdout.write(render(data))


if __name__ == "__main__":
    main()

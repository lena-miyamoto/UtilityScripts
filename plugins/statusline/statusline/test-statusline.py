"""pytest suite for the statusline.

Imports the real ``statusline`` and ``shared`` modules — no re-pasted copies.
Cost functions are monkeypatched in ``render`` tests so no filesystem scan runs.
"""

import json
from datetime import datetime, timezone

import shared
import statusline

# Deterministic peak/off-peak instants: 2026-09-15 is a Tuesday (UTC).
OFFPEAK_MS = int(datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
PEAK_MS = int(datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def render(data, session_cost=0.0, total_cost=1.23, monkeypatch=None):
    """Render ``data`` with cost functions stubbed to fixed values."""
    if monkeypatch is not None:
        monkeypatch.setattr(statusline, "get_session_cost", lambda sid: session_cost)
        monkeypatch.setattr(statusline, "get_cost", lambda monthly: total_cost)
    return statusline.render(data)


# ---------------------------------------------------------------------------
# fmt / round_half_up / _num_str
# ---------------------------------------------------------------------------


def test_fmt():
    assert shared.fmt("") == "--"
    assert shared.fmt(None) == "--"
    assert shared.fmt("abc") == "--"
    assert shared.fmt(999) == "999"
    assert shared.fmt(1000) == "1k"
    assert shared.fmt(1500) == "2k"
    assert shared.fmt(120_000) == "120k"
    assert shared.fmt(1_000_000) == "1.0M"
    assert shared.fmt(1_500_000) == "1.5M"


def test_round_half_up():
    assert shared.round_half_up(0.5) == 1
    assert shared.round_half_up(1.4) == 1
    assert shared.round_half_up(2.5) == 3


def test_num_str():
    assert shared._num_str(200.0) == "200"
    assert shared._num_str(200.5) == "200.5"


# ---------------------------------------------------------------------------
# model_rates
# ---------------------------------------------------------------------------


def test_model_rates_synthetic_and_unknown():
    assert shared.model_rates("")["in"] == 0
    assert shared.model_rates("<synthetic>")["in"] == 0
    assert shared.model_rates("gpt-whatever")["in"] == 3  # SONNET4 fallback


def test_model_rates_known():
    assert shared.model_rates("claude-sonnet-4") == {
        "in": 3, "out": 15, "cw": 3.75, "cr": 0.3,
    }
    assert shared.model_rates("claude-haiku-4")["out"] == 5
    assert shared.model_rates("claude-sonnet-5")["in"] == 2
    assert shared.model_rates("claude-opus-5")["in"] == 5
    assert shared.model_rates("claude-fable-5")["cr"] == 1
    assert shared.model_rates("claude-fable-5.1")["cr"] == 0.25
    assert shared.model_rates("claude-opus-4")["in"] == 15  # retired
    assert shared.model_rates("claude-opus-4-20250514")["in"] == 15  # retired, date-suffixed


def test_deepseek_peak_offpeak():
    assert shared.model_rates("deepseek-v4-pro", OFFPEAK_MS) == {
        "in": 0.66, "out": 1.98, "cw": 0.66, "cr": 0.022,
    }
    assert shared.model_rates("deepseek-v4-pro", PEAK_MS) == {
        "in": 1.32, "out": 3.96, "cw": 1.32, "cr": 0.044,
    }
    assert shared.model_rates("deepseek-flash", OFFPEAK_MS) == {
        "in": 0.15, "out": 0.6, "cw": 0.15, "cr": 0.003,
    }
    assert shared.model_rates("deepseek-flash", PEAK_MS) == {
        "in": 0.3, "out": 1.2, "cw": 0.3, "cr": 0.006,
    }


def test_deepseek_legacy_aliases():
    # legacy aliases resolve to v4-flash rates
    assert shared.model_rates("deepseek-chat", OFFPEAK_MS) == shared.model_rates(
        "deepseek-flash", OFFPEAK_MS
    )
    assert shared.model_rates("deepseek-reasoner", OFFPEAK_MS) == shared.model_rates(
        "deepseek-flash", OFFPEAK_MS
    )


def test_model_rates_case_insensitive():
    assert shared.model_rates("Claude-Opus-5")["in"] == 5


# ---------------------------------------------------------------------------
# is_deepseek_peak
# ---------------------------------------------------------------------------


def _peak_at(hour, weekday):
    """Peak/off-peak at ``hour`` UTC on ``weekday`` (Mon=0) of a fixed week."""
    # 2026-09-14 is a Monday.
    day = 14 + weekday
    ts = int(datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc).timestamp() * 1000)
    return shared.is_deepseek_peak(ts)


def test_is_deepseek_peak():
    # Weekday windows: 01:00–04:00 and 06:00–10:00 UTC.
    assert _peak_at(2, 0) is True    # Mon 02:00
    assert _peak_at(8, 0) is True    # Mon 08:00
    assert _peak_at(12, 0) is False  # Mon 12:00
    assert _peak_at(4, 0) is False   # boundary, not < 4
    assert _peak_at(10, 0) is False  # boundary, not < 10
    # Weekend is always off-peak.
    assert _peak_at(2, 5) is False   # Sat 02:00
    assert _peak_at(8, 6) is False   # Sun 08:00


# ---------------------------------------------------------------------------
# line_cost
# ---------------------------------------------------------------------------


def _line(model="claude-sonnet-4", usage=None, rid="abc", ts="2026-09-18T00:00:00Z"):
    return json.dumps(
        {
            "timestamp": ts,
            "requestId": rid,
            "message": {"model": model, "usage": usage or {}},
        }
    )


def test_line_cost_arithmetic():
    line = _line(usage={"input_tokens": 1000, "output_tokens": 100})
    # (1000*3 + 100*15) / 1e6 = 0.0045
    assert abs(shared.line_cost(line, "2026-09", set()) - 0.0045) < 1e-12


def test_line_cost_cache_tokens():
    line = _line(
        usage={
            "input_tokens": 0,
            "cache_creation_input_tokens": 1000,
            "cache_read_input_tokens": 2000,
        }
    )
    # (1000*3.75 + 2000*0.3) / 1e6 = 0.00435
    assert abs(shared.line_cost(line, "2026-09", set()) - 0.00435) < 1e-12


def test_line_cost_month_filter():
    line = _line(usage={"input_tokens": 1000}, ts="2026-08-31T23:00:00Z")
    assert shared.line_cost(line, "2026-09", set()) == 0.0
    assert shared.line_cost(line, "2026-08", set()) > 0.0
    # empty month skips the filter
    assert shared.line_cost(line, "", set()) > 0.0


def test_line_cost_request_id_dedup():
    line = _line(usage={"input_tokens": 1000})
    seen = set()
    assert shared.line_cost(line, "2026-09", seen) > 0.0
    assert shared.line_cost(line, "2026-09", seen) == 0.0


def test_line_cost_malformed():
    assert shared.line_cost("not json", "2026-09", set()) == 0.0
    assert shared.line_cost("", "2026-09", set()) == 0.0


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def _data(**overrides):
    base = {
        "model": {"display_name": "Opus 5", "id": "claude-opus-5"},
        "context_window": {
            "used_percentage": 42,
            "total_input_tokens": 80_000,
            "context_window_size": 200_000,
            "current_usage": {"cache_read_input_tokens": 5_000},
        },
        "session_id": "sess123",
        "cost": {"total_cost_usd": 0.05},
    }
    base.update(overrides)
    return base


def test_render_model_and_context(monkeypatch):
    out = render(_data(), monkeypatch=monkeypatch)
    assert out.startswith("Opus 5  [")
    assert "42%" in out
    assert "80k/200k" in out
    assert "♻️ 5k" in out
    assert "💳 $0.05 | $1.23 / $200" in out


def test_render_empty_context(monkeypatch):
    out = render(_data(context_window={}), monkeypatch=monkeypatch)
    assert "[░░░░░░░░░░░░░░░] --%  --/--" in out


def test_render_modifiers(monkeypatch):
    out = render(
        _data(
            agent={"name": "explorer"},
            effort={"level": "high"},
            thinking={"enabled": True},
        ),
        monkeypatch=monkeypatch,
    )
    assert out.startswith("Opus 5 [explorer] ⚡high 🧠")


def test_render_worktree_and_vim(monkeypatch):
    out = render(
        _data(
            workspace={"git_worktree": "wt-main", "current_dir": None},
            vim={"mode": "NORMAL"},
        ),
        monkeypatch=monkeypatch,
    )
    assert "⑂ wt-main" in out
    assert "[NORMAL]" in out


def test_render_rate_limits(monkeypatch):
    out = render(
        _data(
            rate_limits={
                "five_hour": {"used_percentage": 75},
                "one_minute": {"used_percentage": 95},
            }
        ),
        monkeypatch=monkeypatch,
    )
    assert "⏰ 75%" in out
    assert "⏱ 95%" in out


def test_render_rate_limits_below_threshold(monkeypatch):
    out = render(
        _data(
            rate_limits={
                "five_hour": {"used_percentage": 60},
                "one_minute": {"used_percentage": 80},
            }
        ),
        monkeypatch=monkeypatch,
    )
    assert "⏰" not in out
    assert "⏱" not in out


def test_render_deepseek_ceiling(monkeypatch):
    monkeypatch.setattr(
        statusline,
        "model_rates",
        lambda model, ts_ms=None: {"in": 0.66, "out": 1.98, "cw": 0.66, "cr": 0.022},
    )
    out = render(
        _data(model={"display_name": "deepseek-v4-pro", "id": "deepseek-v4-pro"}),
        session_cost=0.5,
        monkeypatch=monkeypatch,
    )
    # ctx 200k * 0.66 + 50000 * 1.98 = 231000 / 1e6 = $0.231 ceiling
    assert "⇧$0.23" in out
    assert "$0.50" in out


def test_render_budget_left_pct(monkeypatch):
    monkeypatch.setenv("CLAUDE_MONTHLY_BUDGET", "100")
    out = render(_data(), total_cost=40.0, monkeypatch=monkeypatch)
    # (100 - 40) / 100 = 60% left
    assert "$40.00 / $100" in out
    assert "60%" in out


def test_render_missing_model(monkeypatch):
    out = render({}, monkeypatch=monkeypatch)
    assert out.startswith("unknown  ")

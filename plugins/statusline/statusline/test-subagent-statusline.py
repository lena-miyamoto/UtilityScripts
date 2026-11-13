"""pytest suite for the subagent statusline."""

import pytest
import shared

ssl = shared.load_subagent()

NOW = 1_000_000_000_000  # epoch ms


def test_render_task_basic():
    task = {"id": "t1", "name": "explorer", "description": "Find files"}
    assert ssl.render_task(task) == "explorer · Find files"


def test_render_task_missing_name():
    # falls back to id, then to "?" only when both are absent
    assert ssl.render_task({"id": "t1"}) == "t1"
    assert ssl.render_task({}) == "?"


def test_render_task_name_fallbacks():
    assert ssl.render_task({"id": "t1", "agentType": "Explore"}) == "Explore"
    assert ssl.render_task({"id": "t1", "type": "local_agent"}) == "local_agent"


def test_render_task_all_fields():
    task = {
        "id": "t1",
        "name": "explorer",
        "type": "local_agent",
        "agentType": "Explore",
        "status": "running",
        "description": "Find files",
        "label": "Searching src",
        "startTime": NOW - 72_000,
        "model": "claude-sonnet-5",
        "effort": "high",
        "contextWindowSize": 200_000,
        "tokenCount": 80_000,
        "tokenSamples": [10_000, 40_000, 80_000],
        "cwd": "/repo",
    }
    out = ssl.render_task(task, now=NOW, session_cwd="/repo")
    assert "\x1b[94m▶\x1b[0m explorer [Explore]" in out
    assert "Find files · Searching src" in out
    assert "40%" in out
    assert "80k/200k" in out
    assert "1m12s" in out
    assert "claude-sonnet-5 ⚡high" in out
    assert ssl._sparkline(task["tokenSamples"]) == "▁▄█"


def test_render_task_label_equals_description():
    task = {"id": "t1", "name": "x", "description": "Work", "label": "Work"}
    assert ssl.render_task(task) == "x · Work"


def test_render_task_status():
    assert "\x1b[32m✓ completed\x1b[0m" in ssl.render_task(
        {"id": "t1", "name": "x", "status": "completed"}
    )
    assert "\x1b[91m✗ failed\x1b[0m" in ssl.render_task(
        {"id": "t1", "name": "x", "status": "failed"}
    )
    assert "\x1b[38;5;208m⊘ killed\x1b[0m" in ssl.render_task(
        {"id": "t1", "name": "x", "status": "killed"}
    )


def test_render_task_context_missing_size():
    task = {"id": "t1", "name": "x", "tokenCount": 80_000}
    assert ssl.render_task(task) == "x  80k tok"


def test_render_task_context_missing():
    task = {"id": "t1", "name": "explorer", "model": "claude-sonnet-5"}
    assert ssl.render_task(task) == "explorer  claude-sonnet-5"


def test_render_task_effort_only():
    assert ssl.render_task({"id": "t1", "name": "x", "effort": "max"}) == "x  ⚡max"


def test_render_task_cwd_shown_when_different():
    task = {"id": "t1", "name": "x", "cwd": "/repo/worktrees/agent-wt"}
    assert ssl.render_task(task, session_cwd="/repo").endswith("agent-wt")


def test_render_task_cwd_hidden_when_same():
    task = {"id": "t1", "name": "x", "cwd": "/repo"}
    assert ssl.render_task(task, session_cwd="/repo/") == "x"


def test_render_task_non_local_type_badge():
    task = {"id": "t1", "name": "x", "type": "workflow"}
    assert ssl.render_task(task) == "x [workflow]"


def test_render_task_columns_truncate():
    task = {"id": "t1", "name": "x", "description": "y" * 100}
    out = ssl.render_task(task, columns=40)
    assert ssl.visible_width(out) <= 40
    assert out.endswith("…\x1b[0m")


def test_truncate_counts_wide_characters():
    assert ssl.truncate("漢" * 50, 10) == "漢漢漢漢…\x1b[0m"


def test_truncate_preserves_sgr_sequences():
    out = ssl.truncate("\x1b[31m" + "a" * 50 + "\x1b[0m", 10)
    assert out == "\x1b[31maaaaaaaaa…\x1b[0m"
    assert ssl.visible_width(out) <= 10


def test_truncate_leaves_short_text_untouched():
    assert ssl.truncate("short", 40) == "short"
    assert ssl.truncate("short", 0) == "short"


def test_visible_width_ignores_ansi():
    assert ssl.visible_width("\x1b[31mab\x1b[0m") == 2


@pytest.mark.parametrize(
    ("start_ms", "expected"),
    [
        (NOW, "0s"),
        (NOW - 12_000, "12s"),
        (NOW - 65_000, "1m05s"),
        (NOW - 7_380_000, "2h03m"),
        (None, ""),
    ],
    ids=[
        "zero-seconds",
        "twelve-seconds",
        "one-minute-five-seconds",
        "two-hours-three-minutes",
        "missing-start-is-empty",
    ],
)
def test_elapsed_formats_age(start_ms, expected):
    assert ssl._elapsed(start_ms, NOW) == expected


@pytest.mark.parametrize(
    ("samples", "expected"),
    [
        ([], ""),
        ([5], ""),
        ([5, 5], "▁▁"),
        ([0, 100], "▁█"),
    ],
    ids=[
        "no-samples-is-empty",
        "one-sample-is-empty",
        "flat-line-is-lowest",
        "range-spans-low-to-high",
    ],
)
def test_sparkline_renders_trend(samples, expected):
    assert ssl._sparkline(samples) == expected


def test_sparkline_limits_to_eight_samples():
    assert len(ssl._sparkline(list(range(20)))) == ssl.SPARK_WIDTH


def test_bar_colors_and_clamp():
    assert "50%" in ssl._bar(50)
    # fill clamps to the bar length even when used > 100%
    assert ssl._bar(200).count("█") == 8


def test_render_lines():
    data = {"tasks": [{"id": "a", "name": "x"}, {"id": "b", "name": "y"}]}
    assert ssl.render(data) == [
        {"id": "a", "content": "x"},
        {"id": "b", "content": "y"},
    ]


def test_render_passes_columns():
    data = {"columns": 10, "tasks": [{"id": "a", "name": "x" * 50}]}
    assert ssl.visible_width(ssl.render(data)[0]["content"]) <= 10


def test_render_skips_missing_id():
    assert ssl.render({"tasks": [{"name": "no-id"}, "not-a-dict"]}) == []


def test_render_session_cwd_from_workspace_current_dir():
    data = {
        "workspace": {"current_dir": "/repo"},
        "tasks": [{"id": "a", "name": "x", "cwd": "/repo/worktrees/agent-wt"}],
    }
    content = ssl.render(data)[0]["content"]
    assert content.endswith("agent-wt")


def test_render_empty():
    assert ssl.render({}) == []

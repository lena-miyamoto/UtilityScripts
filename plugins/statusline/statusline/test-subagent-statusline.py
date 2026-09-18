"""pytest suite for the subagent statusline."""

import shared

ssl = shared.load_subagent()


def test_render_task_basic():
    task = {"id": "t1", "name": "explorer", "description": "Find files"}
    assert ssl.render_task(task) == "explorer · Find files"


def test_render_task_missing_name():
    # falls back to id, then to "?" only when both are absent
    assert ssl.render_task({"id": "t1"}) == "t1"
    assert ssl.render_task({}) == "?"


def test_render_task_with_ctx():
    task = {
        "id": "t1",
        "name": "explorer",
        "model": "claude-sonnet-5",
        "effort": "high",
        "contextWindowSize": 200_000,
        "tokenCount": 80_000,
    }
    out = ssl.render_task(task)
    assert out.startswith("explorer")
    assert "40%" in out
    assert "80k/200k" in out
    assert "claude-sonnet-5" in out
    assert "⚡high" in out


def test_render_task_ctx_missing():
    task = {"id": "t1", "name": "explorer", "model": "claude-sonnet-5"}
    assert ssl.render_task(task) == "explorer  claude-sonnet-5"


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


def test_render_skips_missing_id():
    assert ssl.render({"tasks": [{"name": "no-id"}]}) == []


def test_render_empty():
    assert ssl.render({}) == []

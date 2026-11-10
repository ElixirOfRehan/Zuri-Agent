from __future__ import annotations

import pytest

from app.storage import Storage

from .util import make_settings


def test_cost_summary_and_status_filter(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    first = storage.create_task("first")
    second = storage.create_task("second")
    storage.set_status(second, "awaiting_approval")
    storage.add_cost(first, "boss", "deepseek-v4-pro", 1000, 500, 0.01)
    storage.add_cost(first, "worker", "deepseek-flash", 2000, 500, 0.002)
    storage.add_cost(second, "worker", "deepseek-flash", 1000, 250, 0.001)

    summary = storage.cost_summary()
    assert summary["total_tokens"] == 5250
    assert summary["total_cost_usd"] == pytest.approx(0.013)
    assert summary["monthly_cost_usd"] == pytest.approx(0.013)
    assert len(summary["by_agent"]) == 2
    assert len(summary["recent_tasks"]) == 2

    waiting = storage.list_tasks_by_status("awaiting_approval")
    assert [task["id"] for task in waiting] == [second]
    storage.close()


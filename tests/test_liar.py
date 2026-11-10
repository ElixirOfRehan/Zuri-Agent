from __future__ import annotations

from app.kernel import Kernel

from .util import make_settings


def test_liar_worker_cannot_fake_success(tmp_path):
    settings = make_settings(tmp_path)
    kernel = Kernel(settings)
    try:
        result = kernel.liar_test()
        assert result["liar_rejected"] is True
        assert result["status"] == "failed"
        task_data = kernel.task_data(result["task_id"])
        assert task_data["artifacts"] == []
        assert any(not item["passed"] for item in task_data["verifications"])
    finally:
        kernel.close()

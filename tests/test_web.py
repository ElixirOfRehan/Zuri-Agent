from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.storage import Storage
from app.web import create_app

from .util import make_settings


def _wait_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_web_endpoints_and_job_queue(tmp_path):
    settings = make_settings(tmp_path)
    settings.api_key = "sk-test"
    storage = Storage(settings)
    existing = storage.create_task("existing task")
    awaiting = storage.create_task("needs approval")
    storage.set_status(awaiting, "awaiting_approval")
    storage.close()

    def fake_runner(request: str) -> str:
        inner = Storage(settings)
        try:
            task_id = inner.create_task(request)
            inner.set_status(task_id, "succeeded")
            return task_id
        finally:
            inner.close()

    def fake_approver(task_id: str) -> str:
        inner = Storage(settings)
        try:
            inner.set_status(task_id, "succeeded")
            return task_id
        finally:
            inner.close()

    app = create_app(settings, runner=fake_runner, approver=fake_approver)
    try:
        with TestClient(app) as client:
            index = client.get("/")
            assert index.status_code == 200
            assert "Zuri Agent" in index.text

            summary = client.get("/api/summary")
            assert summary.status_code == 200
            payload = summary.json()
            assert payload["api_key_set"] is True
            assert any(task["id"] == existing for task in payload["tasks"])
            assert payload["queue"]["total"] == 0

            detail = client.get(f"/api/tasks/{existing}")
            assert detail.status_code == 200
            assert detail.json()["task"]["id"] == existing
            assert client.get("/api/tasks/missing").status_code == 404

            assert client.get("/api/agents").status_code == 200
            assert client.get("/api/costs").status_code == 200

            run = client.post("/api/run", json={"request": "do the thing"})
            assert run.status_code == 200
            job = _wait_job(client, run.json()["job_id"])
            assert job["status"] == "succeeded"
            assert job["task_id"].startswith("t_")

            approve = client.post(f"/api/tasks/{awaiting}/approve")
            assert approve.status_code == 200
            approved = _wait_job(client, approve.json()["job_id"])
            assert approved["status"] == "succeeded"
            assert approved["task_id"] == awaiting

            assert client.post("/api/run", json={"request": "  "}).status_code == 400
    finally:
        app.state.queue.shutdown()


def test_web_run_requires_api_key(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings, runner=lambda request: "t_x")
    try:
        with TestClient(app) as client:
            response = client.post("/api/run", json={"request": "do work"})
            assert response.status_code == 400
            assert "DEEPSEEK_API_KEY" in response.json()["detail"]
    finally:
        app.state.queue.shutdown()

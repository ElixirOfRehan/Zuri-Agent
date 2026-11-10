from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from .config import Settings
from .kernel import Kernel
from .storage import utc_now


class JobQueue:
    """Small in-process queue: one task at a time, newest jobs wait."""

    def __init__(
        self,
        settings: Settings,
        runner=None,
        approver=None,
        max_workers: int = 1,
    ):
        self.settings = settings
        self.runner = runner or self._default_run
        self.approver = approver or self._default_approve
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="zuri-job"
        )
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _default_run(self, request: str) -> str:
        kernel = Kernel(self.settings)
        try:
            return kernel.plan_and_run(request)
        finally:
            kernel.close()

    def _default_approve(self, task_id: str) -> str:
        kernel = Kernel(self.settings)
        try:
            kernel.approve(task_id)
            return task_id
        finally:
            kernel.close()

    def _new_job(self, kind: str, payload: dict) -> str:
        job_id = "j_" + uuid.uuid4().hex[:10]
        now = utc_now()
        with self.lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "kind": kind,
                **payload,
                "status": "queued",
                "task_id": None,
                "error": None,
                "created_at": now,
                "updated_at": now,
            }
        return job_id

    def submit_run(self, request: str) -> str:
        job_id = self._new_job("run", {"request": request})
        self.executor.submit(self._run_job, job_id, "run", request)
        return job_id

    def submit_approve(self, task_id: str) -> str:
        job_id = self._new_job("approve", {"task_id": task_id})
        self.executor.submit(self._run_job, job_id, "approve", task_id)
        return job_id

    def _run_job(self, job_id: str, kind: str, payload: str) -> None:
        self._update(job_id, status="running")
        try:
            if kind == "run":
                task_id = self.runner(payload)
            else:
                task_id = self.approver(payload)
            self._update(job_id, status="succeeded", task_id=task_id)
        except Exception as error:  # noqa: BLE001
            self._update(job_id, status="failed", error=str(error))

    def _update(self, job_id: str, **fields) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return
            job.update(fields)
            job["updated_at"] = utc_now()

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def status(self) -> dict:
        with self.lock:
            jobs = list(self.jobs.values())
        return {
            "queued": sum(1 for job in jobs if job["status"] == "queued"),
            "running": sum(1 for job in jobs if job["status"] == "running"),
            "failed": sum(1 for job in jobs if job["status"] == "failed"),
            "total": len(jobs),
        }

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

from __future__ import annotations

import uuid

from .config import Settings
from .models import AcceptanceTest, TaskContract, VerificationResult
from .sandbox import SandboxError, resolve_in_workspace, sha256_bytes
from .storage import Storage


class Verifier:
    """Independent checks. The Boss and Worker never decide success."""

    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage

    def run(self, task_id: str, contract: TaskContract) -> list[VerificationResult]:
        run_id = "vr_" + uuid.uuid4().hex[:8]
        results: list[VerificationResult] = []
        for deliverable in contract.deliverables:
            results.append(
                self._check_deliverable(task_id, deliverable.path)
            )
        for test in contract.acceptance_tests:
            results.append(self._check_test(task_id, test))
        for result in results:
            self.storage.add_verification(
                task_id,
                run_id,
                result.name,
                result.passed,
                result.detail,
                result.evidence,
            )
            self.storage.add_event(
                task_id,
                "verifier",
                "verification",
                {
                    "run_id": run_id,
                    "name": result.name,
                    "passed": result.passed,
                    "detail": result.detail,
                    "evidence": result.evidence,
                },
            )
        return results

    def _artifact_file(
        self, task_id: str, path: str
    ) -> tuple[dict | None, str | None, str]:
        artifact = self.storage.get_artifact_for_path(task_id, path)
        if artifact is None:
            return None, None, "no ledger artifact: worker did not write this path"
        try:
            target = resolve_in_workspace(self.settings.workspace_dir, path)
        except SandboxError as error:
            return artifact, None, f"path rejected: {error}"
        if not target.is_file():
            return artifact, None, "file is missing on disk"
        actual = sha256_bytes(target.read_bytes())
        if actual != artifact["sha256"]:
            return (
                artifact,
                None,
                f"file changed after write: {actual} != {artifact['sha256']}",
            )
        return artifact, str(target), ""

    def _check_deliverable(self, task_id: str, path: str) -> VerificationResult:
        artifact, _target, error = self._artifact_file(task_id, path)
        evidence = {}
        if artifact:
            evidence = {
                "artifact_id": artifact["id"],
                "path": path,
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
            }
        if error:
            return VerificationResult(
                name=f"deliverable:{path}",
                passed=False,
                detail=error,
                evidence=evidence,
            )
        return VerificationResult(
            name=f"deliverable:{path}",
            passed=True,
            detail="file exists and matches the ledger artifact",
            evidence=evidence,
        )

    def _check_test(self, task_id: str, test: AcceptanceTest) -> VerificationResult:
        artifact, target_path, error = self._artifact_file(task_id, test.path)
        evidence = {}
        if artifact:
            evidence = {
                "artifact_id": artifact["id"],
                "path": test.path,
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
            }
        if error:
            return VerificationResult(
                name=f"{test.type}:{test.path}",
                passed=False,
                detail=error,
                evidence=evidence,
            )
        target = resolve_in_workspace(self.settings.workspace_dir, test.path)
        data = target.read_bytes()
        if test.type == "file_exists":
            passed, detail = True, "file exists"
        elif test.type == "file_not_empty":
            passed = len(data) > 0
            detail = f"file has {len(data)} bytes"
        elif test.type == "file_contains":
            text = data.decode("utf-8", errors="replace")
            needle = test.text or ""
            if test.case_sensitive:
                passed = needle in text
            else:
                passed = needle.casefold() in text.casefold()
            detail = (
                f"file contains {needle!r}"
                if passed
                else f"file does not contain {needle!r}"
            )
        else:
            passed, detail = False, f"unsupported acceptance test: {test.type}"
        return VerificationResult(
            name=f"{test.type}:{test.path}",
            passed=passed,
            detail=detail,
            evidence=evidence,
        )

from __future__ import annotations

from app.models import AcceptanceTest, Deliverable, TaskContract
from app.sandbox import sha256_bytes
from app.storage import Storage
from app.verifier import Verifier

from .util import make_settings


def _contract() -> TaskContract:
    return TaskContract(
        objective="Create hello",
        deliverables=[Deliverable(path="notes/hello.md")],
        acceptance_tests=[
            AcceptanceTest(type="file_exists", path="notes/hello.md"),
            AcceptanceTest(type="file_contains", path="notes/hello.md", text="Hello"),
        ],
    )


def test_verifier_passes_when_file_matches_artifact(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("test")
    target = settings.workspace_dir / "notes" / "hello.md"
    target.parent.mkdir(parents=True)
    data = b"Hello from Zuri\n"
    target.write_bytes(data)
    storage.add_artifact(task_id, "notes/hello.md", data, sha256_bytes(data), "worker")
    results = Verifier(settings, storage).run(task_id, _contract())
    assert results
    assert all(result.passed for result in results)


def test_verifier_fails_without_ledger_artifact(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("test")
    target = settings.workspace_dir / "notes" / "hello.md"
    target.parent.mkdir(parents=True)
    target.write_text("Hello from Zuri\n", encoding="utf-8")
    results = Verifier(settings, storage).run(task_id, _contract())
    assert any(not result.passed for result in results)
    assert all(
        "no ledger artifact" in result.detail
        for result in results
        if not result.passed
    )


def test_verifier_contains_is_case_insensitive_by_default(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("test")
    target = settings.workspace_dir / "notes" / "hello.md"
    target.parent.mkdir(parents=True)
    data = b"Agent Registry\n"
    target.write_bytes(data)
    storage.add_artifact(task_id, "notes/hello.md", data, sha256_bytes(data), "worker")
    contract = TaskContract(
        objective="Case test",
        deliverables=[Deliverable(path="notes/hello.md")],
        acceptance_tests=[
            AcceptanceTest(
                type="file_contains", path="notes/hello.md", text="agent registry"
            )
        ],
    )
    results = Verifier(settings, storage).run(task_id, contract)
    assert all(result.passed for result in results)


def test_verifier_contains_can_be_case_sensitive(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("test")
    target = settings.workspace_dir / "notes" / "hello.md"
    target.parent.mkdir(parents=True)
    data = b"Agent Registry\n"
    target.write_bytes(data)
    storage.add_artifact(task_id, "notes/hello.md", data, sha256_bytes(data), "worker")
    contract = TaskContract(
        objective="Case test",
        deliverables=[Deliverable(path="notes/hello.md")],
        acceptance_tests=[
            AcceptanceTest(
                type="file_contains",
                path="notes/hello.md",
                text="agent registry",
                case_sensitive=True,
            )
        ],
    )
    results = Verifier(settings, storage).run(task_id, contract)
    assert any(not result.passed for result in results)


def test_verifier_fails_if_file_changed_after_write(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("test")
    target = settings.workspace_dir / "notes" / "hello.md"
    target.parent.mkdir(parents=True)
    data = b"Hello from Zuri\n"
    target.write_bytes(data)
    storage.add_artifact(task_id, "notes/hello.md", data, sha256_bytes(data), "worker")
    target.write_text("tampered\n", encoding="utf-8")
    results = Verifier(settings, storage).run(task_id, _contract())
    assert any(not result.passed for result in results)


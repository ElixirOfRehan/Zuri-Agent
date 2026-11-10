from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import AcceptanceTest, Budget, Deliverable, TaskContract


def test_valid_contract():
    contract = TaskContract(
        objective="Create a note",
        deliverables=[Deliverable(path="notes/hello.md")],
        acceptance_tests=[
            AcceptanceTest(type="file_contains", path="notes/hello.md", text="hello")
        ],
        budget=Budget(max_steps=5, max_tokens=1000, max_cost_usd=0.05),
    )
    assert contract.deliverables[0].path == "notes/hello.md"


def test_absolute_path_rejected():
    with pytest.raises(ValidationError):
        TaskContract(
            objective="bad",
            deliverables=[Deliverable(path="C:\\temp\\x.txt")],
            acceptance_tests=[AcceptanceTest(type="file_exists", path="x.txt")],
        )


def test_test_path_must_match_deliverable():
    with pytest.raises(ValidationError):
        TaskContract(
            objective="bad",
            deliverables=[Deliverable(path="notes/a.md")],
            acceptance_tests=[AcceptanceTest(type="file_exists", path="notes/b.md")],
        )


def test_contains_requires_text():
    with pytest.raises(ValidationError):
        AcceptanceTest(type="file_contains", path="notes/a.md")

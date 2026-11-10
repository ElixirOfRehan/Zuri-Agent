from __future__ import annotations

import pytest

from app.sandbox import SandboxError, normalize_relative, resolve_in_workspace


def test_normalize_relative_accepts_nested_paths():
    assert normalize_relative("notes/hello.md") == "notes/hello.md"
    assert normalize_relative("notes\\hello.md") == "notes/hello.md"
    assert normalize_relative("./notes/hello.md") == "notes/hello.md"


@pytest.mark.parametrize(
    "value",
    ["", "  ", "/absolute.txt", "C:\\Windows\\x.txt", "../escape.txt", "a/../../b.txt"],
)
def test_normalize_relative_rejects_unsafe_paths(value):
    with pytest.raises(SandboxError):
        normalize_relative(value)


def test_resolve_in_workspace_stays_inside(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = resolve_in_workspace(workspace, "a/b.txt")
    assert str(target).startswith(str(workspace.resolve()))


def test_resolve_in_workspace_rejects_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SandboxError):
        resolve_in_workspace(workspace, "../outside.txt")

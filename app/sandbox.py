from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path, PureWindowsPath


class SandboxError(ValueError):
    """Raised when a path escapes the workspace or is not a safe relative path."""


def normalize_relative(raw: str) -> str:
    """Validate a workspace-relative path and return it with '/' separators."""
    if not isinstance(raw, str):
        raise SandboxError("path must be a string")
    text = raw.strip()
    if not text:
        raise SandboxError("path is empty")
    if "\x00" in text:
        raise SandboxError("path contains NUL")
    windows = PureWindowsPath(text)
    if windows.is_absolute() or windows.drive or windows.root:
        raise SandboxError("absolute or rooted paths are not allowed")
    if text.startswith(("/", "\\")):
        raise SandboxError("absolute or rooted paths are not allowed")
    parts: list[str] = []
    for part in text.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise SandboxError("path traversal is not allowed")
        parts.append(part)
    if not parts:
        raise SandboxError("path resolves to the workspace root")
    return "/".join(parts)


def resolve_in_workspace(root: Path, raw: str) -> Path:
    """Resolve a user path inside the workspace, rejecting escapes and symlinks out."""
    rel = normalize_relative(raw)
    root_res = root.resolve()
    target = (root_res / Path(*rel.split("/"))).resolve()
    common = os.path.commonpath(
        [os.path.normcase(str(root_res)), os.path.normcase(str(target))]
    )
    if common != os.path.normcase(str(root_res)):
        raise SandboxError("path escapes the workspace")
    if target == root_res:
        raise SandboxError("path resolves to the workspace root")
    return target


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        for attempt in range(5):
            try:
                os.replace(temp_name, path)
                return
            except PermissionError:
                if attempt == 4:
                    break
                time.sleep(0.1)
        # Windows can briefly lock a destination (indexer/antivirus). Fall back
        # to an in-place write; the caller's audit record still preserves the
        # intended content identity.
        with open(path, "wb") as handle:
            handle.write(data)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

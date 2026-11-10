from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .sandbox import (
    SandboxError,
    normalize_relative,
    resolve_in_workspace,
    sha256_bytes,
    write_atomic,
)
from .storage import Storage

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders inside the workspace (non-recursive).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative folder path. Defaults to the workspace root.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a UTF-8 text file inside the workspace. "
                "Parent folders are created automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
]


KNOWN_TOOLS = {"list_dir", "read_file", "write_file"}


class ToolSet:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        task_id: str,
        agent: str,
        allowed_tools: list[str] | None = None,
    ):
        self.settings = settings
        self.storage = storage
        self.task_id = task_id
        self.agent = agent
        self.allowed = set(allowed_tools) if allowed_tools is not None else set(KNOWN_TOOLS)

    def definitions(self) -> list[dict]:
        return [
            definition
            for definition in TOOL_DEFINITIONS
            if definition["function"]["name"] in self.allowed
        ]

    def execute(self, name: str, arguments: dict) -> str:
        if name not in self.allowed:
            return json.dumps({"error": f"tool not granted to this agent: {name}"})
        try:
            if name == "list_dir":
                return self._list_dir(str(arguments.get("path", ".")))
            if name == "read_file":
                return self._read_file(str(arguments.get("path", "")))
            if name == "write_file":
                return self._write_file(
                    str(arguments.get("path", "")), str(arguments.get("content", ""))
                )
            return json.dumps({"error": f"unknown tool: {name}"})
        except SandboxError as error:
            return json.dumps({"error": f"sandbox: {error}"})
        except OSError as error:
            return json.dumps({"error": f"filesystem: {error}"})
        except Exception as error:  # noqa: BLE001 - tool errors go back to the model
            return json.dumps({"error": f"tool failed: {error}"})

    def _list_dir(self, raw: str) -> str:
        if raw.strip() in ("", ".", "./", ".\\"):
            folder = self.settings.workspace_dir.resolve()
        else:
            folder = resolve_in_workspace(self.settings.workspace_dir, raw)
        if not folder.is_dir():
            return json.dumps({"error": f"not a directory: {raw}"})
        entries = []
        for entry in sorted(folder.iterdir(), key=lambda item: item.name.lower())[:200]:
            entries.append(
                {
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "bytes": entry.stat().st_size if entry.is_file() else None,
                }
            )
        return json.dumps({"path": raw or ".", "entries": entries}, ensure_ascii=False)

    def _read_file(self, raw: str) -> str:
        target = resolve_in_workspace(self.settings.workspace_dir, raw)
        if not target.is_file():
            return json.dumps({"error": f"not a file: {raw}"})
        data = target.read_bytes()
        truncated = len(data) > self.settings.max_read_bytes
        if truncated:
            data = data[: self.settings.max_read_bytes]
        text = data.decode("utf-8", errors="replace")
        return json.dumps(
            {
                "path": normalize_relative(raw),
                "bytes": target.stat().st_size,
                "truncated": truncated,
                "content": text,
            },
            ensure_ascii=False,
        )

    def _write_file(self, raw: str, content: str) -> str:
        target = resolve_in_workspace(self.settings.workspace_dir, raw)
        data = content.encode("utf-8")
        if len(data) > self.settings.max_write_bytes:
            return json.dumps(
                {"error": f"file too large: {len(data)} > {self.settings.max_write_bytes}"}
            )
        write_atomic(target, data)
        digest = sha256_bytes(data)
        relative = normalize_relative(raw)
        artifact = self.storage.add_artifact(
            self.task_id, relative, data, digest, producer=self.agent
        )
        return json.dumps(
            {
                "path": relative,
                "sha256": digest,
                "bytes": len(data),
                "artifact_id": artifact["id"],
            }
        )

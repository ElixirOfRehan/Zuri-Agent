from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
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
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run an allowlisted program inside the workspace without a shell. "
                "Use for python, node, npm, git, pytest and rea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "program": {"type": "string"},
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Argument list; no shell quoting.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 600,
                    },
                },
                "required": ["program"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_blocked",
            "description": (
                "Report that the task cannot be completed and why. Use this "
                "instead of claiming success when blocked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": [
                            "policy_legal",
                            "missing_input",
                            "missing_access",
                            "tool_unavailable",
                            "external_failure",
                            "ambiguity",
                        ],
                    },
                    "detail": {"type": "string"},
                    "needed": {"type": "string"},
                    "goal_blocked": {
                        "type": "boolean",
                        "description": "True only if the goal itself is disallowed.",
                    },
                },
                "required": ["reason", "detail"],
            },
        },
    },
]


KNOWN_TOOLS = {"list_dir", "read_file", "write_file", "run_command"}
CONTROL_TOOLS = {"report_blocked"}

GIT_BLOCKED = {"push", "pull", "fetch", "clone", "remote", "submodule"}
NPM_BLOCKED = {"install", "publish", "exec", "ci", "link", "unpublish", "add"}
OUTPUT_LIMIT = 20_000


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
        self.blocked: dict | None = None

    def definitions(self) -> list[dict]:
        return [
            definition
            for definition in TOOL_DEFINITIONS
            if definition["function"]["name"] in self.allowed
            or definition["function"]["name"] in CONTROL_TOOLS
        ]

    def execute(self, name: str, arguments: dict) -> str:
        if name == "report_blocked":
            return self._report_blocked(arguments)
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
            if name == "run_command":
                return self._run_command(arguments)
            return json.dumps({"error": f"unknown tool: {name}"})
        except SandboxError as error:
            return json.dumps({"error": f"sandbox: {error}"})
        except OSError as error:
            return json.dumps({"error": f"filesystem: {error}"})
        except Exception as error:  # noqa: BLE001 - tool errors go back to the model
            return json.dumps({"error": f"tool failed: {error}"})

    def _run_command(self, arguments: dict) -> str:
        if not self.settings.shell_enabled:
            return json.dumps({"error": "shell is disabled"})
        program = str(arguments.get("program", "")).strip().lower()
        allowed = {item.lower() for item in self.settings.allowed_commands}
        if program not in allowed:
            return json.dumps(
                {
                    "error": f"program not allowed: {program}",
                    "allowed": sorted(allowed),
                }
            )
        raw_args = arguments.get("arguments", [])
        if raw_args is None:
            raw_args = []
        if not isinstance(raw_args, list) or any(
            not isinstance(item, str) for item in raw_args
        ):
            return json.dumps({"error": "arguments must be a list of strings"})
        args = list(raw_args)
        for arg in args:
            if self._unsafe_argument(arg):
                return json.dumps({"error": f"unsafe argument blocked: {arg}"})
        policy_error = self._command_policy(program, args)
        if policy_error:
            return json.dumps({"error": policy_error})
        try:
            timeout = int(arguments.get("timeout_seconds", 120))
        except (TypeError, ValueError):
            timeout = 120
        timeout = max(1, min(600, timeout))
        executable = self._resolve_program(program)
        if executable is None:
            return json.dumps({"error": f"program not found: {program}"})
        command = [executable, *args]
        if program == "pytest":
            command = [sys.executable, "-m", "pytest", *args]
        started = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.settings.workspace_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            self.storage.add_event(
                self.task_id,
                self.agent,
                "command_output",
                {
                    "program": program,
                    "arguments": args,
                    "error": "timeout",
                    "timeout_seconds": timeout,
                },
            )
            return json.dumps(
                {"error": f"command timed out after {timeout}s", "program": program}
            )
        except OSError as error:
            return json.dumps({"error": f"command failed to start: {error}"})
        duration = round(time.time() - started, 3)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        truncated = len(stdout) > OUTPUT_LIMIT or len(stderr) > OUTPUT_LIMIT
        stdout = stdout[:OUTPUT_LIMIT]
        stderr = stderr[:OUTPUT_LIMIT]
        self.storage.add_event(
            self.task_id,
            self.agent,
            "command_output",
            {
                "program": program,
                "arguments": args,
                "exit_code": completed.returncode,
                "duration_seconds": duration,
                "stdout": stdout[:4000],
                "stderr": stderr[:4000],
                "truncated": truncated,
            },
        )
        return json.dumps(
            {
                "program": program,
                "arguments": args,
                "exit_code": completed.returncode,
                "duration_seconds": duration,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": truncated,
            }
        )

    @staticmethod
    def _unsafe_argument(argument: str) -> bool:
        if argument.startswith("-"):
            return False
        if re.match(r"^[A-Za-z]:[\\/]", argument):
            return True
        if argument.startswith(("/", "\\")):
            return True
        parts = argument.replace("\\", "/").split("/")
        return ".." in parts

    @staticmethod
    def _command_policy(program: str, args: list[str]) -> str | None:
        if program == "git":
            if "--global" in args or "--system" in args:
                return "global/system git config is not allowed"
            subcommand = None
            skip = False
            for item in args:
                if skip:
                    skip = False
                    continue
                if item in {"-C", "-c", "--git-dir", "--work-tree"}:
                    skip = True
                    continue
                if item.startswith("-"):
                    continue
                subcommand = item.lower()
                break
            if subcommand in GIT_BLOCKED:
                return f"git {subcommand} is blocked (network/remote)"
        if program == "npm":
            for item in args:
                if item.lower() in NPM_BLOCKED:
                    return f"npm {item} is blocked (network/install)"
        return None

    def _resolve_program(self, program: str) -> str | None:
        if program in {"python", "python3", "py", "pytest"}:
            return sys.executable
        return shutil.which(program)

    def _report_blocked(self, arguments: dict) -> str:
        reason = str(arguments.get("reason", "")).strip()
        allowed = {
            "policy_legal",
            "missing_input",
            "missing_access",
            "tool_unavailable",
            "external_failure",
            "ambiguity",
        }
        if reason not in allowed:
            return json.dumps({"error": f"invalid blocked reason: {reason}"})
        self.blocked = {
            "reason": reason,
            "detail": str(arguments.get("detail", "")).strip(),
            "needed": str(arguments.get("needed", "")).strip(),
            "goal_blocked": bool(arguments.get("goal_blocked", False)),
        }
        return json.dumps({"blocked": True, **self.blocked})

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

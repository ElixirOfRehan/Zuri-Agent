from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

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
            "name": "run_opencode",
            "description": (
                "Delegate a coding change to OpenCode. It can read and edit files "
                "in the workspace but cannot run shell or use the network. Use it "
                "for substantial code edits, then inspect and test the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed coding instruction.",
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional provider/model; defaults to the configured model.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 600,
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": (
                "Fetch a public http(s) URL with GET only. No auth, cookies, "
                "localhost or private networks. Returns status, type and text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_page",
            "description": (
                "Open a public web page in headless Chrome, wait briefly, and "
                "return title, visible text and links. No clicks, forms, auth or "
                "private networks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "wait_ms": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 5000,
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 20000,
                    },
                },
                "required": ["url"],
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


KNOWN_TOOLS = {
    "list_dir",
    "read_file",
    "write_file",
    "run_command",
    "run_opencode",
    "http_get",
    "browse_page",
}
CONTROL_TOOLS = {"report_blocked"}
HTTP_MAX_BYTES = 2_000_000
PUBLIC_PORTS = {80, 443}

OPENCODE_PERMISSIONS = {
    "$schema": "https://opencode.ai/config.json",
    "permission": {
        "edit": "allow",
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "external_directory": "deny",
        "task": "deny",
    },
    "mcp": {"rea": {"enabled": False}},
}

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
            if name == "run_opencode":
                return self._run_opencode(arguments)
            if name == "http_get":
                return self._http_get(arguments)
            if name == "browse_page":
                return self._browse_page(arguments)
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

    def _run_opencode(self, arguments: dict) -> str:
        if not self.settings.shell_enabled:
            return json.dumps({"error": "shell/opencode is disabled"})
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            return json.dumps({"error": "prompt is empty"})
        model = str(arguments.get("model") or self.settings.opencode_model).strip()
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+$", model):
            return json.dumps({"error": f"invalid model: {model}"})
        executable = shutil.which("opencode")
        if executable is None:
            return json.dumps({"error": "opencode CLI not found on PATH"})
        try:
            timeout = int(arguments.get("timeout_seconds", 300))
        except (TypeError, ValueError):
            timeout = 300
        timeout = max(1, min(600, timeout))
        environment = os.environ.copy()
        environment["OPENCODE_CONFIG_CONTENT"] = json.dumps(OPENCODE_PERMISSIONS)
        environment["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
        command = [
            executable,
            "run",
            "--format",
            "json",
            "--model",
            model,
            "--dir",
            str(self.settings.workspace_dir),
            "--pure",
            prompt,
        ]
        started = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.settings.workspace_dir),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"opencode timed out after {timeout}s"})
        except OSError as error:
            return json.dumps({"error": f"opencode failed to start: {error}"})
        duration = round(time.time() - started, 3)
        text_parts: list[str] = []
        errors: list[str] = []
        session_id = None
        cost = 0.0
        input_tokens = 0
        output_tokens = 0
        for line in (completed.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            session_id = event.get("sessionID") or session_id
            part = event.get("part") or {}
            if event.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
            elif event.get("type") == "step_finish":
                cost += float(part.get("cost") or 0)
                tokens = part.get("tokens") or {}
                input_tokens += int(tokens.get("input") or 0)
                output_tokens += int(tokens.get("output") or 0)
            elif event.get("type") == "error":
                errors.append(json.dumps(event, ensure_ascii=False)[:1000])
        text = "".join(text_parts).strip()
        stderr = (completed.stderr or "")[:4000]
        if completed.returncode != 0 or errors:
            output = {
                "error": "opencode failed",
                "exit_code": completed.returncode,
                "stderr": stderr,
                "events": errors[:3],
                "text": text[:4000],
                "duration_seconds": duration,
            }
            self.storage.add_event(self.task_id, self.agent, "opencode_run", output)
            return json.dumps(output)
        if cost or input_tokens or output_tokens:
            self.storage.add_cost(
                self.task_id,
                "opencode",
                model,
                input_tokens,
                output_tokens,
                cost,
            )
        event_data = {
            "model": model,
            "prompt_preview": prompt[:500],
            "session_id": session_id,
            "text": text[:4000],
            "cost_usd": cost,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "exit_code": completed.returncode,
            "duration_seconds": duration,
            "stderr": stderr,
        }
        self.storage.add_event(self.task_id, self.agent, "opencode_run", event_data)
        return json.dumps(
            {
                "text": text[:20000],
                "cost_usd": cost,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "session_id": session_id,
                "exit_code": completed.returncode,
                "stderr": stderr,
                "duration_seconds": duration,
            }
        )

    def _validate_public_url(self, raw: str) -> tuple[str | None, str | None]:
        try:
            parsed = urlparse(raw)
        except ValueError as error:
            return None, str(error)
        if parsed.scheme not in {"http", "https"}:
            return None, "only http/https is allowed"
        if not parsed.hostname:
            return None, "missing host"
        if parsed.username or parsed.password:
            return None, "URL credentials are not allowed"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in PUBLIC_PORTS:
            return None, f"port is not allowed: {port}"
        host = parsed.hostname.strip().rstrip(".").lower()
        if not host:
            return None, "missing host"
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            return None, "local host is blocked"
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as error:
            return None, f"DNS lookup failed: {error}"
        if not infos:
            return None, "no addresses resolved"
        for info in infos:
            address = info[4][0].split("%")[0]
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                return None, f"invalid address: {address}"
            if not ip.is_global:
                return None, f"non-public address is blocked: {address}"
        netloc = f"[{host}]" if ":" in host else host
        return parsed._replace(netloc=netloc, fragment="").geturl(), None

    def _http_get(self, arguments: dict) -> str:
        if not self.settings.network_enabled:
            return json.dumps({"error": "network tools are disabled"})
        url = str(arguments.get("url", "")).strip()
        if not url:
            return json.dumps({"error": "url is empty"})
        current, error = self._validate_public_url(url)
        if current is None:
            return json.dumps({"error": error})
        headers = {"User-Agent": "ZuriAgent/1.0 (local research)"}
        try:
            with httpx.Client(
                follow_redirects=False, timeout=20.0, headers=headers
            ) as client:
                for _redirect in range(6):
                    with client.stream("GET", current) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                return json.dumps(
                                    {"error": "redirect without location"}
                                )
                            next_url, error = self._validate_public_url(
                                urljoin(current, location)
                            )
                            if next_url is None:
                                return json.dumps(
                                    {"error": f"redirect blocked: {error}"}
                                )
                            current = next_url
                            continue
                        chunks: list[bytes] = []
                        total = 0
                        truncated = False
                        for chunk in response.iter_bytes():
                            remaining = HTTP_MAX_BYTES - total
                            if remaining <= 0:
                                truncated = True
                                break
                            if len(chunk) > remaining:
                                chunks.append(chunk[:remaining])
                                total += remaining
                                truncated = True
                                break
                            chunks.append(chunk)
                            total += len(chunk)
                        raw = b"".join(chunks)
                        content_type = response.headers.get("content-type", "")
                        main_type = content_type.split(";")[0].strip().lower()
                        is_text = (
                            main_type.startswith("text/")
                            or main_type
                            in {
                                "application/json",
                                "application/xml",
                                "application/xhtml+xml",
                                "application/javascript",
                            }
                            or main_type.endswith(("+json", "+xml"))
                        )
                        text = (
                            raw.decode("utf-8", errors="replace") if is_text else ""
                        )
                        result = {
                            "url": url,
                            "final_url": current,
                            "status_code": response.status_code,
                            "content_type": content_type,
                            "bytes": len(raw),
                            "truncated": truncated,
                            "text": text[:20000],
                        }
                        self.storage.add_event(
                            self.task_id,
                            self.agent,
                            "http_get",
                            {
                                "url": url,
                                "final_url": current,
                                "status_code": response.status_code,
                                "content_type": content_type,
                                "bytes": len(raw),
                                "truncated": truncated,
                            },
                        )
                        return json.dumps(result)
                return json.dumps({"error": "too many redirects"})
        except httpx.HTTPError as error:
            self.storage.add_event(
                self.task_id,
                self.agent,
                "http_get",
                {"url": url, "error": str(error)},
            )
            return json.dumps({"error": f"request failed: {error}"})

    def _browser_executable(self) -> str | None:
        if self.settings.browser_executable:
            return self.settings.browser_executable
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        return shutil.which("chrome") or shutil.which("msedge")

    def _browse_page(self, arguments: dict) -> str:
        if not self.settings.network_enabled:
            return json.dumps({"error": "network tools are disabled"})
        url = str(arguments.get("url", "")).strip()
        if not url:
            return json.dumps({"error": "url is empty"})
        validated, error = self._validate_public_url(url)
        if validated is None:
            return json.dumps({"error": error})
        executable = self._browser_executable()
        if not executable:
            return json.dumps({"error": "browser executable not found"})
        try:
            from playwright.sync_api import sync_playwright
        except Exception as error:  # noqa: BLE001
            return json.dumps({"error": f"playwright unavailable: {error}"})
        try:
            wait_ms = int(arguments.get("wait_ms", 500))
        except (TypeError, ValueError):
            wait_ms = 500
        wait_ms = max(0, min(5000, wait_ms))
        try:
            max_chars = int(arguments.get("max_chars", 12000))
        except (TypeError, ValueError):
            max_chars = 12000
        max_chars = max(1000, min(20000, max_chars))
        timeout = 60
        blocked: list[str] = []
        started = time.time()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=executable,
                    headless=True,
                    args=[
                        "--disable-background-networking",
                        "--disable-extensions",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-sync",
                        "--disable-component-update",
                    ],
                )
                try:
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 720}
                    )
                    page = context.new_page()
                    page.set_default_timeout(timeout * 1000)

                    def route_handler(route):
                        allowed, _reason = self._validate_public_url(
                            route.request.url
                        )
                        if allowed is None:
                            blocked.append(route.request.url)
                            route.abort()
                            return
                        route.continue_()

                    page.route("**/*", route_handler)
                    response = page.goto(
                        validated,
                        wait_until="domcontentloaded",
                        timeout=timeout * 1000,
                    )
                    if wait_ms:
                        page.wait_for_timeout(wait_ms)
                    final = page.url
                    final_ok, final_error = self._validate_public_url(final)
                    if final_ok is None:
                        return json.dumps(
                            {"error": f"final page URL blocked: {final_error}"}
                        )
                    title = page.title()
                    try:
                        text = page.inner_text("body")[:max_chars]
                    except Exception:
                        text = ""
                    links = page.eval_on_selector_all(
                        "a[href]",
                        "els => els.slice(0, 100).map(e => e.href)",
                    )
                    links = [
                        link
                        for link in links
                        if isinstance(link, str)
                        and link.startswith(("http://", "https://"))
                    ]
                    duration = round(time.time() - started, 3)
                    result = {
                        "url": url,
                        "final_url": final,
                        "status_code": response.status if response else None,
                        "title": title,
                        "text": text,
                        "links": links,
                        "blocked_requests": len(blocked),
                        "blocked_sample": blocked[:10],
                        "duration_seconds": duration,
                    }
                    self.storage.add_event(
                        self.task_id,
                        self.agent,
                        "browse_page",
                        {
                            "url": url,
                            "final_url": final,
                            "status_code": result["status_code"],
                            "title": title,
                            "text_chars": len(text),
                            "blocked_requests": len(blocked),
                            "duration_seconds": duration,
                        },
                    )
                    return json.dumps(result)
                finally:
                    browser.close()
        except Exception as error:  # noqa: BLE001
            return json.dumps({"error": f"browse failed: {error}"})

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

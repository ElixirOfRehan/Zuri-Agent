from __future__ import annotations

import json
import os

import pytest

from app.agents import load_agent_spec
from app.storage import Storage
from app.tools import ToolSet

from .util import PROJECT_ROOT, make_settings


def _toolset(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    task_id = storage.create_task("web test")
    toolset = ToolSet(
        settings,
        storage,
        task_id,
        "research",
        allowed_tools=["http_get", "browse_page"],
    )
    return settings, storage, task_id, toolset


def test_public_url_validation(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    for url in ("http://1.1.1.1", "https://8.8.8.8"):
        valid, error = toolset._validate_public_url(url)
        assert valid is not None, (url, error)
    for url in (
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://localhost",
        "https://example.com:8080",
        "ftp://1.1.1.1",
        "http://user:pass@1.1.1.1",
    ):
        valid, error = toolset._validate_public_url(url)
        assert valid is None, url
        assert error


def test_network_disabled(tmp_path):
    settings, _storage, _task, toolset = _toolset(tmp_path)
    settings.network_enabled = False
    result = json.loads(
        toolset.execute("http_get", {"url": "https://example.com"})
    )
    assert "disabled" in result["error"]
    result = json.loads(
        toolset.execute("browse_page", {"url": "https://example.com"})
    )
    assert "disabled" in result["error"]


def test_empty_url(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = json.loads(toolset.execute("http_get", {"url": ""}))
    assert "empty" in result["error"]


def test_web_tools_are_granted_to_engineering_and_research():
    engineering = load_agent_spec(
        PROJECT_ROOT / "agents" / "engineering" / "profile.json"
    )
    research = load_agent_spec(
        PROJECT_ROOT / "agents" / "research" / "profile.json"
    )
    assert "http_get" in engineering.tools
    assert "browse_page" in engineering.tools
    assert "http_get" in research.tools
    assert "browse_page" in research.tools
    assert "run_command" not in research.tools


@pytest.mark.skipif(
    os.getenv("ZURI_LIVE_TESTS") != "1", reason="set ZURI_LIVE_TESTS=1"
)
def test_live_http_get(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = json.loads(
        toolset.execute("http_get", {"url": "https://example.com"})
    )
    assert result.get("status_code") == 200
    assert "Example Domain" in result.get("text", "")


@pytest.mark.skipif(
    os.getenv("ZURI_LIVE_TESTS") != "1", reason="set ZURI_LIVE_TESTS=1"
)
def test_live_browse_page(tmp_path):
    _settings, _storage, _task, toolset = _toolset(tmp_path)
    result = json.loads(
        toolset.execute(
            "browse_page",
            {"url": "https://example.com", "wait_ms": 500, "max_chars": 4000},
        )
    )
    assert result.get("status_code") == 200
    assert result.get("title") == "Example Domain"
    assert len(result.get("text", "")) > 20

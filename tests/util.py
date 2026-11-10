from __future__ import annotations

from pathlib import Path

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_settings(root: Path) -> Settings:
    return Settings(
        root=root,
        data_dir=root / "data",
        workspace_dir=root / "workspace",
        api_key="",
        base_url="https://api.deepseek.com",
        boss_model="deepseek-v4-pro",
        worker_model="deepseek-flash",
        boss_spec_path=PROJECT_ROOT / "agents" / "boss" / "profile.json",
        worker_spec_path=PROJECT_ROOT / "agents" / "worker" / "profile.json",
        hr_spec_path=PROJECT_ROOT / "agents" / "hr" / "profile.json",
    )

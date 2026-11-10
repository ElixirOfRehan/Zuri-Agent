from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PRICES = {
    # USD per 1M tokens: (input, output). Off-peak DeepSeek defaults.
    "deepseek-flash": (0.15, 0.60),
    "deepseek-v4-pro": (0.66, 1.98),
}


@dataclass
class Settings:
    root: Path
    data_dir: Path
    workspace_dir: Path
    api_key: str
    base_url: str
    boss_model: str
    worker_model: str
    boss_spec_path: Path
    worker_spec_path: Path
    hr_spec_path: Path
    request_timeout_s: int = 120
    max_read_bytes: int = 65_536
    max_write_bytes: int = 1_000_000
    thinking: str = "disabled"
    prices: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(DEFAULT_PRICES)
    )

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "zuri.db"

    @property
    def ledger_path(self) -> Path:
        return self.data_dir / "ledger.jsonl"

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key) and self.api_key != "sk-your-key-here"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def price(self, model: str) -> tuple[float, float]:
        return self.prices.get(model, (0.0, 0.0))

    def estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        input_price, output_price = self.price(model)
        return (
            prompt_tokens / 1_000_000 * input_price
            + completion_tokens / 1_000_000 * output_price
        )

    @classmethod
    def load(cls, root: str | Path | None = None) -> "Settings":
        root_path = Path(root or os.getenv("ZURI_ROOT") or PROJECT_ROOT).resolve()
        load_dotenv(root_path / ".env")

        data_dir = Path(os.getenv("ZURI_DATA_DIR", "./data"))
        if not data_dir.is_absolute():
            data_dir = (root_path / data_dir).resolve()

        workspace_dir = Path(os.getenv("ZURI_WORKSPACE_DIR", "./workspace"))
        if not workspace_dir.is_absolute():
            workspace_dir = (root_path / workspace_dir).resolve()

        return cls(
            root=root_path,
            data_dir=data_dir,
            workspace_dir=workspace_dir,
            api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            boss_model=os.getenv("ZURI_BOSS_MODEL", "deepseek-v4-pro").strip(),
            worker_model=os.getenv("ZURI_WORKER_MODEL", "deepseek-flash").strip(),
            boss_spec_path=root_path / "agents" / "boss" / "profile.json",
            worker_spec_path=root_path / "agents" / "worker" / "profile.json",
            hr_spec_path=root_path / "agents" / "hr" / "profile.json",
            request_timeout_s=int(os.getenv("ZURI_REQUEST_TIMEOUT_S", "120")),
            thinking=os.getenv("ZURI_THINKING", "disabled").strip().lower(),
        )

"""Configuration loading for StockLong."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_dotenv(path: str | Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Real environment variables always win - a value already set in the shell
    is never overwritten by the file. Lines starting with # and blank lines
    are ignored; surrounding quotes on values are stripped."""
    env_path = Path(path) if path else DEFAULT_ENV_PATH
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        load_dotenv()  # picks up UPSTOX_* credentials from .env if present
        cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(cfg_path) as fh:
            return cls(raw=yaml.safe_load(fh) or {})

    def get(self, dotted: str, default: Any = None) -> Any:
        """Fetch a nested key with dotted notation, e.g. cfg.get("risk.delta_min")."""
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # --- credentials come from the environment, never from the YAML file ---
    @property
    def api_key(self) -> str:
        return _require_env("UPSTOX_API_KEY")

    @property
    def api_secret(self) -> str:
        return _require_env("UPSTOX_API_SECRET")

    @property
    def redirect_uri(self) -> str:
        return os.environ.get(
            "UPSTOX_REDIRECT_URI",
            self.get("upstox.redirect_uri", "http://127.0.0.1:5000/callback"),
        )

    @property
    def token_path(self) -> Path:
        return Path(self.get("upstox.token_path", "data/access_token.json"))

    @property
    def paper_trading(self) -> bool:
        return bool(self.get("paper_trading", True))


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Put it in the .env file at the project root "
            "(copy .env.example) or export it in your shell."
        )
    return value

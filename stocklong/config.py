"""Configuration loading for StockLong."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
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
            f"Environment variable {name} is not set. "
            "Export your Upstox app credentials before running."
        )
    return value

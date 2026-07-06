"""Upstox OAuth2 authentication.

Upstox access tokens are valid for one trading day (they expire at ~3:30 AM IST
the next day), so the login flow must be re-run each morning:

    python scripts/login.py            # prints the authorization URL
    python scripts/login.py <code>     # exchanges the code for an access token

The token is cached on disk and picked up automatically by every other module.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .config import Config

AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


class UpstoxAuth:
    def __init__(self, config: Config):
        self.config = config
        self.token_path: Path = config.token_path

    def login_url(self) -> str:
        params = {
            "response_type": "code",
            "client_id": self.config.api_key,
            "redirect_uri": self.config.redirect_uri,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, auth_code: str) -> str:
        """Exchange the authorization code for an access token and cache it."""
        resp = requests.post(
            TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "code": auth_code,
                "client_id": self.config.api_key,
                "client_secret": self.config.api_secret,
                "redirect_uri": self.config.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload["access_token"]
        self._save(token)
        return token

    def access_token(self) -> str:
        """Return the cached access token, failing loudly if missing/stale."""
        if not self.token_path.exists():
            raise RuntimeError(
                "No cached Upstox access token. Run `python scripts/login.py` first."
            )
        data = json.loads(self.token_path.read_text())
        # Tokens die at ~3:30 AM IST daily; warn when the cache is older than 20h.
        age_hours = (time.time() - data.get("saved_at", 0)) / 3600
        if age_hours > 20:
            raise RuntimeError(
                f"Cached Upstox token is {age_hours:.0f}h old and almost certainly "
                "expired. Re-run `python scripts/login.py`."
            )
        return data["access_token"]

    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token()}",
        }

    def _save(self, token: str) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(
            json.dumps({"access_token": token, "saved_at": time.time()})
        )
        try:
            self.token_path.chmod(0o600)
        except OSError:
            pass

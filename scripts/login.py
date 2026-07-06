#!/usr/bin/env python3
"""Daily Upstox login.

Step 1: python scripts/login.py
        -> prints the authorization URL; open it, log in, and copy the
           `code` query parameter from the redirect.
Step 2: python scripts/login.py <code>
        -> exchanges the code and caches the access token for the day.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stocklong.auth import UpstoxAuth
from stocklong.config import Config


def main() -> None:
    auth = UpstoxAuth(Config.load())
    if len(sys.argv) < 2:
        print("Open this URL, authorize, then re-run with the `code` parameter:\n")
        print(auth.login_url())
        return
    token = auth.exchange_code(sys.argv[1])
    print(f"Access token cached at {auth.token_path} ({token[:8]}...)")


if __name__ == "__main__":
    main()

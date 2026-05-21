from __future__ import annotations

import fcntl
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


class TokenStore:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            with open(self._path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("Token file unreadable; re-authentication required")
            return None

    def save(self, token_response: dict) -> None:
        expires_at = time.time() + token_response.get("expires_in", 3600) - 60
        data = {
            "access_token": token_response["access_token"],
            "refresh_token": token_response.get("refresh_token"),
            "expires_at": expires_at,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            f.flush()
        tmp.replace(self._path)
        log.debug("Tokens saved to %s", self._path)

    def has_tokens(self) -> bool:
        return self.load() is not None

    def is_expired(self) -> bool:
        tokens = self.load()
        if not tokens:
            return True
        return time.time() >= tokens.get("expires_at", 0)

    def access_token(self) -> str | None:
        tokens = self.load()
        return tokens.get("access_token") if tokens else None

    def refresh_token(self) -> str | None:
        tokens = self.load()
        return tokens.get("refresh_token") if tokens else None

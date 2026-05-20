from __future__ import annotations

import fcntl
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


class SyncState:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        with open(self._path) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                log.warning("State file corrupt; starting fresh")
                return {}

    def save(self, state: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        state["schema_version"] = _SCHEMA_VERSION
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(state, f, indent=2)
            f.flush()
        tmp.replace(self._path)
        log.debug("State saved to %s", self._path)

    def last_sync_utc(self) -> datetime | None:
        state = self.load()
        ts = state.get("last_sync_utc")
        if ts:
            return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        return None

    def mark_synced(self, up_to: datetime) -> None:
        state = self.load()
        state["last_sync_utc"] = up_to.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.save(state)

    def reset(self) -> None:
        if self._path.exists():
            self._path.unlink()
            log.info("State reset: %s deleted", self._path)

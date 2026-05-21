from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_BATCH_SIZE = 500


class HKWriteError(Exception):
    pass


class HKAuthError(HKWriteError):
    pass


@dataclass
class WriteResult:
    written: int
    skipped: int = 0


class HKWriterBridge:
    def __init__(self, binary_path: Path):
        if not binary_path.exists():
            raise FileNotFoundError(
                f"Swift HealthKit writer not found at {binary_path}.\n"
                "Run ./scripts/build_swift.sh to build it."
            )
        self._binary = binary_path

    def write_payload(self, payload: dict) -> WriteResult:
        quantities = payload.get("quantities", [])
        sleep_stages = payload.get("sleepStages", [])

        total_written = 0
        total_skipped = 0

        for batch in _chunks(quantities, _BATCH_SIZE):
            r = self._invoke({
                "action": "write",
                "quantities": batch,
                "sleepStages": [],
            })
            total_written += r.get("written", 0)
            total_skipped += r.get("skipped", 0)

        if sleep_stages:
            r = self._invoke({
                "action": "write",
                "quantities": [],
                "sleepStages": sleep_stages,
            })
            total_written += r.get("written", 0)
            total_skipped += r.get("skipped", 0)

        return WriteResult(written=total_written, skipped=total_skipped)

    def query_sleep(self, start: datetime, end: datetime) -> list[dict]:
        """Return HealthKit sleep samples overlapping [start, end].

        Each dict has keys: startDate, endDate, value, sourceName.
        Returns [] on auth errors so callers can degrade gracefully.
        """
        try:
            response = self._invoke({
                "action": "query-sleep",
                "start": _iso(start),
                "end": _iso(end),
            })
        except HKAuthError:
            log.info("Sleep read authorization not granted; skipping HK sleep lookup")
            return []
        return response.get("sleepSamples", [])

    def _invoke(self, payload: dict) -> dict:
        payload_bytes = json.dumps(payload).encode()
        log.debug("Calling Swift bridge: action=%s", payload.get("action"))
        try:
            result = subprocess.run(
                [str(self._binary)],
                input=payload_bytes,
                capture_output=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise HKWriteError("Swift bridge timed out after 60s") from exc

        try:
            response = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            stderr = result.stderr.decode(errors="replace")
            raise HKWriteError(
                f"Swift bridge returned non-JSON output.\nstderr: {stderr}"
            ) from exc

        if response.get("status") == "error":
            code = response.get("code", -1)
            message = response.get("message", "unknown error")
            if code == 5:  # HKErrorAuthorizationDenied
                raise HKAuthError(
                    "HealthKit authorization denied. "
                    "Open System Settings → Privacy & Security → Health and grant access."
                )
            raise HKWriteError(f"HealthKit call failed (code {code}): {message}")

        return response


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]

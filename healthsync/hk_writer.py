from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
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

        # Batch quantity samples to stay within HK limits
        for batch in _chunks(quantities, _BATCH_SIZE):
            r = self._write({"quantities": batch, "sleepStages": []})
            total_written += r.written
            total_skipped += r.skipped

        # Sleep stages are typically small; send in one call
        if sleep_stages:
            r = self._write({"quantities": [], "sleepStages": sleep_stages})
            total_written += r.written
            total_skipped += r.skipped

        return WriteResult(written=total_written, skipped=total_skipped)

    def _write(self, payload: dict) -> WriteResult:
        payload_bytes = json.dumps(payload).encode()
        log.debug(
            "Calling Swift writer: %d quantities, %d sleep stages",
            len(payload.get("quantities", [])),
            len(payload.get("sleepStages", [])),
        )
        try:
            result = subprocess.run(
                [str(self._binary)],
                input=payload_bytes,
                capture_output=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise HKWriteError("Swift writer timed out after 60s") from exc

        try:
            response = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            stderr = result.stderr.decode(errors="replace")
            raise HKWriteError(
                f"Swift writer returned non-JSON output.\nstderr: {stderr}"
            ) from exc

        if response.get("status") == "error":
            code = response.get("code", -1)
            message = response.get("message", "unknown error")
            if code == 5:  # HKErrorAuthorizationDenied
                raise HKAuthError(
                    "HealthKit authorization denied. "
                    "Open System Settings → Privacy & Security → Health and grant access."
                )
            raise HKWriteError(f"HealthKit write failed (code {code}): {message}")

        return WriteResult(
            written=response.get("written", 0),
            skipped=response.get("skipped", 0),
        )


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]

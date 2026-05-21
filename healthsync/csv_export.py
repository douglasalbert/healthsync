from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from healthsync.config import Config
from healthsync.models import build_hk_payload
from healthsync.token_store import TokenStore
from healthsync.whoop_client import WhoopClient

log = logging.getLogger(__name__)

HEADER = ["type", "value", "stage", "unit", "startDate", "endDate"]

# Maps HKQuantityTypeIdentifier → short type name used in the CSV / Shortcut.
_QUANTITY_TYPE_MAP: dict[str, str] = {
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "HKQuantityTypeIdentifierRestingHeartRate": "restingHr",
    "HKQuantityTypeIdentifierOxygenSaturation": "oxygenSaturation",
    "HKQuantityTypeIdentifierRespiratoryRate": "respiratoryRate",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "activeEnergy",
    "HKQuantityTypeIdentifierBodyTemperature": "bodyTemp",
    "HKQuantityTypeIdentifierHeartRate": "heartRate",
}


def payload_to_csv_rows(payload: dict) -> list[list[str]]:
    """Convert a `build_hk_payload` dict to CSV rows (header first).

    Each row has the same six columns as HEADER.
    Unknown quantity type identifiers are skipped with a warning.
    Uses str(value) for numbers so csv.writer sees clean strings.
    """
    rows: list[list[str]] = [HEADER]

    for q in payload.get("quantities", []):
        hk_id = q.get("typeIdentifier", "")
        short = _QUANTITY_TYPE_MAP.get(hk_id)
        if short is None:
            log.warning("Skipping unknown quantity type: %s", hk_id)
            continue
        rows.append([
            short,
            str(q.get("value", "")),
            "",                          # stage — empty for quantities
            q.get("unit", ""),
            q.get("startDate", ""),
            q.get("endDate", ""),
        ])

    for s in payload.get("sleepStages", []):
        rows.append([
            "sleep",
            "",                          # value — empty for sleep
            s.get("stage", ""),
            "",                          # unit — not applicable for sleep
            s.get("startDate", ""),
            s.get("endDate", ""),
        ])

    return rows


def rows_to_csv_text(rows: list[list[str]]) -> str:
    """Serialize rows to CSV text using csv.writer (handles quoting/escaping)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerows(rows)
    return buf.getvalue()


def run_csv_export(
    config: Config,
    since: datetime | None = None,
    output: Path | None = None,
) -> Path:
    """Fetch all WHOOP data since `since` and write a CSV to `output`.

    Returns the path of the written file.
    """
    token_store = TokenStore(config.paths.token_file)
    now = datetime.now(tz=timezone.utc)

    if since is None:
        since = now - timedelta(days=365 * 10)

    client = WhoopClient(config.oauth.client_id, config.oauth.client_secret, token_store)

    log.info("Fetching cycles %s → %s", since.date(), now.date())
    cycles = client.get_cycles(since, now)

    log.info("Fetching sleep %s → %s", since.date(), now.date())
    sleep_records = client.get_sleep(since, now)

    payload = build_hk_payload([], cycles, sleep_records, config.healthkit)
    rows = payload_to_csv_rows(payload)
    n_data_rows = len(rows) - 1  # subtract header
    log.info("CSV export: %d rows (%d quantities, %d sleep stages)",
             n_data_rows,
             len(payload["quantities"]),
             len(payload["sleepStages"]))

    if output is None:
        config.paths.export_dir.mkdir(parents=True, exist_ok=True)
        fname = f"healthsync_export_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        output = config.paths.export_dir / fname

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rows_to_csv_text(rows), encoding="utf-8")

    log.info("Saved CSV export to %s", output)
    return output

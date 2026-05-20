from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from healthsync.config import Config
from healthsync.hk_writer import HKWriterBridge
from healthsync.models import build_hk_payload
from healthsync.state import SyncState
from healthsync.whoop_client import WhoopClient

log = logging.getLogger(__name__)


def run_sync(config: Config, dry_run: bool = False) -> None:
    state = SyncState(config.paths.state_file)
    now = datetime.now(tz=timezone.utc)

    last_sync = state.last_sync_utc()
    if last_sync is None:
        start = now - timedelta(days=config.sync.lookback_days)
        log.info("First run — pulling last %d days", config.sync.lookback_days)
    else:
        start = last_sync
        log.info("Resuming from last sync: %s", start.isoformat())

    if not dry_run:
        writer = HKWriterBridge(config.paths.swift_binary)

    client = WhoopClient(config.whoop.username, config.whoop.password)

    # --- fetch ---
    cycles = client.get_cycles(start, now)
    hr_samples = []
    if config.healthkit.write_heart_rate:
        hr_samples = client.get_heart_rate(
            start, now, step=config.sync.heart_rate_step_seconds
        )
    sleep_records = []
    if config.healthkit.write_sleep_stages:
        sleep_records = client.get_sleep(start, now)

    # Log recovery / strain for visibility even though we don't write them to HK
    for cycle in cycles:
        if cycle.recovery_score is not None:
            log.info(
                "Cycle %s: recovery=%.0f strain=%s",
                cycle.cycle_id,
                cycle.recovery_score,
                f"{cycle.strain:.1f}" if cycle.strain is not None else "n/a",
            )

    # --- build HK payload ---
    payload = build_hk_payload(hr_samples, cycles, sleep_records, config.healthkit)
    total_quantities = len(payload["quantities"])
    total_stages = len(payload["sleepStages"])
    log.info(
        "Payload: %d quantity samples, %d sleep stages",
        total_quantities,
        total_stages,
    )

    if dry_run:
        log.info("Dry run — skipping HealthKit write")
        return

    if total_quantities == 0 and total_stages == 0:
        log.info("Nothing new to write — state already up to date")
        state.mark_synced(now)
        return

    # --- write to HealthKit ---
    result = writer.write_payload(payload)
    log.info("HealthKit write complete: %d written, %d skipped", result.written, result.skipped)

    state.mark_synced(now)
    log.info("Sync complete. Next sync will start from %s", now.isoformat())

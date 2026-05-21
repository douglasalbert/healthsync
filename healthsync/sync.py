from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from healthsync.config import Config
from healthsync.hk_writer import HKWriterBridge
from healthsync.models import SleepRecord, build_hk_payload
from healthsync.state import SyncState
from healthsync.token_store import TokenStore
from healthsync.whoop_client import WhoopClient

log = logging.getLogger(__name__)

# How far outside WHOOP's reported sleep window to search HK for a matching block.
_HK_MATCH_MARGIN = timedelta(hours=1)
# Minimum overlap (seconds) for an HK sleep sample to count as a match.
_MIN_OVERLAP_SECONDS = 30 * 60
# Source-name prefix used to exclude our own writes from match candidates.
_OWN_SOURCE_PREFIX = "HealthSync"


def run_sync(config: Config, dry_run: bool = False) -> None:
    state = SyncState(config.paths.state_file)
    token_store = TokenStore(config.paths.token_file)
    now = datetime.now(tz=timezone.utc)

    last_sync = state.last_sync_utc()
    if last_sync is None:
        start = now - timedelta(days=config.sync.lookback_days)
        log.info("First run — pulling last %d days", config.sync.lookback_days)
    else:
        start = last_sync
        log.info("Resuming from last sync: %s", start.isoformat())

    writer = HKWriterBridge(config.paths.swift_binary) if not dry_run else None

    client = WhoopClient(config.oauth.client_id, config.oauth.client_secret, token_store)

    cycles = client.get_cycles(start, now)
    hr_samples = []
    if config.healthkit.write_heart_rate:
        hr_samples = client.get_heart_rate(start, now)
    sleep_records = []
    if config.healthkit.write_sleep_stages or config.healthkit.write_respiratory_rate:
        sleep_records = client.get_sleep(start, now)

    if writer is not None and config.healthkit.write_sleep_stages and sleep_records:
        _attach_existing_blocks(writer, sleep_records)

    for cycle in cycles:
        if cycle.recovery_score is not None:
            log.info(
                "Cycle %s: recovery=%.0f strain=%s",
                cycle.cycle_id,
                cycle.recovery_score,
                f"{cycle.strain:.1f}" if cycle.strain is not None else "n/a",
            )

    payload = build_hk_payload(hr_samples, cycles, sleep_records, config.healthkit)
    total_quantities = len(payload["quantities"])
    total_stages = len(payload["sleepStages"])
    log.info("Payload: %d quantity samples, %d sleep stages", total_quantities, total_stages)

    if dry_run:
        log.info("Dry run — skipping HealthKit write")
        return

    if total_quantities == 0 and total_stages == 0:
        log.info("Nothing new to write — state already up to date")
        state.mark_synced(now)
        return

    result = writer.write_payload(payload)
    log.info("HealthKit write complete: %d written, %d skipped", result.written, result.skipped)

    state.mark_synced(now)
    log.info("Sync complete. Next sync will start from %s", now.isoformat())


def _attach_existing_blocks(writer: HKWriterBridge, sleep_records: list[SleepRecord]) -> None:
    """For each WHOOP sleep, find the best-overlapping HK sleep block (excluding our own
    writes) and store its [start, end] on the record so stages are placed inside it."""
    for sleep in sleep_records:
        hk_samples = writer.query_sleep(
            sleep.start - _HK_MATCH_MARGIN,
            sleep.end + _HK_MATCH_MARGIN,
        )
        match = _find_match(sleep.start, sleep.end, hk_samples)
        if match:
            sleep.existing_block = match
            log.info(
                "Sleep %s: augmenting existing HK block %s → %s",
                sleep.sleep_id,
                match[0].isoformat(),
                match[1].isoformat(),
            )
        else:
            log.info(
                "Sleep %s: no existing HK block found; writing fresh inBed + stages",
                sleep.sleep_id,
            )


def _find_match(
    whoop_start: datetime,
    whoop_end: datetime,
    hk_samples: list[dict],
) -> tuple[datetime, datetime] | None:
    """Return the (start, end) of the HK sample with the most overlap with WHOOP's
    window, requiring at least _MIN_OVERLAP_SECONDS. Ignores our own writes."""
    best: tuple[datetime, datetime] | None = None
    best_overlap = 0.0

    for s in hk_samples:
        if s.get("sourceName", "").startswith(_OWN_SOURCE_PREFIX):
            continue
        try:
            sample_start = _parse_iso(s["startDate"])
            sample_end = _parse_iso(s["endDate"])
        except (KeyError, ValueError):
            continue

        overlap_start = max(whoop_start, sample_start)
        overlap_end = min(whoop_end, sample_end)
        overlap = (overlap_end - overlap_start).total_seconds()
        if overlap < _MIN_OVERLAP_SECONDS:
            continue
        if overlap > best_overlap:
            best_overlap = overlap
            best = (sample_start, sample_end)

    return best


def _parse_iso(s: str) -> datetime:
    """Parse ISO-8601 strings emitted by Swift's JSONEncoder (no microseconds, with 'Z')."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

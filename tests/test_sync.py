import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from healthsync.config import Config, HealthKitConfig, OAuthConfig, PathsConfig, SyncConfig
from healthsync.models import CycleRecord, SleepRecord


@pytest.fixture
def config(tmp_path):
    binary = tmp_path / "healthkit-writer"
    binary.touch()
    return Config(
        oauth=OAuthConfig(client_id="client-id", client_secret="client-secret"),
        sync=SyncConfig(lookback_days=7),
        healthkit=HealthKitConfig(),
        paths=PathsConfig(
            swift_binary=binary,
            state_file=tmp_path / "state.json",
            token_file=tmp_path / "tokens.json",
            log_file=tmp_path / "sync.log",
        ),
    )


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_dry_run_skips_hk_query_and_write(config):
    """Dry run should not instantiate the writer (no HK query, no write)."""
    cycle = CycleRecord(
        cycle_id="c1",
        start=_utc(2025, 5, 18),
        end=_utc(2025, 5, 19),
        hrv_ms=60.0,
        resting_hr=52.0,
        spo2=97.0,
    )

    with (
        patch("healthsync.sync.WhoopClient") as MockClient,
        patch("healthsync.sync.HKWriterBridge") as MockWriter,
    ):
        MockClient.return_value.get_cycles.return_value = [cycle]
        MockClient.return_value.get_heart_rate.return_value = []
        MockClient.return_value.get_sleep.return_value = []

        from healthsync.sync import run_sync
        run_sync(config, dry_run=True)

        MockWriter.assert_not_called()


def test_state_advances_after_successful_sync(config):
    cycle = CycleRecord(
        cycle_id="c1",
        start=_utc(2025, 5, 18),
        end=_utc(2025, 5, 19),
        hrv_ms=60.0,
    )
    sleep = SleepRecord(
        sleep_id="s1",
        start=_utc(2025, 5, 17, 23),
        end=_utc(2025, 5, 18, 7),
        light_ms=14400000,
        deep_ms=5400000,
        rem_ms=8100000,
        awake_ms=900000,
        cycle_count=4,
        respiratory_rate=15.2,
    )

    mock_write_result = MagicMock()
    mock_write_result.written = 1
    mock_write_result.skipped = 0

    with (
        patch("healthsync.sync.WhoopClient") as MockClient,
        patch("healthsync.sync.HKWriterBridge") as MockWriter,
    ):
        MockClient.return_value.get_cycles.return_value = [cycle]
        MockClient.return_value.get_heart_rate.return_value = []
        MockClient.return_value.get_sleep.return_value = [sleep]
        MockWriter.return_value.write_payload.return_value = mock_write_result
        MockWriter.return_value.query_sleep.return_value = []  # no existing block

        from healthsync.sync import run_sync
        run_sync(config, dry_run=False)

    from healthsync.state import SyncState
    state = SyncState(config.paths.state_file)
    assert state.last_sync_utc() is not None


def test_matching_picks_longest_overlap_and_skips_own_writes():
    from healthsync.sync import _find_match

    whoop_start = _utc(2025, 5, 17, 23, 0)
    whoop_end = _utc(2025, 5, 18, 7, 0)

    samples = [
        # Our own previous write — must be ignored
        {
            "startDate": "2025-05-17T23:05:00Z",
            "endDate": "2025-05-18T06:55:00Z",
            "value": "inBed",
            "sourceName": "HealthSyncWriter",
        },
        # Apple Watch block with good overlap
        {
            "startDate": "2025-05-17T22:50:00Z",
            "endDate": "2025-05-18T07:05:00Z",
            "value": "inBed",
            "sourceName": "Apple Watch",
        },
        # Short nap, below minimum overlap
        {
            "startDate": "2025-05-18T06:55:00Z",
            "endDate": "2025-05-18T07:10:00Z",
            "value": "inBed",
            "sourceName": "Apple Watch",
        },
    ]

    match = _find_match(whoop_start, whoop_end, samples)
    assert match == (_utc(2025, 5, 17, 22, 50), _utc(2025, 5, 18, 7, 5))


def test_matching_returns_none_when_no_overlap():
    from healthsync.sync import _find_match

    whoop_start = _utc(2025, 5, 17, 23, 0)
    whoop_end = _utc(2025, 5, 18, 7, 0)

    samples = [
        {
            "startDate": "2025-05-15T23:00:00Z",
            "endDate": "2025-05-16T07:00:00Z",
            "value": "inBed",
            "sourceName": "Apple Watch",
        },
    ]
    assert _find_match(whoop_start, whoop_end, samples) is None


def test_sleep_payload_uses_existing_block_when_present(config):
    """When matching finds an Apple Watch block, stages should be placed inside it
    and no inBed sample should be emitted."""
    sleep = SleepRecord(
        sleep_id="s1",
        start=_utc(2025, 5, 17, 23),
        end=_utc(2025, 5, 18, 7),
        light_ms=14400000,
        deep_ms=5400000,
        rem_ms=8100000,
        awake_ms=900000,
        cycle_count=4,
    )

    mock_write_result = MagicMock()
    mock_write_result.written = 1
    mock_write_result.skipped = 0

    captured_payloads: list[dict] = []
    def capture(payload):
        captured_payloads.append(payload)
        return mock_write_result

    with (
        patch("healthsync.sync.WhoopClient") as MockClient,
        patch("healthsync.sync.HKWriterBridge") as MockWriter,
    ):
        MockClient.return_value.get_cycles.return_value = []
        MockClient.return_value.get_heart_rate.return_value = []
        MockClient.return_value.get_sleep.return_value = [sleep]
        MockWriter.return_value.query_sleep.return_value = [
            {
                "startDate": "2025-05-17T22:50:00Z",
                "endDate": "2025-05-18T07:05:00Z",
                "value": "inBed",
                "sourceName": "Apple Watch",
            }
        ]
        MockWriter.return_value.write_payload.side_effect = capture

        from healthsync.sync import run_sync
        run_sync(config, dry_run=False)

    stages = captured_payloads[0]["sleepStages"]
    # No inBed sample should be written when we're augmenting an existing block.
    assert all(s["stage"] != "inBed" for s in stages)
    # All stage segments should start at or after the existing block's start.
    assert all(s["startDate"] >= "2025-05-17T22:50:00Z" for s in stages)

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from healthsync.config import Config, HealthKitConfig, PathsConfig, SyncConfig, WhoopConfig
from healthsync.models import CycleRecord, HRSample, SleepRecord


@pytest.fixture
def config(tmp_path):
    binary = tmp_path / "healthkit-writer"
    binary.touch()
    return Config(
        whoop=WhoopConfig(username="user@example.com", password="pw"),
        sync=SyncConfig(lookback_days=7, heart_rate_step_seconds=60),
        healthkit=HealthKitConfig(),
        paths=PathsConfig(
            swift_binary=binary,
            state_file=tmp_path / "state.json",
            log_file=tmp_path / "sync.log",
        ),
    )


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_dry_run_does_not_write(config):
    """Dry run fetches but never calls the HK writer."""
    cycle = CycleRecord(
        cycle_id="c1",
        start=_utc(2025, 5, 18),
        end=_utc(2025, 5, 19),
        hrv_ms=60.0,
        resting_hr=52.0,
        resp_rate=15.0,
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
    )

    mock_write_result = MagicMock()
    mock_write_result.written = 1
    mock_write_result.skipped = 0

    with (
        patch("healthsync.sync.WhoopClient") as MockClient,
        patch("healthsync.sync.HKWriterBridge") as MockWriter,
    ):
        MockClient.return_value.get_cycles.return_value = [cycle]
        MockClient.return_value.get_heart_rate.return_value = [
            HRSample(timestamp=_utc(2025, 5, 18, 8), bpm=70.0)
        ]
        MockClient.return_value.get_sleep.return_value = []
        MockWriter.return_value.write_payload.return_value = mock_write_result

        from healthsync.sync import run_sync
        run_sync(config, dry_run=False)

    from healthsync.state import SyncState
    state = SyncState(config.paths.state_file)
    assert state.last_sync_utc() is not None

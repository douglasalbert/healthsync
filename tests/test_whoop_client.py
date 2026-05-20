import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def mock_whoop_module():
    """Patch whoop_data at import time so WhoopClient can be constructed."""
    mock_client = MagicMock()
    mock_module = MagicMock()
    mock_module.WhoopClient.return_value = mock_client
    mock_module.get_cycle_data.return_value = _load("whoop_cycle_response.json")
    mock_module.get_heart_rate_data.return_value = _load("whoop_hr_response.json")
    mock_module.get_sleep_data.return_value = _load("whoop_sleep_response.json")
    with patch.dict("sys.modules", {"whoop_data": mock_module}):
        yield mock_module


def test_parse_cycles(mock_whoop_module):
    from healthsync.whoop_client import WhoopClient

    client = WhoopClient("user@example.com", "password")
    start = datetime(2025, 5, 18, tzinfo=timezone.utc)
    end = datetime(2025, 5, 19, tzinfo=timezone.utc)
    cycles = client.get_cycles(start, end)

    assert len(cycles) == 1
    c = cycles[0]
    assert c.cycle_id == "cycle-001"
    assert c.hrv_ms == pytest.approx(62.3)
    assert c.resting_hr == pytest.approx(52.0)
    assert c.resp_rate == pytest.approx(15.2)
    assert c.spo2 == pytest.approx(97.5)
    assert c.recovery_score == pytest.approx(78.0)
    assert c.strain == pytest.approx(12.4)


def test_parse_heart_rate(mock_whoop_module):
    from healthsync.whoop_client import WhoopClient

    client = WhoopClient("user@example.com", "password")
    start = datetime(2025, 5, 18, tzinfo=timezone.utc)
    end = datetime(2025, 5, 19, tzinfo=timezone.utc)
    samples = client.get_heart_rate(start, end)

    assert len(samples) == 3
    assert samples[0].bpm == 68.0
    assert samples[1].bpm == 70.0
    assert samples[2].bpm == 72.0


def test_parse_sleep_stages(mock_whoop_module):
    from healthsync.whoop_client import WhoopClient

    client = WhoopClient("user@example.com", "password")
    start = datetime(2025, 5, 17, tzinfo=timezone.utc)
    end = datetime(2025, 5, 18, tzinfo=timezone.utc)
    records = client.get_sleep(start, end)

    assert len(records) == 1
    sleep = records[0]
    assert sleep.sleep_id == "sleep-001"
    stages = [s.stage for s in sleep.stages]
    assert stages == ["light", "deep", "rem", "awake", "light"]

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def token_store(tmp_path):
    token_file = tmp_path / "tokens.json"
    token_file.write_text(json.dumps({
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_at": time.time() + 3600,
    }))
    from healthsync.token_store import TokenStore
    return TokenStore(token_file)


def _mock_get(url, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    if "/recovery" in url:
        resp.json.return_value = _load("whoop_recovery_response.json")
    elif "/activity/sleep" in url:
        resp.json.return_value = _load("whoop_sleep_response.json")
    elif "/cycle" in url:
        resp.json.return_value = _load("whoop_cycle_response.json")
    else:
        resp.json.return_value = {"records": [], "next_token": None}
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def client(token_store):
    from healthsync.whoop_client import WhoopClient
    return WhoopClient("client-id", "client-secret", token_store)


def test_parse_cycles(client):
    start = datetime(2025, 5, 18, tzinfo=timezone.utc)
    end = datetime(2025, 5, 19, tzinfo=timezone.utc)

    with patch("requests.get", side_effect=_mock_get):
        cycles = client.get_cycles(start, end)

    assert len(cycles) == 1
    c = cycles[0]
    assert c.cycle_id == "93845"
    assert c.hrv_ms == pytest.approx(62.3)
    assert c.resting_hr == pytest.approx(52.0)
    assert c.spo2 == pytest.approx(97.5)
    assert c.recovery_score == pytest.approx(78.0)
    assert c.strain == pytest.approx(12.4)


def test_parse_sleep_with_stage_summary(client):
    start = datetime(2025, 5, 17, tzinfo=timezone.utc)
    end = datetime(2025, 5, 18, tzinfo=timezone.utc)

    with patch("requests.get", side_effect=_mock_get):
        records = client.get_sleep(start, end)

    assert len(records) == 1
    sleep = records[0]
    assert sleep.sleep_id == "870e1266-3c00-4843-b8bb-bb84dbf84780"
    assert sleep.light_ms == 14400000
    assert sleep.deep_ms == 5400000
    assert sleep.rem_ms == 8100000
    assert sleep.awake_ms == 900000
    assert sleep.cycle_count == 4
    assert sleep.respiratory_rate == pytest.approx(15.2)


def test_get_heart_rate_returns_empty(client):
    start = datetime(2025, 5, 18, tzinfo=timezone.utc)
    end = datetime(2025, 5, 19, tzinfo=timezone.utc)
    assert client.get_heart_rate(start, end) == []


def test_unscored_records_skipped(client):
    start = datetime(2025, 5, 18, tzinfo=timezone.utc)
    end = datetime(2025, 5, 19, tzinfo=timezone.utc)

    def mock_pending(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        if "/recovery" in url:
            data = _load("whoop_recovery_response.json")
            data["records"][0]["score_state"] = "PENDING_SCORE"
            resp.json.return_value = data
        else:
            resp.json.return_value = _load("whoop_cycle_response.json")
        return resp

    with patch("requests.get", side_effect=mock_pending):
        assert client.get_cycles(start, end) == []


def test_4xx_not_retried(client):
    """A 404 should fail fast — no retry, no compounded wait."""
    from healthsync.whoop_client import WhoopAPIError

    call_count = {"n": 0}

    def mock_404(url, **kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"
        return resp

    with patch("requests.get", side_effect=mock_404), pytest.raises(WhoopAPIError, match="404"):
        client.get_cycles(
            datetime(2025, 5, 18, tzinfo=timezone.utc),
            datetime(2025, 5, 19, tzinfo=timezone.utc),
        )

    assert call_count["n"] == 1


def test_auth_error_when_no_tokens(tmp_path):
    from healthsync.token_store import TokenStore
    from healthsync.whoop_client import WhoopAuthError, WhoopClient

    c = WhoopClient("id", "secret", TokenStore(tmp_path / "missing.json"))

    with pytest.raises(WhoopAuthError, match="healthsync auth"):
        c.get_cycles(
            datetime(2025, 5, 18, tzinfo=timezone.utc),
            datetime(2025, 5, 19, tzinfo=timezone.utc),
        )

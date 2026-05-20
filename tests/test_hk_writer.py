import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from healthsync.hk_writer import HKAuthError, HKWriteError, HKWriterBridge, WriteResult


@pytest.fixture
def mock_binary(tmp_path):
    binary = tmp_path / "healthkit-writer"
    binary.touch()
    return binary


def _make_bridge(mock_binary):
    return HKWriterBridge(mock_binary)


def _run_response(bridge, response: dict, returncode: int = 0):
    mock_result = MagicMock()
    mock_result.returncode = returncode
    mock_result.stdout = json.dumps(response).encode()
    mock_result.stderr = b""
    with patch("subprocess.run", return_value=mock_result):
        return bridge.write_payload({"quantities": [{"dummy": True}], "sleepStages": []})


def test_successful_write(mock_binary):
    bridge = _make_bridge(mock_binary)
    result = _run_response(bridge, {"status": "ok", "written": 3, "skipped": 0})
    assert result.written == 3
    assert result.skipped == 0


def test_auth_error_raises(mock_binary):
    bridge = _make_bridge(mock_binary)
    with pytest.raises(HKAuthError):
        _run_response(bridge, {"status": "error", "code": 5, "message": "denied"})


def test_generic_error_raises(mock_binary):
    bridge = _make_bridge(mock_binary)
    with pytest.raises(HKWriteError):
        _run_response(bridge, {"status": "error", "code": 1, "message": "oops"})


def test_missing_binary_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        HKWriterBridge(tmp_path / "nonexistent")


def test_batching_calls_subprocess_multiple_times(mock_binary):
    bridge = _make_bridge(mock_binary)
    # 1200 quantity samples should produce 3 subprocess calls (500, 500, 200)
    quantities = [{"dummy": True}] * 1200
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({"status": "ok", "written": 500, "skipped": 0}).encode()
    mock_result.stderr = b""
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        bridge.write_payload({"quantities": quantities, "sleepStages": []})
        assert mock_run.call_count == 3

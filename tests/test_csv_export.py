import csv
import io

from healthsync.csv_export import HEADER, payload_to_csv_rows, rows_to_csv_text


def _sample_payload():
    return {
        "quantities": [
            {
                "typeIdentifier": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
                "value": 45.2,
                "unit": "ms",
                "startDate": "2025-05-19T08:00:00Z",
                "endDate": "2025-05-19T08:00:00Z",
                "externalUUID": "whoop-cycle-c1-hrv",
            },
            {
                "typeIdentifier": "HKQuantityTypeIdentifierRestingHeartRate",
                "value": 52.0,
                "unit": "count/min",
                "startDate": "2025-05-19T08:00:00Z",
                "endDate": "2025-05-19T08:00:00Z",
                "externalUUID": "whoop-cycle-c1-rhr",
            },
            {
                "typeIdentifier": "HKQuantityTypeIdentifierOxygenSaturation",
                "value": 0.97,
                "unit": "%",
                "startDate": "2025-05-19T08:00:00Z",
                "endDate": "2025-05-19T08:00:00Z",
                "externalUUID": "whoop-cycle-c1-spo2",
            },
        ],
        "sleepStages": [
            {
                "stage": "inBed",
                "startDate": "2025-05-17T23:00:00Z",
                "endDate": "2025-05-18T07:00:00Z",
                "externalUUID": "whoop-sleep-s1-inbed",
            },
            {
                "stage": "asleepDeep",
                "startDate": "2025-05-18T00:30:00Z",
                "endDate": "2025-05-18T01:15:00Z",
                "externalUUID": "whoop-sleep-s1-stage-0",
            },
        ],
    }


def test_header_is_first_row():
    rows = payload_to_csv_rows({"quantities": [], "sleepStages": []})
    assert rows[0] == HEADER


def test_quantity_rows_shape():
    rows = payload_to_csv_rows(_sample_payload())
    # Row index 1 is HRV (first quantity)
    hrv_row = rows[1]
    assert hrv_row[0] == "hrv"
    assert hrv_row[1] == "45.2"
    assert hrv_row[2] == ""        # stage empty
    assert hrv_row[3] == "ms"
    assert hrv_row[4] == "2025-05-19T08:00:00Z"
    assert hrv_row[5] == "2025-05-19T08:00:00Z"


def test_sleep_rows_shape():
    rows = payload_to_csv_rows(_sample_payload())
    # Sleep rows come after quantity rows (3 qty rows + header = index 4)
    sleep_row = rows[4]
    assert sleep_row[0] == "sleep"
    assert sleep_row[1] == ""      # value empty
    assert sleep_row[2] == "inBed"
    assert sleep_row[3] == ""      # unit empty
    assert sleep_row[4] == "2025-05-17T23:00:00Z"
    assert sleep_row[5] == "2025-05-18T07:00:00Z"


def test_all_quantity_types_mapped():
    rows = payload_to_csv_rows(_sample_payload())
    types = [r[0] for r in rows[1:]]
    assert "hrv" in types
    assert "restingHr" in types
    assert "oxygenSaturation" in types


def test_unknown_type_skipped(caplog):
    import logging
    payload = {
        "quantities": [
            {
                "typeIdentifier": "HKQuantityTypeIdentifierStepCount",
                "value": 1000,
                "unit": "count",
                "startDate": "2025-05-19T08:00:00Z",
                "endDate": "2025-05-19T08:00:00Z",
                "externalUUID": "x",
            }
        ],
        "sleepStages": [],
    }
    with caplog.at_level(logging.WARNING, logger="healthsync.csv_export"):
        rows = payload_to_csv_rows(payload)
    # Only header row — the step-count sample should be skipped
    assert len(rows) == 1
    assert "HKQuantityTypeIdentifierStepCount" in caplog.text


def test_csv_quoting():
    # Values that contain commas must be quoted by csv.writer
    payload = {
        "quantities": [
            {
                "typeIdentifier": "HKQuantityTypeIdentifierRestingHeartRate",
                "value": 52.0,
                "unit": "count/min",
                "startDate": "2025-05-19T08:00:00Z",
                "endDate": "2025-05-19T08:00:00Z",
                "externalUUID": "x",
            }
        ],
        "sleepStages": [],
    }
    rows = payload_to_csv_rows(payload)
    text = rows_to_csv_text(rows)
    # Parse it back through csv.reader to confirm it round-trips cleanly
    parsed = list(csv.reader(io.StringIO(text)))
    assert len(parsed) == 2  # header + 1 data row
    assert parsed[1][0] == "restingHr"
    assert parsed[1][3] == "count/min"


def test_row_count_matches_payload():
    payload = _sample_payload()
    rows = payload_to_csv_rows(payload)
    n_qty = len(payload["quantities"])
    n_sleep = len(payload["sleepStages"])
    # header + all quantities + all sleep rows
    assert len(rows) == 1 + n_qty + n_sleep


def test_empty_payload_returns_header_only():
    rows = payload_to_csv_rows({"quantities": [], "sleepStages": []})
    assert rows == [HEADER]

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class HRSample:
    timestamp: datetime
    bpm: float
    external_uuid: str = ""

    def to_hk_quantity(self) -> dict:
        ts = _iso(self.timestamp)
        return {
            "typeIdentifier": "HKQuantityTypeIdentifierHeartRate",
            "value": self.bpm,
            "unit": "count/min",
            "startDate": ts,
            "endDate": ts,
            "externalUUID": self.external_uuid or f"whoop-hr-{ts}",
        }


SleepStageValue = Literal["awake", "light", "rem", "deep"]


@dataclass
class SleepStage:
    start: datetime
    end: datetime
    stage: SleepStageValue

    def to_hk_sleep(self, parent_uuid: str, index: int) -> dict:
        return {
            "stage": self.stage,
            "startDate": _iso(self.start),
            "endDate": _iso(self.end),
            "externalUUID": f"{parent_uuid}-{self.stage}-{index}",
        }


@dataclass
class SleepRecord:
    sleep_id: str
    start: datetime
    end: datetime
    stages: list[SleepStage] = field(default_factory=list)


@dataclass
class CycleRecord:
    cycle_id: str
    start: datetime
    end: datetime
    hrv_ms: float | None = None          # WHOOP reports RMSSD; written to HK SDNN type
    resting_hr: float | None = None
    resp_rate: float | None = None
    spo2: float | None = None            # stored as percentage (0–100); converted to 0.0–1.0 for HK
    recovery_score: float | None = None  # not written to HK; logged only
    strain: float | None = None          # not written to HK; logged only


def build_hk_payload(
    hr_samples: list[HRSample],
    cycles: list[CycleRecord],
    sleep_records: list[SleepRecord],
    hk_cfg,
) -> dict:
    quantities: list[dict] = []
    sleep_stages: list[dict] = []

    if hk_cfg.write_heart_rate:
        quantities.extend(s.to_hk_quantity() for s in hr_samples)

    for cycle in cycles:
        ts = _iso(cycle.end)
        uuid_base = f"whoop-cycle-{cycle.cycle_id}"

        if hk_cfg.write_hrv and cycle.hrv_ms is not None:
            quantities.append({
                "typeIdentifier": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
                "value": cycle.hrv_ms,
                "unit": "ms",
                "startDate": ts,
                "endDate": ts,
                "externalUUID": f"{uuid_base}-hrv",
                # Tag so consumers know this is RMSSD, not true SDNN
                "sourceMetadata": {"WHOOPMetric": "RMSSD"},
            })

        if hk_cfg.write_resting_hr and cycle.resting_hr is not None:
            quantities.append({
                "typeIdentifier": "HKQuantityTypeIdentifierRestingHeartRate",
                "value": cycle.resting_hr,
                "unit": "count/min",
                "startDate": ts,
                "endDate": ts,
                "externalUUID": f"{uuid_base}-rhr",
            })

        if hk_cfg.write_respiratory_rate and cycle.resp_rate is not None:
            quantities.append({
                "typeIdentifier": "HKQuantityTypeIdentifierRespiratoryRate",
                "value": cycle.resp_rate,
                "unit": "count/min",
                "startDate": ts,
                "endDate": ts,
                "externalUUID": f"{uuid_base}-resp",
            })

        if hk_cfg.write_spo2 and cycle.spo2 is not None:
            quantities.append({
                "typeIdentifier": "HKQuantityTypeIdentifierOxygenSaturation",
                "value": cycle.spo2 / 100.0,
                "unit": "%",
                "startDate": ts,
                "endDate": ts,
                "externalUUID": f"{uuid_base}-spo2",
            })

    if hk_cfg.write_sleep_stages:
        for sleep in sleep_records:
            uuid_base = f"whoop-sleep-{sleep.sleep_id}"
            for i, stage in enumerate(sleep.stages):
                sleep_stages.append(stage.to_hk_sleep(uuid_base, i))

    return {"quantities": quantities, "sleepStages": sleep_stages}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

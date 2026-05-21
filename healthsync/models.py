from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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


SleepStageValue = Literal["awake", "light", "rem", "deep", "inBed", "asleep"]


@dataclass
class SleepRecord:
    sleep_id: str
    start: datetime
    end: datetime
    light_ms: int = 0
    deep_ms: int = 0
    rem_ms: int = 0
    awake_ms: int = 0
    in_bed_ms: int = 0
    cycle_count: int = 0
    respiratory_rate: float | None = None
    # Set by sync.py after matching against an existing HK sleep block.
    # When set, stages are written inside this window and no inBed sample is emitted.
    existing_block: tuple[datetime, datetime] | None = None


@dataclass
class CycleRecord:
    cycle_id: str
    start: datetime
    end: datetime
    hrv_ms: float | None = None           # WHOOP reports RMSSD; written to HK SDNN type
    resting_hr: float | None = None
    spo2: float | None = None             # 0–100; converted to 0.0–1.0 for HK
    recovery_score: float | None = None   # not written to HK; logged only
    strain: float | None = None           # not written to HK; logged only
    active_energy_kj: float | None = None # kilojoules from cycle score
    skin_temp_c: float | None = None      # skin temperature celsius from recovery


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
                # WHOOP gives RMSSD; HK has no RMSSD type so we use SDNN and tag the source.
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

        if hk_cfg.write_spo2 and cycle.spo2 is not None:
            quantities.append({
                "typeIdentifier": "HKQuantityTypeIdentifierOxygenSaturation",
                "value": cycle.spo2 / 100.0,
                "unit": "%",
                "startDate": ts,
                "endDate": ts,
                "externalUUID": f"{uuid_base}-spo2",
            })

        if hk_cfg.write_active_energy and cycle.active_energy_kj is not None:
            quantities.append({
                "typeIdentifier": "HKQuantityTypeIdentifierActiveEnergyBurned",
                "value": cycle.active_energy_kj * 0.239006,  # kJ → kcal
                "unit": "kcal",
                "startDate": _iso(cycle.start),
                "endDate": ts,
                "externalUUID": f"{uuid_base}-energy",
            })

        if hk_cfg.write_skin_temp and cycle.skin_temp_c is not None:
            quantities.append({
                "typeIdentifier": "HKQuantityTypeIdentifierBodyTemperature",
                "value": cycle.skin_temp_c,
                "unit": "degC",
                "startDate": ts,
                "endDate": ts,
                "externalUUID": f"{uuid_base}-skintemp",
            })

    if hk_cfg.write_respiratory_rate:
        for sleep in sleep_records:
            if sleep.respiratory_rate is not None:
                ts = _iso(sleep.end)
                quantities.append({
                    "typeIdentifier": "HKQuantityTypeIdentifierRespiratoryRate",
                    "value": sleep.respiratory_rate,
                    "unit": "count/min",
                    "startDate": ts,
                    "endDate": ts,
                    "externalUUID": f"whoop-sleep-{sleep.sleep_id}-resp",
                })

    if hk_cfg.write_sleep_stages:
        for sleep in sleep_records:
            if sleep.existing_block is not None:
                window_start, window_end = sleep.existing_block
            else:
                window_start, window_end = sleep.start, sleep.end
                sleep_stages.append({
                    "stage": "inBed",
                    "startDate": _iso(window_start),
                    "endDate": _iso(window_end),
                    "externalUUID": f"whoop-sleep-{sleep.sleep_id}-inbed",
                })

            segments = synthesize_sleep_stages(
                window_start,
                window_end,
                sleep.light_ms,
                sleep.deep_ms,
                sleep.rem_ms,
                sleep.awake_ms,
                sleep.cycle_count,
            )
            for i, (stage, seg_start, seg_end) in enumerate(segments):
                sleep_stages.append({
                    "stage": stage,
                    "startDate": _iso(seg_start),
                    "endDate": _iso(seg_end),
                    "externalUUID": f"whoop-sleep-{sleep.sleep_id}-stage-{i}",
                })

    return {"quantities": quantities, "sleepStages": sleep_stages}


def synthesize_sleep_stages(
    window_start: datetime,
    window_end: datetime,
    light_ms: int,
    deep_ms: int,
    rem_ms: int,
    awake_ms: int,
    cycle_count: int,
) -> list[tuple[str, datetime, datetime]]:
    """Synthesize realistic-looking sleep stage segments inside [window_start, window_end].

    WHOOP v2 only reports totals per stage, not a timeline. We emit:
      - one awake block at the start (drift-off period)
      - then `cycle_count` sleep cycles, each shaped: light → deep → light → REM
      - deep is weighted toward early cycles, REM toward later cycles

    Stage totals are preserved exactly (integer remainders flow to the last cycle).
    If totals exceed the window, everything is scaled proportionally to fit.
    """
    window_ms = int((window_end - window_start).total_seconds() * 1000)
    total_ms = light_ms + deep_ms + rem_ms + awake_ms

    if total_ms <= 0 or window_ms <= 0:
        return []

    if total_ms > window_ms:
        scale = window_ms / total_ms
        light_ms = int(light_ms * scale)
        deep_ms = int(deep_ms * scale)
        rem_ms = int(rem_ms * scale)
        awake_ms = int(awake_ms * scale)

    segments: list[tuple[str, datetime, datetime]] = []
    cursor = window_start

    if awake_ms > 0:
        seg_end = cursor + timedelta(milliseconds=awake_ms)
        segments.append(("awake", cursor, seg_end))
        cursor = seg_end

    sleep_ms = light_ms + deep_ms + rem_ms
    if sleep_ms <= 0:
        return segments

    if cycle_count < 1:
        cycle_count = max(1, sleep_ms // (90 * 60 * 1000))

    deep_weights = [cycle_count - i for i in range(cycle_count)]
    rem_weights = [i + 1 for i in range(cycle_count)]
    sum_d = sum(deep_weights)
    sum_r = sum(rem_weights)

    deep_per = [(deep_ms * w) // sum_d for w in deep_weights]
    rem_per = [(rem_ms * w) // sum_r for w in rem_weights]
    light_per = [light_ms // cycle_count] * cycle_count

    deep_per[-1] += deep_ms - sum(deep_per)
    rem_per[-1] += rem_ms - sum(rem_per)
    light_per[-1] += light_ms - sum(light_per)

    for i in range(cycle_count):
        l, d, r = light_per[i], deep_per[i], rem_per[i]
        l1 = l // 2
        l2 = l - l1
        for stage, dur in [("light", l1), ("deep", d), ("light", l2), ("rem", r)]:
            if dur <= 0:
                continue
            seg_end = cursor + timedelta(milliseconds=dur)
            segments.append((stage, cursor, seg_end))
            cursor = seg_end

    return segments


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

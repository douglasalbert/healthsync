from __future__ import annotations

import logging
from datetime import datetime, timezone

from tenacity import retry, stop_after_attempt, wait_exponential

from healthsync.models import CycleRecord, HRSample, SleepRecord, SleepStage

log = logging.getLogger(__name__)

# WHOOP sleep stage integers → our canonical stage names.
# Based on WHOOP API conventions; adjust if the whoop-data package
# returns string stage names instead.
_STAGE_MAP: dict[int | str, str] = {
    0: "awake",
    1: "light",
    2: "deep",
    3: "rem",
    4: "awake",
    # String variants some API versions return
    "wake": "awake",
    "light": "light",
    "slow_wave": "deep",
    "rem": "rem",
    "disturbance": "awake",
}


class WhoopAPIError(Exception):
    pass


class WhoopAuthError(WhoopAPIError):
    pass


class WhoopRateLimitError(WhoopAPIError):
    pass


class WhoopClient:
    def __init__(self, username: str, password: str):
        from whoop_data import WhoopClient as _Client  # type: ignore[import-untyped]

        try:
            self._client = _Client(username=username, password=password)
        except Exception as exc:
            raise WhoopAuthError(f"WHOOP authentication failed: {exc}") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_cycles(self, start: datetime, end: datetime) -> list[CycleRecord]:
        from whoop_data import get_cycle_data  # type: ignore[import-untyped]

        log.info("Fetching WHOOP cycles %s → %s", _fmt(start), _fmt(end))
        try:
            raw_cycles = get_cycle_data(self._client, start_date=start, end_date=end)
        except Exception as exc:
            _raise_api_error(exc)

        records = []
        for cycle in raw_cycles or []:
            try:
                records.append(self._parse_cycle(cycle))
            except Exception:
                log.warning("Skipping unparseable cycle: %s", cycle.get("id", "?"))
        log.info("Fetched %d cycle(s)", len(records))
        return records

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_heart_rate(
        self, start: datetime, end: datetime, step: int = 60
    ) -> list[HRSample]:
        from whoop_data import get_heart_rate_data  # type: ignore[import-untyped]

        log.info("Fetching WHOOP heart rate %s → %s (step=%ds)", _fmt(start), _fmt(end), step)
        try:
            raw = get_heart_rate_data(
                self._client, start_date=start, end_date=end, step=step
            )
        except Exception as exc:
            _raise_api_error(exc)

        samples = []
        for item in raw or []:
            try:
                samples.append(self._parse_hr(item))
            except Exception:
                log.debug("Skipping unparseable HR sample: %s", item)
        log.info("Fetched %d HR sample(s)", len(samples))
        return samples

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_sleep(self, start: datetime, end: datetime) -> list[SleepRecord]:
        from whoop_data import get_sleep_data  # type: ignore[import-untyped]

        log.info("Fetching WHOOP sleep %s → %s", _fmt(start), _fmt(end))
        try:
            raw = get_sleep_data(self._client, start_date=start, end_date=end)
        except Exception as exc:
            _raise_api_error(exc)

        records = []
        for item in raw or []:
            try:
                records.append(self._parse_sleep(item))
            except Exception:
                log.warning("Skipping unparseable sleep record: %s", item.get("id", "?"))
        log.info("Fetched %d sleep record(s)", len(records))
        return records

    # --- parsers ---

    def _parse_cycle(self, cycle: dict) -> CycleRecord:
        score = cycle.get("score") or cycle.get("recovery") or {}
        return CycleRecord(
            cycle_id=str(cycle.get("id", "")),
            start=_parse_ts(cycle.get("start") or cycle.get("during", {}).get("lower")),
            end=_parse_ts(cycle.get("end") or cycle.get("during", {}).get("upper")),
            hrv_ms=_float(score.get("hrv_rmssd_milli") or score.get("hrv")),
            resting_hr=_float(score.get("resting_heart_rate") or score.get("rhr")),
            resp_rate=_float(score.get("respiratory_rate") or cycle.get("respiratory_rate")),
            spo2=_float(score.get("spo2_percentage") or score.get("spo2")),
            recovery_score=_float(score.get("recovery_score") or score.get("score")),
            strain=_float(
                (cycle.get("strain") or {}).get("score")
                or cycle.get("strain_score")
            ),
        )

    def _parse_hr(self, item: dict) -> HRSample:
        # whoop-data returns dicts with 'time'/'timestamp' and 'data'/'bpm'/'heart_rate'
        ts = _parse_ts(item.get("time") or item.get("timestamp"))
        bpm = float(item.get("data") or item.get("bpm") or item.get("heart_rate", 0))
        return HRSample(
            timestamp=ts,
            bpm=bpm,
            external_uuid=f"whoop-hr-{ts.strftime('%Y%m%dT%H%M%SZ')}",
        )

    def _parse_sleep(self, item: dict) -> SleepRecord:
        sleep_id = str(item.get("id", ""))
        start = _parse_ts(item.get("start") or item.get("during", {}).get("lower"))
        end = _parse_ts(item.get("end") or item.get("during", {}).get("upper"))

        stages = []
        for stage_item in item.get("stages") or item.get("stage_data") or []:
            stage_name = _STAGE_MAP.get(
                stage_item.get("stage") or stage_item.get("stage_type"), "awake"
            )
            stages.append(
                SleepStage(
                    start=_parse_ts(stage_item.get("start")),
                    end=_parse_ts(stage_item.get("end")),
                    stage=stage_name,  # type: ignore[arg-type]
                )
            )

        return SleepRecord(sleep_id=sleep_id, start=start, end=end, stages=stages)


def _parse_ts(value: str | int | float | None) -> datetime:
    if value is None:
        raise ValueError("Missing timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _raise_api_error(exc: Exception) -> None:
    msg = str(exc).lower()
    if "401" in msg or "unauthorized" in msg or "auth" in msg:
        raise WhoopAuthError(str(exc)) from exc
    if "429" in msg or "rate" in msg:
        raise WhoopRateLimitError(str(exc)) from exc
    raise WhoopAPIError(str(exc)) from exc

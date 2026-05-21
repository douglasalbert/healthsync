from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from healthsync.models import CycleRecord, HRSample, SleepRecord
from healthsync.token_store import TokenStore

log = logging.getLogger(__name__)

_BASE = "https://api.prod.whoop.com/developer/v2"
_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"


class WhoopAPIError(Exception):
    pass


class WhoopAuthError(WhoopAPIError):
    pass


class WhoopRateLimitError(WhoopAPIError):
    pass


class WhoopServerError(WhoopAPIError):
    pass


# Retry only on transient failures (rate limits, server errors). 4xx is not retried.
_retry_transient = retry(
    retry=retry_if_exception_type((WhoopRateLimitError, WhoopServerError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    reraise=True,
)


class WhoopClient:
    def __init__(self, client_id: str, client_secret: str, token_store: TokenStore):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_store = token_store

    @_retry_transient
    def get_cycles(self, start: datetime, end: datetime) -> list[CycleRecord]:
        """Fetch scored recovery records and merge with cycle data for strain."""
        log.info("Fetching WHOOP recoveries %s → %s", _fmt(start), _fmt(end))
        raw_recoveries = self._paginate(f"{_BASE}/recovery", {"start": _iso(start), "end": _iso(end)})

        log.info("Fetching WHOOP cycles %s → %s", _fmt(start), _fmt(end))
        raw_cycles = self._paginate(f"{_BASE}/cycle", {"start": _iso(start), "end": _iso(end)})
        cycles_by_id = {str(c.get("id", "")): c for c in raw_cycles}

        records = []
        for r in raw_recoveries:
            if r.get("score_state") != "SCORED":
                continue
            cycle_id = str(r.get("cycle_id", ""))
            cycle = cycles_by_id.get(cycle_id, {})
            score = r.get("score") or {}
            cycle_score = cycle.get("score") or {}
            try:
                records.append(CycleRecord(
                    cycle_id=cycle_id,
                    start=_parse_ts(cycle.get("start") or r.get("created_at")),
                    end=_parse_ts(cycle.get("end") or r.get("updated_at")),
                    hrv_ms=_float(score.get("hrv_rmssd_milli")),
                    resting_hr=_float(score.get("resting_heart_rate")),
                    spo2=_float(score.get("spo2_percentage")),
                    recovery_score=_float(score.get("recovery_score")),
                    strain=_float(cycle_score.get("strain")),
                    active_energy_kj=_float(cycle_score.get("kilojoules")),
                    skin_temp_c=_float(score.get("skin_temp_celsius")),
                ))
            except Exception:
                log.warning("Skipping unparseable recovery: cycle_id=%s", cycle_id)

        log.info("Fetched %d scored cycle(s)", len(records))
        return records

    def get_heart_rate(self, start: datetime, end: datetime, step: int = 60) -> list[HRSample]:
        log.debug("Heart rate time series is not available in the official WHOOP API")
        return []

    @_retry_transient
    def get_sleep(self, start: datetime, end: datetime) -> list[SleepRecord]:
        log.info("Fetching WHOOP sleep %s → %s", _fmt(start), _fmt(end))
        raw = self._paginate(f"{_BASE}/activity/sleep", {"start": _iso(start), "end": _iso(end)})

        records = []
        for item in raw:
            if item.get("score_state") != "SCORED":
                continue
            try:
                records.append(self._parse_sleep(item))
            except Exception as exc:
                log.warning("Skipping unparseable sleep record %s: %s", item.get("id", "?"), exc)

        log.info("Fetched %d sleep record(s)", len(records))
        return records

    # --- token management ---

    def _ensure_token(self) -> str:
        if not self._token_store.has_tokens():
            raise WhoopAuthError("Not authenticated. Run 'healthsync auth' first.")
        if self._token_store.is_expired():
            return self._do_refresh()
        return self._token_store.access_token()

    def _do_refresh(self) -> str:
        refresh_tok = self._token_store.refresh_token()
        if not refresh_tok:
            raise WhoopAuthError("No refresh token. Run 'healthsync auth' to re-authorize.")
        log.info("Refreshing WHOOP access token")
        resp = requests.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_tok,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise WhoopAuthError(
                f"Token refresh failed ({resp.status_code}). Run 'healthsync auth' to re-authorize."
            )
        self._token_store.save(resp.json())
        return self._token_store.access_token()

    # --- HTTP helpers ---

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(2):
            token = self._ensure_token()
            try:
                resp = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    timeout=30,
                )
            except requests.exceptions.Timeout:
                raise WhoopServerError("WHOOP API request timed out")
            except requests.exceptions.RequestException as exc:
                raise WhoopServerError(str(exc)) from exc

            if resp.status_code == 401 and attempt == 0:
                self._do_refresh()
                continue
            if resp.status_code == 429:
                raise WhoopRateLimitError("WHOOP API rate limit exceeded")
            if 500 <= resp.status_code < 600:
                raise WhoopServerError(f"WHOOP server error ({resp.status_code}): {resp.text}")
            if 400 <= resp.status_code < 500:
                raise WhoopAPIError(f"WHOOP API error ({resp.status_code}): {resp.text}")
            return resp.json()

        raise WhoopAuthError("Authentication failed after token refresh. Run 'healthsync auth'.")

    def _paginate(self, url: str, params: dict) -> list[dict]:
        records: list[dict] = []
        p = dict(params)
        while True:
            data = self._get(url, p)
            records.extend(data.get("records", []))
            next_token = data.get("next_token")
            if not next_token:
                break
            p["nextToken"] = next_token
        return records

    # --- parsers ---

    def _parse_sleep(self, item: dict) -> SleepRecord:
        sleep_id = str(item.get("id", ""))
        start = _parse_ts(item.get("start"))
        end = _parse_ts(item.get("end"))
        score = item.get("score") or {}
        summary = score.get("stage_summary") or {}

        return SleepRecord(
            sleep_id=sleep_id,
            start=start,
            end=end,
            light_ms=int(summary.get("total_light_sleep_time_milli") or 0),
            deep_ms=int(summary.get("total_slow_wave_sleep_time_milli") or 0),
            rem_ms=int(summary.get("total_rem_sleep_time_milli") or 0),
            awake_ms=int(summary.get("total_awake_time_milli") or 0),
            in_bed_ms=int(summary.get("total_in_bed_time_milli") or 0),
            cycle_count=int(summary.get("sleep_cycle_count") or 0),
            respiratory_rate=_float(score.get("respiratory_rate")),
        )


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


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

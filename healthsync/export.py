from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from healthsync.config import Config
from healthsync.models import build_hk_payload
from healthsync.state import SyncState
from healthsync.token_store import TokenStore
from healthsync.whoop_client import WhoopClient

log = logging.getLogger(__name__)


def run_export(config: Config, since: datetime | None = None, output: Path | None = None) -> Path:
    """Fetch all WHOOP data since `since` and write a HealthKit-ready JSON payload to disk.

    Returns the path of the written file.
    """
    token_store = TokenStore(config.paths.token_file)
    now = datetime.now(tz=timezone.utc)

    if since is None:
        # Default: pull everything by going back 10 years (WHOOP launched ~2015)
        since = now - timedelta(days=365 * 10)

    client = WhoopClient(config.oauth.client_id, config.oauth.client_secret, token_store)

    log.info("Fetching cycles %s → %s", since.date(), now.date())
    cycles = client.get_cycles(since, now)

    log.info("Fetching sleep %s → %s", since.date(), now.date())
    sleep_records = client.get_sleep(since, now)

    payload = build_hk_payload([], cycles, sleep_records, config.healthkit)
    n_qty = len(payload["quantities"])
    n_sleep = len(payload["sleepStages"])
    log.info("Export: %d quantity samples, %d sleep stages", n_qty, n_sleep)

    export = {
        "version": 1,
        "exportedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "periodStart": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "periodEnd": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "quantities": payload["quantities"],
        "sleepStages": payload["sleepStages"],
    }

    if output is None:
        config.paths.export_dir.mkdir(parents=True, exist_ok=True)
        fname = f"healthsync_export_{now.strftime('%Y%m%d_%H%M%S')}.json"
        output = config.paths.export_dir / fname

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(export, indent=2))

    log.info("Saved export to %s", output)
    return output

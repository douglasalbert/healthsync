from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


def _icloud_or_local(subdir: str) -> Path:
    icloud = Path("~/Library/Mobile Documents/com~apple~CloudDocs").expanduser()
    if icloud.exists():
        return icloud / subdir
    return Path(f"~/.healthsync/{subdir}").expanduser()


@dataclass
class OAuthConfig:
    client_id: str
    client_secret: str


@dataclass
class SyncConfig:
    lookback_days: int = 7


@dataclass
class HealthKitConfig:
    write_heart_rate: bool = False  # not available from the official WHOOP API
    write_hrv: bool = True
    write_resting_hr: bool = True
    write_respiratory_rate: bool = True
    write_spo2: bool = True
    write_sleep_stages: bool = True
    write_active_energy: bool = True
    write_skin_temp: bool = True


@dataclass
class PathsConfig:
    swift_binary: Path = field(
        default_factory=lambda: Path(
            "~/healthsync/healthkit_writer/HealthSyncWriter.app/Contents/MacOS/healthkit-writer"
        ).expanduser()
    )
    state_file: Path = field(
        default_factory=lambda: Path("~/.healthsync/state.json").expanduser()
    )
    token_file: Path = field(
        default_factory=lambda: Path("~/.healthsync/tokens.json").expanduser()
    )
    log_file: Path = field(
        default_factory=lambda: Path("~/Library/Logs/healthsync/sync.log").expanduser()
    )
    export_dir: Path = field(
        default_factory=lambda: _icloud_or_local("HealthSync")
    )


@dataclass
class Config:
    oauth: OAuthConfig
    sync: SyncConfig
    healthkit: HealthKitConfig
    paths: PathsConfig


def _load_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def load_config(config_path: Path | None = None) -> Config:
    if config_path is None:
        env_path = os.environ.get("HEALTHSYNC_CONFIG")
        config_path = (
            Path(env_path).expanduser()
            if env_path
            else Path("~/.healthsync/config.toml").expanduser()
        )

    raw = _load_toml(config_path)
    raw_oauth = raw.get("oauth", {})

    client_id = os.environ.get("WHOOP_CLIENT_ID") or raw_oauth.get("client_id") or ""
    client_secret = os.environ.get("WHOOP_CLIENT_SECRET") or raw_oauth.get("client_secret") or ""

    if not client_id or not client_secret:
        raise ConfigError(
            "WHOOP OAuth credentials not found. "
            "Set WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET env vars, "
            "or add them to ~/.healthsync/config.toml:\n\n"
            "  [oauth]\n"
            "  client_id = \"your-client-id\"\n"
            "  client_secret = \"your-client-secret\"\n\n"
            "Then run 'healthsync auth' once to authorize your account."
        )

    raw_sync = raw.get("sync", {})
    raw_hk = raw.get("healthkit", {})
    raw_paths = raw.get("paths", {})

    paths = PathsConfig()
    if "swift_binary" in raw_paths:
        paths.swift_binary = Path(raw_paths["swift_binary"]).expanduser()
    if "state_file" in raw_paths:
        paths.state_file = Path(raw_paths["state_file"]).expanduser()
    if "token_file" in raw_paths:
        paths.token_file = Path(raw_paths["token_file"]).expanduser()
    if "log_file" in raw_paths:
        paths.log_file = Path(raw_paths["log_file"]).expanduser()
    if "export_dir" in raw_paths:
        paths.export_dir = Path(raw_paths["export_dir"]).expanduser()

    return Config(
        oauth=OAuthConfig(client_id=client_id, client_secret=client_secret),
        sync=SyncConfig(
            lookback_days=raw_sync.get("lookback_days", 7),
        ),
        healthkit=HealthKitConfig(
            write_heart_rate=raw_hk.get("write_heart_rate", False),
            write_hrv=raw_hk.get("write_hrv", True),
            write_resting_hr=raw_hk.get("write_resting_hr", True),
            write_respiratory_rate=raw_hk.get("write_respiratory_rate", True),
            write_spo2=raw_hk.get("write_spo2", True),
            write_sleep_stages=raw_hk.get("write_sleep_stages", True),
            write_active_energy=raw_hk.get("write_active_energy", True),
            write_skin_temp=raw_hk.get("write_skin_temp", True),
        ),
        paths=paths,
    )

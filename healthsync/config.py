from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class WhoopConfig:
    username: str
    password: str


@dataclass
class SyncConfig:
    lookback_days: int = 7
    heart_rate_step_seconds: int = 60


@dataclass
class HealthKitConfig:
    write_heart_rate: bool = True
    write_hrv: bool = True
    write_resting_hr: bool = True
    write_respiratory_rate: bool = True
    write_spo2: bool = True
    write_sleep_stages: bool = True


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
    log_file: Path = field(
        default_factory=lambda: Path("~/Library/Logs/healthsync/sync.log").expanduser()
    )


@dataclass
class Config:
    whoop: WhoopConfig
    sync: SyncConfig
    healthkit: HealthKitConfig
    paths: PathsConfig


def _load_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def _keychain_password(account: str, service: str = "healthsync") -> str | None:
    # The keychain path is a positional argument, not a -k flag.
    login_keychain = str(Path("~/Library/Keychains/login.keychain-db").expanduser())
    try:
        result = subprocess.run(
            [
                "security", "find-generic-password",
                "-a", account,
                "-s", service,
                "-w",
                login_keychain,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def load_config(config_path: Path | None = None) -> Config:
    if config_path is None:
        env_path = os.environ.get("HEALTHSYNC_CONFIG")
        config_path = Path(env_path).expanduser() if env_path else Path("~/.healthsync/config.toml").expanduser()

    raw = _load_toml(config_path)

    username = (
        os.environ.get("WHOOP_USERNAME")
        or raw.get("whoop", {}).get("username")
        or _keychain_password("whoop_username")
        or ""
    )
    password = (
        os.environ.get("WHOOP_PASSWORD")
        or raw.get("whoop", {}).get("password")
        or _keychain_password("whoop_password")
        or ""
    )

    if not username or not password:
        raise ConfigError(
            "WHOOP credentials not found. Choose one of:\n\n"
            "  1) Environment variables (quickest):\n"
            "       export WHOOP_USERNAME='your@email.com'\n"
            "       export WHOOP_PASSWORD='yourpassword'\n\n"
            "  2) Config file at ~/.healthsync/config.toml:\n"
            "       mkdir -p ~/.healthsync\n"
            "       cp config/healthsync.toml.example ~/.healthsync/config.toml\n"
            "       # then fill in username/password\n\n"
            "  3) macOS Keychain (unlock your keychain first if needed):\n"
            "       security unlock-keychain ~/Library/Keychains/login.keychain-db\n"
            "       security add-generic-password -a whoop_username -s healthsync"
            " -T '' -w 'your@email.com' ~/Library/Keychains/login.keychain-db\n"
            "       security add-generic-password -a whoop_password -s healthsync"
            " -T '' -w 'yourpassword' ~/Library/Keychains/login.keychain-db"
        )

    raw_sync = raw.get("sync", {})
    raw_hk = raw.get("healthkit", {})
    raw_paths = raw.get("paths", {})

    paths = PathsConfig()
    if "swift_binary" in raw_paths:
        paths.swift_binary = Path(raw_paths["swift_binary"]).expanduser()
    if "state_file" in raw_paths:
        paths.state_file = Path(raw_paths["state_file"]).expanduser()
    if "log_file" in raw_paths:
        paths.log_file = Path(raw_paths["log_file"]).expanduser()

    return Config(
        whoop=WhoopConfig(username=username, password=password),
        sync=SyncConfig(
            lookback_days=raw_sync.get("lookback_days", 7),
            heart_rate_step_seconds=raw_sync.get("heart_rate_step_seconds", 60),
        ),
        healthkit=HealthKitConfig(
            write_heart_rate=raw_hk.get("write_heart_rate", True),
            write_hrv=raw_hk.get("write_hrv", True),
            write_resting_hr=raw_hk.get("write_resting_hr", True),
            write_respiratory_rate=raw_hk.get("write_respiratory_rate", True),
            write_spo2=raw_hk.get("write_spo2", True),
            write_sleep_stages=raw_hk.get("write_sleep_stages", True),
        ),
        paths=paths,
    )

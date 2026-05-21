# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

`healthsync` is a macOS CLI tool that pulls health data from the WHOOP API and writes it to Apple HealthKit. It has two distinct components:

1. **Python package (`healthsync/`)** — fetches data from WHOOP, builds a JSON payload, and invokes the Swift binary via subprocess.
2. **Swift CLI (`healthkit_writer/`)** — receives JSON on stdin, calls HealthKit APIs, and returns `{"status":"ok","written":N,"skipped":N}` on stdout. Must be wrapped in a `.app` bundle (with entitlements and a `CFBundleIdentifier`) because HealthKit TCC authorization requires a bundle identity.

## Commands

```bash
# Install dependencies (uses uv)
uv sync

# Run the sync
uv run healthsync sync
uv run healthsync sync --dry-run    # fetch only, no HK write
uv run healthsync status
uv run healthsync reset-state

# Build the Swift binary (requires Xcode CLT: xcode-select --install)
./scripts/build_swift.sh
# or via CLI:
uv run healthsync build-writer

# Install as an hourly launchd agent
./scripts/setup_launchd.sh

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_sync.py

# Run a single test by name
uv run pytest tests/test_sync.py::test_dry_run_does_not_write
```

## Configuration

Config is loaded from `~/.healthsync/config.toml` (or `$HEALTHSYNC_CONFIG`). See `config/healthsync.toml.example` for all options.

Credential resolution order: env vars (`WHOOP_USERNAME`/`WHOOP_PASSWORD`) → config file → macOS Keychain (`security find-generic-password -s healthsync`).

## Architecture

```
healthsync/
  config.py        — load_config(): TOML + env vars + Keychain → Config dataclass
  models.py        — HRSample, SleepStage, SleepRecord, CycleRecord; build_hk_payload()
  whoop_client.py  — WhoopClient wraps the whoop-data package; parse_* methods normalize API quirks
  hk_writer.py     — HKWriterBridge: serializes payload to JSON, calls Swift binary via subprocess
  sync.py          — run_sync(): orchestrates fetch → build_hk_payload → write, updates SyncState
  state.py         — SyncState: atomic JSON write with flock; tracks last_sync_utc
  __main__.py      — Click CLI entry point (sync, status, reset-state, build-writer)
```

**Data flow:** `run_sync` → `WhoopClient.get_{cycles,heart_rate,sleep}` → `build_hk_payload` → `HKWriterBridge.write_payload` (batches in 500s) → Swift binary stdin/stdout → `SyncState.mark_synced`.

**Key design constraints:**
- The Swift binary must live inside an `.app` bundle with entitlements for HealthKit TCC authorization to persist across launchd runs.
- `HKWriterBridge` batches quantity samples at 500 per subprocess call to stay within HealthKit limits.
- WHOOP reports HRV as RMSSD but writes to `HKQuantityTypeIdentifierHeartRateVariabilitySDNN`; this is flagged in `sourceMetadata: {WHOOPMetric: "RMSSD"}`.
- SpO2 from WHOOP is 0–100%; HealthKit expects 0.0–1.0 (division happens in `build_hk_payload`).
- State file uses atomic rename (write to `.tmp` + `replace()`) with `fcntl.LOCK_EX` to survive concurrent runs.

## Testing

Tests use `pytest-mock` and `unittest.mock`. The `whoop_data` package is always mocked at the module level (patched into `sys.modules`) because it requires live WHOOP auth. Fixture JSON lives in `tests/fixtures/`. The Swift binary is mocked via `patch("subprocess.run")`.

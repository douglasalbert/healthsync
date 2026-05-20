from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from healthsync.config import ConfigError, load_config
from healthsync.logging_config import setup_logging
from healthsync.state import SyncState


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


@cli.command()
@click.option("--dry-run", is_flag=True, help="Fetch data but skip HealthKit write")
@click.pass_context
def sync(ctx: click.Context, dry_run: bool) -> None:
    """Fetch WHOOP data and write it to Apple HealthKit."""
    from healthsync.sync import run_sync

    try:
        config = load_config()
    except ConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    setup_logging(log_file=config.paths.log_file, debug=ctx.obj["debug"])

    try:
        run_sync(config, dry_run=dry_run)
    except Exception as exc:
        click.echo(f"Sync failed: {exc}", err=True)
        if ctx.obj["debug"]:
            raise
        sys.exit(1)


@cli.command()
def status() -> None:
    """Show the last successful sync time and state file location."""
    try:
        config = load_config()
    except ConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    state = SyncState(config.paths.state_file)
    last_sync = state.last_sync_utc()
    if last_sync is None:
        click.echo("No sync has run yet.")
    else:
        click.echo(f"Last sync: {last_sync.isoformat()}")
    click.echo(f"State file: {config.paths.state_file}")
    click.echo(f"Swift binary: {config.paths.swift_binary}")
    exists = config.paths.swift_binary.exists()
    click.echo(f"Swift binary present: {'yes' if exists else 'NO — run ./scripts/build_swift.sh'}")


@cli.command("reset-state")
@click.confirmation_option(prompt="This will clear the last-sync marker. Proceed?")
def reset_state() -> None:
    """Reset sync state so the next run pulls from scratch."""
    try:
        config = load_config()
    except ConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    SyncState(config.paths.state_file).reset()
    click.echo("State reset. Next sync will use the configured lookback_days.")


@cli.command("build-writer")
def build_writer() -> None:
    """Build the Swift HealthKit writer binary (requires Xcode Command Line Tools)."""
    script = Path(__file__).parent.parent / "scripts" / "build_swift.sh"
    if not script.exists():
        click.echo(f"Build script not found: {script}", err=True)
        sys.exit(1)
    result = subprocess.run(["bash", str(script)])
    sys.exit(result.returncode)


if __name__ == "__main__":
    cli()

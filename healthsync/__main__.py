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
@click.option("--port", default=8765, show_default=True, help="Local port for the OAuth callback server")
@click.pass_context
def auth(ctx: click.Context, port: int) -> None:
    """Authorize healthsync with your WHOOP account (run once)."""
    from healthsync.auth import run_auth_flow
    from healthsync.token_store import TokenStore

    try:
        config = load_config()
    except ConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    setup_logging(log_file=config.paths.log_file, debug=ctx.obj["debug"])

    try:
        token_response = run_auth_flow(config.oauth.client_id, config.oauth.client_secret, port)
        TokenStore(config.paths.token_file).save(token_response)
        click.echo(f"Authorization successful. Tokens saved to {config.paths.token_file}")
    except Exception as exc:
        click.echo(f"Authorization failed: {exc}", err=True)
        if ctx.obj["debug"]:
            raise
        sys.exit(1)


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
    click.echo(f"Token file: {config.paths.token_file} ({'present' if config.paths.token_file.exists() else 'MISSING — run healthsync auth'})")
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


@cli.command("export-csv")
@click.option(
    "--since",
    default=None,
    metavar="YYYY-MM-DD",
    help="Earliest date to pull (default: full WHOOP history)",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output CSV path (default: export_dir from config, or iCloud Drive/HealthSync/)",
)
@click.pass_context
def export_csv_cmd(ctx: click.Context, since: str | None, output: "Path | None") -> None:
    """Export all WHOOP data to a CSV file for import via the iOS Shortcuts app.

    Each row is one HealthKit sample (HRV, sleep stage, etc.).
    The CSV lands in iCloud Drive/HealthSync/ by default so it's
    immediately available on your iPhone.
    """
    from datetime import datetime, timezone

    from healthsync.csv_export import run_csv_export

    try:
        config = load_config()
    except ConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    setup_logging(log_file=config.paths.log_file, debug=ctx.obj["debug"])

    since_dt = None
    if since:
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            click.echo(f"Invalid date '{since}'. Use YYYY-MM-DD format.", err=True)
            sys.exit(1)

    try:
        out_path = run_csv_export(config, since=since_dt, output=output)
        click.echo(f"Exported to: {out_path}")
        click.echo("Open the iOS Shortcuts app on your iPhone and run")
        click.echo("'Import WHOOP Data', pointing it to this CSV.")
        click.echo("See docs/SHORTCUT_DESIGN.md for setup instructions.")
    except Exception as exc:
        click.echo(f"Export failed: {exc}", err=True)
        if ctx.obj["debug"]:
            raise
        sys.exit(1)


@cli.command("export")
@click.option(
    "--since",
    default=None,
    metavar="YYYY-MM-DD",
    help="Earliest date to pull (default: full WHOOP history)",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output file path (default: export_dir from config, or iCloud Drive/HealthSync/)",
)
@click.pass_context
def export_cmd(ctx: click.Context, since: str | None, output: "Path | None") -> None:
    """Export all WHOOP data to a HealthKit-ready JSON file.

    The file is written to iCloud Drive/HealthSync/ by default so it's
    immediately available on your iPhone for the HealthSync iOS importer.
    """
    from datetime import datetime, timezone

    from healthsync.export import run_export

    try:
        config = load_config()
    except ConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    setup_logging(log_file=config.paths.log_file, debug=ctx.obj["debug"])

    since_dt = None
    if since:
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            click.echo(f"Invalid date '{since}'. Use YYYY-MM-DD format.", err=True)
            sys.exit(1)

    try:
        out_path = run_export(config, since=since_dt, output=output)
        click.echo(f"Exported to: {out_path}")
        click.echo("Transfer this file to your iPhone via Files/iCloud Drive,")
        click.echo("then open the HealthSync iOS app to import into Health.")
    except Exception as exc:
        click.echo(f"Export failed: {exc}", err=True)
        if ctx.obj["debug"]:
            raise
        sys.exit(1)


if __name__ == "__main__":
    cli()

#!/usr/bin/env bash
# Install a launchd agent that runs healthsync every hour.
# Credentials are read from macOS Keychain (preferred) or prompted here.
#
# Usage: ./scripts/setup_launchd.sh

set -euo pipefail

LABEL="com.healthsync.sync"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Resolve uv and the project python
UV_BIN="$(command -v uv 2>/dev/null || echo "")"
if [ -z "$UV_BIN" ]; then
    echo "ERROR: uv not found. Install it first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# Prefer Keychain; fall back to prompting
get_secret() {
    local account="$1"
    local val
    val=$(security find-generic-password -a "$account" -s healthsync -w 2>/dev/null || true)
    if [ -n "$val" ]; then
        echo "$val"
        return
    fi
    read -rsp "Enter $account (will NOT be stored in plist; stored in Keychain): " val
    echo ""
    security add-generic-password -a "$account" -s healthsync -w "$val" 2>/dev/null || \
        security add-generic-password -U -a "$account" -s healthsync -w "$val"
    echo "$val"
}

echo "==> Fetching WHOOP credentials from Keychain (or prompting)..."
WHOOP_USER=$(get_secret "whoop_username")
WHOOP_PASS=$(get_secret "whoop_password")

echo "==> Writing launchd plist to $PLIST_DST..."
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_DST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$UV_BIN</string>
        <string>run</string>
        <string>--project</string>
        <string>$REPO_ROOT</string>
        <string>healthsync</string>
        <string>sync</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>WHOOP_USERNAME</key>
        <string>$WHOOP_USER</string>
        <key>WHOOP_PASSWORD</key>
        <string>$WHOOP_PASS</string>
    </dict>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/healthsync/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/healthsync/launchd-err.log</string>
</dict>
</plist>
EOF

chmod 600 "$PLIST_DST"
mkdir -p "$HOME/Library/Logs/healthsync"

echo "==> Loading launchd agent..."
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
launchctl start "$LABEL"

echo ""
echo "✓ launchd agent installed and started."
echo "  Logs: ~/Library/Logs/healthsync/"
echo "  To stop: launchctl unload $PLIST_DST"
echo "  To check status: launchctl list | grep healthsync"

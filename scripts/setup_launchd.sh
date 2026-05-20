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

LOGIN_KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

# Try to unlock the login keychain so Keychain operations work without a UI prompt.
# This is a no-op if it's already unlocked; it prompts for the keychain password if locked.
_unlock_keychain() {
    if ! security show-keychain-info "$LOGIN_KEYCHAIN" 2>&1 | grep -q "no-timeout\|timeout"; then
        # Keychain is locked — attempt a silent unlock first, then fall back to prompting
        security unlock-keychain "$LOGIN_KEYCHAIN" 2>/dev/null || true
    fi
}

# Store a credential in the login keychain, or update it if it already exists.
# Returns non-zero only on a hard failure (keychain truly inaccessible).
_keychain_store() {
    local account="$1" value="$2"
    # -U updates if already present; fall back to plain add on first run
    security add-generic-password \
        -a "$account" -s healthsync \
        -w "$value" \
        -k "$LOGIN_KEYCHAIN" \
        -T "" \
        2>/dev/null \
    || security add-generic-password \
        -U \
        -a "$account" -s healthsync \
        -w "$value" \
        -k "$LOGIN_KEYCHAIN" \
        -T "" \
        2>/dev/null
}

# Prefer Keychain; fall back to storing the credential in the plist with chmod 600.
# Sets KEYCHAIN_USED=1 when Keychain write succeeds, 0 otherwise.
KEYCHAIN_USED=1
get_secret() {
    local account="$1"
    local val

    # Read existing value from Keychain (silently)
    val=$(security find-generic-password -a "$account" -s healthsync \
          -k "$LOGIN_KEYCHAIN" -w 2>/dev/null || true)
    if [ -n "$val" ]; then
        echo "$val"
        return
    fi

    # Prompt interactively
    read -rsp "Enter $account: " val
    echo "" >&2

    # Try to persist in Keychain
    _unlock_keychain
    if _keychain_store "$account" "$val"; then
        echo "  → saved to Keychain (launchd will read it from there)" >&2
    else
        echo "  → Keychain write failed; credential will be stored in the plist (chmod 600)" >&2
        KEYCHAIN_USED=0
    fi

    echo "$val"
}

echo "==> Fetching WHOOP credentials (Keychain preferred)..."
WHOOP_USER=$(get_secret "whoop_username")
WHOOP_PASS=$(get_secret "whoop_password")
CREDS_IN_KEYCHAIN=$KEYCHAIN_USED

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
echo "  To stop:         launchctl unload $PLIST_DST"
echo "  To check status: launchctl list | grep healthsync"
if [ "$CREDS_IN_KEYCHAIN" -eq 0 ]; then
    echo ""
    echo "NOTE: Credentials are stored in the plist (${PLIST_DST}) because"
    echo "      the Keychain was not accessible. The file is chmod 600."
    echo "      To move them to Keychain later, unlock your keychain and re-run"
    echo "      this script, or run:"
    echo "        security add-generic-password -a whoop_username -s healthsync -k ~/Library/Keychains/login.keychain-db -w '<value>'"
    echo "        security add-generic-password -a whoop_password -s healthsync -k ~/Library/Keychains/login.keychain-db -w '<value>'"
fi

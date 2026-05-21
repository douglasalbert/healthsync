#!/usr/bin/env bash
# Build the Swift HealthKit writer and wrap it in a minimal .app bundle.
# HealthKit TCC authorization on macOS requires a bundle with CFBundleIdentifier.
#
# Requirements:
#   - Xcode (full, not just Command Line Tools)
#   - A signing identity: open Xcode → Settings → Accounts → add your Apple ID,
#     then Manage Certificates → "+" → Apple Development
#
# Override signing identity:
#   SIGN_IDENTITY="Apple Development: Your Name (TEAMID)" ./scripts/build_swift.sh
#
# Usage: ./scripts/build_swift.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWIFT_PKG="$REPO_ROOT/healthkit_writer"
BUNDLE_ID="com.healthsync.writer"
APP_NAME="HealthSyncWriter"
APP_BUNDLE="$SWIFT_PKG/$APP_NAME.app"
BINARY_NAME="healthkit-writer"

# ---------------------------------------------------------------------------
# Resolve signing identity
# ---------------------------------------------------------------------------
pick_identity() {
    # Prefer Apple Development, then Developer ID Application, then any valid cert.
    security find-identity -v -p codesigning 2>/dev/null \
        | grep -oE '"[^"]+"' \
        | sed 's/"//g' \
        | grep -m1 -E "Apple Development:|Developer ID Application:" \
        || security find-identity -v -p codesigning 2>/dev/null \
            | grep -oE '"[^"]+"' \
            | sed 's/"//g' \
            | grep -v "^$" \
            | head -1
}

if [ -n "${SIGN_IDENTITY:-}" ]; then
    IDENTITY="$SIGN_IDENTITY"
else
    IDENTITY="$(pick_identity || true)"
fi

if [ -z "$IDENTITY" ]; then
    echo ""
    echo "ERROR: No code-signing identity found."
    echo ""
    echo "The HealthKit entitlement requires a real certificate — ad-hoc signing"
    echo "is rejected by amfid on macOS 13+."
    echo ""
    echo "To get a free signing identity:"
    echo "  1. Open Xcode → Settings (⌘,) → Accounts"
    echo "  2. Add your Apple ID (free, no paid developer program needed)"
    echo "  3. Select your Personal Team → Manage Certificates"
    echo "  4. Click '+' → Apple Development"
    echo "  5. Re-run this script"
    echo ""
    echo "Or set SIGN_IDENTITY to an existing certificate name:"
    echo "  security find-identity -v -p codesigning"
    exit 1
fi

echo "==> Signing identity: $IDENTITY"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
echo "==> Building Swift package..."
cd "$SWIFT_PKG"
swift build -c release 2>&1

BINARY_SRC="$SWIFT_PKG/.build/release/$BINARY_NAME"
if [ ! -f "$BINARY_SRC" ]; then
    echo "ERROR: Build succeeded but binary not found at $BINARY_SRC"
    exit 1
fi

# ---------------------------------------------------------------------------
# Assemble .app bundle
# ---------------------------------------------------------------------------
echo "==> Creating .app bundle at $APP_BUNDLE..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"

cp "$BINARY_SRC" "$APP_BUNDLE/Contents/MacOS/$BINARY_NAME"

cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleExecutable</key>
    <string>$BINARY_NAME</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>NSHealthUpdateUsageDescription</key>
    <string>HealthSync writes WHOOP health data (heart rate, sleep stages, respiratory rate, SpO2) to Apple Health.</string>
    <key>NSHealthShareUsageDescription</key>
    <string>HealthSync reads Apple Health data to check for existing records.</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

# ---------------------------------------------------------------------------
# Sign the bundle
# ---------------------------------------------------------------------------
echo "==> Code signing with: $IDENTITY"
codesign --force --sign "$IDENTITY" \
    --entitlements "$SWIFT_PKG/HealthKitEntitlements.plist" \
    "$APP_BUNDLE"

# Verify entitlements were applied (amfid rejects bundles where entitlements
# were requested but not recorded in the signature).
if ! codesign -d --entitlements - "$APP_BUNDLE" 2>/dev/null | grep -q "healthkit"; then
    echo ""
    echo "WARNING: HealthKit entitlement not found in signed bundle."
    echo "The binary may still be rejected by amfid."
    echo "Ensure your certificate has the HealthKit capability or use a"
    echo "Developer ID / Apple Development certificate."
fi

FINAL_BINARY="$APP_BUNDLE/Contents/MacOS/$BINARY_NAME"
echo ""
echo "Build complete."
echo ""
echo "Binary: $FINAL_BINARY"
echo ""
echo "First run: launch it once from an interactive Terminal to trigger the"
echo "HealthKit permission dialog:"
echo ""
echo "  uv run healthsync sync"
echo ""
echo "Then approve access in System Settings → Privacy & Security → Health."

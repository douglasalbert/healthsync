#!/usr/bin/env bash
# Build the Swift HealthKit writer and wrap it in a minimal .app bundle.
# HealthKit TCC authorization on macOS requires a bundle with CFBundleIdentifier.
#
# Requirements: Xcode Command Line Tools (xcode-select --install)
# Usage: ./scripts/build_swift.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWIFT_PKG="$REPO_ROOT/healthkit_writer"
BUNDLE_ID="com.healthsync.writer"
APP_NAME="HealthSyncWriter"
APP_BUNDLE="$SWIFT_PKG/$APP_NAME.app"
BINARY_NAME="healthkit-writer"

echo "==> Building Swift package..."
cd "$SWIFT_PKG"
swift build -c release 2>&1

BINARY_SRC="$SWIFT_PKG/.build/release/$BINARY_NAME"
if [ ! -f "$BINARY_SRC" ]; then
    echo "ERROR: Build succeeded but binary not found at $BINARY_SRC"
    exit 1
fi

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

echo "==> Code signing with ad-hoc signature..."
codesign --force --sign "-" \
    --entitlements "$SWIFT_PKG/HealthKitEntitlements.plist" \
    "$APP_BUNDLE"

FINAL_BINARY="$APP_BUNDLE/Contents/MacOS/$BINARY_NAME"
echo ""
echo "✓ Build complete."
echo ""
echo "Binary: $FINAL_BINARY"
echo ""
echo "Next step: run the sync once in an interactive Terminal session to"
echo "trigger the HealthKit authorization dialog:"
echo ""
echo "  uv run healthsync sync --dry-run"
echo ""
echo "Then approve access in System Settings → Privacy & Security → Health."
echo "After that, scheduled (launchd) runs will use the cached authorization."

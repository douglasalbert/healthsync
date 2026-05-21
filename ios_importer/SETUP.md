# HealthSync iOS Importer — Xcode Setup

## What this does

Reads a `healthsync_export_*.json` file (from `uv run healthsync export`) and
writes all WHOOP data into Apple Health on your iPhone. HealthKit on iOS syncs
automatically to your Mac's Health.app via iCloud — this sidesteps the macOS
code-signing issue entirely.

## One-time Xcode setup (~2 min)

1. **Open the pre-configured project:**
   Open the [HealthSync.xcodeproj](file:///Users/da/Development/healthsync/ios_importer/HealthSync/HealthSync.xcodeproj) in Xcode.

2. **Configure signing settings:**
   - Click the `HealthSync` project root in Xcode's left navigator.
   - Go to the **Signing & Capabilities** tab.
   - Under **Signing**, select your Apple ID/Team in the **Team** dropdown.
   - (Optional) Modify the **Bundle Identifier** to something unique if Xcode complains about signing certificates.

3. **Build & run on your iPhone:**
   - Connect your iPhone to your Mac.
   - Select your iPhone as the run destination in the top toolbar.
   - Click the **▶ Run** button (or press `Cmd + R`).
   - The first run will prompt you for Health access permissions — tap **Allow All**.


## Workflow

```
# On Mac: export latest WHOOP data
uv run healthsync export

# File lands in iCloud Drive/HealthSync/healthsync_export_YYYYMMDD_HHMMSS.json
# (auto-syncs to iPhone Files app)

# On iPhone:
# Open HealthSync Importer → Choose Export File → iCloud Drive → HealthSync
# → select the file → Import to Health
```

## After the first import

Subsequent imports are safe to re-run — HealthKit deduplicates by
`HKExternalUUID` (the `externalUUID` field in the JSON), so nothing is
double-written.

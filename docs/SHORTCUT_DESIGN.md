# iOS Shortcut: Import WHOOP Data

Imports a `healthsync_export_*.csv` file into Apple Health using only
built-in iOS Shortcuts actions. No custom app required.

**Requirements:** iOS 16+ (sleep stage granularity), iCloud Drive enabled.

---

## Workflow overview

```
Mac: uv run healthsync export-csv
  → writes CSV to iCloud Drive/HealthSync/healthsync_export_YYYYMMDD.csv

iPhone: run "Import WHOOP Data" shortcut
  → pick the CSV from Files
  → iterates every row, calls Log Health Sample per type
  → data appears in Health.app immediately
```

---

## How to insert a variable into an action parameter

Several steps below tell you to set a parameter to a named variable.
To do this, tap the parameter field → tap the **variable icon** in the
keyboard toolbar (looks like `{x}` or a small square with lines) →
select the variable name from the list.

---

## Building the Shortcut

Open **Shortcuts** → tap **+** (new shortcut) → name it **"Import WHOOP Data"**.

Add actions in order. Tap **+** and search by name to find each action.

---

### 1. Get File

- Action: **Get File**
- Show document picker: **ON**
- File types: leave blank

---

### 2. Get Text from Input

- Action: **Get Text from Input**
- Input: **File** (the output from step 1 — tap the field and pick it from the list above the keyboard)

---

### 3. Split Text (by newline)

- Action: **Split Text**
- Text: **Text** (output of step 2)
- By: **New Lines**

---

### 4. Set Variable — `Lines`

- Action: **Set Variable**
- Variable name: `Lines`
- Value: **Split Text** (output of step 3)

---

### 5. Repeat with Each

- Action: **Repeat with Each**
- Items: tap the field → **Get Variable** → `Lines`

Everything through **End Repeat** is inside this loop.

---

#### 5a. Split current row (by comma)

- Action: **Split Text**
- Text: **Repeat Item**
- By: **Custom** → type a single comma `,`

---

#### 5b. Set Variable — `Fields`

- Action: **Set Variable**
- Variable: `Fields`
- Value: **Split Text** (output of step 5a)

---

#### 5c–5g. Extract each field

Add five pairs of **Get Item from List** + **Set Variable**:

| Get Item from List settings | Set Variable name |
|-----------------------------|-------------------|
| List: `Fields` · Item: **First Item** | `RowType` |
| List: `Fields` · Item: **Item at Index** `2` | `RowValue` |
| List: `Fields` · Item: **Item at Index** `3` | `RowStage` |
| List: `Fields` · Item: **Item at Index** `5` | `RowStart` |
| List: `Fields` · Item: **Item at Index** `6` | `RowEnd` |

For each pair:
1. Add **Get Item from List** (configure List and Item as shown)
2. Immediately after, add **Set Variable** — name as shown, value = **Item from List** (the output of that Get Item)

---

#### 5h. Skip the header row

- Action: **If**
- Input: **Get Variable** → `RowType`
- Condition: **is** → type the literal text `type`

Leave the **If** body empty. Put all remaining branches in the **Otherwise** block.

> This skips the CSV's first row (`type,value,stage,…`) without doing anything.

---

#### 5i. HRV — inside Otherwise

- **If** (Get Variable → `RowType`) **is** `hrv`
  - Action: **Log Health Sample**
    - Sample Type: **Heart Rate Variability**
    - Value: Get Variable → `RowValue`
    - Start Date: Get Variable → `RowStart`
    - End Date: Get Variable → `RowEnd`

---

#### 5j. Resting Heart Rate

- **Otherwise If** (Get Variable → `RowType`) **is** `restingHr`
  - **Log Health Sample**
    - Sample Type: **Resting Heart Rate**
    - Value: Get Variable → `RowValue`
    - Unit: **BPM**
    - Start Date: Get Variable → `RowStart`
    - End Date: Get Variable → `RowEnd`

---

#### 5k. Oxygen Saturation

- **Otherwise If** `RowType` **is** `oxygenSaturation`
  - **Log Health Sample**
    - Sample Type: **Oxygen Saturation**
    - Value: Get Variable → `RowValue`  ← CSV stores 0.0–1.0 (e.g., 0.97)
    - Start Date: Get Variable → `RowStart`
    - End Date: Get Variable → `RowEnd`

---

#### 5l. Respiratory Rate

- **Otherwise If** `RowType` **is** `respiratoryRate`
  - **Log Health Sample**
    - Sample Type: **Respiratory Rate**
    - Value: Get Variable → `RowValue`
    - Unit: **Breaths per Minute**
    - Start Date: Get Variable → `RowStart`
    - End Date: Get Variable → `RowEnd`

---

#### 5m. Active Energy

- **Otherwise If** `RowType` **is** `activeEnergy`
  - **Log Health Sample**
    - Sample Type: **Active Energy**
    - Value: Get Variable → `RowValue`
    - Unit: **Kilocalories**
    - Start Date: Get Variable → `RowStart`
    - End Date: Get Variable → `RowEnd`

---

#### 5n. Body Temperature

- **Otherwise If** `RowType` **is** `bodyTemp`
  - **Log Health Sample**
    - Sample Type: **Body Temperature**
    - Value: Get Variable → `RowValue`
    - Unit: **Celsius**
    - Start Date: Get Variable → `RowStart`
    - End Date: Get Variable → `RowEnd`

---

#### 5o. Sleep — nested stage branches

- **Otherwise If** `RowType` **is** `sleep`

  Add a nested **If / Otherwise If** chain on `RowStage`:

  | **If** `RowStage` **is** | **Log Health Sample** value |
  |--------------------------|-----------------------------|
  | `inBed`    | Sleep Analysis → **In Bed** |
  | `asleep`   | Sleep Analysis → **Asleep** |
  | `awake`    | Sleep Analysis → **Awake** |
  | `light`    | Sleep Analysis → **Asleep (Core)** |
  | `deep`     | Sleep Analysis → **Asleep (Deep)** |
  | `rem`      | Sleep Analysis → **Asleep (REM)** |

  For each branch, the **Log Health Sample** action is:
  - Sample Type: **Sleep Analysis**
  - Value: *(pick from the dropdown — e.g., "In Bed"; this one is NOT a variable)*
  - Start Date: Get Variable → `RowStart`
  - End Date: Get Variable → `RowEnd`

  > "Asleep (Core/Deep/REM)" require iOS 16+. On iOS 15, map all three to "Asleep".

---

### 6. End Repeat

---

### 7. Show Notification

- Action: **Show Notification**
- Title: `Import complete`

---

## Running the Shortcut

1. On your Mac:
   ```
   uv run healthsync export-csv
   ```
   The CSV lands in **iCloud Drive → HealthSync** and syncs to your iPhone.

2. On iPhone: open **Shortcuts** → tap **"Import WHOOP Data"**.

3. In the Files picker: **iCloud Drive → HealthSync** → select the latest CSV.

4. Wait for the loop to finish (30 s to a few minutes depending on history size).

5. Open **Health.app → Browse** to confirm data appears.

---

## Re-import and deduplication

Shortcuts' Log Health Sample has no external UUID support, so running the
same CSV twice creates duplicates.

**Avoid duplicates:** use `--since` to export only new data:
```
uv run healthsync export-csv --since 2025-05-20
```

**Full wipe and re-import:**
1. Health.app → Browse → (any metric) → Data Sources & Access → delete the Shortcuts source entry.
2. `uv run healthsync export-csv` (no `--since`)
3. Run the Shortcut on the full-history file.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Every row is skipped | Step 5h If condition may be wrong — confirm it checks `RowType` **is** the literal string `type` |
| Sleep stages all show as "Asleep" | iOS < 16; stage-specific values aren't available |
| SpO2 reads as 97% instead of 0.97 | Shortcuts may auto-scale percent; if the Health entry is ×100 too high, add a **Calculate** step: `RowValue ÷ 100` and pass that to Log Health Sample |
| Shortcut times out | Use `--since` to limit row count per run |

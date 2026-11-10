# TGA Q50-500 Data Converter

Small Windows app that analyzes and converts TA Instruments TGA Q50-500 raw data files (`.001`, `.002`, … `.00n`) into CSV files.

Current version: **0.8.1**

## Getting the app

Download from the **Actions** tab (latest successful run → *Artifacts*). Each is a single .exe; no installation and no Python needed.

| Download | For |
|---|---|
| `TGA-Q50-500-DataConverter` | Windows 10 and 11 |
| `TGA-Q50-500-DataConverter-Win7-64bit` | Windows 7, 64-bit |
| `TGA-Q50-500-DataConverter-Win7-32bit` | Windows 7, 32-bit |

The Windows 7 versions need **Service Pack 1** and the **Universal C Runtime** update (KB2999226). All three produce identical CSV and info files.

The first time it runs, Windows may show *"Windows protected your PC"* (the .exe is not digitally signed): click **More info → Run anyway**.

## Using it

1. **Section 1 – Files:** add files with *Add files…*, *Add folder…* (picks up every TGA raw file in it), or drag files/folders onto the file list. Raw files are recognised by their **content**, not their name, so names with dots or no extension work too. Text exports, PDFs and method files (`.mth`) are rejected. Aborted, short and still-running runs convert normally; empty runs are flagged.
2. **Check the run type** of each file (also in section 1); it can be changed manually if needed.
3. **Section 2 – Columns to export:** signals recorded by the instrument.
4. **Section 3 – Variables to calculate:** values calculated from the recorded signals.
5. **Section 4 – Info file:** whether to write the info file and which results to put in it.
6. **Section 5 – Save options:** data reduction and output folder.
7. **Convert to CSV.**

The file list shows sample name, run date, number of points, duration and run type. The Status column turns **green** when a file is converted and **red** if it cannot be read or the conversion fails (the reason is shown).

## Section 1 – Run type: ramp or cycling

Each file is classified when it is added (**Run type** column):

- **Ramp** – one or more heating ramps, possibly at different rates, with isothermal holds or temperature dips smaller than the cycle threshold in between.
- **Cycling (N)** – the sample is cooled and heated again, N times. A new cycle starts where heating resumes after the temperature has dropped by at least the **cycle threshold** (default **50 °C**) below the cycle's maximum and risen again by the same amount, **and the method programmes such a cool-down**.

The **Cycle threshold** field under the Run type selector accepts 10–500 °C (back to 50 °C every time the app opens). The Run type column updates immediately, so you can see the effect before converting. A low threshold can split a drying step (e.g. hold at 60 °C, cool to 25 °C, then the real ramp) into two cycles.

Batches can mix both kinds. To correct a file, **double-click its Run type cell** (toggles Ramp/Cycling, shown as "– manual"). The **Run type** selector can also treat all files as ramp or all as cycling. The info file states the run type, whether it was detected, and the threshold.

## Output files

| File | Contents |
|---|---|
| `sample_001.csv` | Plain table; comma-separated, plain ASCII |
| `sample_001_info.txt` | Info file; contents chosen in section 4 |

- The run number is kept in the name, so `sample.001` and `sample.002` never overwrite each other. Names without a run number are kept whole (`6.27 MgCl 1 180` → `6.27 MgCl 1 180.csv`).
- Two runs with the same name in one batch get ` (2)`, ` (3)`, … instead of overwriting.
- If an output file already exists, the app asks: overwrite, skip, or cancel.

## Columns and variables

**Every file gets the same columns** for the same settings, so one analysis script works for a whole batch. If the instrument did not record a signal, the column is kept **empty** and listed under **Flags** in the info file.

### Section 2 – Columns to export

| In the app | CSV column | Source |
|---|---|---|
| Time (min) | `time_min` | Raw signal |
| Temperature (°C) | `temperature_c` | Raw signal |
| Weight (mg) | `weight_mg` | Raw signal |
| Balance purge flow (mL/min) | `balance_flow_ml_per_min` | Raw signal |
| Sample purge flow (mL/min) | `sample_flow_ml_per_min` | Raw signal |
| Active gas (1 or 2) | `gas` | Gas-switch records stored in the file |

### Section 3 – Variables to calculate

Each ticked variable becomes a column in the CSV.

| In the app | CSV column | Definition |
|---|---|---|
| Weight (%) | `weight_pct` | 100 × Weight / first recorded weight |
| Weight (%), dry basis | `weight_dry_pct` | 100 × Weight / dry reference weight (see *Dry basis* below; reference temperature default 150 °C) |
| Mass loss (%) | `mass_loss_pct` | 100 − Weight (%) |
| Heating rate (°C/min) | `heating_rate_c_per_min` | Slope of Temperature vs time |
| Derivative weight (%/min) | `dtg_pct_per_min` | − slope of Weight (%) vs time |
| Derivative weight (%/°C) | `dtg_pct_per_c` | − slope of Weight (%) vs temperature; blank where the heating rate is below 0.1 °C/min (isothermal segments) |
| Derivative weight (mg/min) | `dtg_mg_per_min` | − slope of Weight vs time |

**Derivatives** are **positive for mass loss** and negative for mass gain.

**Smoothing window** (heating rate and derivatives; default 10 s): each slope is a least-squares straight-line fit over a window centred on the point, so peaks are not shifted, only broadened as the window grows.

**Dry basis:**

- If the method holds the sample isothermally at the reference temperature (e.g. *Ramp 10 °C/min to 150 °C*, *Isothermal for 30 min*), the reference is the weight at the **end of the hold**: the last point before the temperature moves again, never later than the programmed hold time or a gas switch. Otherwise it is the weight when the reference temperature is **first reached**.
- The info file states which case was used, e.g. `Dry reference: weight at the end of the isothermal hold at 150 °C (30 min in the method; ends at 42.62 min), 4.10044 mg`.
- Before the reference point the sample still contains moisture, so dry-basis values there are above 100 %, as expected.

### Section 4 – Info file

- **Write info file** – on by default; the options below are greyed out when it is off.
- **Final residue and mass loss** – off by default.
- **Temperature at mass loss** – off by default; the standard set **1, 5, 10, 50 %** or a **custom** list (e.g. `2, 5, 20`). "T at x % loss" is the first time the weight drops x % below the reference weight.
- **Mass loss between temperatures** – off by default; **1–6 steps**, each with a **From** and **To** temperature (see below).

Results are computed from every recorded point:

- **Ramp:** initial and final weight, final residue (%), total mass loss (mg and %), and T at each selected % loss, relative to the first recorded weight.
- **Cycling:** the whole-run final residue, then one row per cycle: start and end time, min and max temperature, weight at the start and end, change (%), and T at each selected % loss. **Per-cycle values are relative to the weight at the start of that cycle.** "n.r." = not reached in that cycle.

### Flags

The info file starts with a **Flags** section: `Flags: none` when everything asked for was produced, otherwise one `[!]` line per problem (what is affected, the reason, the consequence), e.g.

```
Flags
  [!] balance_flow_ml_per_min, sample_flow_ml_per_min: not recorded by this instrument. Columns left empty.
  [!] Mass loss 600-800 °C: not reached while heating (maximum temperature 797.3 °C). Not calculated.
```

Further down, affected entries only carry `[!] see Flags`. In the app, the Status column shows **Done ⚠ see info file**.

Flagged: empty columns (signal not recorded, no gas selection in the method, dry-basis reference temperature never reached), mass-loss steps not reached anywhere in the run, and files with no end-of-data marker. Blanks expected by design (`dtg_pct_per_c` during holds, "n.r." cycles) are explained in the notes, not flagged.

### Mass loss between temperatures

For each step, the app takes the weight when the temperature **first reaches** the From temperature and then the To temperature while heating (interpolated). If the method holds the sample isothermally at the From or To temperature, the weight at the **end of the hold** is used instead (same rule as the dry basis), so drying during a hold at 150 °C counts in the step that ends at 150 °C. It reports:

- **Loss (mg)** = weight at From − weight at To (positive = mass lost);
- **Loss (% of initial)** = loss / first recorded weight; consecutive steps add up (25–150 + 150–600 = 25–600);
- **Loss (% of dry)**, only when *Weight (%), dry basis* is ticked = loss / dry reference weight.

Cycling runs get one table per step with one row per cycle, relative to the **weight at the start of each cycle**; only the heating part of each cycle is used.

- If a run or cycle starts above the From temperature (many start at 30–50 °C), its **first point** is used and the row is marked `*`.
- The To temperature must actually be reached: a ramp programmed to 800 °C may stop at 797 °C, so use 600–790 °C rather than 600–800 °C.

## Section 5 – Save options

- **Save CSV files to:** *Same folder as each file* (default) or *This folder*. Saving directly on the Desktop (normal, OneDrive or Public) is blocked.
- **Reduce long runs to ~19,000 points (UA style)** – off by default, so **every recorded point** is exported. Universal Analysis (UA) caps its text export at about 19,000 points; this option mimics that for runs over 20,000 points by averaging consecutive points (restarting at each gas switch). Close to UA's export, not bit-identical.

## Troubleshooting

Unexpected errors are shown in a message box and appended to `%APPDATA%\TGA-Q50-500-DataConverter\error.log`. Send that file along with the raw file that caused it.

## For developers

| File | Role |
|---|---|
| `tga_reader.py` | Reads the raw files |
| `analysis.py` | Run type / cycle detection, holds, results per run and per cycle |
| `converter.py` | Columns, calculations, reduction, CSV and info file |
| `app.py` | Window (Tkinter, drag-and-drop via tkinterdnd2) |
| `tests/smoke_gui.py` | Checks run on every build |
| `tga_converter.ico`, `icon/` | App icon and its source drawings |
| `.github/workflows/build-windows.yml` | Builds the three .exe files on every push to `main` (Python 3.12; Windows 7: Python 3.8 + PyInstaller 5.13.2) |

To build locally (Windows, Python 3.8 or newer; use 3.8 for Windows 7):

```
pip install pyinstaller tkinterdnd2
pyinstaller --onefile --windowed --name TGA-Q50-500-DataConverter --icon tga_converter.ico --add-data "tga_converter.ico;." --collect-all tkinterdnd2 app.py
```

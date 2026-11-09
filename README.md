# TGA Q50-500 Data Converter & Analyzer

Small Windows app that analyzes and converts TA Instruments TGA Q50-500 raw data files (`.001`, `.002`, … `.00n`) into CSV files.

Current version: **0.8.0**

## Getting the app

Download from the **Actions** tab (latest successful run → *Artifacts*). Each is a single .exe; no installation and no Python needed.

| Download | For |
|---|---|
| `TGA-Q500-DataConverter` | Windows 10 and 11 |
| `TGA-Q500-DataConverter-Win7-64bit` | Windows 7, 64-bit |
| `TGA-Q500-DataConverter-Win7-32bit` | Windows 7, 32-bit |

The Windows 7 versions are built with Python 3.8, the last Python that runs on Windows 7. They need **Service Pack 1** and the Windows **Universal C Runtime** update (KB2999226). All three are built from the same code and produce identical CSV and info files.

The first time it runs, Windows may show *"Windows protected your PC"* (the .exe is not digitally signed): click **More info → Run anyway**.

## Using it

1. **Add files** – *Add files…*, *Add folder…* (picks up every TGA raw file in it), or drag files/folders onto the file list. Raw files are recognised by their **content**, not their name: `.001`, `.002`, … as well as names with dots or no extension. Text exports, PDFs and method files (`.mth`) are rejected. Aborted, short and still-running runs convert normally; empty runs are flagged.
2. **Check the run type** of each file; it can be changed manually if needed.
3. **Section 2 – Columns to export:** signals recorded by the instrument to export.
4. **Section 3 – Variables to calculate:** values calculated from the recorded signals.
5. **Section 4 – Info file:** whether to write the info file and which results to put in it.
6. **Section 5 – Save options:** data reduction and output folder.
7. **Convert to CSV.**

The file list shows sample name, run date, number of points, duration and run type for each file. The Status column turns **green** when a file is converted and **red** if it cannot be read or the conversion fails (the reason is shown).

## Run type: ramp or cycling

Each file is classified when it is added, and the result is shown in the **Run type** column:

- **Ramp** – one or more heating ramps, possibly at different rates, with isothermal holds or temperature dips smaller than the cycle threshold in between.
- **Cycling (N)** – the sample is cooled significantly and heated again, N times. A new cycle starts where heating resumes after the temperature has dropped by at least the **cycle threshold** (default **50 °C**) below the highest temperature of the current cycle and then risen again by at least the same amount, **and the method programmes such a cool-down**. The threshold can be changed in the **Cycle threshold** field under the Run type selector (10–500 °C, back to 50 °C every time the app opens); the Run type column updates immediately, so you can see the effect before converting. A low threshold can split a drying step (e.g. hold at 60 °C, cool to 25 °C, then the real ramp) into two cycles.

Batches can mix both kinds; each file is processed according to its own run type. To correct a file, **double-click its Run type cell** (it toggles between Ramp and Cycling and shows "– manual"). The **Run type** selector next to the file list can also treat all files as ramp or all as cycling. The info file always states the run type used, whether it was detected, and the cycle threshold.

## Output files

For each run, two files are produced next to the original (or in the folder chosen under *This folder*):

| File | Contents |
|---|---|
| `sample_001.csv` | Plain table; comma-separated, plain ASCII |
| `sample_001_info.txt` | Info file; contents chosen in section 4 |

- The run number is kept in the name, so `sample.001` and `sample.002` never overwrite each other. Names without a run number are kept whole (`6.27 MgCl 1 180` → `6.27 MgCl 1 180.csv`).
- Two runs with the same name in one batch (e.g. from different folders, saved to one folder) get ` (2)`, ` (3)`, … instead of overwriting.
- Files are saved in the folder chosen in **section 5 – Save options**.
- If an output file already exists, the app asks: overwrite, skip, or cancel.
- **Saving directly on the Desktop is blocked** (normal, OneDrive or Public Desktop), both when *This folder* is the Desktop and when the source files sit on the Desktop with *Same folder as each file*.

## Columns and variables

**Every file gets the same columns** for the same settings, so one analysis script works for a whole batch. If the instrument did not record a signal, the column is preserved as **empty**. Nothing fails; the column is listed under **Flags** at the top of the info file (see *Flags* below).

### Section 2 – Columns to export (recorded by the instrument)

| In the app | CSV column | Source |
|---|---|---|
| Time (min) | `time_min` | Raw signal |
| Temperature (°C) | `temperature_c` | Raw signal |
| Weight (mg) | `weight_mg` | Raw signal |
| Balance purge flow (mL/min) | `balance_flow_ml_per_min` | Raw signal |
| Sample purge flow (mL/min) | `sample_flow_ml_per_min` | Raw signal |
| Active gas (1 or 2) | `gas` | From the gas-switch records stored in the file |

### Section 3 – Variables to calculate

Each ticked variable becomes a column in the CSV.

| In the app | CSV column | Definition |
|---|---|---|
| Weight (%) | `weight_pct` | 100 × Weight / first recorded weight |
| Weight (%), dry basis | `weight_dry_pct` | 100 × Weight / dry reference weight: the weight at the **end of the isothermal hold** if the method holds the sample at the reference temperature, otherwise the weight when the sample **first** reaches it (default 150 °C; input enabled only when this variable is ticked) |
| Mass loss (%) | `mass_loss_pct` | 100 − Weight (%) |
| Heating rate (°C/min) | `heating_rate_c_per_min` | Slope of Temperature vs time |
| Derivative weight (%/min) | `dtg_pct_per_min` | − slope of Weight (%) vs time |
| Derivative weight (%/°C) | `dtg_pct_per_c` | − slope of Weight (%) vs temperature; blank where the heating rate is below 0.1 °C/min (isothermal segments) |
| Derivative weight (mg/min) | `dtg_mg_per_min` | − slope of Weight vs time |

**Derivatives** are **positive for mass loss** and negative for mass gain.

**Smoothing window** (heating rate and derivatives; default 10 s; enabled only when one of those variables is ticked): each slope is a least-squares straight-line fit over a window centred on the point, so peaks are not shifted, only broadened as the window grows. A different smoothing window can be chosen.

**Dry basis notes:**

- **Which weight is the reference.** If the method holds the sample isothermally at the reference temperature (e.g. *Ramp 10 °C/min to 150 °C*, *Isothermal for 30 min*), the weight at the **end of the hold** is used. Otherwise the weight at the instant it is **first reached** is used.
  - The end of the hold is taken from the data: the last point before the
    temperature starts moving again, never later than the programmed hold
    time or a gas switch.
  - The info file states which case was used, with the time and weight,
    e.g. `Dry reference: weight at the end of the isothermal hold at 150 °C
    (30 min in the method; ends at 42.62 min), 4.10044 mg`.
- **Values above 100 %.** Before the reference point the sample still
  contains moisture, so dry-basis values there are above 100 %, as expected.

### Section 4 – Info file

- **Write info file** – on by default; the options below are greyed out when it is off.
- **Final residue and mass loss** – off by default.
- **Temperature at mass loss** – off by default; when ticked, either the standard set **1, 5, 10, 50 %** or a **custom** list typed by the user (comma-separated, e.g. `2, 5, 20`).
- **Mass loss between temperatures** – off by default; when ticked, choose the number of **steps (1–6)** and enter a **From** and **To** temperature for each. See *Mass loss between temperatures* below.

When ticked, results are computed from every recorded point:

- **Ramp:** initial and final weight, final residue (%), total mass loss (mg and %), and T at each selected % loss, relative to the first recorded weight.
- **Cycling:** the whole-run final residue, then a table with one row per cycle: start and end time, min and max temperature, weight at the start and end of the cycle, change (%), and T at each selected % loss. **Per-cycle values are relative to the weight at the start of that cycle**, so each cycle is measured on its own terms. "n.r." = not reached in that cycle.

"T at x % loss" is the first time the weight drops x % below the
reference weight.

### Flags

The info file starts with a **Flags** section. It reads `Flags: none` when everything asked for was produced. Otherwise it has one `[!]` line per problem: what is affected, the reason, and the consequence (*Column left empty* or *Not calculated*), e.g.

```
Flags
  [!] balance_flow_ml_per_min, sample_flow_ml_per_min: not recorded by this instrument. Columns left empty.
  [!] Mass loss 600-800 °C: not reached while heating (maximum temperature 797.3 °C). Not calculated.
```

Further down, the affected entries only carry `[!] see Flags`, so the explanation is in one place. In the app, the Status column then shows **Done ⚠ see info file**.

Flagged: columns left empty (signal not recorded, no gas selection in the method, dry-basis reference temperature never reached), mass-loss steps not reached anywhere in the run, and files with no end-of-data marker (possibly truncated, or the run was still in progress). Blanks that are expected by design, such as `dtg_pct_per_c` during isothermal holds, or a step not covered by some cycles ("n.r."), are explained in the notes and not flagged.

### Mass loss between temperatures

For each step, the app takes the weight when the temperature **first reaches** the From temperature and the weight when it then **first reaches** the To temperature while heating (interpolated between points). If the method holds the sample isothermally at the From or To temperature, the weight at the **end of the hold** is used instead (same rule as the dry basis), so drying during a hold at 150 °C counts in the step that ends at 150 °C. It reports:

- **Loss (mg)** = weight at From − weight at To (positive = mass lost, negative = mass gained);
- **Loss (% of initial)** = loss / first recorded weight; consecutive steps add up (25–150 + 150–600 = 25–600);
- **Loss (% of dry)**, only when *Weight (%), dry basis* is ticked = loss / dry weight (same reference temperature as the dry-basis column).

Ramp runs get one row per step. Cycling runs get one table per step with one row per cycle; there the % is relative to the **weight at the start of each cycle**, only the heating part of each cycle is used, and "n.r." marks cycles that do not cover the step.

Details:

- Most runs start above room temperature (often 30–50 °C). If a run or cycle starts above the From temperature but below the To temperature, its **first point** is used as start and the row is marked with `*`.
- The To temperature must actually be reached: a ramp programmed to 800 °C may stop at 797 °C, so 600–800 °C shows "not reached" (and is flagged); use 600–790 °C instead.
- **Loss (% of dry)** uses the same dry reference as the dry-basis column, including the end-of-hold rule.

## Section 5 – Save options

- **Reduce long runs to ~19,000 points (UA style)** – off by default (see below). UA = Universal Analysis, TA Instruments' software.
- **Save CSV files to:** *Same folder as each file* (default) or *This folder* (type a path or use *Browse…*). Saving directly on the Desktop is blocked.

## Full data vs. Universal Analysis

By default **every recorded point** is exported. UA caps its text export at roughly 19,000 points. The optional *"Reduce long runs to ~19,000 points (UA style)"* checkbox mimics this for runs over 20,000 points, averaging consecutive points and restarting at each gas switch. It is a close approximation of UA's export, not a bit-identical copy.

## Troubleshooting

Unexpected errors are shown in a message box and appended to
`%APPDATA%\TGA-Q500-DataConverter\error.log`. Send that file along
with the .001 file that caused it.

## Code

| File | Role |
|---|---|
| `tga_reader.py` | Reads `.001`–`.999` files |
| `analysis.py` | Run-type / cycle detection, results per run and per cycle |
| `converter.py` | Columns, calculations, reduction, CSV and info file |
| `app.py` | Window (Tkinter, drag-and-drop via tkinterdnd2) |
| `tests/smoke_gui.py` | Checks run on every build (window, options, run type, cycle detection and threshold, mass-loss steps, dry reference) |
| `tga_converter.ico`, `icon/` | App icon (built into the .exe) and its source drawings |
| `.github/workflows/build-windows.yml` | Builds the .exe on GitHub's Windows machine |

GitHub Actions builds the three `.exe` files on every push to `main`
(Windows 10/11 with Python 3.12; Windows 7 64-bit and 32-bit with
Python 3.8 and PyInstaller 5.13.2) and runs the checks in each.

To build locally (Windows, Python 3.8 or newer; use 3.8 for Windows 7):

```
pip install pyinstaller tkinterdnd2
pyinstaller --onefile --windowed --name TGA-Q500-DataConverter --icon tga_converter.ico --add-data "tga_converter.ico;." --collect-all tkinterdnd2 app.py
```

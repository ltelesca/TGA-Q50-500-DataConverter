# TGA Q50-500 Data Converter & Analyzer

Small Windows app that analyzes and converts TA Instruments TGA Q50-500 raw data files (`.001`, `.002`, … `.00n`) into CSV files.

Current version: **0.7.0**

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

1. **Add files** – *Add files…*, *Add folder…* (picks up every TGA raw file in it), or drag files/folders onto the file list. Raw files are recognised by their **content**, not their name: `.001`, `.002`, … as well as names with dots or no extension. Text exports, PDFs and method files (`.mth`) are rejected. Aborted, short and still-running runs  convert normally; empty runs are flagged.
2. **Check the run type** of each file, it can be changed manually if needed.
3. **Section 2 – Columns to export:** signals recorded by the instrument to export.
4. **Section 3 – Variables to calculate:** values calculated from the recorded signals.
5. **Section 4 – Info file:** whether to write the info file and which results to put in it.
6. **Section 5 – Save options:** data reduction and output folder.
7. **Convert to CSV.**

The file list shows sample name, run date, number of points, duration and run type for each file. The Status column turns **green** when a file is converted and **red** if it cannot be read or the conversion fails (the reason is shown).

### Defaults

- Run type: **Auto-detect**
- Columns to export: **Time, Temperature, Weight** on; purge flows and gas off
- Variables to calculate: **Weight (%)** on; everything else off
- Info file **on**; final residue and temperature at mass loss **off**
- Save options: reduction **off**, output to **the same folder as each file**

## Run type: ramp or cycling

Each file is classified when it is added, and the result is shown in the **Run type** column:

- **Ramp** – one or more heating ramps, possibly at different rates, with isothermal holds or small temperature dips in between.
- **Cycling (N)** – the sample is cooled significantly and heated again, N times. As a default, a new cycle starts where heating resumes after the temperature has dropped **at least 50 °C** below the highest temperature of the current cycle and then risen again by **at least 50 °C**, **and the method programmes such a cool-down**. The temperature threshold for cycles detection can be adjusted.

Batches can mix both kinds; each file is processed according to its own run type. To correct a file, **double-click its Run type cell** (it toggles between Ramp and Cycling and shows "– manual"). The **Run type** selector next to the file list can also treat all files as ramp or all as cycling. The info file always states the run type used and whether it was detected.

### Output files

For each run, two files are produced next to the original (or in the folder chosen under *This folder*):

| File | Contents |
|---|---|
| `sample_001.csv` | Plain table; comma-separated, plain ASCII  |
| `sample_001_info.txt` | Info file; selection in section 4 |

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

**Sign:** derivatives are **positive for mass loss** and negative for
mass gain, the same convention as Universal Analysis.

In the CSV, recorded signals come first, then calculated variables.

**Smoothing window** (heating rate and derivatives; default 10 s,
enabled only when one of those variables is ticked): each slope is a
least-squares straight-line fit over a window centred on the point, so
peaks are not shifted, only broadened as the window grows. What matters
is the temperature span, heating rate × window: 10 s is 0.3 °C at
2 °C/min but 8 °C at 50 °C/min. For fast ramps with sharp steps,
2–4 s keeps peaks sharper. Universal Analysis uses a 60 s window: set
60 s to reproduce UA's derivative curves.

**Dry basis notes:**

- **Which weight is the reference.** If the method holds the sample
  isothermally at the reference temperature (e.g. *Ramp 10 °C/min to
  150 °C*, *Isothermal for 30 min*), the weight at the **end of the
  hold** is used: the hold is there to dry the sample before the ramp
  goes on. Otherwise (a plain ramp through the reference temperature) the
  weight at the instant it is **first reached** is used.
  - The hold must be programmed in the method, at the reference
    temperature (within 3 °C), the first time the run gets there. A hold
    at another temperature (e.g. hold at 110 °C, reference 150 °C) does
    not count, and neither do slow ramps or Hi-Res slow-downs.
  - The end of the hold is taken from the data: the last point before the
    temperature starts moving again.
  - The info file states which case was used, with the time and weight,
    e.g. `Dry reference: weight at the end of the isothermal hold at 150 °C
    (30 min in the method; ends at 42.62 min), 4.10044 mg`.
- **Values above 100 %.** Before the reference point the sample still
  contains moisture, so dry-basis values there are above 100 %. This is
  expected.
- **One reference for the whole run**, so cycles stay on the same scale.
- **Fast ramps without a hold**: some samples are not completely dry at
  the instant 150 °C is reached (0.03–0.86 % further loss before
  decomposition in our test runs at 50 °C/min). A drying hold in the
  method, or a higher reference temperature still below any
  decomposition, avoids this.

### Section 4 – Info file

- **Write info file** – on by default; the options below are greyed out when it is off.
- **Final residue and mass loss** – off by default.
- **Temperature at mass loss** – off by default; when ticked, either the
  standard set **1, 5, 10, 50 %** or a **custom** list typed by the user
  (comma-separated, e.g. `2, 5, 20`).
- **Mass loss between temperatures** – off by default; when ticked, choose
  the number of **steps (1–6)** and enter a **From** and **To**
  temperature for each (e.g. 25 → 150 °C for moisture, 150 → 600 °C for
  decomposition). See *Mass loss between temperatures* below.

With all results off, the info file still contains the run details,
method steps, gas switches and run type, and for cycling runs the start
and end time and temperature range of each cycle.

When ticked, results are computed from every recorded point:

- **Ramp:** initial and final weight, final residue (%), total mass loss
  (mg and %), and T at each selected % loss, relative to the first
  recorded weight.
- **Cycling:** the whole-run final residue, then a table with one row per
  cycle: start and end time, min and max temperature, weight at the start
  and end of the cycle, change (%), and T at each selected % loss.
  **Per-cycle values are relative to the weight at the start of that
  cycle**, so each cycle is measured on its own terms. "n.r." = not
  reached in that cycle.

"T at x % loss" is the first time the weight drops x % below the
reference weight.

### Flags

The info file starts with a **Flags** section. It reads `Flags: none`
when everything asked for was produced. Otherwise it has one `[!]` line
per problem, with the explanation, e.g.

```
Flags
  [!] balance_flow_ml_per_min, sample_flow_ml_per_min: not recorded by this instrument (columns kept but empty)
  [!] mass loss 600-800 °C: not reached while heating in the run (maximum temperature 797.3 °C)
```

Further down, the affected entries only carry `[!] see Flags`, so the
explanation is in one place. In the app, the Status column then shows
**Done ⚠ see info file**.

Flagged: columns left empty (signal not recorded, no gas selection in the
method, dry-basis reference temperature never reached), mass-loss steps
not reached anywhere in the run, and files with no end-of-data marker
(possibly truncated, or the run was still in progress). Blanks that are
expected by design, such as `dtg_pct_per_c` during isothermal holds, or a
step not covered by some cycles ("n.r."), are explained in the notes and
not flagged.

### Mass loss between temperatures

For each step, the app takes the weight when the temperature **first
reaches** the From temperature and the weight when it then **first
reaches** the To temperature while heating (interpolated between
points), and reports:

- **Loss (mg)** = weight at From − weight at To (positive = mass lost,
  negative = mass gained);
- **Loss (% of initial)** = loss / first recorded weight; consecutive
  steps add up (25–150 + 150–600 = 25–600);
- **Loss (% of dry)**, only when *Weight (%), dry basis* is ticked = loss /
  dry weight (same reference temperature as the dry-basis column). For a
  step below the reference temperature this is the water lost per 100 mg
  of dry material.

Ramp runs get one row per step. Cycling runs get one table per step with
one row per cycle; there the % is relative to the **weight at the start
of each cycle**, only the heating part of each cycle is used, and "n.r."
marks cycles that do not cover the step (e.g. 25–150 °C only exists in
the first cycle of the CaCO₃ runs).

Two details:

- Most runs start above room temperature (often 30–50 °C). If a run or
  cycle starts above the From temperature but below the To temperature,
  its **first point** is used as start and the row is marked with `*`.
- The To temperature must actually be reached: a ramp programmed to
  800 °C may stop at 797 °C, so 600–800 °C shows "not reached" (and is
  flagged); use 600–790 °C instead.
- **Loss (% of dry)** uses the same dry reference as the dry-basis column,
  including the end-of-hold rule.

## Section 5 – Save options

- **Reduce long runs to ~19,000 points (UA style)** – off by default (see below).
- **Save CSV files to:** *Same folder as each file* (default) or *This
  folder* (type a path or use *Browse…*). Saving directly on the Desktop
  is blocked.

The window opens at the size its content needs, taking the Windows
display scaling (100 %, 125 %, 150 %, …) into account, and centred on the
screen; it grows when you add mass-loss steps. Only when the screen is
too small for everything (e.g. a 1366×768 laptop with all six mass-loss
steps) does it use the whole screen and show a scroll bar.

## Full data vs. Universal Analysis

By default **every recorded point** is exported. UA caps its text export
at roughly 19,000 points: runs longer than that (about 2.7 h at 0.5 s
sampling) are averaged down. Example: a 438-min run has 52,603 points;
UA exported 18,979.

The optional *"Reduce long runs to ~19,000 points (UA style)"* checkbox
mimics this for runs over 20,000 points, averaging consecutive points
and restarting at each gas switch. It is a close approximation of UA's
export (differences below 0.02 % of sample mass in testing), not a
bit-identical copy.

## Validation

Tested on **606 raw files** from the lab's Q500 (two sets: 50 files, then
556 files from ~30 users, 2021–2026; methods include ramps, isothermal
holds, step-wise ramps, Hi-Res, CaCO₃ cycling, 0.5 s and 2 s sampling,
`.002`–`.008` re-runs, names without run numbers, an unfinished run):

- every file with data parses and converts, with all columns and
  options, in under 1 s per file; 2 files are empty runs and are flagged;
- **229 UA text exports** compared point for point with their raw file
  (32 + 150 with all five signals, 47 with only some signals or extra UA
  derivative columns): all agree within UA's print rounding. Another 51
  exports were reduced by UA or cover only part of the run; their points
  are all found in the raw data;
- **18 UA derivative columns**: with a 60 s window, 15 agree to within 2 %
  of the peak height and all main peak temperatures agree to within
  0.7 °C; the remaining differences are in %/°C around isothermal holds,
  where the value is undefined (left blank here).

Also tested on **62 runs from a TA Q50** at another lab (same software
version, recording only time, temperature and weight; runs up to 15 h /
107,780 points): all convert with every option; **48 UA text exports**
match point for point and 14 more were reduced by UA; 14 UA derivative
columns agree in peak temperature to within 1.5 °C. A batch mixing Q500
and Q50 files gives identical columns, with the Q50's flow columns empty.

The Windows 7 builds (Python 3.8) and the Windows 10/11 build produce
byte-identical CSV and info files on all 666 test runs.

## Troubleshooting

Unexpected errors are shown in a message box and appended to
`%APPDATA%\TGA-Q500-DataConverter\error.log`. Send that file along
with the .001 file that caused it.

## File format notes

Reverse-engineered from Q Series files:

1. UTF-16-LE text header (BOM `FF FE`), `Key value` lines (Sample, Size,
   Nsig, Sig1…SigN, OrgMethod, Date, …).
2. Form feed `0C 00`.
3. One byte: number of signals N.
4. Records of N little-endian float32 values in header `SigN` order.
   Special records: first value `-3` = gas switch (second value = new gas
   number); `-100` = end of data (a short trailer follows and is ignored).

## Code

| File | Role |
|---|---|
| `tga_reader.py` | Reads `.001`–`.999` files |
| `analysis.py` | Run-type / cycle detection, results per run and per cycle |
| `converter.py` | Columns, calculations, reduction, CSV and info file |
| `app.py` | Window (Tkinter, drag-and-drop via tkinterdnd2) |
| `tests/smoke_gui.py` | Checks run on every build (window, options, run type, cycle detection, mass-loss steps, dry reference) |
| `.github/workflows/build-windows.yml` | Builds the .exe on GitHub's Windows machine |

GitHub Actions builds the three `.exe` files on every push to `main`
(Windows 10/11 with Python 3.12; Windows 7 64-bit and 32-bit with
Python 3.8 and PyInstaller 5.13.2) and runs the checks in each. Pushing a
tag such as `v0.6.1` also publishes them on the **Releases** page.

To build locally (Windows, Python 3.8 or newer; use 3.8 for Windows 7):

```
pip install pyinstaller tkinterdnd2
pyinstaller --onefile --windowed --name TGA-Q500-DataConverter --collect-all tkinterdnd2 app.py
```

## Version history

| Version | Changes |
|---|---|
| 0.7.0 | Info file: **Flags** section at the top (`[!]`, or `Flags: none`), affected entries marked `[!] see Flags`; dry basis uses the weight at the end of an isothermal hold at the reference temperature, and the info file states which reference was used; note that dry-basis values before the reference can exceed 100 %; mass loss between temperatures up to 6 steps; green/red status colours fixed on the Windows 7 builds |
| 0.6.1 | Window opens sized to its content and to the Windows display scaling (sharp text at 125/150 %), grows when mass-loss steps are added, scroll bar only when the screen is too small; signals the instrument did not record give empty columns, explained next to each column in the info file; tested on Q50 data |
| 0.6.0 | Code-friendly CSV column names (`time_min`, `temperature_c`, …) in plain ASCII, readable names listed in the info file; mass loss between temperatures (1–5 steps, ramp and per cycle, % of initial and % of dry); window scrolls on small screens; file-list buttons in a 2×2 grid |
| 0.5.3 | Section names: "Variables to calculate" (3) and "Save options" (5) |
| 0.5.2 | Info file: residue and temperature at mass loss off by default |
| 0.5.1 | Windows 7 builds (32- and 64-bit); Python 3.8 compatibility fix |
| 0.5.0 | Raw files recognised by content (names with dots / no extension); derivative sign as in UA (positive = loss) and %/°C computed against temperature; cycles only where the method programmes a cool-down (fixes Hi-Res runs); unique output names within a batch; faster derivatives |
| 0.4.0 | Run type per file (auto-detected ramp / cycling, double-click to change, all-files selector); per-cycle results; new section 4 "Info file" (residue, T at 1/5/10/50 % or custom list); Options becomes section 5 |
| 0.3.0 | Weight dry basis, mass loss, heating rate, DTG in mg/min; results section in info file |
| 0.2.1 | Nothing remembered between sessions |
| 0.2.0 | Separate "export" and "calculate" sections; Desktop guard; smoothing window greyed out unless used |
| 0.1.1 | Fixed buttons that did nothing on Windows; drag-and-drop; error messages and error.log |
| 0.1.0 | First version |

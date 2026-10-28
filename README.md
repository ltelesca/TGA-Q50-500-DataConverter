# TGA Q500 Data Converter

Small Windows app that converts TA Instruments TGA Q500 raw data files
(`.001`, `.002`, … `.999`) into CSV files, without going through
Universal Analysis (UA).

Current version: **0.5.2**

## Getting the app

Download from the **Actions** tab of this repository (latest successful
run → *Artifacts*). Each is a single .exe; no installation and no Python
needed.

| Download | For |
|---|---|
| `TGA-Q500-DataConverter` | Windows 10 and 11 |
| `TGA-Q500-DataConverter-Win7-64bit` | Windows 7, 64-bit |
| `TGA-Q500-DataConverter-Win7-32bit` | Windows 7, 32-bit |

To check which Windows 7 version a PC has: **Control Panel → System →
System type**.

The Windows 7 versions are built with Python 3.8, the last Python that
runs on Windows 7. They need **Service Pack 1** and the Windows
**Universal C Runtime** update (KB2999226), which a Windows 7 PC that
has received Windows Updates already has. The Windows 10/11 version does
**not** run on Windows 7 (typical error: missing
`api-ms-win-core-path-l1-1-0.dll`). All three are built from the same
code and produce identical CSV and info files.

The first time it runs, Windows may show *"Windows protected your PC"*
(the .exe is not digitally signed): click **More info → Run anyway**.

## Using it

1. **Add files** – *Add files…*, *Add folder…* (picks up every TGA raw
   file in it), or drag files/folders onto the file list. Raw files are
   recognised by their **content**, not their name: `.001`, `.002`, … as
   well as names with dots or no extension (`6.27 MgCl 1 180`,
   `2025.02.21_CNI Calicium oxalate std`). Text exports, PDFs and method
   files (`.mth`) are rejected. Aborted, short and still-running runs
   convert normally; empty runs are flagged.
2. **Check the run type** of each file (see *Run type* below).
3. **Section 2 – Columns to export:** signals recorded by the instrument.
4. **Section 3 – Columns to calculate:** derived columns (see below).
5. **Section 4 – Info file:** what goes into the info file.
6. **Section 5 – Options:** data reduction, output folder.
7. **Convert to CSV.**

The file list shows sample name, run date, number of points, duration and
run type for each file. The Status column turns **green** when a file is converted
and **red** if it cannot be read or the conversion fails (the reason is
shown).

### Defaults

The app remembers nothing between sessions (it runs on a shared
instrument PC). Every time it opens:

- Run type: **Auto-detect**
- Columns to export: **Time, Temperature, Weight** on; purge flows and gas off
- Columns to calculate: **Weight (%)** on; everything else off
- Info file **on**; final residue and temperature at mass loss **off** (tick them to add results)
- Reduction **off**, output to **the same folder as each file**

## Run type: ramp or cycling

Each file is classified when it is added, and the result is shown in the
**Run type** column:

- **Ramp** – one or more heating ramps, possibly at different rates, with
  isothermal holds or small temperature dips in between.
- **Cycling (N)** – the sample is cooled significantly and heated again,
  N times. A new cycle starts where heating resumes after the temperature
  has dropped **at least 50 °C** below the highest temperature of the
  current cycle and then risen again by **at least 50 °C**, **and the
  method programmes such a cool-down**. Small dips of 10–20 °C do not
  start a new cycle, and neither do temperature drops the instrument
  makes on its own (Hi-Res runs slow down or reverse heating during fast
  mass loss). Any hold at the low temperature (for example a CO₂-uptake
  step) stays in the cycle it follows.

Batches can mix both kinds; each file is processed according to its own
run type. To correct a file, **double-click its Run type cell** (it
toggles between Ramp and Cycling and shows "– manual"). The **Run type**
selector next to the file list can also treat all files as ramp or all as
cycling. The info file always states the run type used and whether it was
detected, set for that file, or set for all files.

Checked on 554 lab runs against their own method steps: 518 ramp,
36 cycling (2, 10 or 11 cycles). Every cycling run matches its method;
the only runs whose method programmes cycles but which are reported as
ramp are 9 runs aborted inside their first cycle.

### Output files

For each run, two files are written next to the original (or in the
folder chosen under *This folder*):

| File | Contents |
|---|---|
| `sample_001.csv` | Plain table, one header row with column names and units, comma-separated, UTF-8 (opens directly in Excel) |
| `sample_001_info.txt` | Sample, mass, operator, date, instrument, pan/gases, method steps, gas-switch times, point count, results, and notes on how each calculated column was made |

- The run number is kept in the name, so `sample.001` and `sample.002`
  never overwrite each other. Names without a run number are kept whole
  (`6.27 MgCl 1 180` → `6.27 MgCl 1 180.csv`).
- Two runs with the same name in one batch (e.g. from different folders,
  saved to one folder) get ` (2)`, ` (3)`, … instead of overwriting.
- If an output file already exists, the app asks: overwrite, skip, or cancel.
- **Saving directly on the Desktop is blocked** (normal, OneDrive or
  Public Desktop), both when *This folder* is the Desktop and when the
  source files sit on the Desktop with *Same folder as each file*.
  Subfolders of the Desktop are allowed.

## Columns

### Columns to export (recorded by the instrument)

| Column | Source |
|---|---|
| Time (min), Temperature (°C), Weight (mg) | Raw signals |
| Balance / Sample Purge Flow (mL/min) | Raw signals |
| Gas | Active gas (1 or 2), from the gas-switch records stored in the file |

### Columns to calculate

| Column | Definition |
|---|---|
| Weight (%) | 100 × Weight / first recorded weight |
| Weight dry basis (%) | 100 × Weight / weight when the sample **first** reaches the reference temperature (default 150 °C; input enabled only when this column is ticked) |
| Mass Loss (%) | 100 − Weight (%) |
| Heating Rate (°C/min) | Slope of Temperature vs time |
| Deriv. Weight (%/min) and (mg/min) | − slope of Weight vs time |
| Deriv. Weight (%/°C) | − slope of Weight (%) vs temperature; blank where the heating rate is below 0.1 °C/min (isothermal segments) |

**Sign:** derivatives are **positive for mass loss** and negative for
mass gain, the same convention as Universal Analysis.

In the CSV, recorded signals come first, then calculated columns.

**Smoothing window** (heating rate and derivatives; default 10 s,
enabled only when one of those columns is ticked): each slope is a
least-squares straight-line fit over a window centred on the point, so
peaks are not shifted, only broadened as the window grows. What matters
is the temperature span, heating rate × window: 10 s is 0.3 °C at
2 °C/min but 8 °C at 50 °C/min. For fast ramps with sharp steps,
2–4 s keeps peaks sharper. Universal Analysis uses a 60 s window: set
60 s to reproduce UA's derivative curves.

**Dry basis notes:** one reference weight is used for the whole run, so
cycles stay on the same scale. It is taken at the instant the reference
temperature is crossed, not after a hold; on fast ramps (e.g. 50 °C/min)
some samples are not completely dry at 150 °C (0.03–0.86 % further loss
before decomposition in our test runs). A higher reference temperature,
still below any decomposition, reduces this.

### Info file (section 4)

- **Write info file** – on by default; the options below are greyed out when it is off.
- **Final residue and mass loss** – off by default
- **Temperature at mass loss** – off by default; when ticked, either the standard set **1, 5, 10, 50 %**
  or a **custom** list typed by the user (comma-separated, e.g. `2, 5, 20`).

Results are computed from every recorded point:

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
| `tests/smoke_gui.py` | Checks run on every build (window, options, run type, cycle detection) |
| `.github/workflows/build-windows.yml` | Builds the .exe on GitHub's Windows machine |

GitHub Actions builds the three `.exe` files on every push to `main`
(Windows 10/11 with Python 3.12; Windows 7 64-bit and 32-bit with
Python 3.8 and PyInstaller 5.13.2) and runs the checks in each. Pushing a
tag such as `v0.5.1` also publishes them on the **Releases** page.

To build locally (Windows, Python 3.10+):

```
pip install pyinstaller tkinterdnd2
pyinstaller --onefile --windowed --name TGA-Q500-DataConverter --collect-all tkinterdnd2 app.py
```

## Version history

| Version | Changes |
|---|---|
| 0.5.2 | Info file: residue and temperature at mass loss off by default |
| 0.5.1 | Windows 7 builds (32- and 64-bit); Python 3.8 compatibility fix |
| 0.5.0 | Raw files recognised by content (names with dots / no extension); derivative sign as in UA (positive = loss) and %/°C computed against temperature; cycles only where the method programmes a cool-down (fixes Hi-Res runs); unique output names within a batch; faster derivatives |
| 0.4.0 | Run type per file (auto-detected ramp / cycling, double-click to change, all-files selector); per-cycle results; new section 4 "Info file" (residue, T at 1/5/10/50 % or custom list); Options becomes section 5 |
| 0.3.0 | Weight dry basis, mass loss, heating rate, DTG in mg/min; results section in info file |
| 0.2.1 | Nothing remembered between sessions |
| 0.2.0 | Separate "export" and "calculate" sections; Desktop guard; smoothing window greyed out unless used |
| 0.1.1 | Fixed buttons that did nothing on Windows; drag-and-drop; error messages and error.log |
| 0.1.0 | First version |

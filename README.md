# TGA Q500 Data Converter

Small Windows app that converts TA Instruments TGA Q500 raw data files
(`.001`, `.002`, … `.999`) into CSV files, without going through
Universal Analysis (UA).

Current version: **0.4.0**

## Getting the app

Download the latest `TGA-Q500-DataConverter.exe` from the **Actions** tab
of this repository (latest successful run → *Artifacts*). It is a single
file; no installation and no Python needed.

The first time it runs, Windows may show *"Windows protected your PC"*
(the .exe is not digitally signed): click **More info → Run anyway**.

## Using it

1. **Add files** – *Add files…*, *Add folder…* (picks up every
   `.001`–`.999` file in it), or drag files/folders onto the file list.
   Files with any run number (`.001`, `.002`, `.003`, …) are treated the
   same; aborted or short runs convert normally.
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
- Info file **on**, with final residue and temperatures at 1, 5, 10, 50 % mass loss
- Reduction **off**, output to **the same folder as each file**

## Run type: ramp or cycling

Each file is classified when it is added, and the result is shown in the
**Run type** column:

- **Ramp** – one or more heating ramps, possibly at different rates, with
  isothermal holds or small temperature dips in between.
- **Cycling (N)** – the sample is cooled significantly and heated again,
  N times. A new cycle starts where heating resumes after the temperature
  has dropped **at least 50 °C** below the highest temperature of the
  current cycle and then risen again by **at least 50 °C**. Small dips of
  10–20 °C do not start a new cycle. Any hold at the low temperature (for
  example a CO₂-uptake step) stays in the cycle it follows.

Batches can mix both kinds; each file is processed according to its own
run type. To correct a file, **double-click its Run type cell** (it
toggles between Ramp and Cycling and shows "– manual"). The **Run type**
selector next to the file list can also treat all files as ramp or all as
cycling. The info file always states the run type used and whether it was
detected, set for that file, or set for all files.

Tested on the lab's 50 files: 39 detected as ramp (including the LaNiO
runs with two heating rates), 11 CaCO₃ cycling runs detected with 10
cycles each, with boundaries matching the method (start of each re-heat,
just before the switch back to gas 1).

### Output files

For each run, two files are written next to the original (or in the
folder chosen under *This folder*):

| File | Contents |
|---|---|
| `sample_001.csv` | Plain table, one header row with column names and units, comma-separated, UTF-8 (opens directly in Excel) |
| `sample_001_info.txt` | Sample, mass, operator, date, instrument, pan/gases, method steps, gas-switch times, point count, results, and notes on how each calculated column was made |

- The run number is kept in the name, so `sample.001` and `sample.002`
  never overwrite each other.
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
| Deriv. Weight (%/min) and (mg/min) | Slope of Weight vs time |
| Deriv. Weight (%/°C) | (%/min) ÷ heating rate; blank where the heating rate is below 0.1 °C/min (isothermal segments) |

In the CSV, recorded signals come first, then calculated columns.

**Smoothing window** (heating rate and derivatives; default 10 s,
enabled only when one of those columns is ticked): each slope is a
least-squares straight-line fit over a window centred on the point, so
peaks are not shifted, only broadened as the window grows. What matters
is the temperature span, heating rate × window: 10 s is 0.3 °C at
2 °C/min but 8 °C at 50 °C/min. For fast ramps with sharp steps,
2–4 s keeps peaks sharper.

**Dry basis notes:** one reference weight is used for the whole run, so
cycles stay on the same scale. It is taken at the instant the reference
temperature is crossed, not after a hold; on fast ramps (e.g. 50 °C/min)
some samples are not completely dry at 150 °C (0.03–0.86 % further loss
before decomposition in our test runs). A higher reference temperature,
still below any decomposition, reduces this.

### Info file (section 4)

- **Write info file** – on by default; the options below are greyed out when it is off.
- **Final residue and mass loss**
- **Temperature at mass loss** – either the standard set **1, 5, 10, 50 %**
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

Tested on 50 raw files from the lab's Q500 (LaNiO, CaCO₃ cycling, LiCl /
MgCl isotherms, NMC/LCO/LFP, blanks, aborted runs, `.002`–`.004` re-runs):

- all 50 parse and convert;
- the 32 runs short enough for UA to export in full match UA's text export
  value for value (within UA's print rounding, ~1 part in 10⁶).

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

GitHub Actions builds the `.exe` on every push to `main`. Pushing a tag
such as `v0.4.0` also publishes it on the **Releases** page.

To build locally (Windows, Python 3.10+):

```
pip install pyinstaller tkinterdnd2
pyinstaller --onefile --windowed --name TGA-Q500-DataConverter --collect-all tkinterdnd2 app.py
```

## Version history

| Version | Changes |
|---|---|
| 0.4.0 | Run type per file (auto-detected ramp / cycling, double-click to change, all-files selector); per-cycle results; new section 4 "Info file" (residue, T at 1/5/10/50 % or custom list); Options becomes section 5 |
| 0.3.0 | Weight dry basis, mass loss, heating rate, DTG in mg/min; results section in info file |
| 0.2.1 | Nothing remembered between sessions |
| 0.2.0 | Separate "export" and "calculate" sections; Desktop guard; smoothing window greyed out unless used |
| 0.1.1 | Fixed buttons that did nothing on Windows; drag-and-drop; error messages and error.log |
| 0.1.0 | First version |

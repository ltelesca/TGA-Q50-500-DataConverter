# TGA Q500 Data Converter

Small Windows app that converts TA Instruments TGA Q500 raw data files
(`.001`, `.002`, … `.999`) into CSV files, without going through
Universal Analysis.

## Using it

1. Run `TGA-Q500-DataConverter.exe` (no installation needed).
   The first time, Windows may show *"Windows protected your PC"*:
   click **More info → Run anyway**.
2. **Add files…** or **Add folder…** (picks up every `.001`–`.999` file in it).
3. Tick the columns you want and set the options.
4. **Convert to CSV.**

For each run you get two files next to the original (or in the folder you choose):

| File | Contents |
|---|---|
| `sample_001.csv` | Plain table, one header row with column names and units |
| `sample_001_info.txt` | Sample, mass, operator, date, instrument, pan/gases, method steps, gas-switch times, point count, notes on calculations |

The run number from the extension is kept in the name, so `sample.001`
and `sample.002` never overwrite each other. If an output file already
exists, the app asks before overwriting.

## Columns

| Column | Source |
|---|---|
| Time (min), Temperature (°C), Weight (mg) | Raw signals |
| Balance / Sample purge flow (mL/min) | Raw signals |
| Weight (%) | 100 × Weight / first recorded weight |
| Deriv. Weight (%/min) | Least-squares slope of Weight (%) over a centred window (default 10 s) |
| Deriv. Weight (%/°C) | (%/min) ÷ heating rate; blank where heating rate < 0.1 °C/min (isothermal) |
| Gas | Active gas (1 or 2), from the gas-switch records in the file |

## Full data vs. Universal Analysis

By default **every recorded point** is exported. Universal Analysis caps
its text export at roughly 19,000 points: runs longer than that (about
2.7 h at 0.5 s sampling) are averaged down. The optional
*"Reduce long runs to ~19,000 points"* checkbox mimics this for runs over
20,000 points by averaging consecutive points, restarting at each gas
switch. It is a close approximation of UA's export (differences below
0.02 % of sample mass in testing), not a bit-identical copy.

## File format notes

Reverse-engineered from Q Series files and validated against UA text
exports (32 files identical to print precision):

1. UTF-16-LE text header (BOM `FF FE`), `Key value` lines.
2. Form feed `0C 00`.
3. One byte: number of signals N.
4. Records of N little-endian float32 values in header `SigN` order.
   First value `-3` = gas switch (second value = gas number);
   `-100` = end of data (trailer follows and is ignored).

## Building

GitHub Actions builds the `.exe` on every push to `main`
(**Actions** tab → latest run → *Artifacts*). Pushing a tag such as
`v0.1.0` also publishes it on the **Releases** page.

Locally (Windows, Python 3.10+): `pip install pyinstaller` then
`pyinstaller --onefile --windowed --name TGA-Q500-DataConverter app.py`.

"""Turn a TGARun into a CSV table plus an info text file."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from tga_reader import TGARun

APP_NAME = "TGA Q500 Data Converter"
APP_VERSION = "0.3.0"

UA_POINT_TARGET = 19000
UA_REDUCE_ABOVE = 20000  # UA leaves runs of up to ~19,800 points untouched; 21,450 were reduced
DTG_MIN_HEATING_RATE = 0.1  # °C/min; below this, %/°C is left blank (isothermal)


@dataclass(frozen=True)
class ColumnDef:
    key: str
    label: str           # shown in the app
    header: str          # CSV header
    default: bool
    group: str           # "raw" = recorded by the instrument, "calc" = calculated


# Order here is the column order in the CSV: recorded signals first, then calculated.
COLUMNS: list[ColumnDef] = [
    ColumnDef("time", "Time (min)", "Time (min)", True, "raw"),
    ColumnDef("temp", "Temperature (°C)", "Temperature (°C)", True, "raw"),
    ColumnDef("weight", "Weight (mg)", "Weight (mg)", True, "raw"),
    ColumnDef("balance_flow", "Balance purge flow (mL/min)", "Balance Purge Flow (mL/min)", False, "raw"),
    ColumnDef("sample_flow", "Sample purge flow (mL/min)", "Sample Purge Flow (mL/min)", False, "raw"),
    ColumnDef("gas", "Active gas (1 or 2)", "Gas", False, "raw"),
    ColumnDef("weight_pct", "Weight (%)", "Weight (%)", True, "calc"),
    ColumnDef("weight_pct_dry", "Weight (%), dry basis", "Weight dry basis (%)", False, "calc"),
    ColumnDef("mass_loss", "Mass loss (%)", "Mass Loss (%)", False, "calc"),
    ColumnDef("heating_rate", "Heating rate (°C/min)", "Heating Rate (°C/min)", False, "calc"),
    ColumnDef("dtg_time", "Derivative weight (%/min)", "Deriv. Weight (%/min)", False, "calc"),
    ColumnDef("dtg_temp", "Derivative weight (%/°C)", "Deriv. Weight (%/°C)", False, "calc"),
    ColumnDef("dtg_mg", "Derivative weight (mg/min)", "Deriv. Weight (mg/min)", False, "calc"),
]
# Calculated columns that use the smoothing window.
SMOOTHED_KEYS = ("heating_rate", "dtg_time", "dtg_temp", "dtg_mg")
COLUMN_KEYS = [c.key for c in COLUMNS]

# Which raw signal each direct column comes from (matched by name prefix).
SIGNAL_PREFIX = {
    "time": "Time",
    "temp": "Temperature",
    "weight": "Weight",
    "balance_flow": "Balance Purge Flow",
    "sample_flow": "Sample Purge Flow",
}


@dataclass
class ExportOptions:
    columns: list[str] = field(default_factory=lambda: [c.key for c in COLUMNS if c.default])
    reduce_like_ua: bool = False
    write_info: bool = True
    dtg_window_s: float = 10.0
    dry_temp_c: float = 150.0
    output_dir: Path | None = None  # None = next to the source file


@dataclass
class ExportResult:
    csv_path: Path
    info_path: Path | None
    points_written: int
    points_raw: int
    warnings: list[str]


class ConversionError(Exception):
    pass


def output_paths(src: Path, out_dir: Path | None) -> tuple[Path, Path]:
    """sample.001 -> sample_001.csv / sample_001_info.txt (run number kept)."""
    stem = src.stem + "_" + src.suffix.lstrip(".") if src.suffix else src.name
    folder = out_dir or src.parent
    return folder / f"{stem}.csv", folder / f"{stem}_info.txt"


def _signal_index(run: TGARun, prefix: str) -> int | None:
    for i, name in enumerate(run.signals):
        if name.lower().startswith(prefix.lower()):
            return i
    return None


def _local_slope(x: list[float], y: list[float], half: int) -> list[float | None]:
    """Least-squares slope dy/dx over a centred window of +-half points."""
    n = len(x)
    out: list[float | None] = [None] * n
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        m = b - a
        if m < 3:
            continue
        xs, ys = x[a:b], y[a:b]
        mx = sum(xs) / m
        my = sum(ys) / m
        sxx = sum((v - mx) ** 2 for v in xs)
        if sxx == 0:
            continue
        out[i] = sum((xs[k] - mx) * (ys[k] - my) for k in range(m)) / sxx
    return out


def _weight_at_temperature(T: list[float], W: list[float], target: float) -> float | None:
    """Weight when the temperature first reaches `target` (linear interpolation)."""
    if T[0] >= target:
        return W[0]
    for i in range(1, len(T)):
        if T[i] >= target:
            t0, t1 = T[i - 1], T[i]
            f = (target - t0) / (t1 - t0) if t1 != t0 else 0.0
            return W[i - 1] + f * (W[i] - W[i - 1])
    return None


def _temperature_at_loss(T: list[float], pct: list[float], loss: float) -> float | None:
    """Temperature where Weight (%) first drops to 100 - loss (linear interpolation)."""
    level = 100.0 - loss
    for i in range(1, len(pct)):
        if pct[i] <= level < pct[i - 1]:
            f = (pct[i - 1] - level) / (pct[i - 1] - pct[i])
            return T[i - 1] + f * (T[i] - T[i - 1])
    return None


def _reduce_blocks(n: int, event_rows: list[int], target: int) -> list[tuple[int, int]]:
    """Blocks of consecutive rows to average, restarting at every gas switch."""
    if n <= target:
        return [(i, i + 1) for i in range(n)]
    ratio = n / target
    bounds = [0] + [e for e in event_rows if 0 < e < n] + [n]
    blocks = []
    for s0, s1 in zip(bounds, bounds[1:]):
        start, key = s0, 0
        for i in range(s0, s1):
            k = math.floor((i - s0) / ratio)
            if k != key:
                blocks.append((start, i))
                start, key = i, k
        if start < s1:
            blocks.append((start, s1))
    return blocks


def build_table(run: TGARun, opts: ExportOptions) -> tuple[list[str], list[list[float | None]], list[str]]:
    warnings: list[str] = []
    rows = run.rows
    n = len(rows)
    cols: dict[str, list[float | None]] = {}

    idx = {k: _signal_index(run, p) for k, p in SIGNAL_PREFIX.items()}
    for key in ("time", "temp", "weight"):
        if idx[key] is None:
            raise ConversionError(f"signal '{SIGNAL_PREFIX[key]}' not found in file")
    t = [r[idx["time"]] for r in rows]
    T = [r[idx["temp"]] for r in rows]
    W = [r[idx["weight"]] for r in rows]
    cols["time"], cols["temp"], cols["weight"] = t, T, W

    w0 = W[0]
    if w0 == 0:
        raise ConversionError("first recorded weight is zero; cannot compute Weight (%)")
    pct = [100.0 * w / w0 for w in W]
    cols["weight_pct"] = pct
    cols["mass_loss"] = [100.0 - p for p in pct]

    if "weight_pct_dry" in opts.columns:
        w_dry = _weight_at_temperature(T, W, opts.dry_temp_c)
        if w_dry is None or w_dry == 0:
            warnings.append(
                f"sample never reached {opts.dry_temp_c:g} °C; Weight dry basis column left blank"
            )
            cols["weight_pct_dry"] = [None] * n
        else:
            cols["weight_pct_dry"] = [100.0 * w / w_dry for w in W]

    for key in ("balance_flow", "sample_flow"):
        if key in opts.columns:
            if idx[key] is None:
                warnings.append(f"'{SIGNAL_PREFIX[key]}' not recorded in this file; column left blank")
                cols[key] = [None] * n
            else:
                cols[key] = [r[idx[key]] for r in rows]

    if any(k in opts.columns for k in SMOOTHED_KEYS):
        dt_s = (t[-1] - t[0]) * 60 / max(n - 1, 1) if n > 1 else 0.5
        half = max(1, round(opts.dtg_window_s / 2 / dt_s)) if dt_s > 0 else 1
        dWdt = _local_slope(t, W, half)  # mg/min
        cols["dtg_mg"] = dWdt
        cols["dtg_time"] = [None if v is None else 100.0 * v / w0 for v in dWdt]  # %/min
        dTdt = _local_slope(t, T, half) if ("heating_rate" in opts.columns or "dtg_temp" in opts.columns) else []
        cols["heating_rate"] = dTdt
        if "dtg_temp" in opts.columns:
            cols["dtg_temp"] = [
                (a / b) if (a is not None and b is not None and abs(b) >= DTG_MIN_HEATING_RATE) else None
                for a, b in zip(cols["dtg_time"], dTdt)
            ]

    if "gas" in opts.columns:
        cols["gas"] = [float(g) if g is not None else None for g in run.gas]
        if all(g is None for g in run.gas):
            warnings.append("active gas unknown (no gas selection in method); Gas column left blank")

    keys = [k for k in COLUMN_KEYS if k in opts.columns]
    if not keys:
        raise ConversionError("no columns selected")
    data = [cols[k] for k in keys]

    if opts.reduce_like_ua and n > UA_REDUCE_ABOVE:
        out = []
        for a, b in _reduce_blocks(n, run.event_rows, UA_POINT_TARGET):
            row = []
            for k, col in zip(keys, data):
                if k == "gas":
                    row.append(col[a])
                    continue
                vals = [v for v in col[a:b] if v is not None]
                row.append(sum(vals) / len(vals) if vals else None)
            out.append(row)
    else:
        out = [list(r) for r in zip(*data)]

    headers = [next(c.header for c in COLUMNS if c.key == k) for k in keys]
    return headers, out, warnings


def _fmt(v: float | None) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return ""
    return f"{v:.7g}"


def _duration(run: TGARun) -> float:
    return run.rows[-1][0] - run.rows[0][0] if run.rows else 0.0


def build_info(run: TGARun, opts: ExportOptions, n_out: int, headers: list[str], warnings: list[str]) -> str:
    g = run.get
    lines = [
        f"{APP_NAME} {APP_VERSION} - run information",
        "",
        f"Source file        {run.path.name}",
        f"Original path      {g('OrgFile') or g('File')}",
        f"Sample             {g('Sample')}",
        f"Sample mass        {g('Size')}",
        f"Operator           {g('Operator')}",
        f"Run date / time    {g('Date')} {g('Time')}",
        f"Instrument         {g('Instrument')}  (serial {g('InstSerial')})",
        f"Mode               {g('Mode')}",
        f"Run serial         {g('RunSerial')}",
        f"Method name        {g('Method') or g('ProcName')}",
        f"Comment            {g('Comment')}",
    ]
    for xc in run.get_all("Xcomment"):
        lines.append(f"                   {xc}")
    lines += ["", "Method steps"]
    lines += [f"  {s}" for s in run.get_all("OrgMethod")] or ["  (not recorded)"]

    lines += ["", "Data"]
    lines.append(f"  Signals recorded   {', '.join(run.signals)}")
    lines.append(f"  Raw data points    {len(run.rows)}")
    lines.append(f"  Points in CSV      {n_out}")
    lines.append(f"  Run duration       {_duration(run):.2f} min")
    ti = _signal_index(run, "Temperature")
    if ti is not None:
        lines.append(
            f"  Temperature range  {min(r[ti] for r in run.rows):.2f} to {max(r[ti] for r in run.rows):.2f} °C"
        )
    if not run.complete:
        lines.append("  NOTE: end-of-data marker missing - file may be truncated or the run was still in progress.")

    if run.gas_events:
        lines += ["", "Gas switches (time of first point after the switch)"]
        lines += [f"  {t:10.4f} min  -> gas {gnum}" for t, gnum in run.gas_events]

    wi = _signal_index(run, "Weight")
    if wi is not None and ti is not None and run.rows[0][wi] != 0:
        W = [r[wi] for r in run.rows]
        T = [r[ti] for r in run.rows]
        pct = [100.0 * w / W[0] for w in W]
        lines += ["", "Results (from all recorded points, relative to the first recorded weight)"]
        lines.append(f"  Initial weight     {W[0]:.4f} mg")
        lines.append(f"  Final weight       {W[-1]:.4f} mg   (at {T[-1]:.1f} °C)")
        lines.append(f"  Final residue      {pct[-1]:.2f} %")
        lines.append(f"  Total mass loss    {W[0] - W[-1]:.4f} mg   ({100 - pct[-1]:.2f} %)")
        for loss in (1, 5, 10):
            tx = _temperature_at_loss(T, pct, loss)
            label = f"T at {loss}% loss"
            lines.append(f"  {label:<19}" + (f"{tx:.1f} °C" if tx is not None else "not reached"))
        lines.append("  (T at x% loss = temperature where the weight first drops below 100 - x %;")
        lines.append("   for runs with isothermal holds, cooling or gas cycling, read it with care.)")

    lines += ["", "CSV columns"]
    lines += [f"  {h}" for h in headers]
    lines += ["", "Notes"]
    if wi is not None:
        lines.append(f"  Weight (%) = 100 x Weight / first recorded weight ({run.rows[0][wi]:.6g} mg).")
        if "mass_loss" in opts.columns:
            lines.append("  Mass loss (%) = 100 - Weight (%).")
        if "weight_pct_dry" in opts.columns and ti is not None:
            wd = _weight_at_temperature([r[ti] for r in run.rows], [r[wi] for r in run.rows], opts.dry_temp_c)
            if wd is not None:
                lines.append(
                    f"  Weight dry basis (%) = 100 x Weight / weight when the sample first reached "
                    f"{opts.dry_temp_c:g} °C ({wd:.6g} mg)."
                )
    if any(k in opts.columns for k in SMOOTHED_KEYS):
        lines.append(
            f"  Heating rate and derivatives: least-squares slope over a {opts.dtg_window_s:g} s window."
        )
        if "dtg_temp" in opts.columns:
            lines.append(
                f"  %/°C is left blank where the heating rate is below {DTG_MIN_HEATING_RATE} °C/min (isothermal segments)."
            )
    if opts.reduce_like_ua and len(run.rows) > UA_REDUCE_ABOVE:
        lines.append(
            f"  Data reduced to about {UA_POINT_TARGET} points by averaging consecutive points "
            "(restarting at each gas switch). This approximates Universal Analysis' export; "
            "it is not bit-identical to it."
        )
    else:
        lines.append("  Full data: every recorded point is included.")
    for w in warnings:
        lines.append(f"  WARNING: {w}")
    return "\r\n".join(lines) + "\r\n"


def export_run(run: TGARun, opts: ExportOptions) -> ExportResult:
    headers, table, warnings = build_table(run, opts)
    csv_path, info_path = output_paths(run.path, opts.output_dir)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(",".join(_quote(h) for h in headers) + "\r\n")
        for row in table:
            fh.write(",".join(_fmt(v) for v in row) + "\r\n")
    if opts.write_info:
        info_path.write_text(build_info(run, opts, len(table), headers, warnings), encoding="utf-8-sig", newline="")
    else:
        info_path = None
    return ExportResult(csv_path, info_path, len(table), len(run.rows), warnings)


def _quote(s: str) -> str:
    return f'"{s}"' if re.search(r'[",\n]', s) else s

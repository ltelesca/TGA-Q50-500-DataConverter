"""Turn a TGARun into a CSV table plus an info text file."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from analysis import (
    COOL_DROP_C,
    CYCLING,
    RAMP,
    REHEAT_RISE_C,
    STANDARD_LOSS_LEVELS,
    detect_cycles,
    fmt_level,
    method_programs_cooling,
    segment_result,
)
from tga_reader import TGARun, has_run_number

APP_NAME = "TGA Q500 Data Converter"
APP_VERSION = "0.5.3"

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
    info_residue: bool = False
    info_tloss: bool = False
    tloss_levels: list[float] = field(default_factory=lambda: list(STANDARD_LOSS_LEVELS))
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


def output_paths(src: Path, out_dir: Path | None, stem: str | None = None) -> tuple[Path, Path]:
    """sample.001 -> sample_001.csv / sample_001_info.txt (run number kept).

    Names without a run number keep their full name, dots included:
    '6.27 MgCl 1 180' -> '6.27 MgCl 1 180.csv'.
    """
    if stem is None:
        stem = src.stem + "_" + src.suffix.lstrip(".") if has_run_number(src) else src.name
    folder = out_dir or src.parent
    return folder / f"{stem}.csv", folder / f"{stem}_info.txt"


def _signal_index(run: TGARun, prefix: str) -> int | None:
    for i, name in enumerate(run.signals):
        if name.lower().startswith(prefix.lower()):
            return i
    return None


def _local_slope(x: list[float], y: list[float], half: int) -> list[float | None]:
    """Least-squares slope dy/dx over a centred window of +-half points.

    Uses running sums, so the cost does not grow with the window size.
    """
    n = len(x)
    out: list[float | None] = [None] * n
    if n == 0:
        return out
    x0, y0 = x[n // 2], y[n // 2]  # shift to limit rounding error
    sx = [0.0] * (n + 1)
    sy = [0.0] * (n + 1)
    sxx = [0.0] * (n + 1)
    sxy = [0.0] * (n + 1)
    for i in range(n):
        xi, yi = x[i] - x0, y[i] - y0
        sx[i + 1] = sx[i] + xi
        sy[i + 1] = sy[i] + yi
        sxx[i + 1] = sxx[i] + xi * xi
        sxy[i + 1] = sxy[i] + xi * yi
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        m = b - a
        if m < 3:
            continue
        Sx, Sy = sx[b] - sx[a], sy[b] - sy[a]
        den = m * (sxx[b] - sxx[a]) - Sx * Sx
        if den <= 0:
            continue
        out[i] = (m * (sxy[b] - sxy[a]) - Sx * Sy) / den
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
        # Sign convention as in Universal Analysis: positive = mass loss.
        dWdt = _local_slope(t, W, half)  # mg/min
        cols["dtg_mg"] = [None if v is None else -v for v in dWdt]
        cols["dtg_time"] = [None if v is None else -100.0 * v / w0 for v in dWdt]  # %/min
        dTdt = _local_slope(t, T, half) if ("heating_rate" in opts.columns or "dtg_temp" in opts.columns) else []
        cols["heating_rate"] = dTdt
        if "dtg_temp" in opts.columns:
            # Slope of Weight (%) against temperature over the same window (as UA does);
            # undefined where the temperature hardly changes, so left blank there.
            dPdT = _local_slope(T, pct, half)
            cols["dtg_temp"] = [
                (-a) if (a is not None and r is not None and abs(r) >= DTG_MIN_HEATING_RATE) else None
                for a, r in zip(dPdT, dTdt)
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


def run_type_label(run_type: str, n_cycles: int) -> str:
    return "Ramp" if run_type == RAMP else f"Cycling ({n_cycles} cycle{'s' if n_cycles != 1 else ''})"


def _t(v: float | None, width: int) -> str:
    return (f"{v:.1f}" if v is not None else "n.r.").rjust(width)


def _results_lines(run, opts, run_type, run_type_source, cycles) -> list[str]:
    ti, wi = _signal_index(run, "Temperature"), _signal_index(run, "Weight")
    t = [r[0] for r in run.rows]
    T = [r[ti] for r in run.rows]
    W = [r[wi] for r in run.rows]
    levels = opts.tloss_levels if opts.info_tloss else []
    n = len(run.rows)
    out = ["", f"Run type: {run_type_label(run_type, len(cycles))}  ({run_type_source})"]

    if run_type == RAMP:
        if not (opts.info_residue or opts.info_tloss):
            return out
        r = segment_result(t, T, W, 0, n, levels)
        out += ["", "Results (whole run, relative to the first recorded weight)"]
        if opts.info_residue:
            out.append(f"  Initial weight     {r.w_start:.4f} mg")
            out.append(f"  Final weight       {r.w_end:.4f} mg   (at {T[-1]:.1f} °C)")
            out.append(f"  Final residue      {r.residue_pct:.2f} %")
            out.append(f"  Total mass loss    {r.w_start - r.w_end:.4f} mg   ({100 - r.residue_pct:.2f} %)")
        for x in levels:
            v = r.t_at_loss[x]
            out.append(f"  {'T at ' + fmt_level(x) + '% loss':<19}" + (f"{v:.1f} °C" if v is not None else "not reached"))
        if levels:
            out.append("  (T at x% loss = temperature where the weight first drops below 100 - x % of the initial weight.)")
        return out

    # cycling
    res = [segment_result(t, T, W, a, b, levels) for a, b in cycles]
    if opts.info_residue:
        w0, w1 = W[0], W[-1]
        out += ["", "Whole run"]
        out.append(f"  Initial weight {w0:.4f} mg, final weight {w1:.4f} mg, "
                   f"final residue {100 * w1 / w0:.2f} % of the initial weight")
    out += ["", "Results per cycle (relative to the weight at the start of each cycle)"]
    head1 = ["Cycle", "Start", "End", "T min", "T max"]
    head2 = ["", "(min)", "(min)", "(°C)", "(°C)"]
    widths = [5, 9, 9, 7, 7]
    if opts.info_residue:
        head1 += ["W start", "W end", "Change"]
        head2 += ["(mg)", "(mg)", "(%)"]
        widths += [9, 9, 8]
    for x in levels:
        head1.append(f"T{fmt_level(x)}%")
        head2.append("(°C)")
        widths.append(max(7, len(fmt_level(x)) + 3))
    out.append("  " + " ".join(h.rjust(w) for h, w in zip(head1, widths)))
    out.append("  " + " ".join(h.rjust(w) for h, w in zip(head2, widths)))
    for k, r in enumerate(res, 1):
        cells = [str(k), f"{r.start_time:.2f}", f"{r.end_time:.2f}", f"{r.t_min:.1f}", f"{r.t_max:.1f}"]
        if opts.info_residue:
            cells += [f"{r.w_start:.4f}", f"{r.w_end:.4f}", f"{r.change_pct:+.2f}"]
        row = "  " + " ".join(c.rjust(w) for c, w in zip(cells, widths))
        tcols = [_t(r.t_at_loss[x], w) for x, w in zip(levels, widths[len(cells):])]
        out.append(row + ("" if not tcols else " " + " ".join(tcols)))
    if opts.info_residue:
        out.append("  Change = 100 x (W end - W start) / W start; negative = mass lost in that cycle.")
    if levels:
        out.append("  Tx% = temperature where the weight first drops x % below the weight at the start of the cycle;")
        out.append("  n.r. = not reached in that cycle.")
    return out


def build_info(
    run: TGARun,
    opts: ExportOptions,
    n_out: int,
    headers: list[str],
    warnings: list[str],
    run_type: str = RAMP,
    run_type_source: str = "detected automatically",
    cycles: list[tuple[int, int]] | None = None,
) -> str:
    if cycles is None:
        cycles = [(0, len(run.rows))]
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
    if wi is not None and ti is not None:
        lines += _results_lines(run, opts, run_type, run_type_source, cycles)

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
            f"  Heating rate and derivatives: least-squares slope over a {opts.dtg_window_s:g} s window "
            "centred on each point."
        )
        if any(k in opts.columns for k in ("dtg_time", "dtg_temp", "dtg_mg")):
            lines.append(
                "  Derivative weight sign: positive = mass loss, negative = mass gain "
                "(same convention as Universal Analysis)."
            )
        if "dtg_temp" in opts.columns:
            lines.append(
                f"  %/°C is left blank where the heating rate is below {DTG_MIN_HEATING_RATE} °C/min (isothermal segments)."
            )
    if run_type == CYCLING:
        lines.append(
            f"  Cycles: a new cycle starts where heating resumes after the temperature has dropped at least "
            f"{COOL_DROP_C:g} °C below the cycle's maximum and then risen again by at least {REHEAT_RISE_C:g} °C, "
            "provided the method programmes such a cool-down."
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


def cycles_for(run: TGARun) -> list[tuple[int, int]]:
    """Cycles found in the data, but only if the method programmes a cool-down."""
    ti = _signal_index(run, "Temperature")
    if ti is None or not run.rows:
        return [(0, len(run.rows))]
    T = [r[ti] for r in run.rows]
    if method_programs_cooling(run.get_all("OrgMethod"), T[0]) is False:
        return [(0, len(run.rows))]
    return detect_cycles([r[0] for r in run.rows], T)


def export_run(
    run: TGARun,
    opts: ExportOptions,
    run_type: str | None = None,
    run_type_source: str = "detected automatically",
    cycles: list[tuple[int, int]] | None = None,
    stem: str | None = None,
) -> ExportResult:
    """run_type None = detect. cycles may be passed in if already detected.
    stem overrides the output file name (used to keep names unique in a batch)."""
    if cycles is None:
        cycles = cycles_for(run)
    if run_type is None:
        run_type = CYCLING if len(cycles) > 1 else RAMP
    headers, table, warnings = build_table(run, opts)
    csv_path, info_path = output_paths(run.path, opts.output_dir, stem)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(",".join(_quote(h) for h in headers) + "\r\n")
        for row in table:
            fh.write(",".join(_fmt(v) for v in row) + "\r\n")
    if opts.write_info:
        text = build_info(run, opts, len(table), headers, warnings, run_type, run_type_source, cycles)
        with open(info_path, "w", encoding="utf-8-sig", newline="") as fh:  # Path.write_text(newline=) needs 3.10
            fh.write(text)
    else:
        info_path = None
    return ExportResult(csv_path, info_path, len(table), len(run.rows), warnings)


def _quote(s: str) -> str:
    return f'"{s}"' if re.search(r'[",\n]', s) else s

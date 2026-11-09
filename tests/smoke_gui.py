"""Builds the main window and exercises the code paths behind the buttons
that open dialogs, without showing any dialog. Run on the CI build machine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402
from analysis import CYCLING, RAMP, detect_cycles, parse_loss_levels  # noqa: E402

a = app.App()
assert app.DND_FILES is not None, "drag-and-drop library failed to load"
# The method name must not shadow tkinter's internal Misc._options,
# which every file dialog and message box relies on.
assert app.App._options is app._BaseTk._options, "App overrides tkinter's _options"
opts = a._collect_options()
assert opts is not None and opts.columns, "options not collected"
assert opts.write_info and not opts.info_residue and not opts.info_tloss, "info-file defaults changed"

# custom mass-loss list
a.tloss_var.set(True)
a.tloss_mode.set("custom")
a.tloss_custom.set("20, 2; 5")
assert a._collect_options().tloss_levels == [2, 5, 20]
assert parse_loss_levels("3 %") == [3]

# run-type resolution: auto / forced / per-file override
info = {"detected": CYCLING, "override": None, "cycles": [(0, 1), (1, 2)], "run": None}
assert a._effective_type(info)[0] == CYCLING
info["override"] = RAMP
assert a._effective_type(info) == (RAMP, "set by user for this file")
a.mode_var.set(a.MODES[2])
assert a._effective_type(info) == (CYCLING, "set for all files")

# cycle detection: ramp, ramp with a small dip, and two real cycles
t = [i / 120 for i in range(4000)]
ramp = [20 + 10 * x for x in t]
dip = [v - (15 if 1500 < i < 1700 else 0) for i, v in enumerate(ramp)]
two = [20 + 10 * x if x < 15 else (170 - 10 * (x - 15) if x < 25 else 70 + 10 * (x - 25)) for x in t]
assert len(detect_cycles(t, ramp)) == 1
assert len(detect_cycles(t, dip)) == 1
assert len(detect_cycles(t, two)) == 2

# Hi-Res-style data: the temperature drops > 50 °C and rises again, but the
# method programmes no cool-down, so it must stay a single ramp.
from analysis import method_programs_cooling  # noqa: E402
assert method_programs_cooling(["1: Ramp 5.00 °C/min res -4.00 °C to 800.00 °C"], 20) is False
assert method_programs_cooling(["2: Ramp 50.00 °C/min to 900.00 °C", "4: Equilibrate at 650.00 °C",
                                "8: Ramp 50.00 °C/min to 900.00 °C"], 20) is True

# derivative sign follows Universal Analysis: positive = mass loss
from converter import ExportOptions, build_table, output_paths  # noqa: E402
from tga_reader import TGARun  # noqa: E402
rows = [(i / 120, 20 + i / 12, 10 - i / 1200, 40.0, 60.0) for i in range(600)]
run = TGARun(Path("x.001"), [], ["Time (min)", "Temperature (°C)", "Weight (mg)",
             "Balance Purge Flow (mL/min)", "Sample Purge Flow (mL/min)"], rows, [None] * 600)
_, tab, _, _ = build_table(run, ExportOptions(columns=["time", "dtg_time", "dtg_temp"]))
assert tab[300][1] > 0 and tab[300][2] > 0, "derivative of a mass loss must be positive"

# output names: run number kept, dotted names kept whole
assert output_paths(Path("a/s.002"), None)[0].name == "s_002.csv"
assert output_paths(Path("a/6.27 MgCl 1 180"), None)[0].name == "6.27 MgCl 1 180.csv"

# code-friendly CSV headers
from converter import COLUMNS  # noqa: E402
import re as _re  # noqa: E402
for c in COLUMNS:
    assert _re.fullmatch(r"[a-z][a-z0-9_]*", c.header), f"CSV header not code-friendly: {c.header}"

# mass loss between temperatures: collected from the window, computed per interval
a.ml_var.set(True)
a.ml_steps.set("2")
a._info_state()
a.ml_rows[0][0].set("25"); a.ml_rows[0][1].set("150")
a.ml_rows[1][0].set("150"); a.ml_rows[1][1].set("600")
assert a._collect_options().mass_loss_intervals == [(25.0, 150.0), (150.0, 600.0)]
from analysis import interval_loss  # noqa: E402
T = [50 + i for i in range(600)]
W = [10 - 0.01 * i for i in range(600)]
r = interval_loss(T, W, 25, 150)
assert r.reached and abs(r.loss_mg - 1.0) < 1e-9 and r.start_used == 50
assert not interval_loss(T, W, 700, 800).reached
assert app.MAX_ML_STEPS == 6 and len(a.ml_rows) == 6, "mass loss between temperatures: 6 steps"

# dry-basis reference: first reach on a ramp, end of the hold when the method holds there
from analysis import dry_reference  # noqa: E402
t = [i / 60 for i in range(6000)]  # 1 s points, 100 min
Th = [min(25 + 10 * x, 150) if x < 30 else 150 + 10 * (x - 30) for x in t]  # hold 150 °C from 12.5 to 30 min
Wh = [10 - 0.5 * min(x, 30) / 30 for x in t]  # dries during the hold
steps = ["1: Ramp 10.00 °C/min to 150.00 °C", "2: Isothermal for 17.50 min", "3: Ramp 10.00 °C/min to 800.00 °C"]
r = dry_reference(t, Th, Wh, 150, steps)
assert r.hold and abs(r.time - 30) < 0.3 and abs(r.weight - 9.5) < 0.01, r
r = dry_reference(t, Th, Wh, 150, ["1: Ramp 10.00 °C/min to 800.00 °C"])  # same data, no hold in the method
assert not r.hold and abs(r.time - 12.5) < 0.05
r = dry_reference(t, Th, Wh, 110, steps)  # hold is at another temperature
assert not r.hold and abs(r.time - 8.5) < 0.05
r = dry_reference(t, Th, Wh, 1500, steps)
assert r.weight is None

# mass loss between temperatures: end of a programmed hold at From / To
r = interval_loss(Th, Wh, 25, 150, t, steps)   # To = hold temperature -> end of hold
assert r.hold_to and abs(r.w_to - 9.5) < 0.01, r
r = interval_loss(Th, Wh, 150, 300, t, steps)  # From = hold temperature -> end of hold
assert r.hold_from and abs(r.w_from - 9.5) < 0.01, r
r2 = interval_loss(Th, Wh, 150, 300)           # no method: first reach, as before
assert not r2.hold_from and r2.w_from > 9.5
a1, a2, a3 = (interval_loss(Th, Wh, x, y, t, steps) for x, y in ((25, 150), (150, 300), (25, 300)))
assert abs(a1.loss_mg + a2.loss_mg - a3.loss_mg) < 1e-9  # steps still add up
r = interval_loss(Th, Wh, 100, 200, t, ["1: Ramp 10.00 °C/min to 100.00 °C", "2: Isothermal for 5.00 min"])
assert not r.hold_from  # the data pass straight through 100 °C: no hold, first reach

# the hold never runs past its programmed length or a gas switch (e.g. burn-off after a hold)
short = ["1: Ramp 10.00 °C/min to 150.00 °C", "2: Isothermal for 5.00 min", "3: Select gas 2"]
r = interval_loss(Th, Wh, 25, 150, t, short)
assert r.hold_to and abs(r.w_to - (10 - 0.5 * 17.5 / 30)) < 0.01, r  # 12.5 + 5 min
r = interval_loss(Th, Wh, 25, 150, t, steps, switches=[15.0])
assert r.hold_to and abs(r.w_to - (10 - 0.5 * 15 / 30)) < 0.01, r
assert abs(dry_reference(t, Th, Wh, 150, steps, [15.0]).weight - 9.75) < 0.01

# cycle threshold: 30 °C cycles count only when the threshold is 30 or less
small = [20 + 10 * x if x < 15 else (170 - 10 * (x - 15) if x < 18 else 140 + 10 * (x - 18)) for x in t]
assert len(detect_cycles(t, small)) == 1
assert len(detect_cycles(t, small, 25)) == 2
assert method_programs_cooling(["1: Ramp 10 °C/min to 170.00 °C", "2: Ramp 10 °C/min to 140.00 °C",
                                "3: Ramp 10 °C/min to 300.00 °C"], 20, 25) is True
assert method_programs_cooling(["1: Ramp 10 °C/min to 170.00 °C", "2: Ramp 10 °C/min to 140.00 °C",
                                "3: Ramp 10 °C/min to 300.00 °C"], 20) is False
_warn = app.messagebox.showwarning
app.messagebox.showwarning = lambda *args, **kw: None  # don't block on the expected warning
a.threshold_var.set("5")
assert not a._apply_threshold() and a.threshold == 50 and a.threshold_var.get() == "50"
a.threshold_var.set("30")
assert a._apply_threshold() and a.threshold == 30 and a._collect_options().cycle_threshold_c == 30
a.threshold_var.set("50")
a._apply_threshold()
app.messagebox.showwarning = _warn
assert Path(__file__).resolve().parents[1].joinpath("tga_converter.ico").is_file()

a.update()
a.destroy()
print("GUI smoke test passed")

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
assert opts.info_residue and opts.info_tloss and opts.tloss_levels == [1, 5, 10, 50]

# custom mass-loss list
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
_, tab, _ = build_table(run, ExportOptions(columns=["time", "dtg_time", "dtg_temp"]))
assert tab[300][1] > 0 and tab[300][2] > 0, "derivative of a mass loss must be positive"

# output names: run number kept, dotted names kept whole
assert output_paths(Path("a/s.002"), None)[0].name == "s_002.csv"
assert output_paths(Path("a/6.27 MgCl 1 180"), None)[0].name == "6.27 MgCl 1 180.csv"

a.update()
a.destroy()
print("GUI smoke test passed")

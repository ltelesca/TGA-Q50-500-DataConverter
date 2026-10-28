"""TGA Q500 Data Converter - desktop app (Tkinter)."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from analysis import CYCLING, RAMP, STANDARD_LOSS_LEVELS, parse_loss_levels
from converter import (
    APP_NAME,
    APP_VERSION,
    COLUMNS,
    SMOOTHED_KEYS,
    UA_POINT_TARGET,
    ConversionError,
    ExportOptions,
    cycles_for,
    export_run,
    output_paths,
)
from tga_reader import TGAFormatError, is_raw_file, read_tga


try:  # drag-and-drop support (bundled in the .exe); the app still works without it
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _BaseTk = TkinterDnD.Tk
except Exception:  # pragma: no cover
    DND_FILES = None
    _BaseTk = tk.Tk


def desktop_dirs() -> list[Path]:
    """Every folder Windows shows as 'Desktop' (incl. OneDrive-redirected and Public)."""
    found: list[Path] = []
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

            def known_folder(a, b, c, d) -> Path | None:
                g = GUID(a, b, c, (ctypes.c_ubyte * 8)(*d))
                buf = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(buf)) == 0:
                    p = Path(buf.value)
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                    return p
                return None

            for guid in (
                (0xB4BFCC3A, 0xDB2C, 0x424C, (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)),  # user Desktop
                (0xC4AA340D, 0xF20F, 0x4863, (0xAF, 0xEF, 0xF8, 0x7E, 0xF2, 0xE6, 0xBA, 0x25)),  # Public Desktop
            ):
                p = known_folder(*guid)
                if p:
                    found.append(p)
        except Exception:
            pass
    for env in ("USERPROFILE", "OneDrive", "PUBLIC"):
        if os.environ.get(env):
            found.append(Path(os.environ[env]) / "Desktop")
    found.append(Path.home() / "Desktop")
    return found


def is_desktop(folder: Path) -> bool:
    """True if `folder` IS a Desktop folder (subfolders of the Desktop are allowed)."""
    try:
        target = os.path.normcase(str(folder.resolve()))
    except OSError:
        return False
    for d in desktop_dirs():
        try:
            if os.path.normcase(str(d.resolve())) == target:
                return True
        except OSError:
            continue
    return False


DESKTOP_MSG = (
    "Saving converted files directly on the Desktop is not allowed.\n\n"
    "Choose another folder, or create a subfolder on the Desktop and save there."
)


def settings_path() -> Path:
    """Location of error.log (no settings are stored)."""
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "TGA-Q500-DataConverter" / "settings.json"


class App(_BaseTk):
    MODES = ("Auto-detect", "Treat all as ramp", "Treat all as cycling")

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry("1120x780")
        self.minsize(1060, 740)
        self.files: dict[str, dict] = {}  # tree item id -> {"path", "run", "error"}
        self.queue: queue.Queue = queue.Queue()
        self.busy = False

        self._style()
        self._build()
        self._enable_drop()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- layout ----------
    def _style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Sub.TLabel", foreground="#555555")
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 6))
        style.configure("Treeview", rowheight=24)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        head = ttk.Frame(root)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(head, text="TGA Q500 Data Converter", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            head,
            text="Converts TA Instruments TGA raw files (.001, .002, … or any name) to CSV, with a separate info file.",
            style="Sub.TLabel",
        ).pack(anchor="w")

        # --- files ---
        files = ttk.LabelFrame(root, text=" 1. Files ", style="Section.TLabelframe", padding=8)
        files.grid(row=1, column=0, sticky="nsew")
        files.columnconfigure(0, weight=1)
        files.rowconfigure(0, weight=1)

        cols = ("file", "sample", "date", "points", "duration", "runtype", "status")
        tree = ttk.Treeview(files, columns=cols, show="headings", selectmode="extended")
        for c, text, w, anchor in [
            ("file", "File", 230, "w"),
            ("sample", "Sample", 140, "w"),
            ("date", "Run date", 90, "w"),
            ("points", "Points", 65, "e"),
            ("duration", "Duration", 78, "e"),
            ("runtype", "Run type", 140, "w"),
            ("status", "Status", 200, "w"),
        ]:
            tree.heading(c, text=text, anchor=anchor)
            tree.column(c, width=w, anchor=anchor, stretch=(c in ("file", "status")))
        tree.tag_configure("error", foreground="#b00020")
        tree.tag_configure("done", foreground="#1b7f3b")
        tree.bind("<Double-1>", self._on_double_click)
        tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(files, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree = tree

        btns = ttk.Frame(files)
        btns.grid(row=0, column=2, sticky="n", padx=(10, 0))
        for text, cmd in [
            ("Add files…", self.add_files),
            ("Add folder…", self.add_folder),
            ("Remove", self.remove_selected),
            ("Clear list", self.clear),
        ]:
            ttk.Button(btns, text=text, command=cmd, width=14).pack(fill="x", pady=2)
        ttk.Separator(btns).pack(fill="x", pady=(10, 6))
        ttk.Label(btns, text="Run type:").pack(anchor="w")
        self.mode_var = tk.StringVar(value=self.MODES[0])
        mode = ttk.Combobox(btns, textvariable=self.mode_var, values=self.MODES, state="readonly", width=16)
        mode.pack(fill="x", pady=2)
        mode.bind("<<ComboboxSelected>>", lambda e: self._refresh_run_types())
        ttk.Label(
            btns, text="Double-click a Run type\ncell to change one file.", style="Sub.TLabel", justify="left"
        ).pack(anchor="w", pady=(2, 0))
        self.empty_hint = ttk.Label(
            files, text="Add TGA raw files to get started.", style="Sub.TLabel"
        )
        self.empty_hint.place(relx=0.4, rely=0.5, anchor="center")

        # --- columns + options ---
        mid = ttk.Frame(root)
        mid.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for i, w in enumerate((2, 3, 4)):
            mid.columnconfigure(i, weight=w)
        self.col_vars: dict[str, tk.BooleanVar] = {}

        rawbox = ttk.LabelFrame(mid, text=" 2. Columns to export ", style="Section.TLabelframe", padding=8)
        rawbox.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        calcbox = ttk.LabelFrame(mid, text=" 3. Columns to calculate ", style="Section.TLabelframe", padding=8)
        calcbox.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self.window_var = tk.StringVar(value="10")
        self.dry_var = tk.StringVar(value="150")
        self.sub_rows: dict[str, tuple] = {}

        def sub_row(parent, label, var, lo, hi, unit):
            row = ttk.Frame(parent)
            row.pack(anchor="w", padx=(22, 0), pady=(0, 3))
            lab = ttk.Label(row, text=label)
            lab.pack(side="left")
            spin = ttk.Spinbox(row, from_=lo, to=hi, increment=1, width=6, textvariable=var)
            spin.pack(side="left", padx=4)
            un = ttk.Label(row, text=unit)
            un.pack(side="left")
            return (lab, spin, un)

        for box, group in ((rawbox, "raw"), (calcbox, "calc")):
            for c in (c for c in COLUMNS if c.group == group):
                v = tk.BooleanVar(value=c.default)
                self.col_vars[c.key] = v
                ttk.Checkbutton(box, text=c.label, variable=v, command=self._sub_state).pack(anchor="w", pady=1)
                if c.key == "weight_pct_dry":
                    self.sub_rows["dry"] = sub_row(box, "Reference temperature:", self.dry_var, 0, 1000, "°C")
        self.sub_rows["window"] = sub_row(calcbox, "Smoothing window:", self.window_var, 1, 120, "s")

        right = ttk.Frame(mid)
        right.grid(row=0, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1)

        info = ttk.LabelFrame(right, text=" 4. Info file ", style="Section.TLabelframe", padding=8)
        info.grid(row=0, column=0, sticky="ew")
        self.info_var = tk.BooleanVar(value=True)
        self.residue_var = tk.BooleanVar(value=False)
        self.tloss_var = tk.BooleanVar(value=False)
        self.tloss_mode = tk.StringVar(value="standard")
        self.tloss_custom = tk.StringVar(value="")
        std = ", ".join(f"{x:g}" for x in STANDARD_LOSS_LEVELS)
        ttk.Checkbutton(
            info, text="Write info file (sample, method, gas switches…)", variable=self.info_var,
            command=self._info_state,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        self.info_widgets = []
        w = ttk.Checkbutton(info, text="Final residue and mass loss", variable=self.residue_var)
        w.grid(row=1, column=0, columnspan=3, sticky="w", padx=(22, 0))
        self.info_widgets.append(w)
        w = ttk.Checkbutton(
            info, text="Temperature at mass loss:", variable=self.tloss_var, command=self._info_state
        )
        w.grid(row=2, column=0, columnspan=3, sticky="w", padx=(22, 0))
        self.info_widgets.append(w)
        self.tloss_std_rb = ttk.Radiobutton(
            info, text=f"{std} %", value="standard", variable=self.tloss_mode, command=self._info_state
        )
        self.tloss_std_rb.grid(row=3, column=0, columnspan=3, sticky="w", padx=(44, 0))
        self.tloss_cus_rb = ttk.Radiobutton(
            info, text="Custom:", value="custom", variable=self.tloss_mode, command=self._info_state
        )
        self.tloss_cus_rb.grid(row=4, column=0, sticky="w", padx=(44, 0))
        self.tloss_entry = ttk.Entry(info, textvariable=self.tloss_custom, width=16)
        self.tloss_entry.grid(row=4, column=1, sticky="w", padx=4)
        self.tloss_hint = ttk.Label(info, text="% (e.g. 2, 5, 20)", style="Sub.TLabel")
        self.tloss_hint.grid(row=4, column=2, sticky="w")

        opt = ttk.LabelFrame(right, text=" 5. Options ", style="Section.TLabelframe", padding=8)
        opt.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        right.rowconfigure(1, weight=1)
        opt.columnconfigure(1, weight=1)
        self.reduce_var = tk.BooleanVar(value=False)
        self.outmode_var = tk.StringVar(value="same")
        self.outdir_var = tk.StringVar(value="")

        ttk.Checkbutton(
            opt, text=f"Reduce long runs to ~{UA_POINT_TARGET:,} points (UA style)", variable=self.reduce_var
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(opt, text="Save CSV files to:").grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Radiobutton(
            opt, text="Same folder as each file", value="same", variable=self.outmode_var, command=self._out_mode
        ).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(opt, text="This folder:", value="custom", variable=self.outmode_var, command=self._out_mode).grid(
            row=3, column=0, sticky="w"
        )
        self.outdir_entry = ttk.Entry(opt, textvariable=self.outdir_var)
        self.outdir_entry.grid(row=3, column=1, sticky="ew", padx=4)
        self.browse_btn = ttk.Button(opt, text="Browse…", command=self.pick_outdir)
        self.browse_btn.grid(row=3, column=2)

        # --- bottom bar ---
        bottom = ttk.Frame(root)
        bottom.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        bottom.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(bottom, textvariable=self.status_var, width=48).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.convert_btn = ttk.Button(bottom, text="Convert to CSV", style="Accent.TButton", command=self.convert)
        self.convert_btn.grid(row=0, column=2)

        self._out_mode()
        self._sub_state()
        self._info_state()

    def _info_state(self) -> None:
        on = self.info_var.get()
        for w in self.info_widgets:
            w.configure(state="normal" if on else "disabled")
        t_on = on and self.tloss_var.get()
        for w in (self.tloss_std_rb, self.tloss_cus_rb):
            w.configure(state="normal" if t_on else "disabled")
        c_on = t_on and self.tloss_mode.get() == "custom"
        self.tloss_entry.configure(state="normal" if c_on else "disabled")
        self.tloss_hint.configure(state="normal" if c_on else "disabled")

    # ---------- run type ----------
    def _effective_type(self, info: dict) -> tuple[str, str]:
        mode = self.mode_var.get()
        if mode == self.MODES[1]:
            return RAMP, "set for all files"
        if mode == self.MODES[2]:
            return CYCLING, "set for all files"
        if info.get("override"):
            return info["override"], "set by user for this file"
        return info["detected"], "detected automatically"

    def _show_run_type(self, iid: str) -> None:
        info = self.files[iid]
        if not info["run"]:
            return
        rtype, source = self._effective_type(info)
        label = "Ramp" if rtype == RAMP else f"Cycling ({len(info['cycles'])})"
        if source == "set by user for this file":
            label += " – manual"
        self.tree.set(iid, "runtype", label)

    def _refresh_run_types(self) -> None:
        for iid in self.files:
            self._show_run_type(iid)

    def _on_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not iid or col != f"#{self.tree['columns'].index('runtype') + 1}":
            return
        info = self.files.get(iid)
        if not info or not info["run"]:
            return
        if self.mode_var.get() != self.MODES[0]:
            messagebox.showinfo(
                APP_NAME,
                f"Run type is set to '{self.mode_var.get()}'.\n\n"
                "Choose 'Auto-detect' to change the run type of single files.",
            )
            return
        current, _ = self._effective_type(info)
        new = CYCLING if current == RAMP else RAMP
        info["override"] = None if new == info["detected"] else new
        self._show_run_type(iid)

    def _sub_state(self) -> None:
        """Grey out the extra inputs unless a column that uses them is ticked."""
        uses = {
            "dry": self.col_vars["weight_pct_dry"].get(),
            "window": any(self.col_vars[k].get() for k in SMOOTHED_KEYS),
        }
        for name, on in uses.items():
            for w in self.sub_rows[name]:
                w.configure(state="normal" if on else "disabled")

    # ---------- errors ----------
    def report_callback_exception(self, exc, val, tb) -> None:
        """Show unexpected errors instead of failing silently (no console in the .exe)."""
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            log = settings_path().with_name("error.log")
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            log = None
        messagebox.showerror(
            APP_NAME,
            f"Unexpected error:\n\n{val}\n\n" + (f"Details were saved to:\n{log}" if log else ""),
        )

    # ---------- drag and drop ----------
    def _enable_drop(self) -> None:
        if DND_FILES is None:
            return
        for w in (self.tree, self.empty_hint, self):
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass
        self.empty_hint.configure(text="Drag TGA raw files or folders here, or use Add files…")

    def _on_drop(self, event) -> None:
        paths: list[Path] = []
        for item in self.tk.splitlist(event.data):
            p = Path(item)
            if p.is_dir():
                paths += sorted(q for q in p.iterdir() if q.is_file() and is_raw_file(q))
            elif p.is_file():
                paths.append(p)
        self._add_paths(paths)

    # ---------- files ----------
    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select TGA raw data files",
            filetypes=[("All files", "*.*"), ("Files ending in .001, .002, …", "*.0*")],
        )
        self._add_paths([Path(p) for p in paths])

    def add_folder(self) -> None:
        d = filedialog.askdirectory(title="Select a folder with TGA raw data files")
        if not d:
            return
        found = sorted(p for p in Path(d).iterdir() if p.is_file() and is_raw_file(p))
        if not found:
            messagebox.showinfo(APP_NAME, "No TGA raw data files found in that folder.")
            return
        self._add_paths(found)

    def _add_paths(self, paths: list[Path]) -> None:
        known = {str(v["path"]) for v in self.files.values()}
        for p in paths:
            if str(p) in known:
                continue
            known.add(str(p))
            info = {"path": p, "run": None, "error": None, "cycles": [], "detected": RAMP, "override": None}
            try:
                if not is_raw_file(p):
                    raise TGAFormatError("not a TGA raw data file")
                run = read_tga(p)
                info["run"] = run
                info["cycles"] = cycles_for(run)
                info["detected"] = CYCLING if len(info["cycles"]) > 1 else RAMP
                dur = run.rows[-1][0] - run.rows[0][0]
                status = "Ready" if run.complete else "Ready (run incomplete)"
                vals = (p.name, run.get("Sample"), run.get("Date"), f"{len(run.rows):,}", f"{dur:.1f} min", "", status)
                tags = ()
            except (TGAFormatError, OSError, ValueError) as e:
                info["error"] = str(e)
                vals = (p.name, "", "", "", "", "", f"Cannot read: {e}")
                tags = ("error",)
            iid = self.tree.insert("", "end", values=vals, tags=tags)
            self.files[iid] = info
            self._show_run_type(iid)
        self._update_hint()

    def remove_selected(self) -> None:
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.files.pop(iid, None)
        self._update_hint()

    def clear(self) -> None:
        for iid in list(self.files):
            self.tree.delete(iid)
        self.files.clear()
        self._update_hint()

    def _update_hint(self) -> None:
        if self.files:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.4, rely=0.5, anchor="center")
        ok = sum(1 for v in self.files.values() if v["run"])
        self.status_var.set(f"{ok} file(s) ready." if self.files else "Ready.")

    # ---------- options ----------
    def _out_mode(self) -> None:
        state = "normal" if self.outmode_var.get() == "custom" else "disabled"
        self.outdir_entry.configure(state=state)
        self.browse_btn.configure(state=state)

    def pick_outdir(self) -> None:
        d = filedialog.askdirectory(title="Save CSV files to…")
        if d:
            if is_desktop(Path(d)):
                messagebox.showwarning(APP_NAME, DESKTOP_MSG)
                return
            self.outdir_var.set(d)

    def _collect_options(self) -> ExportOptions | None:
        cols = [k for k, v in self.col_vars.items() if v.get()]
        if not cols:
            messagebox.showwarning(APP_NAME, "Select at least one column to export.")
            return None
        dry = 150.0
        if "weight_pct_dry" in cols:
            try:
                dry = float(self.dry_var.get())
                if not 0 <= dry <= 1000:
                    raise ValueError
            except ValueError:
                messagebox.showwarning(APP_NAME, "Dry-basis reference temperature must be a number (0–1000 °C).")
                return None
        window = 10.0
        if any(k in cols for k in SMOOTHED_KEYS):
            try:
                window = float(self.window_var.get())
                if not 0 < window <= 600:
                    raise ValueError
            except ValueError:
                messagebox.showwarning(APP_NAME, "Smoothing window must be a number of seconds (1–600).")
                return None
        outdir = None
        if self.outmode_var.get() == "custom":
            if not self.outdir_var.get().strip():
                messagebox.showwarning(APP_NAME, "Choose an output folder, or select 'Same folder as each file'.")
                return None
            outdir = Path(self.outdir_var.get().strip())
            if is_desktop(outdir):
                messagebox.showwarning(APP_NAME, DESKTOP_MSG)
                return None
        levels = list(STANDARD_LOSS_LEVELS)
        if self.info_var.get() and self.tloss_var.get() and self.tloss_mode.get() == "custom":
            try:
                levels = parse_loss_levels(self.tloss_custom.get())
            except ValueError:
                messagebox.showwarning(
                    APP_NAME,
                    "Custom mass-loss values must be numbers between 0 and 100, separated by commas "
                    "(for example: 2, 5, 20).",
                )
                return None
        return ExportOptions(
            columns=cols,
            info_residue=self.residue_var.get(),
            info_tloss=self.tloss_var.get(),
            tloss_levels=levels,
            reduce_like_ua=self.reduce_var.get(),
            write_info=self.info_var.get(),
            dtg_window_s=window,
            dry_temp_c=dry,
            output_dir=outdir,
        )

    # ---------- conversion ----------
    def convert(self) -> None:
        if self.busy:
            return
        jobs = [(iid, v) for iid, v in self.files.items() if v["run"]]
        if not jobs:
            messagebox.showinfo(APP_NAME, "Add at least one readable TGA raw file first.")
            return
        opts = self._collect_options()
        if opts is None:
            return
        if opts.output_dir is None:
            on_desktop = [v["path"].name for _, v in jobs if is_desktop(v["path"].parent)]
            if on_desktop:
                names = "\n".join(on_desktop[:8]) + ("\n…" if len(on_desktop) > 8 else "")
                messagebox.showwarning(
                    APP_NAME,
                    f"{len(on_desktop)} file(s) are on the Desktop:\n\n{names}\n\n"
                    "With 'Same folder as each file' their CSVs would be saved on the Desktop.\n"
                    "Select 'This folder' and choose another location.",
                )
                return

        # Planned output names; two runs with the same name (e.g. from different
        # folders, saved to one folder) get " (2)", " (3)", ... instead of overwriting.
        planned: dict[str, str] = {}
        used: set[str] = set()
        for iid, v in jobs:
            csv_p, _ = output_paths(v["path"], opts.output_dir)
            stem, k = csv_p.stem, 2
            while str(csv_p.with_name(stem + ".csv")).lower() in used:
                stem, k = f"{csv_p.stem} ({k})", k + 1
            used.add(str(csv_p.with_name(stem + ".csv")).lower())
            planned[iid] = stem

        existing = []
        for iid, v in jobs:
            csv_p, info_p = output_paths(v["path"], opts.output_dir, planned[iid])
            if csv_p.exists() or (opts.write_info and info_p.exists()):
                existing.append((iid, csv_p.name))
        if existing:
            names = "\n".join(n for _, n in existing[:8]) + ("\n…" if len(existing) > 8 else "")
            ans = messagebox.askyesnocancel(
                APP_NAME,
                f"{len(existing)} output file(s) already exist:\n\n{names}\n\n"
                "Yes = overwrite them\nNo = skip those files\nCancel = do nothing",
            )
            if ans is None:
                return
            if not ans:
                skip = {iid for iid, _ in existing}
                jobs = [(iid, v) for iid, v in jobs if iid not in skip]

        self.busy = True
        self.n_failed = 0
        self.convert_btn.configure(state="disabled")
        self.progress.configure(maximum=len(jobs), value=0)
        for iid, _ in jobs:
            self.tree.set(iid, "status", "Waiting…")
        jobs = [(iid, v, *self._effective_type(v), planned[iid]) for iid, v in jobs]
        threading.Thread(target=self._worker, args=(jobs, opts), daemon=True).start()
        self.after(100, self._poll)

    def _worker(self, jobs, opts: ExportOptions) -> None:
        for iid, v, rtype, source, stem in jobs:
            self.queue.put(("start", iid, None))
            try:
                res = export_run(v["run"], opts, rtype, source, v["cycles"], stem)
                note = "Done" if res.csv_path.stem == output_paths(v["path"], None)[0].stem else f"Done → {res.csv_path.name}"
                if res.points_written != res.points_raw:
                    note += f" (reduced to {res.points_written:,} pts)"
                if res.warnings:
                    note += "  ⚠ see info file"
                self.queue.put(("done", iid, note))
            except (ConversionError, OSError) as e:
                self.queue.put(("error", iid, f"Failed: {e}"))
        self.queue.put(("finished", None, None))

    def _poll(self) -> None:
        try:
            while True:
                kind, iid, msg = self.queue.get_nowait()
                if kind == "start":
                    self.tree.set(iid, "status", "Converting…")
                    self.status_var.set(f"Converting {self.files[iid]['path'].name}…")
                elif kind in ("done", "error"):
                    self.tree.set(iid, "status", msg)
                    self.tree.item(iid, tags=("done",) if kind == "done" else ("error",))
                    self.progress.configure(value=self.progress["value"] + 1)
                    if kind == "error":
                        self.n_failed += 1
                elif kind == "finished":
                    self.busy = False
                    self.convert_btn.configure(state="normal")
                    done = int(self.progress["value"]) - self.n_failed
                    msg = f"Finished: {done} file(s) converted."
                    if self.n_failed:
                        msg += f" {self.n_failed} failed."
                    self.status_var.set(msg)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _on_close(self) -> None:
        self.destroy()


def main() -> None:
    app = App()
    # Files passed on the command line (e.g. dropped onto the .exe) are added at start.
    args = [Path(a) for a in sys.argv[1:] if Path(a).is_file()]
    if args:
        app._add_paths(args)
    app.mainloop()


if __name__ == "__main__":
    main()

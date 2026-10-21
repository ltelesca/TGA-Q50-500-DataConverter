"""TGA Q500 Data Converter - desktop app (Tkinter)."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import (
    APP_NAME,
    APP_VERSION,
    COLUMNS,
    UA_POINT_TARGET,
    ConversionError,
    ExportOptions,
    export_run,
    output_paths,
)
from tga_reader import TGAFormatError, is_raw_file, read_tga


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "TGA-Q500-DataConverter" / "settings.json"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry("980x640")
        self.minsize(860, 560)
        self.files: dict[str, dict] = {}  # tree item id -> {"path", "run", "error"}
        self.queue: queue.Queue = queue.Queue()
        self.busy = False

        self._style()
        self._build()
        self._load_settings()
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
            text="Converts TA Instruments raw files (.001, .002, ...) to CSV, with a separate info file.",
            style="Sub.TLabel",
        ).pack(anchor="w")

        # --- files ---
        files = ttk.LabelFrame(root, text=" 1. Files ", style="Section.TLabelframe", padding=8)
        files.grid(row=1, column=0, sticky="nsew")
        files.columnconfigure(0, weight=1)
        files.rowconfigure(0, weight=1)

        cols = ("file", "sample", "date", "points", "duration", "status")
        tree = ttk.Treeview(files, columns=cols, show="headings", selectmode="extended")
        for c, text, w, anchor in [
            ("file", "File", 240, "w"),
            ("sample", "Sample", 140, "w"),
            ("date", "Run date", 90, "w"),
            ("points", "Points", 65, "e"),
            ("duration", "Duration", 78, "e"),
            ("status", "Status", 260, "w"),
        ]:
            tree.heading(c, text=text, anchor=anchor)
            tree.column(c, width=w, anchor=anchor, stretch=(c in ("file", "status")))
        tree.tag_configure("error", foreground="#b00020")
        tree.tag_configure("done", foreground="#1b7f3b")
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
        self.empty_hint = ttk.Label(
            files, text="Add .001 / .002 / … files to get started.", style="Sub.TLabel"
        )
        self.empty_hint.place(relx=0.4, rely=0.5, anchor="center")

        # --- columns + options ---
        mid = ttk.Frame(root)
        mid.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)

        colbox = ttk.LabelFrame(mid, text=" 2. Columns to export ", style="Section.TLabelframe", padding=8)
        colbox.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.col_vars: dict[str, tk.BooleanVar] = {}
        half = (len(COLUMNS) + 1) // 2
        for i, c in enumerate(COLUMNS):
            v = tk.BooleanVar(value=c.default)
            self.col_vars[c.key] = v
            ttk.Checkbutton(colbox, text=c.label, variable=v).grid(
                row=i % half, column=i // half, sticky="w", padx=(0, 24), pady=1
            )

        opt = ttk.LabelFrame(mid, text=" 3. Options ", style="Section.TLabelframe", padding=8)
        opt.grid(row=0, column=1, sticky="nsew")
        opt.columnconfigure(1, weight=1)
        self.reduce_var = tk.BooleanVar(value=False)
        self.info_var = tk.BooleanVar(value=True)
        self.window_var = tk.StringVar(value="10")
        self.outmode_var = tk.StringVar(value="same")
        self.outdir_var = tk.StringVar(value="")

        ttk.Checkbutton(
            opt, text=f"Reduce long runs to ~{UA_POINT_TARGET:,} points (Universal Analysis style)", variable=self.reduce_var
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(opt, text="Write info file (sample, method, gas switches…)", variable=self.info_var).grid(
            row=1, column=0, columnspan=3, sticky="w"
        )
        wrow = ttk.Frame(opt)
        wrow.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 6))
        ttk.Label(wrow, text="Derivative smoothing window:").pack(side="left")
        ttk.Spinbox(wrow, from_=1, to=120, increment=1, width=5, textvariable=self.window_var).pack(
            side="left", padx=4
        )
        ttk.Label(wrow, text="s").pack(side="left")

        ttk.Label(opt, text="Save CSV files to:").grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(
            opt, text="Same folder as each file", value="same", variable=self.outmode_var, command=self._out_mode
        ).grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(opt, text="This folder:", value="custom", variable=self.outmode_var, command=self._out_mode).grid(
            row=5, column=0, sticky="w"
        )
        self.outdir_entry = ttk.Entry(opt, textvariable=self.outdir_var)
        self.outdir_entry.grid(row=5, column=1, sticky="ew", padx=4)
        self.browse_btn = ttk.Button(opt, text="Browse…", command=self.pick_outdir)
        self.browse_btn.grid(row=5, column=2)

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

    # ---------- files ----------
    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select TGA raw data files",
            filetypes=[("TA raw data (.001, .002, …)", "*.0*"), ("All files", "*.*")],
        )
        self._add_paths([Path(p) for p in paths])

    def add_folder(self) -> None:
        d = filedialog.askdirectory(title="Select a folder with TGA raw data files")
        if not d:
            return
        found = sorted(p for p in Path(d).iterdir() if p.is_file() and is_raw_file(p.name))
        if not found:
            messagebox.showinfo(APP_NAME, "No .001 / .002 / … files found in that folder.")
            return
        self._add_paths(found)

    def _add_paths(self, paths: list[Path]) -> None:
        known = {str(v["path"]) for v in self.files.values()}
        for p in paths:
            if str(p) in known:
                continue
            known.add(str(p))
            info = {"path": p, "run": None, "error": None}
            try:
                if not is_raw_file(p.name):
                    raise TGAFormatError("not a .001 / .002 / … file")
                run = read_tga(p)
                info["run"] = run
                dur = run.rows[-1][0] - run.rows[0][0]
                status = "Ready" if run.complete else "Ready (run incomplete)"
                vals = (p.name, run.get("Sample"), run.get("Date"), f"{len(run.rows):,}", f"{dur:.1f} min", status)
                tags = ()
            except (TGAFormatError, OSError, ValueError) as e:
                info["error"] = str(e)
                vals = (p.name, "", "", "", "", f"Cannot read: {e}")
                tags = ("error",)
            iid = self.tree.insert("", "end", values=vals, tags=tags)
            self.files[iid] = info
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
            self.outdir_var.set(d)

    def _options(self) -> ExportOptions | None:
        cols = [k for k, v in self.col_vars.items() if v.get()]
        if not cols:
            messagebox.showwarning(APP_NAME, "Select at least one column to export.")
            return None
        try:
            window = float(self.window_var.get())
            if not 0 < window <= 600:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_NAME, "Derivative window must be a number of seconds (1–600).")
            return None
        outdir = None
        if self.outmode_var.get() == "custom":
            if not self.outdir_var.get().strip():
                messagebox.showwarning(APP_NAME, "Choose an output folder, or select 'Same folder as each file'.")
                return None
            outdir = Path(self.outdir_var.get().strip())
        return ExportOptions(
            columns=cols,
            reduce_like_ua=self.reduce_var.get(),
            write_info=self.info_var.get(),
            dtg_window_s=window,
            output_dir=outdir,
        )

    # ---------- conversion ----------
    def convert(self) -> None:
        if self.busy:
            return
        jobs = [(iid, v) for iid, v in self.files.items() if v["run"]]
        if not jobs:
            messagebox.showinfo(APP_NAME, "Add at least one readable .001 / .002 / … file first.")
            return
        opts = self._options()
        if opts is None:
            return

        existing = []
        for _, v in jobs:
            csv_p, info_p = output_paths(v["path"], opts.output_dir)
            if csv_p.exists() or (opts.write_info and info_p.exists()):
                existing.append(csv_p.name)
        skip_existing = False
        if existing:
            names = "\n".join(existing[:8]) + ("\n…" if len(existing) > 8 else "")
            ans = messagebox.askyesnocancel(
                APP_NAME,
                f"{len(existing)} output file(s) already exist:\n\n{names}\n\n"
                "Yes = overwrite them\nNo = skip those files\nCancel = do nothing",
            )
            if ans is None:
                return
            skip_existing = not ans

        if skip_existing:
            jobs = [
                (iid, v) for iid, v in jobs if output_paths(v["path"], opts.output_dir)[0].name not in existing
            ]
        self._save_settings()
        self.busy = True
        self.n_failed = 0
        self.convert_btn.configure(state="disabled")
        self.progress.configure(maximum=len(jobs), value=0)
        for iid, _ in jobs:
            self.tree.set(iid, "status", "Waiting…")
        threading.Thread(target=self._worker, args=(jobs, opts), daemon=True).start()
        self.after(100, self._poll)

    def _worker(self, jobs, opts: ExportOptions) -> None:
        for iid, v in jobs:
            self.queue.put(("start", iid, None))
            try:
                res = export_run(v["run"], opts)
                note = "Done"
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

    # ---------- settings ----------
    def _load_settings(self) -> None:
        try:
            s = json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, v in s.get("columns", {}).items():
            if k in self.col_vars:
                self.col_vars[k].set(bool(v))
        self.reduce_var.set(bool(s.get("reduce", False)))
        self.info_var.set(bool(s.get("info", True)))
        self.window_var.set(str(s.get("dtg_window_s", 10)))
        self.outmode_var.set(s.get("outmode", "same"))
        self.outdir_var.set(s.get("outdir", ""))
        self._out_mode()

    def _save_settings(self) -> None:
        s = {
            "columns": {k: v.get() for k, v in self.col_vars.items()},
            "reduce": self.reduce_var.get(),
            "info": self.info_var.get(),
            "dtg_window_s": self.window_var.get(),
            "outmode": self.outmode_var.get(),
            "outdir": self.outdir_var.get(),
        }
        try:
            p = settings_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(s, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _on_close(self) -> None:
        self._save_settings()
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

"""HTML Video Studio — desktop GUI (Tkinter). No coding needed.

Design: light modern flat UI — flat indigo header, white cards, a to-scale
graphical resolution picker, right-hand quality/duration column, accent
Export button with explicit states, dark console-style log. All text is
English. Voiceover works via text-to-speech narration scripts.
"""

import ctypes
import os
import queue
import tempfile
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .capture import Cancelled
from .config import (CAPTURE_DETAIL, FPS_CHOICES, QUALITY, RES_LABELS,
                     RESOLUTIONS, RES_SIZE, VOICE_AUTO, VOICES, Settings)
from .pipeline import Cancelled as PipelineCancelled  # noqa: F401 (alias)
from .pipeline import RenderError, render, scan_html
from .tts import (is_bengali, mp3_to_wav, parse_script, read_script, synth,
                  voice_for)

BROWSER_HINT = ("Could not start the browser engine. Possible fixes:\n"
                "1) Make sure no antivirus blocked Python.\n"
                "2) Re-run this program.")

C = dict(
    bg="#f3f4f8", card="#ffffff", border="#e3e7f0",
    panel="#f7f8fc",
    ink="#1f2430", sub="#6b7280",
    accent="#4f46e5", accent_hi="#4338ca",
    box="#dde4f4", box_hover="#ccd7f2", box_line="#c3cdea",
    ok="#15803d", err="#dc2626", warn="#b45309",
    log_bg="#111827", log_fg="#d1d9e8", log_ok="#7ee2a8", log_err="#ff9a9a",
)

QUALITY_DESC = {
    "Normal": "Smaller file — fastest export",
    "High": "Recommended — sharp text, balanced size",
    "Best": "Largest file — maximum detail",
}

SAMPLE_EN = ("This is a sample of the selected voice. Your slides will be "
             "narrated exactly like this.")
SAMPLE_BN = ("স্টুডিওর ভয়েস নমুনা। এভাবেই আপনার প্রতিটি স্লাইডের বর্ণনা "
             "শোনাবে।")

# Project logo for the title bar, taskbar and Alt-Tab (the default Tk
# icon must never appear). Resolved relative to this file, so it works
# no matter which folder the app is launched from.
LOGO = Path(__file__).resolve().parent / "logo" / "presentation.ico"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.ffmpeg: str | None = None
        self.rendering = False
        self.setup_state = "running"          # running | ready | failed
        self.cancel_event = threading.Event()
        self.scan_cache: dict | None = None
        self._playing_sample = False
        self.script_lang_bn: bool | None = None   # language of loaded script

        root.title("HTML Video Studio")
        self._apply_icon()
        root.configure(bg=C["bg"])

        self._style()
        self._build_ui()
        self._fit_window()
        self._poll_queue()
        threading.Thread(target=self._setup_env, daemon=True).start()

    # ─────────────────────────── look ──────────────────────────────
    def _fit_window(self):
        """Size the window to its content so every control is visible.

        Hardcoded heights break when sections grow or Windows display
        scaling enlarges the widgets — measuring the real requirement
        keeps the action row, progress bar and log on screen. The log
        (packed last, expandable) is what flexes when the screen is too
        small for the full requirement.
        """
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        usable = max(480, self.root.winfo_screenheight() - 80)  # taskbar
        w = max(920, req_w + 16)
        h = max(680, min(req_h + 16, usable))
        self.root.minsize(840, 620)
        self.root.geometry(f"{w}x{h}")
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - 80 - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_icon(self):
        """Show the project logo on the window, taskbar and Alt-Tab.

        Called before the window is mapped, so the default Tk icon never
        becomes visible. `default` also covers every dialog toplevel.
        """
        try:
            if LOGO.exists():
                self.root.iconbitmap(default=str(LOGO))
                self.root.iconbitmap(str(LOGO))
        except Exception:
            pass  # a missing/broken logo must never block startup

    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=C["bg"], foreground=C["ink"],
                     font=("Segoe UI", 10))
        st.configure("TFrame", background=C["bg"])
        st.configure("CardTitle.TLabel", background=C["card"],
                     foreground=C["ink"], font=("Segoe UI", 11, "bold"))
        st.configure("TLabel", background=C["card"], foreground=C["ink"])
        st.configure("Sub.TLabel", background=C["card"],
                     foreground=C["sub"], font=("Segoe UI", 9))
        st.configure("TEntry", fieldbackground="white", bordercolor=C["border"],
                     lightcolor=C["border"], darkcolor=C["border"],
                     padding=4)
        st.configure("TCombobox", fieldbackground="white",
                     bordercolor=C["border"], arrowsize=13, padding=3)
        st.configure("TSpinbox", fieldbackground="white",
                     bordercolor=C["border"], arrowsize=12, padding=3)
        st.configure("TCheckbutton", background=C["card"])
        st.map("TCheckbutton", background=[("active", C["card"])])
        st.configure("TRadiobutton", background=C["panel"],
                     foreground=C["ink"])
        st.map("TRadiobutton", background=[("active", C["panel"])])
        st.configure("Accent.TButton", foreground="white",
                     background=C["accent"], font=("Segoe UI", 11, "bold"),
                     padding=(30, 12), borderwidth=0)
        st.map("Accent.TButton",
               background=[("active", C["accent_hi"]),
                           ("disabled", "#b9b6ea")],
               foreground=[("disabled", "#f2f2fd")])
        st.configure("Ghost.TButton", foreground=C["ink"], background="white",
                     bordercolor=C["border"], padding=(14, 8))
        st.map("Ghost.TButton", background=[("active", "#f1f4fb")])
        st.configure("Danger.TButton", foreground="white", background="#e11d48",
                     font=("Segoe UI", 10, "bold"), padding=(16, 8),
                     borderwidth=0)
        st.map("Danger.TButton", background=[("active", "#be123c")])
        st.configure("Horizontal.TProgressbar", background=C["accent"],
                     troughcolor="#dfe4f2", borderwidth=0, thickness=10)

    def _header(self):
        cv = tk.Canvas(self.root, height=88, highlightthickness=0,
                       bg=C["accent"])
        cv.pack(fill="x")

        def repaint(event=None):
            cv.delete("all")
            width = max(2, cv.winfo_width())
            # subtle horizontal gradient, drawn in 48 bands (cheap repaint)
            c1, c2 = (0x4f, 0x46, 0xe5), (0x6d, 0x28, 0xd9)
            bands = 48
            bw = width / bands
            for i in range(bands):
                t = i / (bands - 1)
                col = "#%02x%02x%02x" % tuple(
                    int(a + (b - a) * t) for a, b in zip(c1, c2))
                cv.create_rectangle(i * bw, 0, (i + 1) * bw + 1, 88,
                                    fill=col, outline=col)
            cv.create_text(28, 30, anchor="w", text="HTML Video Studio",
                           fill="white", font=("Segoe UI", 19, "bold"))
            cv.create_text(
                30, 60, anchor="w", fill="#ddd6fe", font=("Segoe UI", 10),
                text="Turn any animated HTML presentation into an HD / 4K "
                     "video — no coding needed")

        cv.bind("<Configure>", repaint)
        return cv

    def _card(self, parent, title):
        """White card with title. Returns the content frame (use ONE
        geometry manager inside it — pack or grid — consistently)."""
        outer = tk.Frame(parent, bg=C["bg"])
        outer.pack(fill="x", pady=(0, 12))
        body = tk.Frame(outer, bg=C["card"], highlightbackground=C["border"],
                        highlightthickness=1)
        body.pack(fill="x")
        inner = tk.Frame(body, bg=C["card"])
        inner.pack(fill="x", padx=16, pady=12)
        ttk.Label(inner, text=title, style="CardTitle.TLabel").pack(
            anchor="w", pady=(0, 8))
        content = tk.Frame(inner, bg=C["card"])
        content.pack(fill="x")
        return content

    # ──────────────────────────── UI ───────────────────────────────
    def _build_ui(self):
        self._header()

        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=18, pady=14)

        # ── card 1: files + voice ────────────────────────────────
        f1 = self._card(main, "1 ·  Choose your files")
        self.html_var = tk.StringVar()
        self.script_var = tk.StringVar()
        self._file_row(f1, "HTML file", self.html_var, self._pick_html,
                       [("HTML files", "*.html *.htm"), ("All files", "*.*")])
        self._file_row(f1, "Voiceover script", self.script_var,
                       self._pick_script,
                       [("Text files", "*.txt"), ("All files", "*.*")],
                       clear=self._clear_script)

        voicerow = tk.Frame(f1, bg=C["card"])
        voicerow.pack(fill="x", pady=(4, 0))
        ttk.Label(voicerow, text="TTS voice", width=19,
                  anchor="e").pack(side="left", padx=(0, 8))
        self.voice_var = tk.StringVar(value=VOICE_AUTO)
        self.voice_cb = ttk.Combobox(voicerow, textvariable=self.voice_var,
                                     state="disabled", width=34,
                                     values=VOICES)
        self.voice_cb.pack(side="left")
        self.sample_btn = ttk.Button(voicerow, text="Play sample",
                                     style="Ghost.TButton",
                                     command=self._play_sample,
                                     state="disabled")
        self.sample_btn.pack(side="left", padx=(8, 0))
        ttk.Label(voicerow, text="Converts the script to speech — slide "
                                 "timing follows the narration",
                  style="Sub.TLabel").pack(side="left", padx=(8, 0))

        self.scan_label = tk.Label(
            f1, text="Checking the video engine ...",
            bg=C["card"], fg=C["warn"], font=("Segoe UI", 9))
        self.scan_label.pack(anchor="w", pady=(6, 0))

        # ── card 2: settings ─────────────────────────────────────
        f2 = self._card(main, "2 ·  Export settings")
        self.res_var = tk.StringVar(value="Full HD 1080p")
        self.q_var = tk.StringVar(value="High")
        self.sec_var = tk.DoubleVar(value=8.0)

        # ── resolution: full-width to-scale picker ───────────────
        head = tk.Frame(f2, bg=C["card"])
        head.pack(fill="x")
        tk.Label(head, text="OUTPUT RESOLUTION", bg=C["card"], fg=C["sub"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        self.res_readout = tk.Label(head, text="", bg=C["card"],
                                    fg=C["accent"],
                                    font=("Segoe UI", 9, "bold"))
        self.res_readout.pack(side="right")
        self._make_res_picker(f2)

        # ── quality + duration: two titled sub-panels ────────────
        duo = tk.Frame(f2, bg=C["card"])
        duo.pack(fill="x", pady=(8, 0))
        duo.columnconfigure((0, 1), weight=1, uniform="opt")

        pq = self._panel(duo, "QUALITY", 0)
        for q in QUALITY:
            row = tk.Frame(pq, bg=C["panel"])
            row.pack(fill="x", pady=2)
            ttk.Radiobutton(row, text=q, value=q,
                            variable=self.q_var).pack(side="left")
            tk.Label(row, text=QUALITY_DESC[q], bg=C["panel"], fg=C["sub"],
                     font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))

        pd = self._panel(duo, "SECONDS / SLIDE", 1)
        secrow = tk.Frame(pd, bg=C["panel"])
        secrow.pack(anchor="w")
        ttk.Spinbox(secrow, from_=1, to=120, increment=0.5, width=7,
                    textvariable=self.sec_var,
                    font=("Segoe UI", 11)).pack(side="left")
        tk.Label(secrow, text="seconds", bg=C["panel"], fg=C["sub"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
        tk.Label(pd, text="Used for slides without narration — narrated "
                          "slides follow the voiceover instead",
                 bg=C["panel"], fg=C["sub"], font=("Segoe UI", 9),
                 wraplength=260, justify="left").pack(anchor="w", pady=(8, 0))

        ttk.Separator(f2, orient="horizontal").pack(fill="x", pady=(10, 6))

        # output name preview
        self.out_var = tk.StringVar(value="")
        tk.Label(f2, textvariable=self.out_var, bg=C["card"], fg=C["sub"],
                 font=("Segoe UI", 9)).pack(anchor="w")

        # ── advanced disclosure ──────────────────────────────────
        self.adv_open = False
        self.adv_btn = tk.Label(
            f2, text="▸  Advanced options — FPS, slide selector, capture "
                     "detail",
            bg=C["card"], fg=C["sub"], font=("Segoe UI", 9, "bold"),
            cursor="hand2")
        self.adv_btn.pack(anchor="w", pady=(8, 0))
        self.adv_btn.bind("<Button-1>", lambda e: self._toggle_advanced())
        adv = tk.Frame(f2, bg=C["panel"], highlightbackground=C["border"],
                       highlightthickness=1)
        self.adv_frame = adv
        adv_body = tk.Frame(adv, bg=C["panel"])
        adv_body.pack(fill="x", padx=12, pady=10)
        tk.Label(adv_body, text="FPS", bg=C["panel"], fg=C["ink"],
                 font=("Segoe UI", 9), width=13,
                 anchor="e").grid(row=0, column=0, sticky="e", padx=(0, 8),
                                  pady=3)
        self.fps_var = tk.IntVar(value=30)
        ttk.Combobox(adv_body, textvariable=self.fps_var, state="readonly",
                     width=6, values=list(FPS_CHOICES)).grid(
            row=0, column=1, sticky="w", pady=3)
        tk.Label(adv_body, text="24 cinematic · 30 standard · 60 smoothest",
                 bg=C["panel"], fg=C["sub"],
                 font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w",
                                            padx=(12, 0), pady=3)
        tk.Label(adv_body, text="Slide selector", bg=C["panel"], fg=C["ink"],
                 font=("Segoe UI", 9), width=13,
                 anchor="e").grid(row=1, column=0, sticky="e", padx=(0, 8),
                                  pady=3)
        self.sel_var = tk.StringVar(value="")
        ttk.Entry(adv_body, width=26, textvariable=self.sel_var).grid(
            row=1, column=1, sticky="w", pady=3)
        tk.Label(adv_body, text="CSS selector for slides — empty = "
                                "auto-detect", bg=C["panel"], fg=C["sub"],
                 font=("Segoe UI", 9)).grid(row=1, column=2, sticky="w",
                                            padx=(12, 0), pady=3)
        tk.Label(adv_body, text="Capture detail", bg=C["panel"], fg=C["ink"],
                 font=("Segoe UI", 9), width=13,
                 anchor="e").grid(row=2, column=0, sticky="e", padx=(0, 8),
                                  pady=3)
        self.detail_var = tk.StringVar(value="Faster (recommended)")
        ttk.Combobox(adv_body, textvariable=self.detail_var, state="readonly",
                     width=28, values=list(CAPTURE_DETAIL.keys())).grid(
            row=2, column=1, sticky="w", pady=3)
        tk.Label(adv_body, text="“Maximum smoothness” captures every frame "
                                "— very slow", bg=C["panel"], fg=C["sub"],
                 font=("Segoe UI", 9)).grid(row=2, column=2, sticky="w",
                                            padx=(12, 0), pady=3)
        adv_body.columnconfigure(2, weight=1)

        # ── actions ──────────────────────────────────────────────
        act = tk.Frame(main, bg=C["bg"])
        act.pack(fill="x", pady=(2, 10))
        self.export_btn = ttk.Button(
            act, text="Preparing the video engine ...",
            style="Accent.TButton", command=self._export, state="disabled")
        self.export_btn.pack(side="left")
        self.cancel_btn = ttk.Button(act, text="Cancel", style="Danger.TButton",
                                     command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=12)
        self.open_btn = ttk.Button(act, text="Open output folder",
                                   style="Ghost.TButton",
                                   command=self._open_folder,
                                   state="disabled")
        self.open_btn.pack(side="right")

        # ── progress + status ────────────────────────────────────
        self.progress = ttk.Progressbar(main, maximum=100, mode="indeterminate")
        self.progress.pack(fill="x")
        self.progress.start(14)   # pulsing while setup runs
        self.status = tk.Label(
            main, text="Checking the video engine ...", bg=C["bg"],
            fg=C["ink"], font=("Segoe UI", 10), anchor="w")
        self.status.pack(fill="x", pady=(6, 10))

        # ── log ──────────────────────────────────────────────────
        logcard = tk.Frame(main, bg=C["log_bg"],
                           highlightbackground=C["border"],
                           highlightthickness=1)
        logcard.pack(fill="both", expand=True)
        self.log = tk.Text(logcard, height=7, state="disabled", wrap="word",
                           font=("Consolas", 9), bg=C["log_bg"],
                           fg=C["log_fg"], relief="flat", padx=10, pady=8,
                           insertbackground=C["log_fg"])
        self.log.tag_configure("ok", foreground=C["log_ok"])
        self.log.tag_configure("err", foreground=C["log_err"])
        self.log.tag_configure("dim", foreground="#8a94ab")
        sb = ttk.Scrollbar(logcard, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self._log("HTML Video Studio starting. Pick an HTML file and press "
                  "Export.\nFirst run: required components are being "
                  "installed automatically — please wait.\n", "dim")

        self.html_var.trace_add("write", lambda *_: self._update_outname())
        self.res_var.trace_add("write", lambda *_: self._update_outname())
        self._update_res()

    # ───────────── graphical resolution picker ──────────────────────
    def _make_res_picker(self, parent):
        cv = tk.Canvas(parent, height=140, highlightthickness=0,
                       bg=C["card"], cursor="hand2")
        cv.pack(fill="x")
        self.res_canvas = cv
        self._res_rects: list[tuple[int, int, int, int, str]] = []
        cv.bind("<Button-1>", self._on_res_click)
        cv.bind("<Configure>", lambda e: self._draw_res())
        self.res_var.trace_add("write", lambda *_: self._update_res())

    def _update_res(self):
        """Refresh the live readout and the picker artwork."""
        h = RESOLUTIONS[self.res_var.get()]
        w_px, h_px = RES_SIZE[h]
        self.res_readout.configure(
            text=f"{self.res_var.get()}  ·  {w_px}×{h_px}")
        self._draw_res()

    def _draw_res(self):
        cv = self.res_canvas
        cv.delete("all")
        self._res_rects = []
        width = cv.winfo_width()
        if width < 80:
            return  # not laid out yet — Configure fires again shortly
        labels = list(RESOLUTIONS.keys())
        n = len(labels)
        slot = (width - 24) / n
        unit = min(88 / 2160, (slot - 30) / 3840)
        baseline = 96
        sel_h = RESOLUTIONS[self.res_var.get()]
        cv.create_line(12, baseline, width - 12, baseline,
                       fill=C["box_line"])
        for i, label in enumerate(labels):
            w_px, h_px = RES_SIZE[RESOLUTIONS[label]]
            bw, bh = w_px * unit, h_px * unit
            cx = 12 + slot * (i + 0.5)
            x0, y0, x1, y1 = cx - bw / 2, baseline - bh, cx + bw / 2, baseline
            is_sel = RESOLUTIONS[label] == sel_h
            tag = f"res{i}"
            cv.create_rectangle(x0, y0, x1, y1,
                                fill=C["accent"] if is_sel else C["box"],
                                outline=C["accent_hi"] if is_sel
                                else C["box_line"],
                                width=2 if is_sel else 1, tags=tag)
            short = RES_LABELS[RESOLUTIONS[label]]
            cv.create_text(cx, baseline + 14, text=short,
                           fill=C["accent"] if is_sel else C["ink"],
                           font=("Segoe UI", 10,
                                 "bold" if is_sel else "normal"), tags=tag)
            cv.create_text(cx, baseline + 28, text=f"{w_px}×{h_px}",
                           fill=C["sub"], font=("Segoe UI", 8), tags=tag)
            if label == "Full HD 1080p":
                cv.create_text(cx, baseline - 8, text="recommended",
                               fill="#ffffff" if is_sel else C["ok"],
                               font=("Segoe UI", 7, "italic"), tags=tag)
            self._res_rects.append((x0, y0, x1, baseline + 36, label))
            if not is_sel:
                cv.tag_bind(tag, "<Enter>",
                            lambda e, t=tag: cv.itemconfigure(
                                t, fill=C["box_hover"]))
                cv.tag_bind(tag, "<Leave>",
                            lambda e, t=tag: cv.itemconfigure(
                                t, fill=C["box"]))

    def _on_res_click(self, event):
        for x0, y0, x1, y1, label in self._res_rects:
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.res_var.set(label)
                return

    def _panel(self, parent, title: str, col: int):
        """Light bordered mini-panel with a small caption, placed in grid
        column `col`. Returns the content frame."""
        outer = tk.Frame(parent, bg=C["panel"],
                         highlightbackground=C["border"],
                         highlightthickness=1)
        outer.grid(row=0, column=col, sticky="nsew",
                   padx=((0, 0) if col == 0 else (10, 0)))
        tk.Label(outer, text=title, bg=C["panel"], fg=C["sub"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 6))
        content = tk.Frame(outer, bg=C["panel"])
        content.pack(fill="x")
        return content

    # ─────────────────────────── rows ──────────────────────────────
    def _file_row(self, parent, label, var, cmd, patterns, clear=None):
        rowf = tk.Frame(parent, bg=C["card"])
        rowf.pack(fill="x", pady=4)
        ttk.Label(rowf, text=label, width=19, anchor="e").pack(
            side="left", padx=(0, 8))
        ttk.Entry(rowf, textvariable=var).pack(
            side="left", fill="x", expand=True)
        ttk.Button(rowf, text="Browse…", style="Ghost.TButton",
                   command=cmd).pack(side="left", padx=(8, 0))
        if clear:
            ttk.Button(rowf, text="Clear", style="Ghost.TButton",
                       command=clear).pack(side="left", padx=(4, 0))

    def _toggle_advanced(self):
        self.adv_open = not self.adv_open
        if self.adv_open:
            self.adv_btn.configure(
                text="▾  Advanced options — FPS, slide selector, capture "
                     "detail")
            self.adv_frame.pack(fill="x", pady=(6, 0))
            self.root.update_idletasks()
            self._resize_window_by(self.adv_frame.winfo_reqheight() + 6)
        else:
            self.adv_btn.configure(
                text="▸  Advanced options — FPS, slide selector, capture "
                     "detail")
            self._resize_window_by(-(self.adv_frame.winfo_reqheight() + 6))
            self.adv_frame.pack_forget()

    def _resize_window_by(self, dy: int):
        """Grow/shrink the window height so toggled panels always fit."""
        min_h = (self.root.minsize() or (0, 620))[1] or 620
        h = max(min_h, self.root.winfo_height() + dy)
        self.root.geometry(f"{self.root.winfo_width()}x{h}")

    def _update_outname(self):
        html = self.html_var.get().strip()
        if not html:
            self.out_var.set("")
            return
        try:
            s = self._settings()
            self.out_var.set(f"Video will be saved to:  {s.output_path()}")
        except Exception:
            self.out_var.set("")

    # ────────────────────────── helpers ─────────────────────────────
    def _log(self, msg: str, tag: str | None = None):
        self.log.configure(state="normal")
        self.log.insert("end", msg.rstrip() + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_export_state(self):
        if self.rendering:
            return
        if self.setup_state == "ready":
            self.export_btn.configure(state="normal", text="Export video")
        elif self.setup_state == "failed":
            self.export_btn.configure(state="normal", text="Retry setup")
        else:
            # setup still running — button stays disabled until ready
            self.export_btn.configure(state="disabled",
                                      text="Preparing the video engine ...")

    def _pick_html(self):
        p = filedialog.askopenfilename(title="Choose an HTML file",
                                       filetypes=[("HTML files",
                                                   "*.html *.htm"),
                                                  ("All files", "*.*")])
        if p:
            self.html_var.set(p)
            self.scan_cache = None
            self.scan_label.configure(text="Checking this page ...",
                                      fg=C["sub"])
            threading.Thread(target=self._scan,
                             args=(Path(p), self.sel_var.get().strip()),
                             daemon=True).start()

    def _pick_script(self):
        p = filedialog.askopenfilename(
            title="Choose a narration script (text-to-speech)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not p:
            return
        self.script_var.set(p)
        self.voice_cb.configure(state="readonly")
        try:
            blocks = parse_script(read_script(Path(p)))
        except Exception:
            return
        if blocks:
            first = next(iter(blocks.values()))
            self.script_lang_bn = is_bengali(first)
            self._log(f"Script loaded: {len(blocks)} slide narrations "
                      f"(up to slide {max(blocks)}).", "dim")
        else:
            self._log("Script loaded, but no \"[[SLIDE n]]\" blocks were "
                      "found — see samples/english.txt for the format.",
                      "dim")

    def _clear_script(self):
        self.script_var.set("")
        self.voice_cb.configure(state="disabled")
        self.script_lang_bn = None

    # ───────────────────── voice sample playback ────────────────────
    def _sample_text(self) -> str:
        label = self.voice_var.get()
        if label == VOICE_AUTO:
            bn = bool(self.script_lang_bn)   # match the loaded script
        else:
            bn = "Bangla" in label
        return SAMPLE_BN if bn else SAMPLE_EN

    def _play_sample(self):
        if self._playing_sample or self.ffmpeg is None:
            return
        # read all Tk state HERE (main thread) — never from the worker
        text = self._sample_text()
        voice = voice_for(text, self.voice_var.get())
        self._playing_sample = True
        self.sample_btn.configure(state="disabled", text="Generating ...")
        threading.Thread(target=self._sample_worker, args=(text, voice),
                         daemon=True).start()

    def _sample_worker(self, text: str, voice: str):
        try:
            tmp = Path(tempfile.gettempdir()) / "hvs_voice_sample"
            tmp.mkdir(exist_ok=True)
            mp3 = tmp / "sample.mp3"
            synth(text, voice, mp3)
            wav = tmp / "sample.wav"
            mp3_to_wav(mp3, wav, self.ffmpeg)
            import winsound  # stdlib on Windows
            winsound.PlaySound(str(wav), winsound.SND_FILENAME)
            self.q.put(("sample_done", None, None))
        except Exception as e:
            self.q.put(("sample_fail", str(e), None))

    # ────────────────────────── threads ─────────────────────────────
    def _scan(self, path: Path, selector: str):
        if self.ffmpeg is None:
            self.q.put(("scan_skip", None, None))
            return
        try:
            info = scan_html(path, selector)
            self.q.put(("scan_done", info, None))
        except Exception as e:
            self.q.put(("scan_fail", str(e), None))

    def _setup_env(self):
        from .environment import ensure_environment
        try:
            ff = ensure_environment(lambda m: self.q.put(("log", m, None)))
            self.q.put(("env_ready", ff, None))
        except Exception as e:
            self.q.put(("env_fail", str(e), None))

    def _settings(self) -> Settings:
        res_h = RESOLUTIONS[self.res_var.get()]
        return Settings(
            html_path=Path(self.html_var.get()),
            script_path=Path(self.script_var.get())
            if self.script_var.get() else None,
            tts_voice=self.voice_var.get(),
            res_h=res_h,
            fps=int(self.fps_var.get()),
            crf=QUALITY[self.q_var.get()],
            seconds_per_slide=float(self.sec_var.get()),
            selector=self.sel_var.get().strip(),
            capture_detail=CAPTURE_DETAIL.get(self.detail_var.get(), "normal"),
        )

    # ────────────────────────── actions ─────────────────────────────
    def _export(self):
        if self.rendering:
            return
        if self.setup_state == "running":
            messagebox.showinfo(
                "One-time setup running",
                "The video engine is still preparing (first run only).\n"
                "Watch the log below — Export unlocks automatically when it "
                "says \"Setup complete\".")
            return
        if self.setup_state == "failed":
            self.setup_state = "running"
            self.export_btn.configure(state="disabled",
                                      text="Retrying setup ...")
            self.status.configure(text="Checking the video engine ...",
                                  fg=C["ink"])
            self.progress.configure(mode="indeterminate")
            self.progress.start(14)
            self._log("Retrying setup ...", "dim")
            threading.Thread(target=self._setup_env, daemon=True).start()
            return

        html = self.html_var.get().strip()
        if not html or not Path(html).exists():
            messagebox.showwarning(
                "HTML Video Studio", "Please choose an HTML file first.")
            return
        script = self.script_var.get().strip()
        if script and not Path(script).exists():
            messagebox.showwarning(
                "HTML Video Studio",
                "The voiceover script file was not found. Please choose "
                "it again.")
            return
        s = self._settings()
        out = s.output_path()
        if out.exists():
            if not messagebox.askyesno(
                    "Overwrite?",
                    f"{out.name} already exists.\nOverwrite it?"):
                return

        self.rendering = True
        self.cancel_event.clear()
        self.export_btn.configure(state="disabled",
                                  text="Exporting — see progress below")
        self.cancel_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        threading.Thread(target=self._render, args=(s,), daemon=True).start()

    def _render(self, s: Settings):
        t0 = time.time()

        def progress(kind, pct, msg):
            # message-carrying kinds put the message as payload; the queue
            # handler reads payload for everything
            if kind in ("log", "phase", "error"):
                self.q.put((kind, msg, None))
            else:
                self.q.put((kind, pct, None))

        try:
            out = render(s, progress, self.cancel_event)
            self.q.put(("done", (out, time.time() - t0), None))
        except (Cancelled,) + (PipelineCancelled,):
            self.q.put(("cancelled", None, None))
        except RenderError as e:
            self.q.put(("error", str(e), None))
        except Exception:
            self.q.put(("error", traceback.format_exc(limit=4), None))

    def _cancel(self):
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled")
        self.status.configure(text="Cancelling after the current frame ...")

    def _open_folder(self):
        html = self.html_var.get().strip()
        target = Path(html).parent if html else Path.cwd()
        try:
            os.startfile(target)  # Windows — no console window involved
        except Exception:
            pass

    # ────────────────────────── queue pump ──────────────────────────
    def _poll_queue(self):
        try:
            while True:
                kind, payload, extra = self.q.get_nowait()
                try:
                    self._handle(kind, payload, extra)
                except Exception:
                    # never let one bad message kill the UI pump
                    self._log("Internal UI warning: could not process a "
                              "status update.", "err")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _handle(self, kind, payload, extra):
        if kind == "log":
            msg = str(payload)
            tag = None
            if "✓" in msg or "ready" in msg.lower():
                tag = "ok"
            self._log(msg, tag)
        elif kind == "progress":
            if str(self.progress.cget("mode")) != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
            self.progress.configure(value=float(payload))
        elif kind == "phase":
            self.status.configure(text=str(payload))
        elif kind == "env_ready":
            self.ffmpeg = payload
            self.setup_state = "ready"
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.scan_label.configure(
                text="Engine ready — choose an HTML file above.",
                fg=C["ok"])
            self.status.configure(
                text="Ready — choose an HTML file and press Export video.",
                fg=C["ok"])
            self._set_export_state()
            self.sample_btn.configure(state="normal")
            self._log("Setup complete — ready to export!  ✓", "ok")
            if self.html_var.get():
                self.scan_label.configure(text="Checking this page ...",
                                          fg=C["sub"])
                threading.Thread(target=self._scan,
                                 args=(Path(self.html_var.get()),
                                       self.sel_var.get().strip()),
                                 daemon=True).start()
        elif kind == "env_fail":
            self.setup_state = "failed"
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self._set_export_state()
            self.scan_label.configure(
                text="Setup failed — press the button above to retry.",
                fg=C["err"])
            self.status.configure(
                text="Setup failed — press \"Retry setup\" above.",
                fg=C["err"])
            self._log(str(payload), "err")
            messagebox.showerror("Setup failed", str(payload))
        elif kind == "scan_done":
            self.scan_cache = payload
            info = payload
            if info["count"] == 0:
                self.scan_label.configure(
                    text="No slides found — one continuous clip will be "
                         "exported.", fg=C["warn"])
            elif info["continuous"]:
                self.scan_label.configure(
                    text=f"{info['count']} slides found, but no automatic "
                         "navigation — a continuous clip will be exported.",
                    fg=C["warn"])
            else:
                self.scan_label.configure(
                    text=f"{info['count']} slides detected "
                         f"(selector '{info['selector']}') — ready to export",
                    fg=C["ok"])
        elif kind == "scan_skip":
            self.scan_label.configure(
                text="Slide check will happen during export "
                     "(setup still running).", fg=C["sub"])
        elif kind == "scan_fail":
            self.scan_label.configure(
                text="Slide preview unavailable (export will still "
                     "work).", fg=C["sub"])
        elif kind == "sample_done":
            self._playing_sample = False
            self.sample_btn.configure(state="normal", text="Play sample")
        elif kind == "sample_fail":
            self._playing_sample = False
            self.sample_btn.configure(state="normal", text="Play sample")
            self._log("Voice sample failed: " + str(payload), "err")
        elif kind == "done":
            out, secs = payload
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.open_btn.configure(state="normal")
            self.status.configure(text=f"Video saved:  {out}")
            self._log(f"VIDEO SAVED:  {out}", "ok")
            self._log("   It is in the SAME folder as your HTML file — "
                      "press \"Open output folder\" to see it.", "ok")
            messagebox.showinfo(
                "Video ready",
                f"Your video is saved here:\n\n{out}\n\n"
                f"(Same folder as your HTML file)\n"
                f"Time taken: {secs / 60:.1f} minutes")
        elif kind == "cancelled":
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="Cancelled.")
            self._log("Export cancelled by user.", "dim")
        elif kind == "error":
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="Export failed — see log below.")
            self._log("ERROR:\n" + str(payload), "err")
            msg = str(payload)
            if "browser" in msg.lower() or "chromium" in msg.lower():
                msg = BROWSER_HINT + "\n\n" + msg[:400]
            messagebox.showerror("Export failed", msg[:1200])


def main():
    try:  # crisp text on high-DPI Windows
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()

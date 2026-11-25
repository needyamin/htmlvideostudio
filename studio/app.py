"""HTML Video Studio — desktop GUI (Tkinter). No coding needed.

Design: modern two-column studio layout — dark-indigo header with live
status pill, clean white Source/Voiceover and Export Settings cards,
interactive segmented resolution/quality/FPS selectors, mutually
exclusive Windows & Google TTS cards, and an integrated progress + log
footer.
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
from .config import (CAPTURE_DETAIL, FPS_CHOICES, GOOGLE_VOICE_DEFAULT,
                     GOOGLE_VOICES, QUALITY, RES_LABELS, RESOLUTIONS, RES_SIZE,
                     TTS_ENGINE_GOOGLE, TTS_ENGINE_WINDOWS, VOICE_AUTO, VOICES,
                     Settings, load_gemini_api_key)
from .pipeline import Cancelled as PipelineCancelled  # noqa: F401 (alias)
from .pipeline import RenderError, render, scan_html
from .tts import is_bengali, parse_script, read_script, synth_wav, voice_for

BROWSER_HINT = ("Could not start the browser engine. Possible fixes:\n"
                "1) Make sure no antivirus blocked Python.\n"
                "2) Re-run this program.")

C = dict(
    bg="#f1f5f9",
    card="#ffffff",
    panel="#f8fafc",
    border="#e2e8f0",
    border_hi="#cbd5e1",
    ink="#0f172a",
    sub="#64748b",
    muted="#94a3b8",
    accent="#4f46e5",
    accent_hi="#4338ca",
    accent_soft="#eef2ff",
    accent_hover="#f1f5f9",
    ok="#15803d",
    ok_bg="#dcfce7",
    err="#dc2626",
    err_bg="#fee2e2",
    warn="#b45309",
    warn_bg="#fef3c7",
    log_bg="#0f172a",
    log_fg="#cbd5e1",
    log_ok="#6ee7b7",
    log_err="#fca5a5",
)

RES_SHORT = {
    "HD 720p": ("720p", "HD"),
    "Full HD 1080p": ("1080p", "Recommended"),
    "QHD 1440p": ("1440p", "QHD"),
    "4K UHD 2160p": ("4K", "Ultra HD"),
}

QUALITY_META = {
    "Normal": ("Normal", "Fastest"),
    "High": ("High", "Recommended"),
    "Best": ("Best", "Max detail"),
}
QUALITY_HINT = {
    "Normal": "Smaller file size — fastest export speed",
    "High": "Recommended — razor-sharp slides with balanced file size",
    "Best": "Largest file size — near-lossless detail for 4K/presentations",
}

SAMPLE_EN = ("This is a sample of the selected voice. Your slides will be "
             "narrated exactly like this.")
SAMPLE_BN = ("স্টুডিওর ভয়েস নমুনা। এভাবেই আপনার প্রতিটি স্লাইডের বর্ণনা "
             "শোনাবে।")

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
        self.script_lang_bn: bool | None = None

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
        """Measure required size and center the window inside the work area."""
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        w = min(max(980, req_w + 16), max(860, scr_w - 40))
        h = min(max(660, req_h + 12), max(540, scr_h - 80))
        self.root.minsize(900, 600)
        x = max(0, (scr_w - w) // 2)
        y = max(0, (scr_h - 80 - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_icon(self):
        try:
            if LOGO.exists():
                self.root.iconbitmap(default=str(LOGO))
                self.root.iconbitmap(str(LOGO))
        except Exception:
            pass

    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=C["bg"], foreground=C["ink"],
                     font=("Segoe UI", 10))
        st.configure("TFrame", background=C["bg"])
        st.configure("TLabel", background=C["card"], foreground=C["ink"])
        st.configure("Sub.TLabel", background=C["card"],
                     foreground=C["sub"], font=("Segoe UI", 9))
        st.configure("TEntry", fieldbackground="white",
                     bordercolor=C["border_hi"], lightcolor=C["border"],
                     darkcolor=C["border"], padding=(6, 5))
        st.configure("TCombobox", fieldbackground="white",
                     bordercolor=C["border_hi"], arrowsize=13,
                     padding=(6, 4))
        st.map("TCombobox",
               fieldbackground=[("disabled", "#f1f5f9")],
               foreground=[("disabled", C["muted"])])
        st.configure("TSpinbox", fieldbackground="white",
                     bordercolor=C["border_hi"], arrowsize=12,
                     padding=(6, 4))
        st.configure("Accent.TButton", foreground="white",
                     background=C["accent"], font=("Segoe UI", 10, "bold"),
                     padding=(24, 10), borderwidth=0)
        st.map("Accent.TButton",
               background=[("active", C["accent_hi"]),
                           ("disabled", "#a5b4fc")],
               foreground=[("disabled", "#eef2ff")])
        st.configure("Ghost.TButton", foreground=C["ink"], background="white",
                     bordercolor=C["border_hi"], font=("Segoe UI", 9),
                     padding=(12, 6))
        st.map("Ghost.TButton",
               background=[("active", "#f1f5f9"), ("disabled", "#f8fafc")],
               foreground=[("disabled", C["muted"])])
        st.configure("Danger.TButton", foreground="white", background="#e11d48",
                     font=("Segoe UI", 10, "bold"), padding=(16, 10),
                     borderwidth=0)
        st.map("Danger.TButton", background=[("active", "#be123c")])
        st.configure("Horizontal.TProgressbar", background=C["accent"],
                     troughcolor="#e2e8f0", borderwidth=0, thickness=8)

    def _header(self):
        cv = tk.Canvas(self.root, height=58, highlightthickness=0,
                       bg=C["accent"])
        cv.pack(fill="x")
        self.header_cv = cv
        self._badge_text = "Preparing engine…"
        self._badge_fg = C["warn"]
        self._badge_bg = C["warn_bg"]

        def repaint(event=None):
            cv.delete("all")
            width = max(2, cv.winfo_width())
            c1, c2 = (0x1e, 0x1b, 0x4b), (0x4f, 0x46, 0xe5)
            bands = 48
            bw = width / bands
            for i in range(bands):
                t = i / (bands - 1)
                col = "#%02x%02x%02x" % tuple(
                    int(a + (b - a) * t) for a, b in zip(c1, c2))
                cv.create_rectangle(i * bw, 0, (i + 1) * bw + 1, 58,
                                    fill=col, outline=col)
            cv.create_text(22, 21, anchor="w", text="HTML Video Studio",
                           fill="white", font=("Segoe UI", 15, "bold"))
            cv.create_text(
                22, 42, anchor="w", fill="#c7d2fe", font=("Segoe UI", 9),
                text="Turn any animated HTML presentation into HD / 4K MP4")

            # Live engine status pill on the right
            bx1 = width - 20
            bx0 = max(320, bx1 - max(140, len(self._badge_text) * 8 + 24))
            cv.create_rectangle(bx0, 16, bx1, 42, fill=self._badge_bg,
                                outline="", width=0)
            cv.create_text((bx0 + bx1) / 2, 29, text=self._badge_text,
                           fill=self._badge_fg, font=("Segoe UI", 9, "bold"))

        cv.bind("<Configure>", repaint)
        self._repaint_header = repaint
        return cv

    def _set_badge(self, text: str, fg: str, bg: str):
        self._badge_text = text
        self._badge_fg = fg
        self._badge_bg = bg
        if hasattr(self, "_repaint_header"):
            self._repaint_header()

    def _card(self, parent, step: str, title: str, subtitle: str = ""):
        """White rounded-feel card with numbered badge header."""
        body = tk.Frame(parent, bg=C["card"], highlightbackground=C["border"],
                        highlightthickness=1)
        inner = tk.Frame(body, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=14, pady=11)

        hdr = tk.Frame(inner, bg=C["card"])
        hdr.pack(fill="x", pady=(0, 8))
        badge = tk.Label(hdr, text=step, bg=C["accent_soft"], fg=C["accent"],
                         font=("Segoe UI", 9, "bold"), padx=7, pady=1)
        badge.pack(side="left")
        tk.Label(hdr, text=title, bg=C["card"], fg=C["ink"],
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=(8, 0))
        if subtitle:
            tk.Label(hdr, text=subtitle, bg=C["card"], fg=C["sub"],
                     font=("Segoe UI", 9)).pack(side="right")

        content = tk.Frame(inner, bg=C["card"])
        content.pack(fill="both", expand=True)
        return body, content

    def _section_label(self, parent, text: str, right_var=None):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=(4, 5))
        tk.Label(row, text=text, bg=C["card"], fg=C["sub"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        if right_var is not None:
            tk.Label(row, textvariable=right_var, bg=C["card"],
                     fg=C["accent"],
                     font=("Segoe UI", 9, "bold")).pack(side="right")
        return row

    def _make_segmented(self, parent, options, var, on_change=None):
        """Render a clean horizontal row of clickable option cards.

        options: list of (value, title, sub_or_none)
        """
        grid = tk.Frame(parent, bg=C["card"])
        grid.pack(fill="x")
        cards = []
        for idx, (val, title, sub) in enumerate(options):
            grid.columnconfigure(idx, weight=1, uniform="seg")
            box = tk.Frame(grid, bg=C["panel"], highlightbackground=C["border"],
                           highlightthickness=1, cursor="hand2")
            box.grid(row=0, column=idx, sticky="nsew",
                     padx=(0 if idx == 0 else 6, 0))
            pad = tk.Frame(box, bg=C["panel"], cursor="hand2")
            pad.pack(fill="both", expand=True, padx=8, pady=7)
            t_lbl = tk.Label(pad, text=title, bg=C["panel"], fg=C["ink"],
                             font=("Segoe UI", 10, "bold"), cursor="hand2")
            t_lbl.pack()
            s_lbl = None
            if sub:
                s_lbl = tk.Label(pad, text=sub, bg=C["panel"], fg=C["sub"],
                                 font=("Segoe UI", 8), cursor="hand2")
                s_lbl.pack(pady=(1, 0))

            widgets = [w for w in (box, pad, t_lbl, s_lbl) if w is not None]
            for w in widgets:
                w.bind("<Button-1>", lambda e, v=val: var.set(v))
                w.bind("<Enter>", lambda e, v=val, ws=widgets:
                       self._seg_hover(ws, var.get() == v, True))
                w.bind("<Leave>", lambda e, v=val, ws=widgets:
                       self._seg_hover(ws, var.get() == v, False))
            cards.append((val, box, pad, t_lbl, s_lbl))

        def refresh(*_):
            cur = var.get()
            for val, box, pad, t_lbl, s_lbl in cards:
                sel = (val == cur)
                bg = C["accent_soft"] if sel else C["panel"]
                fg = C["accent"] if sel else C["ink"]
                sfg = C["accent_hi"] if sel else C["sub"]
                box.configure(
                    bg=bg,
                    highlightbackground=C["accent"] if sel else C["border"],
                    highlightthickness=2 if sel else 1)
                pad.configure(bg=bg)
                t_lbl.configure(bg=bg, fg=fg)
                if s_lbl is not None:
                    s_lbl.configure(bg=bg, fg=sfg)
            if on_change:
                on_change()

        var.trace_add("write", refresh)
        refresh()
        return grid

    @staticmethod
    def _seg_hover(widgets, is_selected: bool, entering: bool):
        if is_selected:
            return
        bg = C["accent_hover"] if entering else C["panel"]
        for w in widgets:
            w.configure(bg=bg)

    # ──────────────────────────── UI ───────────────────────────────
    def _build_ui(self):
        self._header()

        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=16, pady=12)

        # Two-column workspace: left = Source & Voiceover, right = Export Settings
        cols = tk.Frame(main, bg=C["bg"])
        cols.pack(fill="x")
        cols.columnconfigure(0, weight=11, uniform="col")
        cols.columnconfigure(1, weight=10, uniform="col")

        # ── Left Card: Source & Voiceover ────────────────────────
        left_card, f1 = self._card(cols, "1", "Source & Voiceover")
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.html_var = tk.StringVar()
        self.script_var = tk.StringVar()

        self._section_label(f1, "HTML PRESENTATION")
        self._compact_file_row(f1, self.html_var, "Choose HTML file…",
                               self._pick_html)
        self.scan_label = tk.Label(
            f1, text="Choose an HTML file to detect slides automatically",
            bg=C["card"], fg=C["sub"], font=("Segoe UI", 9), anchor="w")
        self.scan_label.pack(fill="x", pady=(2, 5))

        self._section_label(f1, "VOICEOVER SCRIPT (OPTIONAL)")
        self.clear_script_btn = self._compact_file_row(
            f1, self.script_var, "No narration script — silent timing",
            self._pick_script, clear=self._clear_script)
        self.script_info_lbl = tk.Label(
            f1, text="Supports [[SLIDE n]] blocks (samples/english.txt)",
            bg=C["card"], fg=C["sub"], font=("Segoe UI", 9), anchor="w")
        self.script_info_lbl.pack(fill="x", pady=(2, 5))

        # Mutually exclusive TTS engine cards
        self._section_label(f1, "TEXT-TO-SPEECH ENGINE (PICK ONE)")
        self.engine_var = tk.StringVar(value=TTS_ENGINE_WINDOWS)
        self.win_voice_var = tk.StringVar(value=VOICE_AUTO)
        self.google_voice_var = tk.StringVar(value=GOOGLE_VOICE_DEFAULT)

        self.win_card, self.win_dot, self.win_title, self.win_voice_cb = (
            self._make_engine_card(
                f1,
                engine_val=TTS_ENGINE_WINDOWS,
                title="Windows TTS",
                badge="Microsoft · Free",
                voice_var=self.win_voice_var,
                voices=VOICES,
            ))
        self.google_card, self.google_dot, self.google_title, self.google_voice_cb = (
            self._make_engine_card(
                f1,
                engine_val=TTS_ENGINE_GOOGLE,
                title="Google TTS",
                badge="Gemini · Enceladus",
                voice_var=self.google_voice_var,
                voices=GOOGLE_VOICES,
                pady=(6, 0),
            ))

        sample_row = tk.Frame(f1, bg=C["card"])
        sample_row.pack(fill="x", pady=(8, 0))
        self.sample_btn = ttk.Button(
            sample_row, text="▶  Play voice sample", style="Ghost.TButton",
            command=self._play_sample, state="disabled")
        self.sample_btn.pack(side="left")
        self.tts_hint = tk.Label(
            sample_row, text="Windows TTS active · Google TTS disabled",
            bg=C["card"], fg=C["sub"], font=("Segoe UI", 9))
        self.tts_hint.pack(side="left", padx=(10, 0))

        # ── Right Card: Export Settings ──────────────────────────
        right_card, f2 = self._card(cols, "2", "Export Settings")
        right_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self.res_var = tk.StringVar(value="Full HD 1080p")
        self.q_var = tk.StringVar(value="High")
        self.fps_var = tk.IntVar(value=30)
        self.sec_var = tk.DoubleVar(value=8.0)

        self.res_readout_var = tk.StringVar(value="")
        self._section_label(f2, "OUTPUT RESOLUTION", self.res_readout_var)
        res_opts = [
            (label, RES_SHORT[label][0],
             f"{RES_SIZE[h][0]}×{RES_SIZE[h][1]}"
             + (" ★" if label == "Full HD 1080p" else ""))
            for label, h in RESOLUTIONS.items()
        ]
        self._make_segmented(f2, res_opts, self.res_var,
                             on_change=self._update_res)

        self._section_label(f2, "VIDEO QUALITY")
        q_opts = [(k, QUALITY_META[k][0], QUALITY_META[k][1])
                  for k in QUALITY]
        self.q_hint_var = tk.StringVar(value=QUALITY_HINT["High"])
        self._make_segmented(
            f2, q_opts, self.q_var,
            on_change=lambda: self.q_hint_var.set(
                QUALITY_HINT.get(self.q_var.get(), "")))
        tk.Label(f2, textvariable=self.q_hint_var, bg=C["card"],
                 fg=C["sub"], font=("Segoe UI", 8), anchor="w").pack(
            fill="x", pady=(3, 6))

        # Timing + Frame rate side by side
        tf = tk.Frame(f2, bg=C["card"])
        tf.pack(fill="x", pady=(2, 6))
        tf.columnconfigure(0, weight=1)
        tf.columnconfigure(1, weight=2)

        dur_box = tk.Frame(tf, bg=C["card"])
        dur_box.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tk.Label(dur_box, text="SLIDE DURATION", bg=C["card"], fg=C["sub"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))
        spin_row = tk.Frame(dur_box, bg=C["card"])
        spin_row.pack(anchor="w")
        ttk.Spinbox(spin_row, from_=1, to=120, increment=0.5, width=6,
                    textvariable=self.sec_var,
                    font=("Segoe UI", 10)).pack(side="left")
        tk.Label(spin_row, text="sec / slide", bg=C["card"], fg=C["sub"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(6, 0))
        tk.Label(dur_box, text="Silent slides only", bg=C["card"],
                 fg=C["muted"], font=("Segoe UI", 8)).pack(anchor="w",
                                                            pady=(2, 0))

        fps_box = tk.Frame(tf, bg=C["card"])
        fps_box.grid(row=0, column=1, sticky="nsew")
        tk.Label(fps_box, text="FRAME RATE", bg=C["card"], fg=C["sub"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))
        fps_opts = [(f, f"{f} fps",
                     {24: "Cinema", 30: "Standard", 60: "Smooth"}[f])
                    for f in FPS_CHOICES]
        self._make_segmented(fps_box, fps_opts, self.fps_var)

        # Output file preview bar
        out_box = tk.Frame(f2, bg=C["panel"], highlightbackground=C["border"],
                           highlightthickness=1)
        out_box.pack(fill="x", pady=(4, 0))
        self.out_var = tk.StringVar(
            value="Output: choose an HTML file to preview filename")
        tk.Label(out_box, textvariable=self.out_var, bg=C["panel"],
                 fg=C["ink"], font=("Segoe UI", 9), anchor="w",
                 padx=10, pady=7).pack(fill="x")

        # Collapsible Advanced drawer
        self.adv_open = False
        self.adv_btn = tk.Label(
            f2, text="▸  Advanced options (slide selector, capture detail, "
                     "API key)",
            bg=C["card"], fg=C["sub"], font=("Segoe UI", 9, "bold"),
            cursor="hand2")
        self.adv_btn.pack(anchor="w", pady=(8, 0))
        self.adv_btn.bind("<Button-1>", lambda e: self._toggle_advanced())

        adv = tk.Frame(f2, bg=C["panel"], highlightbackground=C["border"],
                       highlightthickness=1)
        self.adv_frame = adv
        adv_body = tk.Frame(adv, bg=C["panel"])
        adv_body.pack(fill="x", padx=12, pady=10)
        adv_body.columnconfigure(1, weight=1)

        tk.Label(adv_body, text="Slide selector", bg=C["panel"], fg=C["ink"],
                 font=("Segoe UI", 9), width=13,
                 anchor="e").grid(row=0, column=0, sticky="e", padx=(0, 8),
                                  pady=3)
        self.sel_var = tk.StringVar(value="")
        ttk.Entry(adv_body, textvariable=self.sel_var).grid(
            row=0, column=1, sticky="ew", pady=3)

        tk.Label(adv_body, text="Capture detail", bg=C["panel"], fg=C["ink"],
                 font=("Segoe UI", 9), width=13,
                 anchor="e").grid(row=1, column=0, sticky="e", padx=(0, 8),
                                  pady=3)
        self.detail_var = tk.StringVar(value="Faster (recommended)")
        ttk.Combobox(adv_body, textvariable=self.detail_var, state="readonly",
                     values=list(CAPTURE_DETAIL.keys())).grid(
            row=1, column=1, sticky="ew", pady=3)

        tk.Label(adv_body, text="Gemini API key", bg=C["panel"], fg=C["ink"],
                 font=("Segoe UI", 9), width=13,
                 anchor="e").grid(row=2, column=0, sticky="e", padx=(0, 8),
                                  pady=3)
        self.gemini_key_var = tk.StringVar(value=load_gemini_api_key())
        self.gemini_key_entry = ttk.Entry(
            adv_body, textvariable=self.gemini_key_var, show="•")
        self.gemini_key_entry.grid(row=2, column=1, sticky="ew", pady=3)
        tk.Label(adv_body, text="Loaded from root .env (Google TTS only)",
                 bg=C["panel"], fg=C["muted"], font=("Segoe UI", 8),
                 anchor="w").grid(row=3, column=1, sticky="w", pady=(0, 2))

        # ── Action & Progress Card ───────────────────────────────
        act_card = tk.Frame(main, bg=C["card"], highlightbackground=C["border"],
                            highlightthickness=1)
        act_card.pack(fill="x", pady=(8, 8))
        act_in = tk.Frame(act_card, bg=C["card"])
        act_in.pack(fill="x", padx=14, pady=10)

        act = tk.Frame(act_in, bg=C["card"])
        act.pack(fill="x")
        self.export_btn = ttk.Button(
            act, text="Preparing the video engine …",
            style="Accent.TButton", command=self._export, state="disabled")
        self.export_btn.pack(side="left")
        self.cancel_btn = ttk.Button(act, text="Cancel", style="Danger.TButton",
                                     command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(10, 0))
        self.open_btn = ttk.Button(act, text="Open output folder",
                                   style="Ghost.TButton",
                                   command=self._open_folder,
                                   state="disabled")
        self.open_btn.pack(side="right")

        prog_row = tk.Frame(act_in, bg=C["card"])
        prog_row.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(prog_row, maximum=100,
                                        mode="indeterminate")
        self.progress.pack(fill="x")
        self.progress.start(14)
        self.status = tk.Label(
            act_in, text="Checking the video engine …", bg=C["card"],
            fg=C["ink"], font=("Segoe UI", 9), anchor="w")
        self.status.pack(fill="x", pady=(4, 0))

        # ── Activity Log ─────────────────────────────────────────
        logcard = tk.Frame(main, bg=C["log_bg"],
                           highlightbackground=C["border"],
                           highlightthickness=1)
        logcard.pack(fill="both", expand=True)
        log_hdr = tk.Frame(logcard, bg="#1e293b")
        log_hdr.pack(fill="x")
        tk.Label(log_hdr, text="ACTIVITY LOG", bg="#1e293b", fg="#94a3b8",
                 font=("Segoe UI", 8, "bold"), padx=10, pady=3).pack(
            side="left")
        self.log = tk.Text(logcard, height=4, state="disabled", wrap="word",
                           font=("Consolas", 9), bg=C["log_bg"],
                           fg=C["log_fg"], relief="flat", padx=10, pady=6,
                           insertbackground=C["log_fg"])
        self.log.tag_configure("ok", foreground=C["log_ok"])
        self.log.tag_configure("err", foreground=C["log_err"])
        self.log.tag_configure("dim", foreground="#94a3b8")
        sb = ttk.Scrollbar(logcard, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self._log("HTML Video Studio starting. Pick an HTML file and press "
                  "Export.\nFirst run: required components are checked "
                  "automatically — please wait.", "dim")

        self.html_var.trace_add("write", lambda *_: self._update_outname())
        self.res_var.trace_add("write", lambda *_: self._update_outname())
        self.engine_var.trace_add("write", lambda *_: self._on_engine_change())
        self._update_res()
        self._on_engine_change()

    def _compact_file_row(self, parent, var, placeholder: str, cmd,
                          clear=None):
        rowf = tk.Frame(parent, bg=C["card"])
        rowf.pack(fill="x")
        ent = ttk.Entry(rowf, textvariable=var)
        ent.pack(side="left", fill="x", expand=True)
        ttk.Button(rowf, text="Browse…", style="Ghost.TButton",
                   command=cmd).pack(side="left", padx=(6, 0))
        clr_btn = None
        if clear:
            clr_btn = ttk.Button(rowf, text="Clear", style="Ghost.TButton",
                                 command=clear, state="disabled")
            clr_btn.pack(side="left", padx=(4, 0))
        return clr_btn

    def _make_engine_card(self, parent, engine_val: str, title: str,
                          badge: str, voice_var: tk.StringVar,
                          voices: list[str], pady=(0, 0)):
        card = tk.Frame(parent, bg=C["panel"], highlightbackground=C["border"],
                        highlightthickness=1, cursor="hand2")
        card.pack(fill="x", pady=pady)
        inner = tk.Frame(card, bg=C["panel"], cursor="hand2")
        inner.pack(fill="x", padx=10, pady=6)

        top = tk.Frame(inner, bg=C["panel"], cursor="hand2")
        top.pack(fill="x")
        dot = tk.Label(top, text="●", bg=C["panel"], fg=C["accent"],
                       font=("Segoe UI", 11), cursor="hand2")
        dot.pack(side="left")
        t_lbl = tk.Label(top, text=title, bg=C["panel"], fg=C["ink"],
                         font=("Segoe UI", 10, "bold"), cursor="hand2")
        t_lbl.pack(side="left", padx=(6, 0))
        b_lbl = tk.Label(top, text=badge, bg=C["panel"], fg=C["sub"],
                         font=("Segoe UI", 8), cursor="hand2")
        b_lbl.pack(side="right")

        cb = ttk.Combobox(inner, textvariable=voice_var, state="readonly",
                          values=voices)
        cb.pack(fill="x", pady=(6, 0))

        for w in (card, inner, top, dot, t_lbl, b_lbl):
            w.bind("<Button-1>",
                   lambda e, v=engine_val: self.engine_var.set(v))
        return card, dot, t_lbl, cb

    def _update_res(self):
        h = RESOLUTIONS[self.res_var.get()]
        w_px, h_px = RES_SIZE[h]
        self.res_readout_var.set(f"{w_px} × {h_px}")

    def _toggle_advanced(self):
        self.adv_open = not self.adv_open
        if self.adv_open:
            self.adv_btn.configure(
                text="▾  Advanced options (slide selector, capture detail, "
                     "API key)")
            self.adv_frame.pack(fill="x", pady=(6, 0))
            self.root.update_idletasks()
            self._resize_window_by(self.adv_frame.winfo_reqheight() + 6)
        else:
            self.adv_btn.configure(
                text="▸  Advanced options (slide selector, capture detail, "
                     "API key)")
            self._resize_window_by(-(self.adv_frame.winfo_reqheight() + 6))
            self.adv_frame.pack_forget()

    def _resize_window_by(self, dy: int):
        min_h = (self.root.minsize() or (0, 620))[1] or 620
        max_h = max(min_h, self.root.winfo_screenheight() - 80)
        h = min(max_h, max(min_h, self.root.winfo_height() + dy))
        self.root.geometry(f"{self.root.winfo_width()}x{h}")

    def _update_outname(self):
        html = self.html_var.get().strip()
        if not html:
            self.out_var.set("Output: choose an HTML file to preview filename")
            return
        try:
            s = self._settings()
            out = s.output_path()
            self.out_var.set(f"Output: {out.name}   (in {out.parent.name}/)")
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
            self._set_badge("● Ready", C["ok"], C["ok_bg"])
        elif self.setup_state == "failed":
            self.export_btn.configure(state="normal", text="Retry setup")
            self._set_badge("● Setup failed", C["err"], C["err_bg"])
        else:
            self.export_btn.configure(state="disabled",
                                      text="Preparing the video engine …")
            self._set_badge("● Preparing…", C["warn"], C["warn_bg"])

    def _pick_html(self):
        p = filedialog.askopenfilename(title="Choose an HTML file",
                                       filetypes=[("HTML files",
                                                   "*.html *.htm"),
                                                  ("All files", "*.*")])
        if p:
            self.html_var.set(p)
            self.scan_cache = None
            self.scan_label.configure(text="Checking slides in this page …",
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
        if self.clear_script_btn is not None:
            self.clear_script_btn.configure(state="normal")
        try:
            blocks = parse_script(read_script(Path(p)))
        except Exception:
            return
        if blocks:
            first = next(iter(blocks.values()))
            self.script_lang_bn = is_bengali(first)
            lang = "Bangla" if self.script_lang_bn else "English"
            self.script_info_lbl.configure(
                text=f"✓ {len(blocks)} slide narrations loaded ({lang})",
                fg=C["ok"])
            self._log(f"Script loaded: {len(blocks)} slide narrations "
                      f"(up to slide {max(blocks)}).", "dim")
        else:
            self.script_info_lbl.configure(
                text="⚠ No [[SLIDE n]] blocks found in file", fg=C["warn"])
            self._log("Script loaded, but no \"[[SLIDE n]]\" blocks were "
                      "found — see samples/english.txt for the format.",
                      "dim")

    def _clear_script(self):
        self.script_var.set("")
        self.script_lang_bn = None
        if self.clear_script_btn is not None:
            self.clear_script_btn.configure(state="disabled")
        self.script_info_lbl.configure(
            text="Supports [[SLIDE n]] blocks (samples/english.txt)",
            fg=C["sub"])

    def _style_engine_card(self, card, dot, title, active: bool):
        bg = C["accent_soft"] if active else C["panel"]
        border = C["accent"] if active else C["border"]
        card.configure(bg=bg, highlightbackground=border,
                       highlightthickness=2 if active else 1)
        for child in card.winfo_children():
            self._recolor_frame(child, bg)
        dot.configure(text="●" if active else "○",
                      fg=C["accent"] if active else C["muted"])
        title.configure(fg=C["ink"] if active else C["muted"])

    @staticmethod
    def _recolor_frame(widget, bg: str):
        if isinstance(widget, (tk.Frame, tk.Label)):
            widget.configure(bg=bg)
        for ch in widget.winfo_children():
            if isinstance(ch, (tk.Frame, tk.Label)):
                App._recolor_frame(ch, bg)

    def _on_engine_change(self):
        google_on = self.engine_var.get() == TTS_ENGINE_GOOGLE
        self._style_engine_card(self.win_card, self.win_dot, self.win_title,
                                active=not google_on)
        self._style_engine_card(self.google_card, self.google_dot,
                                self.google_title, active=google_on)
        self.win_voice_cb.configure(
            state="disabled" if google_on else "readonly")
        self.google_voice_cb.configure(
            state="readonly" if google_on else "disabled")
        self.gemini_key_entry.configure(
            state="normal" if google_on else "disabled")
        if google_on:
            self.tts_hint.configure(
                text="Google Gemini TTS active · Windows TTS disabled")
        else:
            self.tts_hint.configure(
                text="Windows TTS active · Google TTS disabled")

    def _active_voice_label(self) -> str:
        if self.engine_var.get() == TTS_ENGINE_GOOGLE:
            return self.google_voice_var.get()
        return self.win_voice_var.get()

    # ───────────────────── voice sample playback ────────────────────
    def _sample_text(self) -> str:
        if self.engine_var.get() == TTS_ENGINE_GOOGLE:
            return SAMPLE_BN if self.script_lang_bn else SAMPLE_EN
        label = self.win_voice_var.get()
        if label == VOICE_AUTO:
            bn = bool(self.script_lang_bn)
        else:
            bn = "Bangla" in label
        return SAMPLE_BN if bn else SAMPLE_EN

    def _play_sample(self):
        if self._playing_sample or self.ffmpeg is None:
            return
        engine = self.engine_var.get()
        text = self._sample_text()
        voice = voice_for(text, self._active_voice_label(), engine=engine)
        api_key = self.gemini_key_var.get().strip() or load_gemini_api_key()
        self._playing_sample = True
        self.sample_btn.configure(state="disabled", text="Generating …")
        threading.Thread(target=self._sample_worker,
                         args=(text, voice, engine, api_key),
                         daemon=True).start()

    def _sample_worker(self, text: str, voice: str, engine: str, api_key: str):
        try:
            tmp = Path(tempfile.gettempdir()) / "hvs_voice_sample"
            tmp.mkdir(exist_ok=True)
            wav = tmp / "sample.wav"
            synth_wav(text, voice, wav, self.ffmpeg,
                      engine=engine, api_key=api_key)
            import winsound
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
            tts_engine=self.engine_var.get(),
            tts_voice=self._active_voice_label(),
            gemini_api_key=(self.gemini_key_var.get().strip()
                            or load_gemini_api_key()),
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
            self._set_export_state()
            self.status.configure(text="Checking the video engine …",
                                  fg=C["ink"])
            self.progress.configure(mode="indeterminate")
            self.progress.start(14)
            self._log("Retrying setup …", "dim")
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
                                  text="Exporting…")
        self._set_badge("● Exporting…", C["accent"], C["accent_soft"])
        self.cancel_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        threading.Thread(target=self._render, args=(s,), daemon=True).start()

    def _render(self, s: Settings):
        t0 = time.time()

        def progress(kind, pct, msg):
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
        self.status.configure(text="Cancelling after the current frame …")

    def _open_folder(self):
        html = self.html_var.get().strip()
        target = Path(html).parent if html else Path.cwd()
        try:
            os.startfile(target)
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
            self.status.configure(
                text="Ready — choose an HTML file and press Export video.",
                fg=C["ok"])
            self._set_export_state()
            self.sample_btn.configure(state="normal")
            self._log("Setup complete — ready to export!  ✓", "ok")
            if self.html_var.get():
                self.scan_label.configure(text="Checking slides in this page …",
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
                         "exported", fg=C["warn"])
            elif info["continuous"]:
                self.scan_label.configure(
                    text=f"{info['count']} slides found, no auto-navigation "
                         "— continuous clip", fg=C["warn"])
            else:
                self.scan_label.configure(
                    text=f"✓ {info['count']} slides detected "
                         f"({info['selector']})", fg=C["ok"])
        elif kind == "scan_skip":
            self.scan_label.configure(
                text="Slide check will run during export.", fg=C["sub"])
        elif kind == "scan_fail":
            self.scan_label.configure(
                text="Slide preview unavailable (export will still work).",
                fg=C["sub"])
        elif kind == "sample_done":
            self._playing_sample = False
            self.sample_btn.configure(state="normal",
                                      text="▶  Play voice sample")
        elif kind == "sample_fail":
            self._playing_sample = False
            self.sample_btn.configure(state="normal",
                                      text="▶  Play voice sample")
            self._log("Voice sample failed: " + str(payload), "err")
        elif kind == "done":
            out, secs = payload
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.open_btn.configure(state="normal")
            self.status.configure(text=f"Video saved:  {out}", fg=C["ok"])
            self._log(f"VIDEO SAVED:  {out}", "ok")
            self._log("   Saved in the SAME folder as your HTML file — "
                      "press \"Open output folder\" to view it.", "ok")
            messagebox.showinfo(
                "Video ready",
                f"Your video is saved here:\n\n{out}\n\n"
                f"(Same folder as your HTML file)\n"
                f"Time taken: {secs / 60:.1f} minutes")
        elif kind == "cancelled":
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="Cancelled.", fg=C["sub"])
            self._log("Export cancelled by user.", "dim")
        elif kind == "error":
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="Export failed — see log below.",
                                  fg=C["err"])
            self._log("ERROR:\n" + str(payload), "err")
            msg = str(payload)
            if "browser" in msg.lower() or "chromium" in msg.lower():
                msg = BROWSER_HINT + "\n\n" + msg[:400]
            messagebox.showerror("Export failed", msg[:1200])


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()

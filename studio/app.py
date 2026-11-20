"""HTML Video Studio — desktop GUI (Tkinter). No coding needed.

Design: light modern flat UI — gradient header, white cards, accent
Export button with explicit states, dark console-style log.
"""

import ctypes
import os
import queue
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .capture import Cancelled
from .config import (CAPTURE_DETAIL, FPS_CHOICES, QUALITY, RESOLUTIONS,
                     Settings)
from .pipeline import Cancelled as PipelineCancelled  # noqa: F401 (alias)
from .pipeline import RenderError, render, scan_html

BROWSER_HINT = ("Could not start the browser engine. Possible fixes:\n"
                "1) Make sure no antivirus blocked Python.\n"
                "2) Re-run this program.\n"
                "বাংলা: ব্রাউজার ইঞ্জিন চালু হয়নি — অ্যান্টিভাইরাস চেক করে আবার চালান।")

C = dict(
    bg="#eef1f7", card="#ffffff", border="#dbe1ee",
    ink="#1c2333", sub="#64748b",
    accent="#5a54d6", accent_hi="#453fc4",
    ok="#15803d", err="#dc2626", warn="#b45309",
    log_bg="#131a2b", log_fg="#d8e0ee", log_ok="#7ee2a8", log_err="#ff9a9a",
)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.ffmpeg: str | None = None
        self.rendering = False
        self.setup_state = "running"          # running | ready | failed
        self.cancel_event = threading.Event()
        self.scan_cache: dict | None = None

        root.title("HTML Video Studio")
        root.configure(bg=C["bg"])
        root.geometry("860x720")
        root.minsize(780, 640)
        self._center(860, 720)

        self._style()
        self._build_ui()
        self._poll_queue()
        threading.Thread(target=self._setup_env, daemon=True).start()

    # ─────────────────────────── look ──────────────────────────────
    def _center(self, w, h):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

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
        st.configure("Accent.TButton", foreground="white",
                     background=C["accent"], font=("Segoe UI", 12, "bold"),
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

    def _gradient_header(self):
        cv = tk.Canvas(self.root, height=92, highlightthickness=0,
                       bg="#4f46e5")
        cv.pack(fill="x")

        def repaint(event=None):
            cv.delete("all")
            width = max(2, cv.winfo_width())
            c1, c2 = (0x4f, 0x46, 0xe5), (0x8b, 0x5c, 0xf6)
            for i in range(width):
                t = i / (width - 1)
                col = "#%02x%02x%02x" % tuple(
                    int(a + (b - a) * t) for a, b in zip(c1, c2))
                cv.create_line(i, 0, i, 92, fill=col)
            cv.create_text(28, 30, anchor="w", text="🎬  HTML Video Studio",
                           fill="white", font=("Segoe UI", 19, "bold"))
            cv.create_text(
                30, 62, anchor="w", fill="#e4e1ff", font=("Segoe UI", 10),
                text="HTML → HD / 4K video in one click  ·  কোডিং ছাড়াই "
                     "ভিডিও বানান")

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
        inner.pack(fill="x", padx=14, pady=10)
        ttk.Label(inner, text=title, style="CardTitle.TLabel").pack(
            anchor="w", pady=(0, 8))
        content = tk.Frame(inner, bg=C["card"])
        content.pack(fill="x")
        return content

    # ──────────────────────────── UI ───────────────────────────────
    def _build_ui(self):
        try:  # crisp text on high-DPI Windows
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self._gradient_header()

        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=16, pady=14)

        # ── card 1: files ────────────────────────────────────────
        f1 = self._card(main, "1 ·  Choose your files   (ফাইল নির্বাচন)")
        self.html_var = tk.StringVar()
        self.audio_var = tk.StringVar()
        self._file_row(f1, 0, "HTML file", self.html_var, self._pick_html,
                       [("HTML files", "*.html *.htm"), ("All files", "*.*")])
        self._file_row(f1, 1, "Voiceover (optional)", self.audio_var,
                       self._pick_audio,
                       [("Audio", "*.wav *.mp3 *.m4a *.aac *.ogg"),
                        ("All files", "*.*")], clear=True)
        self.scan_label = tk.Label(
            f1, text="⏳  Preparing the video engine (one-time setup) ...",
            bg=C["card"], fg=C["warn"], font=("Segoe UI", 9))
        self.scan_label.pack(anchor="w", pady=(6, 0))

        # ── card 2: settings ─────────────────────────────────────
        f2 = self._card(main, "2 ·  Export settings   (সেটিংস)")
        grid = tk.Frame(f2, bg=C["card"])   # grid-managed sub-frame
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="Resolution").grid(row=0, column=0, sticky="e",
                                                padx=(0, 8), pady=4)
        self.res_var = tk.StringVar(value="4K UHD 2160p")
        cb_res = ttk.Combobox(grid, textvariable=self.res_var, state="readonly",
                              width=18, values=list(RESOLUTIONS.keys()))
        cb_res.grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="Quality").grid(row=0, column=2, sticky="e",
                                             padx=(20, 8), pady=4)
        self.q_var = tk.StringVar(value="High")
        ttk.Combobox(grid, textvariable=self.q_var, state="readonly", width=12,
                     values=list(QUALITY.keys())).grid(row=0, column=3,
                                                       sticky="w", pady=4)

        ttk.Label(grid, text="Seconds / slide").grid(row=1, column=0,
                                                     sticky="e", padx=(0, 8),
                                                     pady=4)
        self.sec_var = tk.DoubleVar(value=8.0)
        ttk.Spinbox(grid, from_=1, to=120, increment=0.5, width=6,
                    textvariable=self.sec_var).grid(row=1, column=1,
                                                    sticky="w", pady=4)
        ttk.Label(grid, text="(each slide switches automatically after this "
                             "many seconds)", style="Sub.TLabel").grid(
            row=1, column=2, columnspan=2, sticky="w", padx=(20, 0), pady=4)

        # advanced disclosure
        self.adv_open = False
        self.adv_btn = tk.Label(
            f2, text="▸  Advanced options (FPS, slide selector)",
            bg=C["card"], fg=C["accent"], font=("Segoe UI", 9, "bold"),
            cursor="hand2")
        self.adv_btn.pack(anchor="w", pady=(10, 0))
        self.adv_btn.bind("<Button-1>", lambda e: self._toggle_advanced())
        self.adv_frame = tk.Frame(f2, bg=C["card"])
        ttk.Label(self.adv_frame, text="FPS").grid(row=0, column=0, sticky="e",
                                                   padx=(0, 8), pady=4)
        self.fps_var = tk.IntVar(value=30)
        ttk.Combobox(self.adv_frame, textvariable=self.fps_var,
                     state="readonly", width=6,
                     values=list(FPS_CHOICES)).grid(row=0, column=1,
                                                    sticky="w", pady=4)
        ttk.Label(self.adv_frame,
                  text="Slide selector (CSS, empty = auto)").grid(
            row=0, column=2, sticky="e", padx=(20, 8), pady=4)
        self.sel_var = tk.StringVar(value="")
        ttk.Entry(self.adv_frame, width=26, textvariable=self.sel_var).grid(
            row=0, column=3, sticky="w", pady=4)
        ttk.Label(self.adv_frame, text="Capture detail").grid(
            row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        self.detail_var = tk.StringVar(value="Faster (recommended)")
        ttk.Combobox(self.adv_frame, textvariable=self.detail_var,
                     state="readonly", width=28,
                     values=list(CAPTURE_DETAIL.keys())).grid(
            row=1, column=1, columnspan=3, sticky="w", pady=4)

        # output name preview
        self.out_var = tk.StringVar(value="")
        tk.Label(f2, textvariable=self.out_var, bg=C["card"], fg=C["sub"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))

        # ── actions ──────────────────────────────────────────────
        act = tk.Frame(main, bg=C["bg"])
        act.pack(fill="x", pady=(2, 10))
        self.export_btn = ttk.Button(
            act, text="⏳  Preparing — one-time setup running ...",
            style="Accent.TButton", command=self._export)
        self.export_btn.pack(side="left")
        self.cancel_btn = ttk.Button(act, text="Cancel", style="Danger.TButton",
                                     command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=12)
        self.open_btn = ttk.Button(act, text="📂  Open output folder",
                                   style="Ghost.TButton",
                                   command=self._open_folder,
                                   state="disabled")
        self.open_btn.pack(side="right")

        # ── progress + status ────────────────────────────────────
        self.progress = ttk.Progressbar(main, maximum=100, mode="indeterminate")
        self.progress.pack(fill="x")
        self.progress.start(14)   # pulsing while setup runs
        self.status = tk.Label(
            main, text="Starting one-time setup ...   |   "
            "প্রথমবারের সেটআপ চলছে ...", bg=C["bg"], fg=C["ink"],
            font=("Segoe UI", 10), anchor="w")
        self.status.pack(fill="x", pady=(6, 10))

        # ── log ──────────────────────────────────────────────────
        logcard = tk.Frame(main, bg=C["log_bg"],
                           highlightbackground=C["border"],
                           highlightthickness=1)
        logcard.pack(fill="both", expand=True)
        self.log = tk.Text(logcard, height=9, state="disabled", wrap="word",
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
                  "Export.\nপ্রথমবার চালালে দরকারি জিনিস নিজে থেকেই ইনস্টল "
                  "হবে — একটু অপেক্ষা করুন।\n", "dim")

        self.html_var.trace_add("write", lambda *_: self._update_outname())
        self.res_var.trace_add("write", lambda *_: self._update_outname())

    def _file_row(self, parent, row, label, var, cmd, patterns, clear=False):
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
                       command=lambda: self._set_audio("")).pack(
                side="left", padx=(4, 0))

    def _toggle_advanced(self):
        self.adv_open = not self.adv_open
        if self.adv_open:
            self.adv_btn.configure(text="▾  Advanced options (FPS, slide "
                                        "selector)")
            self.adv_frame.pack(fill="x", pady=(6, 0))
        else:
            self.adv_btn.configure(text="▸  Advanced options (FPS, slide "
                                        "selector)")
            self.adv_frame.pack_forget()

    def _update_outname(self):
        html = self.html_var.get().strip()
        if not html:
            self.out_var.set("")
            return
        try:
            s = self._settings()
            self.out_var.set(f"💾 Video will be saved to:   {s.output_path()}")
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
            self.export_btn.configure(state="normal", text="🎬  Export video")
        elif self.setup_state == "failed":
            self.export_btn.configure(state="normal", text="↻  Retry setup")
        else:
            self.export_btn.configure(state="normal",
                                      text="⏳  Preparing — one-time setup "
                                           "running ...")

    def _pick_html(self):
        p = filedialog.askopenfilename(title="Choose an HTML file",
                                       filetypes=[("HTML files",
                                                   "*.html *.htm"),
                                                  ("All files", "*.*")])
        if p:
            self.html_var.set(p)
            self.scan_cache = None
            self.scan_label.configure(text="🔎  Checking this page …",
                                      fg=C["sub"])
            threading.Thread(target=self._scan, args=(Path(p),),
                             daemon=True).start()

    def _pick_audio(self):
        p = filedialog.askopenfilename(
            title="Choose a voiceover audio file (optional)",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.aac *.ogg"),
                       ("All files", "*.*")])
        if p:
            self._set_audio(p)

    def _set_audio(self, p: str):
        self.audio_var.set(p)

    def _scan(self, path: Path):
        if self.ffmpeg is None:
            self.q.put(("scan_skip", None, None))
            return
        try:
            info = scan_html(path, self.sel_var.get().strip())
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
            audio_path=Path(self.audio_var.get()) if self.audio_var.get()
            else None,
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
                "says “Setup complete”.\n\n"
                "বাংলা: প্রথমবারের সেটআপ এখনো চলছে — নিচের লগে দেখুন, শেষ "
                "হলে Export চালু হয়ে যাবে।")
            return
        if self.setup_state == "failed":
            self.setup_state = "running"
            self.export_btn.configure(state="disabled", text="⏳  Retrying "
                                      "setup ...")
            self._log("Retrying setup ...", "dim")
            threading.Thread(target=self._setup_env, daemon=True).start()
            return

        html = self.html_var.get().strip()
        if not html or not Path(html).exists():
            messagebox.showwarning("HTML Video Studio",
                                   "Please choose an HTML file first.\n"
                                   "বাংলা: আগে একটি HTML ফাইল নির্বাচন করুন।")
            return
        s = self._settings()
        out = s.output_path()
        if out.exists():
            if not messagebox.askyesno(
                    "Overwrite?",
                    f"{out.name} already exists.\nOverwrite it?\n"
                    "বাংলা: ফাইলটি আগে থেকেই আছে — নতুন করে তৈরি করবেন?"):
                return

        self.rendering = True
        self.cancel_event.clear()
        self.export_btn.configure(state="disabled",
                                  text="⏳  Exporting — see progress below")
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
        self.status.configure(text="Cancelling after the current frame ...   "
                              "|   বাতিল করা হচ্ছে ...")

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
            if "✓" in msg or "ready" in msg.lower() or "সম্পন্ন" in msg:
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
            self.scan_label.configure(
                text="✅  Engine ready — choose an HTML file above.",
                fg=C["ok"])
            self._set_export_state()
            self._log("Setup complete — ready to export!  ✓", "ok")
            if self.html_var.get():
                self.scan_label.configure(text="🔎  Checking this page …",
                                          fg=C["sub"])
                threading.Thread(target=self._scan,
                                 args=(Path(self.html_var.get()),),
                                 daemon=True).start()
        elif kind == "env_fail":
            self.setup_state = "failed"
            self._set_export_state()
            self.scan_label.configure(
                text="⚠️  Setup failed — press the button above to retry.",
                fg=C["err"])
            self._log(str(payload), "err")
            messagebox.showerror("Setup failed", str(payload))
        elif kind == "scan_done":
            self.scan_cache = payload
            info = payload
            if info["count"] == 0:
                self.scan_label.configure(
                    text="ℹ️  No slides found — one continuous clip will be "
                         "exported.", fg=C["warn"])
            elif info["continuous"]:
                self.scan_label.configure(
                    text=f"ℹ️  {info['count']} slides found, but no automatic "
                         "navigation — a continuous clip will be exported.",
                    fg=C["warn"])
            else:
                self.scan_label.configure(
                    text=f"✅  {info['count']} slides detected "
                         f"(selector '{info['selector']}') — ready to export",
                    fg=C["ok"])
        elif kind == "scan_skip":
            self.scan_label.configure(
                text="🔎  Slide check will happen during export "
                     "(setup still running).", fg=C["sub"])
        elif kind == "scan_fail":
            self.scan_label.configure(
                text="ℹ️  Slide preview unavailable (export will still "
                     "work).", fg=C["sub"])
        elif kind == "done":
            out, secs = payload
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.open_btn.configure(state="normal")
            self.status.configure(
                text=f"✅  Video saved!   {out}")
            self._log(f"✅ VIDEO SAVED:  {out}", "ok")
            self._log("   It is in the SAME folder as your HTML file — "
                      "press “📂 Open output folder” to see it.\n"
                      "   বাংলা: ভিডিওটি আপনার HTML ফাইলের একই ফোল্ডারে "
                      "সেভ হয়েছে।", "ok")
            messagebox.showinfo(
                "Video ready ✓",
                f"Your video is saved here:\n\n{out}\n\n"
                f"(Same folder as your HTML file)\n"
                f"Time taken: {secs / 60:.1f} minutes\n\n"
                f"বাংলা: ভিডিও তৈরি সম্পন্ন! উপরের ফোল্ডারে সেভ হয়েছে।")
        elif kind == "cancelled":
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="Cancelled.   |   বাতিল করা হয়েছে।")
            self._log("Export cancelled by user.", "dim")
        elif kind == "error":
            self.rendering = False
            self._set_export_state()
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="⚠️  Export failed — see log below.")
            self._log("ERROR:\n" + str(payload), "err")
            msg = str(payload)
            if "browser" in msg.lower() or "chromium" in msg.lower():
                msg = BROWSER_HINT + "\n\n" + msg[:400]
            messagebox.showerror("Export failed", msg[:1200])


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

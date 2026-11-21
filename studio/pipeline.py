"""Render pipeline: HTML file in, MP4 out. Drives detection, capture and
encoding, reporting progress through a callback.

progress(kind, percent, message) where kind in:
  "log" | "progress" | "phase" | "done" | "info"
"""

import shutil
import tempfile
import time
from pathlib import Path

from .capture import (LAUNCH_ARGS, Cancelled, create_engine)
from .config import ANIM_CAP_FPS, RES_LABELS, RES_SIZE, Settings
from .detector import SlideDetector
from .encoder import encode_steps, join_segments
from .tts import (LEAD, TAIL, build_track, mp3_to_wav, parse_script,
                  read_script, synth, voice_for, wav_duration)


class RenderError(Exception):
    """User-facing render failure. Message is plain-language."""


def scan_html(html_path: Path, selector: str = "") -> dict:
    """Quick one-shot detection used by the GUI preview.
    Returns {'count', 'selector', 'activator', 'continuous'}."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = ctx.new_page()
            page.goto(html_path.resolve().as_uri(), timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.evaluate("() => document.fonts ? document.fonts.ready : 0")
            det = SlideDetector(page)
            found = det.detect(selector)
            act = det.find_activator() if found["count"] else None
            continuous = found["count"] == 0 or (
                act is None and not det.activate(1))
            return {"count": found["count"], "selector": found["selector"],
                    "activator": act, "continuous": continuous}
        finally:
            browser.close()


def render(settings: Settings, progress, cancel_event) -> Path:
    """Full export. Raises Cancelled or RenderError."""
    html = settings.html_path
    if not html.exists():
        raise RenderError("HTML file not found.")

    audio = settings.audio_path
    if audio is not None and not audio.exists():
        raise RenderError("Audio file not found.")

    script = settings.script_path
    if script is not None and not script.exists():
        raise RenderError("Narration script file not found.")

    ffmpeg = _get_ffmpeg(progress)
    out = settings.output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    progress("log", 0, f"Output will be saved to:  {out}")
    progress("log", 0, "   (same folder as your HTML file)")

    work = Path(tempfile.mkdtemp(prefix="hvs_frames_"))
    segments: list[Path] = []

    from playwright.sync_api import sync_playwright

    browser = None
    engine = None
    try:
        progress("phase", 2, "Opening page ...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
            ctx = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=settings.res_h / 1080.0)
            page = ctx.new_page()
            page.goto(html.resolve().as_uri(), timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                progress("log", 0, "Network idle wait skipped (page keeps "
                                  "loading in background) — continuing.")
            try:
                page.evaluate("() => document.fonts.ready")
            except Exception:
                pass
            time.sleep(1.2)  # settle layout

            # ── detect slides ────────────────────────────────────
            progress("phase", 5, "Detecting slides ...")
            det = SlideDetector(page)
            found = det.detect(settings.selector)
            n_slides = found["count"]

            if n_slides == 0:
                mode = "continuous"
                total = settings.seconds_per_slide
                durations = [total]
                progress("log", 0,
                         f"No slides detected — exporting one continuous "
                         f"clip of {total:.1f}s.")
            else:
                mode = "slides"
                durations = [settings.seconds_per_slide] * n_slides
                total = sum(durations)
                act = det.find_activator()
                if act:
                    progress("log", 0, f"Found {n_slides} slides "
                                      f"(selector '{found['selector']}', "
                                      f"navigation '{act}()').")
                elif not det.activate(1):
                    mode = "continuous"
                    durations = [settings.seconds_per_slide]
                    total = settings.seconds_per_slide
                    n_slides = 1
                    progress("log", 0, "Slides found but no navigation "
                                      "function — exporting one continuous "
                                      "clip instead.")

            # ── text-to-speech voiceover ─────────────────────────
            # A narration script overrides the fixed slide duration: each
            # slide stays on screen exactly as long as its narration.
            vo_track = None
            if script is not None and mode == "slides":
                blocks = parse_script(read_script(script))
                if not blocks:
                    raise RenderError(
                        "The narration script has no \"[[SLIDE n]]\" "
                        "blocks. See samples/english.txt for the format.")
                extra = [n for n in sorted(blocks) if n > n_slides]
                if extra:
                    progress("log", 0, f"Script narrates slides "
                                      f"{extra[0]}–{extra[-1]} but only "
                                      f"{n_slides} slides were detected — "
                                      f"those blocks are skipped.")
                narrated = sum(1 for i in range(n_slides)
                               if blocks.get(i + 1))
                progress("phase", 5, "Generating voiceover ...")
                progress("log", 0, f"Text-to-speech: {narrated}/{n_slides} "
                                  f"slides have narration.")
                tts_dir = work / "tts"
                tts_dir.mkdir()
                entries: list[tuple[Path, float]] = []
                durations = []
                cursor = 0.0
                for i in range(n_slides):
                    text = blocks.get(i + 1)
                    if not text:
                        durations.append(settings.seconds_per_slide)
                        cursor += settings.seconds_per_slide
                        continue
                    mp3 = tts_dir / f"vo{i:03d}.mp3"
                    synth(text, voice_for(text, settings.tts_voice), mp3)
                    wav = tts_dir / f"vo{i:03d}.wav"
                    mp3_to_wav(mp3, wav, ffmpeg)
                    d = wav_duration(wav)
                    entries.append((wav, cursor + LEAD))
                    slide_d = LEAD + d + TAIL
                    durations.append(round(slide_d, 3))
                    cursor += slide_d
                    progress("phase", 5 + (i + 1) / n_slides * 5,
                             f"Generating voiceover {i + 1}/{n_slides} ...")
                    progress("log", 0,
                             f"✓ Narration {i + 1}/{n_slides}: {d:.1f}s")
                total = sum(durations)
                vo_track = work / "voiceover.wav"
                build_track(entries, total, vo_track)
                progress("log", 0, f"Voiceover ready ({total / 60:.1f} min) "
                                  f"— slide timing follows the narration.")
            elif script is not None:
                progress("log", 0, "Narration script ignored — the page has "
                                  "no navigable slides to match \"[[SLIDE "
                                  "n]]\" blocks against.")

            fps = settings.fps
            # screenshots are the expensive step — cap capture rate in
            # "normal" mode (frames are duplicated smoothly by the encoder)
            if settings.capture_detail == "max":
                cap_fps = fps
            else:
                cap_fps = min(fps, ANIM_CAP_FPS.get(settings.res_h, 12))
            res_label = RES_LABELS.get(settings.res_h)
            w, h = RES_SIZE[settings.res_h]
            engine = create_engine(page, cap_fps)
            progress("log", 0, f"Capture engine: {engine.name} · "
                              f"{w}×{h} · output {fps} fps · capture "
                              f"{cap_fps} fps · {total:.1f}s total")
            if settings.res_h >= 1440 and settings.capture_detail != "max":
                progress("log", 0, "Tip: high resolutions take time — for "
                                  "quick drafts use Full HD 1080p.")

            # ── capture + encode each slide ──────────────────────
            t_start = time.monotonic()
            frames_done = 0
            frames_all = sum(int(round(d * cap_fps)) for d in durations)

            def frame_cb(done, total_frames):
                nonlocal frames_done
                frames_done += 1
                elapsed = time.monotonic() - t_start
                if frames_done and elapsed > 0.5:
                    rate = frames_done / elapsed
                    remain = (frames_all - frames_done) / max(rate, 0.1)
                    pct = 10 + frames_done / max(1, frames_all) * 70
                    progress("phase", pct,
                             f"Capturing slide {slide_pos + 1}/"
                             f"{len(durations)} — frame {done}/{total_frames}"
                             f"  ·  ~{remain / 60:.1f} min left")
                else:
                    pct = 10 + frames_done / max(1, frames_all) * 70
                    progress("progress", pct, "")

            for idx in range(len(durations)):
                slide_pos = idx
                dur = durations[idx]
                seg_dir = work / f"slide{idx:03d}"
                seg_dir.mkdir()
                seg = work / f"seg_{idx:03d}.mp4"

                if mode == "slides":
                    def activate():
                        if not det.activate(idx, advance=engine.advance):
                            progress("log", 0,
                                     f"Could not verify slide {idx + 1} "
                                     f"is visible — capturing anyway.")

                    progress("phase", 10 + idx / len(durations) * 70,
                             f"Capturing slide {idx + 1}/{len(durations)} "
                             f"({dur:.1f}s) ...")
                else:
                    def activate():
                        pass
                    progress("phase", 10, "Recording ...")

                steps = engine.capture_steps(
                    activate, dur, seg_dir, on_frame=frame_cb,
                    cancel=lambda: cancel_event.is_set())
                if cancel_event.is_set():
                    raise Cancelled()
                encode_steps(steps, seg, fps, settings.res_h,
                             settings.crf, ffmpeg)
                for p, _ in steps:
                    p.unlink(missing_ok=True)
                segments.append(seg)
                progress("log", 0, f"✓ Slide {idx + 1}/{len(durations)} "
                                  f"captured & encoded "
                                  f"({seg.stat().st_size // 1024} KB)")
                progress("progress", 10 + (idx + 1) / len(durations) * 70, "")

        # ── final join + optional voiceover ──────────────────────
        progress("phase", 82, "Encoding final video — real progress shown "
                              "on the bar ...")
        progress("log", 0, "⏳ Final encoding — this is the last step and "
                          "can take a few minutes at high resolution.")

        def _join_progress(frac):
            progress("progress", 82 + frac * 17, "")

        if vo_track is not None:
            audio = vo_track
        join_segments(segments, out, settings.fps, settings.res_h,
                      settings.crf, ffmpeg,
                      audio=audio,
                      total=total,
                      log=lambda m: progress("log", 0, m),
                      on_progress=_join_progress)
        progress("log", 0, f"✅ VIDEO SAVED:  {out}", )
        progress("log", 0, "   Open it from the same folder as your HTML "
                          "file, or press “Open output folder”.")
        progress("progress", 100, "")
        return out

    except Cancelled:
        raise
    except RenderError:
        raise
    except Exception as e:
        raise RenderError(_friendly(e)) from e
    finally:
        if engine is not None:
            engine.release_time()
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        shutil.rmtree(work, ignore_errors=True)


def _get_ffmpeg(progress) -> str:
    from .environment import ensure_environment
    return ensure_environment(lambda m: progress("log", 0, m))


def _friendly(e: Exception) -> str:
    s = str(e)
    table = [
        ("Target closed", "The browser closed unexpectedly. Try again."),
        ("Begin frame control", "This Chromium build cannot capture "
         "deterministically — real-time capture was also unavailable."),
        ("out of memory", "Not enough memory for this resolution. Try "
         "1080p, or close other programs."),
        (" net::ERR", "The page failed to load. Check the file path."),
    ]
    for key, msg in table:
        if key.lower() in s.lower():
            return msg
    return s[:500] if s.strip() else "Unknown error."

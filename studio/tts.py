"""Text-to-speech voiceover: [[SLIDE n]] narration scripts -> per-slide
audio, assembled into one track that starts exactly when each slide starts.

Uses edge-tts (free Microsoft neural voices, no API key; requires
internet). The narration script format is the one in samples/english.txt:

    [[SLIDE 1]]
    Narration text for slide 1 ...

    [[SLIDE 2]]
    Narration text for slide 2 ...
"""

import asyncio
import re
import subprocess
import threading
import wave
from pathlib import Path

from .config import NO_WINDOW, VOICE_AUTO, VOICE_BN, VOICE_EN, VOICE_MAP

# Script marker: "[[SLIDE 12]]" (one or two brackets, case-insensitive)
_MARKER = re.compile(
    r"^[ \t]*\[{1,2}[ \t]*SLIDE[ \t]+(\d+)[ \t]*\]{1,2}[ \t]*$",
    re.IGNORECASE | re.MULTILINE)

SR = 24000        # assembly sample rate (matches edge-tts output)
LEAD = 0.35       # silence before narration starts on a slide (seconds)
TAIL = 0.65       # silence after narration before the slide switches


class TtsError(Exception):
    """User-facing text-to-speech failure. Message is plain-language."""


def read_script(path: Path) -> str:
    """Read a script file tolerating UTF-8 BOM, UTF-8 or legacy encodings.

    Line endings are normalized to LF so markers match regardless of
    whether the file was saved with CRLF (Windows editors) or LF.
    """
    data = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_script(text: str) -> dict[int, str]:
    """Split a narration script into {slide_number: narration_text}.

    Anything before the first marker (file headers etc.) is ignored.
    """
    marks = list(_MARKER.finditer(text))
    blocks: dict[int, str] = {}
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[start:end].strip()
        if body:
            blocks[int(m.group(1))] = body
    return blocks


def is_bengali(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    bn = sum(1 for ch in letters if 0x0980 <= ord(ch) <= 0x09FF)
    return bn / len(letters) > 0.5


def voice_for(text: str, voice_label: str) -> str:
    """Resolve the GUI voice choice to an edge-tts voice id.

    The "Auto" choice picks a Bangla voice for Bengali text and an
    English voice otherwise, per slide.
    """
    vid = VOICE_MAP.get(voice_label)
    if vid:
        return vid
    if voice_label != VOICE_AUTO:
        return VOICE_EN
    return VOICE_BN if is_bengali(text) else VOICE_EN


def _run_async(coro):
    """Run a coroutine on a fresh event loop in its own thread.

    Needed because the render pipeline runs inside Playwright's sync API,
    which already drives an asyncio loop on the calling thread.
    """
    box: dict = {}

    def _target():
        try:
            box["ok"] = asyncio.run(coro)
        except BaseException as e:  # propagate to the joining thread
            box["err"] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]
    return box.get("ok")


def synth(text: str, voice: str, out_mp3: Path, retries: int = 2) -> None:
    """Synthesize one narration block to an mp3 file via edge-tts."""
    import edge_tts

    last_err: Exception | str = "no output produced"
    for _attempt in range(retries + 1):
        try:
            communicator = edge_tts.Communicate(text, voice)
            _run_async(communicator.save(str(out_mp3)))
            if out_mp3.exists() and out_mp3.stat().st_size > 0:
                return
        except Exception as e:  # network hiccups etc. — retry, then fail
            last_err = e
    raise TtsError(
        "Speech generation failed (check your internet connection and try "
        f"again): {last_err}")


def mp3_to_wav(mp3: Path, wav: Path, ffmpeg: str) -> None:
    """Convert a tts mp3 to the assembly format (mono 24 kHz s16 wav)."""
    proc = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(mp3),
         "-ar", str(SR), "-ac", "1", "-sample_fmt", "s16", str(wav)],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    if proc.returncode != 0 or not wav.exists():
        raise TtsError(f"Could not process generated speech: {mp3.name}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def build_track(entries: list[tuple[Path, float]], total: float,
                out: Path) -> None:
    """Assemble one voiceover wav by placing segments at their start time.

    entries: [(segment_wav, start_seconds)] — segments never overlap by
    construction (one narration per slide), so plain placement is exact.
    """
    n_samples = int(round(total * SR))
    buf = bytearray(n_samples * 2)
    for path, start in entries:
        with wave.open(str(path), "rb") as w:
            if (w.getframerate() != SR or w.getnchannels() != 1
                    or w.getsampwidth() != 2):
                raise TtsError(f"Unexpected audio format in {path.name}")
            data = w.readframes(w.getnframes())
        ofs = int(round(start * SR)) * 2
        end = min(len(buf), ofs + len(data))
        if end > ofs:
            buf[ofs:end] = data[:end - ofs]
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(buf))

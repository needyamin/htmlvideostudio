"""Text-to-speech voiceover: [[SLIDE n]] narration scripts -> per-slide
audio, assembled into one track that starts exactly when each slide starts.

Supports two selectable engines:
- Windows TTS (Microsoft edge-tts neural voices, free, no API key)
- Google TTS (Gemini TTS API, e.g. voice Enceladus)

The narration script format is the one in samples/english.txt:

    [[SLIDE 1]]
    Narration text for slide 1 ...

    [[SLIDE 2]]
    Narration text for slide 2 ...
"""

import asyncio
import base64
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

from .config import (GEMINI_TTS_MODEL, GOOGLE_VOICE_MAP, NO_WINDOW,
                     TTS_ENGINE_GOOGLE, TTS_ENGINE_WINDOWS, VOICE_AUTO,
                     VOICE_BN, VOICE_EN, VOICE_MAP, load_gemini_api_key)

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


def voice_for(text: str, voice_label: str,
              engine: str = TTS_ENGINE_WINDOWS) -> str:
    """Resolve the GUI voice choice to an engine-specific voice id.

    For Windows/Edge TTS, "Auto" picks a Bangla voice for Bengali text
    and an English voice otherwise, per slide. For Google Gemini TTS,
    maps the display label to the Gemini voice name (default: Enceladus).
    """
    if engine == TTS_ENGINE_GOOGLE:
        if voice_label in GOOGLE_VOICE_MAP:
            return GOOGLE_VOICE_MAP[voice_label]
        if voice_label in GOOGLE_VOICE_MAP.values():
            return voice_label
        return "Enceladus"

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


def _convert_to_wav(src: Path, wav: Path, ffmpeg: str) -> None:
    """Convert any audio file to the assembly format (mono 24 kHz s16 wav)."""
    proc = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
         "-ar", str(SR), "-ac", "1", "-sample_fmt", "s16", str(wav)],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    if proc.returncode != 0 or not wav.exists():
        raise TtsError(f"Could not process generated speech: {src.name}")


def mp3_to_wav(mp3: Path, wav: Path, ffmpeg: str) -> None:
    """Convert a tts mp3 to the assembly format (mono 24 kHz s16 wav)."""
    _convert_to_wav(mp3, wav, ffmpeg)


def pcm_to_wav(pcm: bytes, path: Path, sample_rate: int = SR) -> None:
    """Wrap raw 16-bit mono PCM bytes in a WAV container."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)


def _extract_gemini_audio(data: dict) -> tuple[bytes, str]:
    """Extract raw audio bytes and mimeType from a Gemini generateContent reply."""
    candidates = data.get("candidates")
    if not candidates or "content" not in candidates[0]:
        finish = candidates[0].get("finishReason") if candidates else None
        prompt_fb = data.get("promptFeedback", {})
        raise TtsError(
            "Google TTS returned no audio "
            f"(finishReason={finish}, promptFeedback={prompt_fb}).")
    parts = candidates[0]["content"].get("parts", [])
    for part in parts:
        inline = part.get("inlineData")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"]), inline.get("mimeType", "")
    raise TtsError("Google TTS response did not contain audio data.")


def _parse_http_error(err: urllib.error.HTTPError) -> str:
    body = err.read().decode("utf-8", "replace")
    try:
        parsed = json.loads(body)
        msg = parsed.get("error", {}).get("message")
        if msg:
            return f"HTTP {err.code}: {msg}"
    except Exception:
        pass
    return f"HTTP {err.code}: {body[:300]}"


def synth_google(text: str, voice: str, out_wav: Path,
                 api_key: str = "",
                 ffmpeg: str | None = None, retries: int = 2) -> None:
    """Synthesize one narration block to a 24 kHz mono WAV via Gemini TTS."""
    key = (api_key or "").strip() or load_gemini_api_key()
    if not key:
        raise TtsError(
            "Google TTS requires GEMINI_API_KEY in the project root .env "
            "file (or enter it in Advanced options).")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_TTS_MODEL}:generateContent")
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice}
                }
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-goog-api-key": key}

    last_err: Exception | str = "no output produced"
    data = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            msg = _parse_http_error(e)
            last_err = msg
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise TtsError(f"Google TTS failed ({msg})") from e
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise TtsError(
                "Google TTS failed (check your internet connection and try "
                f"again): {last_err}") from e

    if data is None:
        raise TtsError(f"Google TTS failed: {last_err}")

    raw, mime = _extract_gemini_audio(data)
    if not raw:
        raise TtsError("Google TTS returned empty audio.")

    mime_l = mime.lower()
    if raw[:4] == b"RIFF" or "wav" in mime_l:
        tmp = out_wav.with_suffix(".raw.wav")
        tmp.write_bytes(raw)
        try:
            with wave.open(str(tmp), "rb") as w:
                ok = (w.getframerate() == SR and w.getnchannels() == 1
                      and w.getsampwidth() == 2)
        except Exception:
            ok = False
        if ok:
            shutil.move(str(tmp), str(out_wav))
        elif ffmpeg:
            _convert_to_wav(tmp, out_wav, ffmpeg)
            tmp.unlink(missing_ok=True)
        else:
            shutil.move(str(tmp), str(out_wav))
        return

    if not mime_l or "pcm" in mime_l or "l16" in mime_l:
        m_rate = re.search(r"rate=(\d+)", mime_l)
        rate = int(m_rate.group(1)) if m_rate else SR
        if rate == SR or not ffmpeg:
            pcm_to_wav(raw, out_wav, sample_rate=rate)
        else:
            tmp = out_wav.with_suffix(".raw.wav")
            pcm_to_wav(raw, tmp, sample_rate=rate)
            _convert_to_wav(tmp, out_wav, ffmpeg)
            tmp.unlink(missing_ok=True)
        return

    if not ffmpeg:
        raise TtsError(f"Unsupported Google TTS audio format: {mime}")
    tmp = out_wav.with_suffix(".raw.bin")
    tmp.write_bytes(raw)
    try:
        _convert_to_wav(tmp, out_wav, ffmpeg)
    finally:
        tmp.unlink(missing_ok=True)


def synth_wav(text: str, voice: str, out_wav: Path, ffmpeg: str,
              engine: str = TTS_ENGINE_WINDOWS,
              api_key: str = "",
              retries: int = 2) -> None:
    """Synthesize one narration block directly to a 24 kHz mono WAV."""
    if engine == TTS_ENGINE_GOOGLE:
        synth_google(text, voice, out_wav, api_key=api_key,
                     ffmpeg=ffmpeg, retries=retries)
        return
    mp3 = out_wav.with_suffix(".mp3")
    try:
        synth(text, voice, mp3, retries=retries)
        mp3_to_wav(mp3, out_wav, ffmpeg)
    finally:
        mp3.unlink(missing_ok=True)


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

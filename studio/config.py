"""Central configuration for HTML Video Studio."""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Windows: prevent child processes (ffmpeg, pip, browser installer) from
# flashing a console window when the GUI runs window-less via pythonw.
NO_WINDOW = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             if os.name == "nt" else 0)

# Viewport the page is rendered at. Every presentation designed for a normal
# browser window will lay out exactly as the author sees it; higher
# resolutions are produced with device-scale-factor, keeping text and
# vector graphics razor sharp.
BASE_W = 1920
BASE_H = 1080

RESOLUTIONS = {
    "HD 720p": 720,
    "Full HD 1080p": 1080,
    "QHD 1440p": 1440,
    "4K UHD 2160p": 2160,
}
RES_LABELS = {
    720: "720p",
    1080: "1080p",
    1440: "1440p",
    2160: "4K",
}
RES_SIZE = {720: (1280, 720), 1080: (1920, 1080),
            1440: (2560, 1440), 2160: (3840, 2160)}

QUALITY = {"Normal": 22, "High": 18, "Best": 14}
FPS_CHOICES = (24, 30, 60)

# Text-to-speech engines & voices.
TTS_ENGINE_WINDOWS = "Windows TTS (Microsoft)"
TTS_ENGINE_GOOGLE = "Google TTS (Gemini)"
TTS_ENGINES = [TTS_ENGINE_WINDOWS, TTS_ENGINE_GOOGLE]

# Microsoft edge-tts voices. The Auto choice matches each slide's language:
# Bangla text -> bn-BD voice, everything else -> en-US voice.
VOICE_AUTO = "Auto — match each slide's language"
VOICES = [
    VOICE_AUTO,
    "English — Aria (female)",
    "English — Guy (male)",
    "Bangla BD — Nabanita (female)",
    "Bangla BD — Pradeep (male)",
]
VOICE_MAP = {
    VOICES[1]: "en-US-AriaNeural",
    VOICES[2]: "en-US-GuyNeural",
    VOICES[3]: "bn-BD-NabanitaNeural",
    VOICES[4]: "bn-BD-PradeepNeural",
}
VOICE_EN = "en-US-AriaNeural"      # auto-detect choice for non-Bengali text
VOICE_BN = "bn-BD-NabanitaNeural"  # auto-detect choice for Bengali text

# Google Gemini TTS settings & voices.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"


def load_env_var(name: str, default: str = "") -> str:
    """Read a credential from process env or the project root .env file."""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    if ENV_FILE.is_file():
        try:
            for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() != name:
                    continue
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                return v.strip()
        except OSError:
            pass
    return default


def load_gemini_api_key() -> str:
    """Return the configured Gemini API key from env / .env, or empty str."""
    return load_env_var("GEMINI_API_KEY")
GOOGLE_VOICES = [
    "Enceladus — Breathy, soft (default)",
    "Kore — Firm",
    "Puck — Upbeat",
    "Charon — Informative",
    "Fenrir — Excitable",
    "Leda — Youthful",
    "Zephyr — Bright",
    "Aoede — Breezy",
]
GOOGLE_VOICE_MAP = {
    "Enceladus — Breathy, soft (default)": "Enceladus",
    "Kore — Firm": "Kore",
    "Puck — Upbeat": "Puck",
    "Charon — Informative": "Charon",
    "Fenrir — Excitable": "Fenrir",
    "Leda — Youthful": "Leda",
    "Zephyr — Bright": "Zephyr",
    "Aoede — Breezy": "Aoede",
}
GOOGLE_VOICE_DEFAULT = GOOGLE_VOICES[0]

# Max frames captured per second of animation (screenshots are the most
# expensive step; identical/interpolated frames are duplicated smoothly
# by the CFR encoder). "Maximum smoothness" mode bypasses this cap.
ANIM_CAP_FPS = {720: 15, 1080: 12, 1440: 10, 2160: 8}
CAPTURE_DETAIL = {"Faster (recommended)": "normal",
                  "Maximum smoothness (very slow)": "max"}

ANIM_WAIT = 1.2          # real-time settle after page load (seconds)
ACTIVATORS = ["go", "goTo", "gotoSlide", "showSlide", "selectSlide",
              "goToSlide", "navigateTo", "jumpTo", "setSlide", "changeSlide",
              "next", "nextSlide", "advance"]
AUTO_SELECTORS = [".slide", "[data-slide]", ".slide-frame",
                  ".slides > section", "#slides > section", "section.slide",
                  ".reveal .slides > section"]


@dataclass
class Settings:
    html_path: Path = Path("presentation.html")
    audio_path: Path | None = None
    script_path: Path | None = None   # narration script (.txt) for TTS
    tts_engine: str = TTS_ENGINE_WINDOWS
    tts_voice: str = VOICE_AUTO       # voice choice for selected TTS engine
    gemini_api_key: str = field(default_factory=load_gemini_api_key)
    res_h: int = 2160                 # 720 / 1080 / 1440 / 2160
    fps: int = 30
    crf: int = 18                     # x264 quality (lower = better)
    seconds_per_slide: float = 8.0
    selector: str = ""                # custom CSS selector, "" = auto
    capture_detail: str = "normal"    # "normal" = adaptive capture fps

    def output_path(self) -> Path:
        out = self.html_path.with_name(
            f"{self.html_path.stem}_{RES_LABELS.get(self.res_h, self.res_h)}.mp4")
        return out

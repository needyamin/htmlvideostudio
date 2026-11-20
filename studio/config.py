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

# Max frames captured per second of animation (screenshots are the most
# expensive step; identical/interpolated frames are duplicated smoothly
# by the CFR encoder). "Maximum smoothness" mode bypasses this cap.
ANIM_CAP_FPS = {720: 15, 1080: 12, 1440: 10, 2160: 8}
CAPTURE_DETAIL = {"Faster (recommended)": "normal",
                  "Maximum smoothness (very slow)": "max"}

ANIM_WAIT = 1.2          # real-time settle after page load (seconds)
ACTIVATORS = ["go", "goTo", "gotoSlide", "showSlide", "selectSlide",
              "goToSlide", "navigateTo", "jumpTo", "setSlide", "changeSlide"]
AUTO_SELECTORS = [".slide", "[data-slide]", ".slide-frame",
                  ".slides > section", "#slides > section", "section.slide",
                  ".reveal .slides > section"]


@dataclass
class Settings:
    html_path: Path = Path("presentation.html")
    audio_path: Path | None = None
    res_h: int = 2160                 # 720 / 1080 / 1440 / 2160
    fps: int = 30
    crf: int = 18                     # x264 quality (lower = better)
    seconds_per_slide: float = 8.0
    selector: str = ""                # custom CSS selector, "" = auto
    match_audio: bool = False         # split voiceover duration evenly
    capture_detail: str = "normal"    # "normal" = adaptive capture fps

    def output_path(self) -> Path:
        out = self.html_path.with_name(
            f"{self.html_path.stem}_{RES_LABELS.get(self.res_h, self.res_h)}.mp4")
        return out

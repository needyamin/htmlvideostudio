"""First-run environment setup: Python packages, Chromium browser, ffmpeg."""

import subprocess
import sys
from pathlib import Path

from .config import NO_WINDOW

_REQUIRED = [
    ("playwright", "playwright>=1.40,<2"),
    ("imageio_ffmpeg", "imageio-ffmpeg>=0.4.9,<0.6"),
    ("edge_tts", "edge-tts>=6.1,<8"),
]

# Short English messages shown in the GUI log
MSG = {
    "pip_missing": "Installing required Python packages (one time only) ...",
    "pip_done": "Python packages ready ✓",
    "pip_fail": "Could not install Python packages. Check your internet "
                "connection, then try again.",
    "chromium_missing": "Downloading Chromium browser (~150 MB, one time "
                        "only) ...",
    "chromium_done": "Chromium ready ✓",
    "chromium_fail": "Could not download the Chromium browser. Check your "
                     "internet connection and try again.",
    "ffmpeg_ok": "Video encoder ready ✓",
    "env_ready": "Setup complete — ready to export!",
}


class EnvironmentError(Exception):
    """Raised when setup cannot complete; message is user-friendly."""


def _pip_install(packages: list[str], log) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *packages]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=NO_WINDOW)
        if proc.returncode != 0:
            log(proc.stderr.strip() or proc.stdout.strip())
            raise EnvironmentError(MSG["pip_fail"])
    except FileNotFoundError:
        raise EnvironmentError(MSG["pip_fail"])


def ensure_environment(log) -> str:
    """Install anything missing and return the path of an ffmpeg binary.

    `log` is a callable(str) used for progress messages.
    Raises EnvironmentError with a plain-language message on failure.
    """
    import importlib

    missing_pkgs, missing_mods = [], []
    for mod, pkg in _REQUIRED:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing_pkgs.append(pkg)
            missing_mods.append(mod)

    if missing_pkgs:
        log(MSG["pip_missing"])
        _pip_install(missing_pkgs, log)
        log(MSG["pip_done"])

    # Chromium browser
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            exe = p.chromium.executable_path
            ok = Path(exe).exists()
        except Exception:
            ok = False
        if not ok:
            log(MSG["chromium_missing"])
            proc = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, creationflags=NO_WINDOW)
            if proc.returncode != 0:
                log(proc.stderr.strip() or proc.stdout.strip())
                raise EnvironmentError(MSG["chromium_fail"])
            log(MSG["chromium_done"])

    # ffmpeg (bundled via imageio-ffmpeg; downloads once if needed)
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    log(MSG["ffmpeg_ok"])
    log(MSG["env_ready"])
    return ffmpeg

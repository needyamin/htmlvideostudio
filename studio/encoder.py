"""ffmpeg encoding helpers: frame steps -> segment MP4s -> final video."""

import subprocess
import tempfile
from pathlib import Path

from .config import NO_WINDOW, RES_SIZE


def _quote(p) -> str:
    return "'" + str(p).replace("'", "'\\''") + "'"


def _run_progressive(cmd: list[str], total: float, on_progress=None,
                     log=None) -> None:
    """Run ffmpeg streaming live progress (frac 0..1) via -progress pipe:1.

    stderr goes to a temp file (avoids pipe deadlocks) so failures can be
    reported. Falls back from -fps_mode to -vsync for old ffmpeg builds.
    """
    attempts = [cmd + ["-progress", "pipe:1", "-nostats", "-fps_mode", "cfr"],
                cmd + ["-progress", "pipe:1", "-nostats", "-vsync", "cfr"]]
    last_err = ""
    for attempt, full in enumerate(attempts):
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                    errors="replace") as errf:
            proc = subprocess.Popen(full, stdout=subprocess.PIPE,
                                    stderr=errf, text=True,
                                    creationflags=NO_WINDOW)
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if (line.startswith("out_time_ms=")
                        or line.startswith("out_time_us=")) and total > 0:
                    try:
                        micro = float(line.split("=", 1)[1])
                        if on_progress:
                            on_progress(min(1.0, max(0.0, micro / 1e6 / total)))
                    except ValueError:
                        pass
            proc.wait()
            if proc.returncode == 0:
                return
            errf.seek(0)
            last_err = errf.read().strip()[-1500:]
    if log:
        log(last_err or "ffmpeg failed")
    raise RuntimeError("ffmpeg encoding failed (see log for details)")


def probe_duration(path: Path, ffmpeg: str) -> float:
    """Media duration in seconds via ffmpeg stderr probing."""
    proc = subprocess.run([ffmpeg, "-i", str(path)],
                          capture_output=True, text=True,
                          creationflags=NO_WINDOW)
    for line in proc.stderr.splitlines():
        if "Duration:" in line:
            try:
                h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            except Exception:
                break
    return 0.0


def _encode_cmd(ffmpeg: str, inputs: list[str], out: Path, fps: int, w: int,
                h: int, crf: int, audio: Path | None = None,
                total: float | None = None) -> list:
    vf = f"scale={w}:{h}:flags=lanczos,format=yuv420p"
    cmd = [ffmpeg, "-y", "-loglevel", "error", *inputs,
           "-map", "0:v:0",
           "-vf", vf, "-r", str(fps),
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-profile:v", "high", "-movflags", "+faststart"]
    if audio is not None:
        cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k",
                "-af", "apad"]
        if total:
            cmd += ["-t", f"{total:.3f}"]
    else:
        cmd += ["-an"]
    cmd += [str(out)]
    return cmd


def encode_steps(steps, out: Path, fps: int, res_h: int, crf: int,
                 ffmpeg: str, log=None) -> None:
    """Encode a list of (png_or_jpg_path, duration) into one MP4 segment."""
    w, h = RES_SIZE[res_h]
    concat = out.with_suffix(".txt")
    lines = []
    for p, d in steps:
        lines.append(f"file {_quote(p)}")
        lines.append(f"duration {max(0.01, d):.3f}")
    if steps:  # concat demuxer quirk: repeat the final file
        lines.append(f"file {_quote(steps[-1][0])}")
    concat.write_text("\n".join(lines), encoding="utf-8")

    base = ["-f", "concat", "-safe", "0", "-i", str(concat)]
    _run_progressive(_encode_cmd(ffmpeg, base, out, fps, w, h, crf),
                     0.0, None, log)


def join_segments(segments: list[Path], out: Path, fps: int, res_h: int,
                  crf: int, ffmpeg: str, audio: Path | None = None,
                  total: float | None = None, log=None,
                  on_progress=None) -> None:
    """Concatenate per-slide segments (re-encode keeps timestamps exact).
    Streams real encoding progress (0..1) through on_progress."""
    w, h = RES_SIZE[res_h]
    concat = out.with_name(out.stem + "_join.txt")
    concat.write_text(
        "\n".join(f"file {_quote(s)}" for s in segments), encoding="utf-8")
    base = ["-f", "concat", "-safe", "0", "-i", str(concat)]
    if audio is not None:
        base += ["-i", str(audio)]
    _run_progressive(
        _encode_cmd(ffmpeg, base, out, fps, w, h, crf, audio, total),
        float(total or 0), on_progress, log)
    concat.unlink(missing_ok=True)

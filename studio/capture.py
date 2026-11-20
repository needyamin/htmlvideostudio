"""Frame capture engines.

Engine 1 (default) — Deterministic virtual-time capture:
  Chromium is launched with begin-frame control. The page's internal clock
  is paused and advanced in exact frame steps via CDP virtual-time budget,
  while HeadlessExperimental.beginFrame returns a screenshot per frame.
  Every animation — CSS, WAAPI, requestAnimationFrame/canvas and even
  setTimeout-driven effects — is captured deterministically at any
  resolution (including 4K), independent of machine speed.

Engine 2 (fallback) — Real-time screencast capture:
  CDP Page.startScreencast records frames as the page animates in real
  time. Used automatically if the deterministic engine is unavailable.
"""

import base64
import hashlib
import threading
import time
from pathlib import Path

LAUNCH_ARGS = [
    "--enable-begin-frame-control",
    "--run-all-compositor-stages-before-draw",
    "--force-color-profile=srgb",
    "--hide-scrollbars",
]


class EngineUnsupported(Exception):
    pass


class Cancelled(Exception):
    pass


class DeterministicEngine:
    name = "deterministic"

    def __init__(self, page, fps: int):
        self.page = page
        self.fps = fps
        self.cdp = page.context.new_cdp_session(page)
        self._expired = threading.Event()
        self.cdp.on("Emulation.virtualTimeBudgetExpired",
                    lambda *_: self._expired.set())

    # ── virtual-time control ──────────────────────────────────────
    def setup(self) -> None:
        try:
            self.cdp.send("Emulation.setVirtualTimePolicy",
                          {"policy": "pause"})
        except Exception as e:  # begin-frame control missing
            raise EngineUnsupported(str(e))

    def release_time(self) -> None:
        try:
            self.cdp.send("Emulation.setVirtualTimePolicy",
                          {"policy": "advance"})
        except Exception:
            pass

    def _vnow(self) -> float:
        """Virtual page clock in ms (performance.now follows virtual time)."""
        try:
            res = self.cdp.send("Runtime.evaluate",
                                {"expression": "performance.now()",
                                 "returnByValue": True})
            return float(res.get("result", {}).get("value", 0.0))
        except Exception:
            return 0.0

    def advance(self, seconds: float, timeout: float = 60.0) -> None:
        """Advance virtual time by `seconds`, blocking until consumed."""
        target = self._vnow() + seconds * 1000.0
        self.cdp.send("Emulation.setVirtualTimePolicy", {
            "policy": "pauseIfNetworkFetchesPending",
            "budget": max(1, int(seconds * 1000) + 10),
        })
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # budget-expired events only dispatch inside Playwright calls,
            # so poll the virtual clock directly (each _vnow() also lets
            # pending events through).
            if self._expired.is_set() or self._vnow() >= target - 1.0:
                return
            time.sleep(0.004)
        raise EngineUnsupported("virtual-time budget did not expire")

    def snap(self) -> bytes | None:
        # jpeg q96 is dramatically faster to save/load than png while
        # being visually lossless for video frames
        res = self.cdp.send("HeadlessExperimental.beginFrame",
                            {"screenshot": {"format": "jpeg", "quality": 96}})
        data = res.get("screenshotData")
        if not data:
            return None
        return base64.b64decode(data)

    # ── capture one slide ─────────────────────────────────────────
    def capture_steps(self, activate, duration: float, workdir: Path,
                      on_frame=None, cancel=None):
        """activate() brings the slide into its initial state.
        Returns list of (png_path, duration_seconds) with identical
        consecutive frames merged into holds."""
        dt = 1.0 / self.fps
        n_frames = max(2, int(round(duration * self.fps)))

        activate()
        raw: list[bytes] = []
        first = self.snap()
        if first is None:
            self.advance(0.002)
            first = self.snap()
            if first is None:
                raise EngineUnsupported("beginFrame returned no screenshot")
        raw.append(first)
        nulls = 0
        for f in range(1, n_frames):
            if cancel is not None and cancel():
                raise Cancelled()
            self.advance(dt)
            shot = self.snap()
            if shot is None:
                nulls += 1
                if nulls > 10:
                    raise EngineUnsupported(
                        "beginFrame stopped returning screenshots")
                shot = raw[-1]
            else:
                nulls = 0
            raw.append(shot)
            if on_frame:
                on_frame(f + 1, n_frames)

        # save unique frames, merge identical consecutive ones
        steps: list[tuple[Path, float]] = []
        prev_hash = None
        for data in raw:
            h = hashlib.md5(data).hexdigest()
            if h != prev_hash:
                p = workdir / f"f{len(steps):05d}.jpg"
                p.write_bytes(data)
                steps.append([p, 0.0])
                prev_hash = h
            steps[-1][1] += dt
        return [(p, d) for p, d in steps]


class RealtimeEngine:
    name = "real-time"

    def __init__(self, page, fps: int):
        self.page = page
        self.fps = fps
        self.cdp = page.context.new_cdp_session(page)

    def setup(self) -> None:
        pass

    def release_time(self) -> None:
        pass

    def advance(self, seconds: float, timeout: float = 60.0) -> None:
        time.sleep(seconds)

    def snap(self) -> bytes | None:
        return None

    def capture_steps(self, activate, duration: float, workdir: Path,
                      on_frame=None, cancel=None):
        frames: list[tuple[float, bytes]] = []
        done = threading.Event()

        def on_frame(params):
            try:
                self.cdp.send("Page.screencastFrameAck",
                              {"sessionId": params["sessionId"]})
            except Exception:
                pass
            data = params.get("data")
            if data:
                frames.append((time.monotonic(), base64.b64decode(data)))

        self.cdp.on("Page.screencastFrame", on_frame)
        self.cdp.send("Page.startScreencast",
                      {"format": "jpeg", "quality": 95, "everyNthFrame": 1})
        try:
            activate()
            start = time.monotonic()
            while True:
                now = time.monotonic()
                if cancel is not None and cancel():
                    raise Cancelled()
                if on_frame:
                    on_frame(now - start, duration)
                if now - start >= duration:
                    break
                time.sleep(min(0.05, max(0.01, 1.0 / self.fps / 2)))
        finally:
            try:
                self.cdp.send("Page.stopScreencast")
            except Exception:
                pass

        if not frames:
            raise EngineUnsupported("screencast produced no frames")

        # merge identical consecutive frames, durations from wall time
        steps: list[tuple[Path, float]] = []
        prev_hash = None
        prev_t = None
        for t, data in frames:
            h = hashlib.md5(data).hexdigest()
            if h != prev_hash:
                ext = ".jpg"
                p = workdir / f"f{len(steps):05d}{ext}"
                p.write_bytes(data)
                if prev_t is not None and steps:
                    steps[-1] = (steps[-1][0], t - prev_t)
                steps.append((p, 0.0))
                prev_hash = h
                prev_t = t
        # pad last frame so the slide lasts exactly `duration`
        covered = sum(d for _, d in steps)
        if covered < duration and steps:
            steps[-1] = (steps[-1][0], steps[-1][1] + duration - covered)
        return steps


def create_engine(page, fps: int, prefer_deterministic: bool = True):
    """Return a working capture engine, falling back to real-time."""
    if prefer_deterministic:
        eng = DeterministicEngine(page, fps)
        try:
            eng.setup()
            return eng
        except EngineUnsupported:
            eng.release_time()
    eng = RealtimeEngine(page, fps)
    eng.setup()
    return eng

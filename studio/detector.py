"""Slide detection and activation inside the live page.

Everything here runs through page.evaluate() so it works identically for
the deterministic (virtual-time) engine and the real-time engine.
"""

from .config import ACTIVATORS, AUTO_SELECTORS

DETECT_JS = """
(selector) => {
  const sels = [];
  if (selector) sels.push(selector);
  for (const s of %AUTO_SELECTORS%) if (!sels.includes(s)) sels.push(s);
  for (const sel of sels) {
    let els;
    try { els = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
    els = els.filter(e => e.tagName !== 'SCRIPT' && e.tagName !== 'STYLE');
    if (els.length >= 2) {
      window.__hvs_slides = els;
      window.__hvs_selector = sel;
      return { count: els.length, selector: sel };
    }
  }
  window.__hvs_slides = null;
  return { count: 0, selector: '' };
}
""".replace("%AUTO_SELECTORS%", str(AUTO_SELECTORS).replace("'", '"'))

ACTIVATOR_JS = """
(names) => {
  for (const n of names) {
    try { if (typeof window[n] === 'function') return n; } catch (e) {}
  }
  return null;
}
"""

ACTIVE_INDEX_JS = """
() => {
  const els = window.__hvs_slides;
  if (!els) return -1;
  // 1) class-based detection (active / current / visible ...)
  const marks = ['active', 'current', 'visible', 'present', 'shown', 'on'];
  for (let i = 0; i < els.length; i++) {
    const cl = (els[i].className || '').toString().toLowerCase();
    for (const m of marks) {
      if (cl.split(/\\s+/).includes(m)) return i;
    }
  }
  // 2) computed-visibility detection
  for (let i = 0; i < els.length; i++) {
    const cs = getComputedStyle(els[i]);
    const r = els[i].getBoundingClientRect();
    if (cs.display !== 'none' && cs.visibility !== 'hidden'
        && r.width > 1 && r.height > 1
        && parseFloat(cs.opacity || '1') > 0.05) return i;
  }
  return -1;
}
"""


# Generic "step forward" strategies for decks that wire navigation inside
# a closure (no global activator function). Each snippet dispatches ONE
# forward-navigation event; Python then verifies the active slide changed.
STEP_STRATEGIES = [
    # 1) right-arrow key — the most common deck shortcut
    "() => { const ev = new KeyboardEvent('keydown',"
    "{key: 'ArrowRight', code: 'ArrowRight', bubbles: true, cancelable: true});"
    "(document.body || document.documentElement).dispatchEvent(ev);"
    " return true; }",
    # 2) a visible Next button
    "() => { const b = document.getElementById('nextBtn') "
    "|| document.querySelector('[id*=\"next\" i], [class*=\"nextbtn\" i]');"
    " if (b) { b.click(); return true; } return false; }",
    # 3) click the right half of the page (many decks advance on click)
    "() => { const x = innerWidth - 20, y = Math.round(innerHeight / 2);"
    " const t = document.elementFromPoint(x, y) || document.body;"
    " const ev = new MouseEvent('click', {bubbles: true, cancelable: true,"
    " clientX: x, clientY: y}); t.dispatchEvent(ev); return true; }",
    # 4) pagedown shortcut
    "() => { const ev = new KeyboardEvent('keydown',"
    "{key: 'PageDown', code: 'PageDown', bubbles: true, cancelable: true});"
    "(document.body || document.documentElement).dispatchEvent(ev);"
    " return true; }",
]
STEP_BACK_JS = (
    "() => { const ev = new KeyboardEvent('keydown',"
    "{key: 'ArrowLeft', code: 'ArrowLeft', bubbles: true, cancelable: true});"
    "(document.body || document.documentElement).dispatchEvent(ev);"
    " return true; }")

# Hide -> force reflow -> restore: every CSS animation inside the slide
# restarts from its beginning (same as re-visiting the slide), so
# entrance reveals play in the video for EVERY slide — including slide 1,
# whose animations otherwise already ran during the page load.
RESTART_ANIM_JS = """
(i) => {
  const el = (window.__hvs_slides || [])[i];
  if (!el) return false;
  const sx = scrollX, sy = scrollY;
  const prev = el.style.display;
  el.style.display = 'none';
  void el.offsetWidth;              // force reflow
  el.style.display = prev;          // restore deck-controlled visibility
  scrollTo(sx, sy);                 // scroll decks: keep position stable
  try {
    document.getAnimations({subtree: el}).forEach(a => {
      if (a.playState === 'finished') { a.currentTime = 0; a.play(); }
    });
  } catch (e) {}
  return true;
}
"""


class SlideDetector:
    def __init__(self, page):
        self.page = page

    def detect(self, selector: str = "") -> dict:
        """Find slides. Returns {'count': int, 'selector': str}."""
        return self.page.evaluate(DETECT_JS, selector)

    def find_activator(self) -> str | None:
        return self.page.evaluate(ACTIVATOR_JS, ACTIVATORS)

    def active_index(self) -> int:
        return self.page.evaluate(ACTIVE_INDEX_JS)

    def activate(self, index: int, advance=None, max_tries: int = 2) -> bool:
        """Try to bring slide `index` into view. Returns True when verified.

        `advance(seconds)` — optional callback that advances page time
        (virtual or real) so class/opacity transitions can settle.

        Strategy order: named global activator function → generic step
        navigation (keyboard / next button / click) → scrollIntoView.
        """
        fn = getattr(self, "_activator", None)
        if fn is None:
            fn = self.find_activator()
            self._activator = fn
        for attempt in range(max_tries):
            if fn:
                try:
                    self.page.evaluate(f"window[{fn!r}]({index})")
                except Exception:
                    fn = None
                    continue
            else:
                # generic navigation (works for closure-based decks)
                if self._step_to(index, advance):
                    return True
                # scroll-based decks: bring the element into view
                try:
                    self.page.evaluate(
                        "i => { const e = window.__hvs_slides[i];"
                        " if (e) e.scrollIntoView({behavior: 'instant', block: 'center'}); }",
                        index)
                except Exception:
                    return False
            if advance:
                advance(0.15)
            if self.active_index() == index:
                return True
        return False

    def _step_to(self, index: int, advance=None, max_steps: int = 8) -> bool:
        """Reach slide `index` by stepping through the deck with generic
        forward navigation. Caches whichever strategy works. Forward-only
        decks start at slide 0, so stepping reaches every index."""
        for _ in range(max_steps):
            try:
                cur = self.active_index()
            except Exception:
                return False
            if cur == index:
                return True

            if cur > index:
                js = STEP_BACK_JS          # overshot — step back
            else:
                js = getattr(self, "_step_js", None)
                if js is None:
                    # discover a working forward strategy by trial
                    for cand in STEP_STRATEGIES:
                        try:
                            self.page.evaluate(cand)
                        except Exception:
                            continue
                        if advance:
                            advance(0.15)
                        try:
                            new = self.active_index()
                        except Exception:
                            return False
                        if new != cur:
                            self._step_js = cand
                            if new == index:
                                return True
                            break
                    else:
                        return False       # nothing moved the deck
                    continue
            try:
                self.page.evaluate(js)
            except Exception:
                self._step_js = None
                continue
            if advance:
                advance(0.15)
        try:
            return self.active_index() == index
        except Exception:
            return False

    def restart_animations(self, index: int) -> bool:
        """Restart every animation inside slide `index` (CSS keyframes,
        reveals and WAAPI), as if the slide were visited fresh.

        Called at capture start so entrance animations play in the video
        for every slide — slide 1's animations otherwise already ran
        during the page load and would appear finished.
        """
        try:
            return bool(self.page.evaluate(RESTART_ANIM_JS, index))
        except Exception:
            return False

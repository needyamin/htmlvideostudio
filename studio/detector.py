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

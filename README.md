# HTML Video Studio

Turn **any animated HTML page** into a high-quality **HD / Full-HD / 4K MP4 video** — no coding required.

---

## Quick start (3 steps)

1. **Double-click `Start Studio.bat`**
   The app window opens. On the very first run it automatically installs
   everything it needs (Python packages + browser engine, ~1–2 minutes).
2. **Choose your HTML file** (and optionally a narration script `.txt`
   for text-to-speech — use *Play sample* to preview the voice).
3. **Press `Export video`** and wait. When it finishes, the MP4 appears
   next to your HTML file — press `Open output folder` to find it.

> Requirements: Windows with **Python 3.10+** installed
> (tick *“Add python.exe to PATH”* during install).
> Everything else is installed automatically.

---

## What the settings do

| Setting | Meaning |
|---|---|
| **Resolution** | Output video size — shown as clickable boxes drawn to real scale: 720p / 1080p (default) / 1440p / **4K** |
| **Quality** | Compression quality: Normal / High / **Best**. Higher = sharper text, bigger file |
| **Seconds / slide** | Used for slides without narration (default 8s); narrated slides follow the voiceover instead |
| **Voiceover script** | A `.txt` narration script — converted to speech and matched slide-by-slide (see below) |
| **TTS voice** | Voice for the script: *Auto* matches each slide's language (English / Bangla), or pick a specific voice. **Play sample** previews it |
| FPS *(advanced)* | Frames per second: 24 (cinematic) / 30 (default) / 60 (smoothest) |
| Slide selector *(advanced)* | CSS selector for slides. Leave empty for auto-detect (`.slide`, `[data-slide]`, …) |

**No slides in your HTML?** The app detects that and exports one continuous
clip of your page instead — nothing breaks.

---

## Voiceover from text (text-to-speech)

Write (or generate) a narration script as a plain `.txt` file — one block
per slide:

```
[[SLIDE 1]]
Welcome to the presentation. Today we will ...

[[SLIDE 2]]
The architecture has three parts ...
```

Pick it as **Voiceover script** and press Export. The app:

1. Splits the script by the `[[SLIDE n]]` markers and matches block *n*
   to slide *n* of your HTML.
2. Converts each block to natural speech (free Microsoft neural voices —
   no API key needed; internet required).
3. **Times every slide to its narration** — the slide switches shortly
   after the voice finishes, and the narration starts exactly when the
   slide appears.

The *Auto* voice reads English blocks with an English voice and Bangla
blocks with a Bangla voice (bn-BD), so one deck can mix languages.
A full example is in [`samples/english.txt`](samples/english.txt)
(English) and [`samples/bangla.txt`](samples/bangla.txt) (Bangla).
Slides without a matching block fall back to *Seconds per slide*.

---

## How it works (for the curious)

The app opens your HTML in a headless Chromium browser, **pauses the page's
internal clock and advances it frame by frame**, taking a perfect screenshot
of every frame. That means *every* animation is captured — CSS transitions,
JavaScript canvas drawing, typing effects, anything — at exact timing,
regardless of how fast your computer is. Identical frames are automatically
skipped to make rendering faster, and the result is encoded to H.264 MP4
(playable everywhere) with optional AAC voiceover audio.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| “Python was not found” / window doesn't open | Install Python 3.10+ from python.org, tick *Add to PATH*, then run again. (The launcher auto-picks any installed Python that supports the GUI.) |
| Setup fails / download errors | Check your internet connection and re-run. |
| 4K export is slow | 4K renders are heavy — try 1080p, or reduce FPS to 24. |
| Export fails with a browser error | Check `studio_error.log` next to `studio.pyw`, make sure antivirus isn't blocking Python, retry. |
| Wrong slides detected | Set *Slide selector* in Advanced to your deck's selector (e.g. `.my-slide`). |

Files: `studio/` (program code) · `samples/demo.html` (test presentation —
export it first to see everything working) · `studio.pyw` + `Start Studio.bat` (launcher).

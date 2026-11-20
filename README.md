# 🎬 HTML Video Studio

Turn **any animated HTML page** into a high-quality **HD / Full-HD / 4K MP4 video** — no coding required.

> বাংলা: যেকোনো অ্যানিমেটেড HTML প্রেজেন্টেশন থেকে কোডিং ছাড়াই HD বা 4K ভিডিও বানান।

---

## Quick start (3 steps)

1. **Double-click `Start Studio.bat`**
   The app window opens. On the very first run it automatically installs
   everything it needs (Python packages + browser engine, ~1-2 minutes).
2. **Choose your HTML file** (and optionally a voiceover audio file).
3. **Press `🎬 Export video`** and wait. When it finishes, the MP4 appears
   next to your HTML file — press `Open output folder` to find it.

> Requirements: Windows with **Python 3.10+** installed
> (tick *“Add python.exe to PATH”* during install).
> Everything else is installed automatically.

বাংলা গাইড:
1. `Start Studio.bat`-এ ডাবল ক্লিক করুন — প্রথমবার চালালে সব দরকারি জিনিস নিজে থেকেই ইনস্টল হবে।
2. আপনার HTML ফাইলটি নির্বাচন করুন (চাইলে ভয়েসওভার অডিওও দিতে পারেন)।
3. `Export video` চাপুন — ভিডিও তৈরি হয়ে HTML ফাইলের পাশেই সেভ হবে।

---

## What the settings do

| Setting | Meaning |
|---|---|
| **Resolution** | Output video quality: 720p / 1080p / 1440p / **4K** |
| **Quality** | Compression quality: Normal / High / **Best** (file size grows) |
| **Seconds per slide** | Each slide switches automatically after this many seconds (default 8s) |
| **Voiceover** | Optional audio mixed into the video (trimmed to the video length) |
| FPS *(advanced)* | Frames per second: 24 (cinematic) / 30 (default) / 60 (smoothest) |
| Slide selector *(advanced)* | CSS selector for slides. Leave empty for auto-detect (`.slide`, `[data-slide]`, …) |

**No slides in your HTML?** The app detects that and exports one continuous
clip of your page instead — nothing breaks.

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

# proximity.

**YouTube downloader. MP4 or MP3. No browser, no account, no BS.**

Download videos, music, and entire playlists from YouTube and YouTube Music — up to 4K video or 320kbps audio — through a clean desktop GUI.

---

## features

- MP4 downloads up to 4K (via yt-dlp format selection)
- MP3 extraction at 320 / 256 / 192 / 128 kbps
- YouTube Music support
- **Parallel downloads** — run 1–6 downloads at once (default 4), each with its own live progress bar, speed and ETA
- **Paste multiple links** — separated by spaces, commas or newlines; each becomes its own queue entry
- Multiple playlists downloading simultaneously
- Playlist downloads — auto-organized into a folder named after the playlist, real song names, no `01 -` prefixes, no underscores
- Live quality selection — fetches available resolutions before you download
- Video preview with thumbnail (title, channel, duration) before committing
- **Embedded metadata** — title, artist, album, cover art written into the file
- **Synced lyrics** — time-synced `.lrc` files via lrclib.net (MP3 mode)
- Saves to your **Downloads folder by default** (registry-aware on Windows, always browseable)
- Log output so you can see exactly what's happening
- No account, no API key, no browser extension

---

## getting started

### option 1 — download the app

Grab the latest release from the [releases page](https://github.com/nithilan-manivannan/proximity/releases/latest):

| Platform | File |
|----------|------|
| Windows  | `proximity.exe` |
| macOS    | `proximity` |

Just run it — yt-dlp and ffmpeg are bundled.

### option 2 — run from source

**requirements:**
- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (on PATH or in the same folder)
- [ffmpeg](https://ffmpeg.org/download.html) (required for MP3 and merged MP4)

```bash
git clone https://github.com/nithilan-manivannan/proximity
cd proximity
pip install -r requirements.txt
python app.py
```

---

## usage

1. Paste a YouTube or YouTube Music URL (or a bunch of them at once)
2. Hit **look up** — Proximity fetches the title, channel, duration, thumbnail and available qualities
3. Pick your format (MP4 or MP3) and quality
4. Toggle **embed metadata & cover art** (on by default) and **synced lyrics** (MP3 mode)
5. Set **downloads at once** (1–6) if you want more or less parallelism
6. Choose where to save (defaults to your Downloads folder)
7. Hit **download** — queue as many as you like, they run in parallel with per-item progress

Playlist URLs are detected automatically and saved into a named subfolder. Keep pasting links — new downloads queue up while others are running.

---

## dependencies

| Dependency | Purpose |
|------------|---------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Core downloading engine |
| [ffmpeg](https://ffmpeg.org/) | Audio extraction, video merging, metadata embedding |
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | GUI framework |
| [lrclib.net](https://lrclib.net) | Synced lyrics API (no key needed) |

---

## building from source

Binaries are built with PyInstaller via GitHub Actions when a release is created.

To build locally:

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name proximity app.py
```

The bundled `yt-dlp` and `ffmpeg` binaries are included automatically if placed in the project root before building (handled by the CI workflow).

---

## license

MIT — see [LICENSE](LICENSE).

# proximity.

**YouTube downloader. MP4 or MP3. No browser, no account, no BS.**

Download videos, music, and entire playlists from YouTube and YouTube Music — up to 4K video or 320kbps audio — through a clean desktop GUI.

---

## features

- MP4 downloads up to 4K (via yt-dlp format selection)
- MP3 extraction at 320 / 256 / 192 / 128 kbps
- YouTube Music support
- Playlist downloads (auto-organized into folders)
- Live quality selection — fetches available resolutions before you download
- Video preview (title, channel, duration) before committing
- **Embedded metadata** — title, artist, album, cover art written into the file
- **Synced lyrics** — time-synced `.lrc` files via lrclib.net (MP3 mode)
- Download progress bar with percentage
- Log output so you can see exactly what's happening
- No account, no API key, no browser extension

---

## getting started

### option 1 — download the app

Grab the latest release from the [releases page](https://github.com/nithilan-alt-f4/proximity/releases/latest):

| Platform | File |
|----------|------|
| Windows  | `proximity.exe` |
| macOS    | `proximity` |

Just run it — yt-dlp and ffmpeg are bundled.

### option 2 — run from source

**requirements:**
- Python 3.9+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (on PATH or in the same folder)
- [ffmpeg](https://ffmpeg.org/download.html) (required for MP3 and merged MP4)

```bash
git clone https://github.com/nithilan-alt-f4/proximity
cd proximity
pip install customtkinter
python ytdl.py
```

---

## usage

1. Paste a YouTube or YouTube Music URL into the input field
2. Hit **look up** — Proximity fetches the title, channel, duration, and available qualities
3. Pick your format (MP4 or MP3) and quality
4. Toggle **embed metadata & cover art** (on by default) and **synced lyrics** (MP3 mode)
5. Choose where to save (defaults to a `downloads/` folder next to the script)
6. Hit **download**

Playlist URLs are detected automatically and saved into a named subfolder.

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

Binaries are built with PyInstaller via GitHub Actions on push to `main`.

To build locally:

```bash
pip install pyinstaller customtkinter
pyinstaller --onefile --noconsole --name proximity ytdl.py
```

The bundled `yt-dlp` and `ffmpeg` binaries are included automatically if placed in the project root before building (handled by the CI workflow).

---

## license

MIT

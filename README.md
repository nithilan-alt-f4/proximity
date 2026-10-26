# proximity

**YouTube downloader for Windows. MP4 or MP3, with parallel queueing, synced lyrics, and embedded artwork. No browser, no account, no API keys.**

Drop in one or many YouTube or YouTube Music links, pick a format and quality, and proximity downloads them in parallel with per item progress. Playlists land in their own named folder with real track names. MP3 exports come with title, artist, album, and cover art embedded, plus an optional time synced `.lrc` lyric file saved alongside.

## Features

- **Parallel downloads**: run up to six downloads at once (default four), each with its own live progress bar, speed, and ETA. Keep pasting links while the queue drains.
- **Multi link input**: paste several URLs in one go, separated by spaces, commas, or newlines. Each becomes its own queue entry.
- **MP4 up to 4K**: format selection is delegated to yt-dlp, so every adaptive quality YouTube serves is available.
- **MP3 extraction**: 320, 256, 192, or 128 kbps, produced with ffmpeg.
- **Video preview**: before downloading, the app fetches title, channel, duration, thumbnail, and the list of available resolutions.
- **Playlist handling**: playlist URLs are detected automatically and saved into a folder named after the playlist, with clean track names: no `01 -` prefixes and no underscore soup.
- **Metadata and artwork**: toggled by default: title, artist, album, and cover art are written into the file by ffmpeg while it works.
- **Synced lyrics**: fetches line by line `.lrc` pairs from the LRCLIB API in MP3 mode. No key needed.
- **Smart save folder**: defaults to your real Downloads folder, read through the Windows registry so OneDrive redirections and custom locations are honored. Always overridable with a browse dialog.
- **Log panel**: the raw yt-dlp and ffmpeg output is visible so nothing happens invisibly.

## Usage

1. Paste one or more YouTube or YouTube Music URLs.
2. Press the lookup button. Proximity fetches the thumbnail, title, channel, duration, and available qualities.
3. Pick MP4 or MP3 and the quality, decide whether to embed metadata, artwork, and synced lyrics.
4. Choose how many downloads run at once (one through six).
5. Set the save folder, or leave it at Downloads.
6. Press download. The queue runs in parallel and accepts more links while it works.

## Getting started

### Option 1, release build

Grab the latest exe from the releases page. yt-dlp and ffmpeg ship inside it.

| Platform | File |
|---|---|
| Windows | `proximity.exe` |

### Option 2, run from source

Requirements: Python 3.10+, yt-dlp on PATH (or sitting next to `app.py`), and ffmpeg (required for MP3 and merged MP4).

```bash
git clone https://github.com/nithilan-manivannan/proximity
cd proximity
pip install -r requirements.txt
python app.py
```

## How it works

- The interface is CustomTkinter on dark mode, with a Pillow based thumbnail preview when Pillow is present. Everything degrades gracefully if Pillow is missing.
- Behind the GUI, proximity shells out to `yt-dlp` for download logic and `ffmpeg` for audio extraction, merging, and metadata. Both are resolved at runtime in three places: the PyInstaller bundle directory, the project folder, then PATH.
- URLs are cleaned before use: track parameters are stripped, youtu.be short links are normalized, and playlist links are routed into playlist mode.
- Progress comes from yt-dlp's progress output then is fed into per item bars updated from worker threads via Tkinter's `after` scheduling.
- Lyrics: the metadata clean title is matched against LRCLIB's public API; a matching pair saves as `track.lrc` next to the MP3.
- Windows console flashes are suppressed for child processes, so the app stays quiet on screen and in the margins.

## Dependencies

| Dependency | Role |
|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Core download engine |
| [ffmpeg](https://ffmpeg.org/) | Audio extraction, merging, metadata writing |
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | Interface |
| [Pillow](https://python-pillow.org/) | Thumbnail rendering (optional, recommended) |
| [LRCLIB](https://lrclib.net/) | Synced lyrics, free and keyless |

## Building from source

Release artifacts are built with PyInstaller through GitHub Actions whenever a release is created. The workflow bundles `yt-dlp.exe` and `ffmpeg.exe` into the exe automatically.

To build on your own machine:

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name proximity --add-binary "yt-dlp.exe;." --add-binary "ffmpeg.exe;." app.py
```

## Repository structure

```
proximity/
├── app.py                # interface and downloader logic
├── index.html            # landing page
├── requirements.txt      # customtkinter, Pillow, yt-dlp
├── LICENSE               # MIT
└── .github/workflows/build.yml
```

## License

MIT, see [LICENSE](LICENSE).

#!/usr/bin/env python3
"""
proximity — YouTube downloader GUI  (vintage edition)
pip install customtkinter pillow

Vintage look restored (v1.0.1 era): lime accent on black, rounded cards,
Courier New + Segoe UI, lowercase buttons.
Features kept/added on top: thumbnail preview, embedded metadata + cover art,
synced lyrics (.lrc via lrclib.net), parallel downloads, default save folder
= the user's Downloads folder.
"""

import json, os, re, sys, subprocess, urllib.parse, urllib.request, threading, tempfile, platform
from pathlib import Path
from collections import deque
from tkinter import filedialog
import customtkinter as ctk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── design tokens (v1.0.1 vintage palette) ───────────────────────────────────

BG      = "#0d0d0d"
CARD    = "#1a1a1a"
BORDER  = "#2a2a2a"
ACCENT  = "#c8f557"
ACCENTD = "#a8d93a"
MUTED   = "#555555"
TEXT    = "#ebebeb"
RED     = "#ff5555"
YELLOW  = "#e3b341"
MONO    = "Courier New"
SANS    = "Segoe UI"

NO_WINDOW = dict(creationflags=0x08000000) if platform.system() == "Windows" else {}

LRCLIB_BASE  = "https://lrclib.net/api"
LYRICS_MARKER = "LYRICSPATH::"

MAX_PARALLEL = 6   # hard cap for safety (rate limits)

# ── backend ──────────────────────────────────────────────────────────────────

def find_ytdlp():
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        for name in ["yt-dlp.exe", "yt-dlp"]:
            p = Path(bundle) / name
            if p.exists():
                return str(p)
    for name in ["yt-dlp.exe", "yt-dlp"]:
        local = Path(__file__).parent / name
        if local.exists():
            return str(local)
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True, **NO_WINDOW)
        return "yt-dlp"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

def check_ffmpeg():
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        for name in ["ffmpeg.exe", "ffmpeg"]:
            p = Path(bundle) / name
            if p.exists():
                os.environ["PATH"] = str(bundle) + os.pathsep + os.environ.get("PATH", "")
                return True
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, **NO_WINDOW)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def default_downloads_dir():
    """The user's Downloads folder (relocation- and OneDrive-aware on Windows)."""
    if platform.system() == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            guid = "{374DE290-123F-4565-9164-39C4925E467B}"  # shell:Downloads
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                val, _ = winreg.QueryValueEx(k, guid)
                val = os.path.expandvars(val)
                if val and Path(val).is_dir():
                    return str(Path(val))
        except Exception:
            pass
    home = Path.home() / "Downloads"
    if home.is_dir():
        return str(home)
    return str(Path.home())

def clean_url(url):
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname == "music.youtube.com":
            return url
        if parsed.hostname == "youtu.be":
            vid = parsed.path.lstrip("/").split("?")[0]
            return f"https://www.youtube.com/watch?v={vid}"
        qs = urllib.parse.parse_qs(parsed.query)
        if "list" in qs and "v" not in qs:
            return url
        cq = {k: v for k, v in qs.items() if k == "v"}
        c = parsed._replace(query=urllib.parse.urlencode(cq, doseq=True))
        return urllib.parse.urlunparse(c)
    except Exception:
        return url

def is_playlist(url):
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return "list" in qs and "v" not in qs
    except Exception:
        return False

def fetch_info(ytdlp, url):
    """Fetch video info including thumbnail URL via --dump-json."""
    r = subprocess.run(
        [ytdlp, "--no-warnings", "--dump-json", "--playlist-items", "1", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        **NO_WINDOW
    )
    if r.stdout.strip():
        try:
            data = json.loads(r.stdout.strip().splitlines()[0])
            return {
                "title":    data.get("title", "Unknown"),
                "channel":  data.get("channel") or data.get("uploader", ""),
                "duration": data.get("duration_string") or str(data.get("duration", "")),
                "thumbnail": data.get("thumbnail", ""),
            }
        except (json.JSONDecodeError, IndexError):
            pass
    r2 = subprocess.run(
        [ytdlp, "--no-warnings", "--print",
         "%(title)s\n%(channel)s\n%(duration_string)s",
         "--playlist-items", "1", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        **NO_WINDOW
    )
    lines = r2.stdout.strip().splitlines()
    if not lines or not lines[0]:
        raise RuntimeError(r2.stderr[:300] or "Could not fetch video info")
    return {
        "title":    lines[0],
        "channel":  lines[1] if len(lines) > 1 else "",
        "duration": lines[2] if len(lines) > 2 else "",
        "thumbnail": "",
    }

def fetch_qualities(ytdlp, url, ffmpeg):
    r = subprocess.run(
        [ytdlp, "--list-formats", "--no-warnings", "--playlist-items", "1", url],
        capture_output=True, text=True, **NO_WINDOW
    )
    heights = set()
    for line in r.stdout.splitlines():
        m = re.search(r'\b(\d{3,4})p\b', line)
        if m:
            if not ffmpeg and ("video only" in line.lower() or "audio only" in line.lower()):
                continue
            heights.add(int(m.group(1)))
    return sorted(heights, reverse=True)

def download_thumbnail(url, dest_path):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            with open(dest_path, "wb") as f:
                f.write(resp.read())
        return True
    except Exception:
        return False

# ── lyrics (lrclib.net) ──────────────────────────────────────────────────────

def _lrclib_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "proximity-ytdl/2.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_synced_lyrics(track_name, artist_name, album_name=None, duration=None):
    params = {"track_name": track_name, "artist_name": artist_name}
    if album_name:
        params["album_name"] = album_name
    if duration:
        params["duration"] = str(int(duration))
    try:
        data = _lrclib_get(f"{LRCLIB_BASE}/get?{urllib.parse.urlencode(params)}")
        if data.get("syncedLyrics"):
            return data["syncedLyrics"]
    except Exception:
        pass
    try:
        q = urllib.parse.urlencode({"track_name": track_name, "artist_name": artist_name})
        for r in _lrclib_get(f"{LRCLIB_BASE}/search?{q}"):
            if r.get("syncedLyrics"):
                return r["syncedLyrics"]
    except Exception:
        pass
    return None

def save_lyrics(audio_path, lrc_text):
    lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
    with open(lrc_path, "w", encoding="utf-8") as f:
        f.write(lrc_text)
    return lrc_path

# ── GUI ──────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("proximity.")
        self.geometry("560x780")
        self.minsize(540, 640)
        self.configure(fg_color=BG)

        self.ytdlp   = find_ytdlp()
        self.ffmpeg  = check_ffmpeg()
        self.out_dir = default_downloads_dir()
        self._unlocked = False
        self._looking_up = False

        self._last_info = None
        self._last_qualities = None
        self._last_url = None
        self._thumb_img = None  # prevent GC

        # download queue state
        self._job_no = 0
        self._pending = deque()
        self._active = 0
        self._wlock = threading.Lock()
        self._rows = {}       # job_id -> {"bar":…, "status":…, "row":…}

        self._build()
        self.after(200, self._check_deps)

    # ── build ─────────────────────────────────────────────────────────────

    def _build(self):
        # header
        hdr = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="proximity.", font=(MONO, 22, "bold"),
                     text_color=ACCENT).pack(side="left", padx=20)
        self._dep_lbl = ctk.CTkLabel(hdr, text="", font=(MONO, 11),
                                     text_color=MUTED)
        self._dep_lbl.pack(side="right", padx=20)

        # bottom bar (always visible) — the big lime button
        bot = ctk.CTkFrame(self, fg_color=BG)
        bot.pack(fill="x", side="bottom", padx=20, pady=20)
        self._dl_btn = ctk.CTkButton(
            bot, text="\u2193  download", height=46,
            font=(MONO, 13, "bold"), fg_color=ACCENT,
            hover_color=ACCENTD, text_color=BG,
            corner_radius=8, command=self._start_download,
            state="disabled"
        )
        self._dl_btn.pack(fill="x")

        # scrollable body
        body = ctk.CTkScrollableFrame(self, fg_color=BG,
                                      scrollbar_button_color=BORDER)
        body.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        # ── url card ──────────────────────────────────────────────────────
        uc = self._card(body)
        ctk.CTkLabel(uc, text="URL", font=(MONO, 10),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(12, 4))
        row = ctk.CTkFrame(uc, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        self._url_var = ctk.StringVar()
        self._url_entry = ctk.CTkEntry(
            row, textvariable=self._url_var,
            placeholder_text="https://youtu.be/...  \u00b7  multiple links = multiple downloads",
            font=(MONO, 12), height=40, fg_color=BG,
            border_color=BORDER, border_width=1,
            text_color=TEXT, placeholder_text_color=MUTED, corner_radius=8
        )
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._url_entry.bind("<Return>", lambda e: self._lookup())

        self._look_btn = ctk.CTkButton(
            row, text="look up", width=88, height=40,
            font=(MONO, 12, "bold"), fg_color=ACCENT,
            hover_color=ACCENTD, text_color=BG,
            corner_radius=8, command=self._lookup
        )
        self._look_btn.pack(side="right")

        # ── preview card (hidden until a lookup succeeds) ─────────────────
        self._prev_card = self._card(body)
        self._prev_title = ctk.CTkLabel(
            self._prev_card, text="", font=(SANS, 13, "bold"),
            text_color=TEXT, wraplength=480, justify="left", anchor="w")
        self._prev_title.pack(anchor="w", padx=16, pady=(14, 2))
        self._prev_meta = ctk.CTkLabel(
            self._prev_card, text="", font=(MONO, 11),
            text_color=MUTED, anchor="w")
        self._prev_meta.pack(anchor="w", padx=16, pady=(0, 12))
        self._prev_thumb = ctk.CTkLabel(self._prev_card, text="", height=10)
        self._prev_card.pack_forget()

        # ── options card (hidden until a lookup succeeds) ─────────────────
        self._opts_card = self._card(body)
        inner = ctk.CTkFrame(self._opts_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(1, weight=1)

        # format
        fl = ctk.CTkFrame(inner, fg_color="transparent")
        fl.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(fl, text="FORMAT", font=(MONO, 10),
                     text_color=MUTED).pack(anchor="w")
        self._fmt_var = ctk.StringVar(value="mp4")
        self._fmt_seg = ctk.CTkSegmentedButton(
            fl, values=["mp4", "mp3"],
            variable=self._fmt_var, command=self._on_fmt,
            font=(MONO, 12, "bold"), height=38,
            fg_color=BORDER,
            selected_color=ACCENT, selected_hover_color=ACCENTD,
            unselected_color=BORDER, unselected_hover_color="#333",
            text_color=BG, corner_radius=8
        )
        self._fmt_seg.pack(fill="x", pady=(6, 0))

        # quality
        ql = ctk.CTkFrame(inner, fg_color="transparent")
        ql.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ctk.CTkLabel(ql, text="QUALITY", font=(MONO, 10),
                     text_color=MUTED).pack(anchor="w")
        self._q_var = ctk.StringVar(value="\u2014")
        self._q_menu = ctk.CTkOptionMenu(
            ql, variable=self._q_var, values=["\u2014"],
            font=(MONO, 12), dropdown_font=(MONO, 12), height=38,
            fg_color=BG, button_color=BORDER, button_hover_color="#333",
            text_color=TEXT, corner_radius=8
        )
        self._q_menu.pack(fill="x", pady=(6, 0))

        # checkbox: embed metadata + cover art
        self._meta_var = ctk.BooleanVar(value=True)
        self._meta_chk = ctk.CTkCheckBox(
            inner, text="embed metadata  \u00b7  title, artist, cover art",
            variable=self._meta_var, onvalue=True, offvalue=False,
            font=(MONO, 11), fg_color=ACCENT, hover_color=ACCENTD,
            text_color=TEXT, border_color=BORDER,
            checkbox_width=18, checkbox_height=18, corner_radius=4
        )
        self._meta_chk.grid(row=1, column=0, columnspan=2, sticky="w", pady=(14, 0))

        # checkbox: synced lyrics
        self._lyrics_var = ctk.BooleanVar(value=False)
        self._lyrics_chk = ctk.CTkCheckBox(
            inner, text="synced lyrics  \u00b7  time-synced .lrc file  (mp3 only)",
            variable=self._lyrics_var, onvalue=True, offvalue=False,
            font=(MONO, 11), fg_color=ACCENT, hover_color=ACCENTD,
            text_color=TEXT, border_color=BORDER,
            checkbox_width=18, checkbox_height=18, corner_radius=4
        )
        self._lyrics_chk.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # parallel downloads
        prow = ctk.CTkFrame(inner, fg_color="transparent")
        prow.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ctk.CTkLabel(prow, text="DOWNLOADS AT ONCE", font=(MONO, 10),
                     text_color=MUTED).pack(side="left")
        self._parallel_var = ctk.StringVar(value="4")
        self._parallel_menu = ctk.CTkOptionMenu(
            prow, variable=self._parallel_var,
            values=[str(i) for i in range(1, MAX_PARALLEL + 1)],
            font=(MONO, 11), dropdown_font=(MONO, 11), height=30, width=80,
            fg_color=BG, button_color=BORDER, button_hover_color="#333",
            text_color=TEXT, corner_radius=8,
            command=lambda _=None: self._spawn_workers()
        )
        self._parallel_menu.pack(side="right")

        self._opts_card.pack_forget()

        # ── save-to card (hidden until a lookup succeeds) ─────────────────
        self._fold_card = self._card(body)
        ctk.CTkLabel(self._fold_card, text="SAVE TO", font=(MONO, 10),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(12, 4))
        frow = ctk.CTkFrame(self._fold_card, fg_color="transparent")
        frow.pack(fill="x", padx=16, pady=(0, 14))
        self._fold_lbl = ctk.CTkLabel(
            frow, text=self.out_dir, font=(MONO, 10),
            text_color=MUTED, anchor="w", wraplength=400)
        self._fold_lbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            frow, text="browse", width=76, height=30,
            font=(MONO, 11), fg_color=BORDER,
            hover_color="#333", text_color=TEXT,
            corner_radius=6, command=self._browse
        ).pack(side="right", padx=(8, 0))
        self._fold_card.pack_forget()

        # ── downloads card (always visible) ───────────────────────────────
        qc = self._card(body)
        qhead = ctk.CTkFrame(qc, fg_color="transparent")
        qhead.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(qhead, text="DOWNLOADS", font=(MONO, 10),
                     text_color=MUTED).pack(side="left")
        self._queue_cnt = ctk.CTkLabel(qhead, text="", font=(MONO, 9),
                                        text_color=MUTED)
        self._queue_cnt.pack(side="right")
        self._queue_inner = ctk.CTkFrame(qc, fg_color="transparent")
        self._queue_inner.pack(fill="x", padx=16, pady=(8, 12))
        self._queue_empty = ctk.CTkLabel(self._queue_inner,
                                          text="nothing in the queue yet",
                                          font=(MONO, 10), text_color=MUTED)
        self._queue_empty.pack(anchor="w")

        # ── log card ──────────────────────────────────────────────────────
        lc = self._card(body)
        ctk.CTkLabel(lc, text="LOG", font=(MONO, 10),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(12, 4))
        self._log_box = ctk.CTkTextbox(
            lc, font=(MONO, 11), fg_color=CARD,
            text_color="#888", wrap="word",
            border_width=0, height=150,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#333"
        )
        self._log_box.pack(fill="x", padx=8, pady=(0, 8))
        self._log_box.configure(state="disabled")

    def _card(self, parent):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        f.pack(fill="x", pady=(0, 12))
        return f

    # ── deps ──────────────────────────────────────────────────────────────

    def _check_deps(self):
        parts = []
        if self.ytdlp:
            parts.append("yt-dlp \u2713")
        else:
            parts.append("yt-dlp \u2717")
            self._log("\u2717 yt-dlp.exe not found \u2014 put it in the same folder as this script")
        if self.ffmpeg:
            parts.append("ffmpeg \u2713")
        else:
            parts.append("ffmpeg \u2717 (MP3 unavailable)")
            self._log("\u26a0 ffmpeg not found \u2014 MP3 disabled")
        self._dep_lbl.configure(text="  \u00b7  ".join(parts))

    # ── ui helpers ────────────────────────────────────────────────────────

    def _log(self, msg):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _set_busy(self, busy):
        s = "disabled" if busy else "normal"
        self._look_btn.configure(state=s)
        if busy:
            self._look_btn.configure(text="looking...")
        else:
            self._look_btn.configure(text="look up")

    def _on_fmt(self, val):
        if val == "mp3":
            self._q_menu.configure(values=["320kbps", "256kbps", "192kbps", "128kbps"],
                                   state="normal", fg_color=BG, text_color=TEXT)
            self._q_var.set("320kbps")
            self._lyrics_chk.configure(state="normal")
        else:
            cur = self._q_menu.cget("values")
            if cur and "kbps" in cur[0]:
                self._q_menu.configure(values=["\u2014"])
                self._q_var.set("\u2014")
            self._q_menu.configure(state="normal", fg_color=BG, text_color=TEXT)
            self._lyrics_var.set(False)
            self._lyrics_chk.configure(state="disabled")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.out_dir)
        if d:
            self.out_dir = d
            self._fold_lbl.configure(text=d)

    def _unlock(self):
        if not self._unlocked:
            self._prev_card.pack(fill="x", pady=(0, 12))
            self._opts_card.pack(fill="x", pady=(0, 12))
            self._fold_card.pack(fill="x", pady=(0, 12))
            self._unlocked = True
        self._dl_btn.configure(state="normal")

    # ── preview ───────────────────────────────────────────────────────────

    def _lookup(self):
        if not self.ytdlp:
            self._log("\u2717 yt-dlp not found"); return
        if self._looking_up:
            return
        url = self._url_var.get().strip()
        if not url: return
        url = clean_url(url)
        self._url_var.set(url)
        self._looking_up = True
        self._set_busy(True)
        self._log(f"\n\u2192 looking up {url}")
        threading.Thread(target=self._lookup_bg, args=(url,), daemon=True).start()

    def _lookup_bg(self, url):
        try:
            info = fetch_info(self.ytdlp, url)
            qs = [] if is_playlist(url) else fetch_qualities(self.ytdlp, url, self.ffmpeg)
            self._ui(self._lookup_done, info, qs, url)
        except Exception as e:
            self._ui(self._log, f"\u2717 {e}")
            self._ui(self._lookup_failed)

    def _lookup_failed(self):
        self._looking_up = False
        self._set_busy(False)

    def _lookup_done(self, info, qualities, url):
        self._looking_up = False
        self._set_busy(False)
        self._last_info = info
        self._last_qualities = qualities
        self._last_url = url

        # preview text
        meta = f"{info['channel']}  \u00b7  {info['duration']}"
        if is_playlist(url):
            meta += "  \u00b7  playlist"
        self._prev_meta.configure(text=meta)

        if qualities:
            vals = [f"{q}p" for q in qualities]
            self._q_menu.configure(values=vals)
            self._q_var.set(vals[0])
        else:
            self._q_menu.configure(values=["best"])
            self._q_var.set("best")

        # quality dropdown must respect current fmt (mp3 → kbps list)
        self._on_fmt(self._fmt_var.get())

        self._unlock()
        self._log(f"\u2713 {info['title']}  [{info['duration']}]")

        # thumbnail (background)
        thumb_url = info.get("thumbnail", "")
        if thumb_url and HAS_PIL:
            threading.Thread(target=self._thumb_bg, args=(thumb_url,), daemon=True).start()
        else:
            self._thumb_img = None
            self._prev_thumb.configure(image=None, text="", height=10)

    def _thumb_bg(self, url):
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        if download_thumbnail(url, tmp.name):
            self._ui(self._thumb_done, tmp.name)
        else:
            try: os.unlink(tmp.name)
            except OSError: pass

    def _thumb_done(self, path):
        try:
            img = Image.open(path).convert("RGB")
            target_w = 500
            ratio = target_w / img.width
            target_h = int(img.height * ratio)
            img = img.resize((target_w, target_h), Image.LANCZOS)
            self._thumb_img = ctk.CTkImage(light_image=img, dark_image=img,
                                           size=(target_w, target_h))
            self._prev_thumb.configure(image=self._thumb_img, text="")
            self._prev_below_thumb()
        except Exception:
            pass

    def _prev_below_thumb(self):
        # make sure the thumbnail label sits above the title (repack order)
        self._prev_thumb.pack_forget()
        self._prev_thumb.pack(fill="x", padx=16, pady=(12, 4))
        self._prev_title.pack_forget()
        self._prev_title.pack(anchor="w", padx=16, pady=(0, 2))
        self._prev_meta.pack_forget()
        self._prev_meta.pack(anchor="w", padx=16, pady=(4, 12))

    # ── download queue ────────────────────────────────────────────────────

    def _start_download(self):
        raw = self._url_var.get()
        urls = []
        for chunk in re.split(r'[\s,]+', raw):
            c = chunk.strip()
            if not c:
                continue
            if not c.startswith("http"):
                c = "https://" + c
            urls.append(clean_url(c))
        urls = list(dict.fromkeys(urls))  # de-dupe, keep order
        if not urls:
            self._log("\u2717 nothing to download \u2014 paste a url first")
            return
        fmt = self._fmt_var.get()
        qual = self._q_var.get()

        if fmt == "mp3" and not self.ffmpeg:
            self._log("\u2717 MP3 requires ffmpeg"); return

        want_meta  = self._meta_var.get()
        want_lyrics = (fmt == "mp3") and self._lyrics_var.get()
        out = self.out_dir

        Path(out).mkdir(parents=True, exist_ok=True)

        for url in urls:
            playlist = is_playlist(url)

            # no numbering, no underscores — keep the real song name
            outtmpl = str(Path(out) / (
                "%(playlist_title)s/%(title)s.%(ext)s"
                if playlist else "%(title)s.%(ext)s"
            ))

            cmd = [self.ytdlp, "--no-warnings", "--newline", "--ignore-config",
                   "--windows-filenames", "-o", outtmpl]

            if fmt == "mp3":
                bitrate = qual.replace("kbps", "") if "kbps" in qual else "320"
                cmd += ["-x", "--audio-format", "mp3", "--audio-quality", bitrate]
            else:
                if qual in ("\u2014", "best", ""):
                    h = None
                else:
                    h = qual.replace("p", "")
                h = int(h) if (h and h.isdigit()) else 1080
                if self.ffmpeg:
                    fs = (f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                          f"/best[height<={h}][ext=mp4]/best")
                else:
                    fs = f"best[height<={h}][ext=mp4]/best[ext=mp4]/best"
                cmd += ["-f", fs, "--merge-output-format", "mp4"]

            if want_meta:
                cmd += ["--embed-metadata", "--embed-thumbnail"]

            if playlist:
                cmd += ["--yes-playlist"]

            if want_lyrics:
                cmd += [
                    "--print",
                    f"after_move:{LYRICS_MARKER}%(filepath)s::%(title)s::"
                    f"%(artist,creator,uploader,channel)s::%(duration)s",
                ]

            cmd.append(url)

            # job record
            self._job_no += 1
            job = {
                "id": self._job_no,
                "url": url,
                "fmt": fmt,
                "qual": qual,
                "playlist": playlist,
                "cmd": cmd,
                "out": out,
                "lyrics": want_lyrics,
                "title": (self._last_info["title"] if
                          (self._last_url == url and self._last_info) else url),
            }
            label = fmt.upper()
            if fmt == "mp4" and qual not in ("\u2014", "best"):
                label += f" @ {qual}"
            self._log(f"\n\u2192 queued #{job['id']}  {label}  \u2192  {out}")
            self._add_job_row(job)
            self._queue_upd()

            with self._wlock:
                self._pending.append(job)

        self._spawn_workers()

    def _spawn_workers(self):
        with self._wlock:
            limit = int(self._parallel_var.get())
            if self._active < limit and self._pending:
                self._active += 1
                threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            with self._wlock:
                if not self._pending:
                    self._active -= 1
                    return
                job = self._pending.popleft()
            self._run_job(job)

    def _queue_upd(self):
        with self._wlock:
            active = self._active
            queued = len(self._pending)
        txt = f"working {active}  \u00b7  queued {queued}"
        self._queue_cnt.configure(text=txt)

    # ── per-job rows ──────────────────────────────────────────────────────

    def _add_job_row(self, job):
        if self._queue_empty is not None:
            self._queue_empty.pack_forget()
            self._queue_empty = None
        row = ctk.CTkFrame(self._queue_inner, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))

        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        title = job["title"]
        if job["playlist"]:
            title += "  [playlist]"
        ctk.CTkLabel(top, text=title, font=(SANS, 12), text_color=TEXT,
                     anchor="w", wraplength=440, justify="left"
                     ).pack(side="left", fill="x", expand=True)
        st = ctk.CTkLabel(top, text="queued", font=(MONO, 9), text_color=MUTED)
        st.pack(side="right", padx=(8, 0))

        bar = ctk.CTkProgressBar(row, fg_color=BORDER, progress_color=ACCENT,
                                 height=6, corner_radius=3)
        bar.set(0)
        bar.pack(fill="x", pady=(6, 3))

        self._rows[job["id"]] = {"bar": bar, "status": st, "row": row}

    def _job_ui(self, job_id, status=None, color=None, pct=None):
        info = self._rows.get(job_id)
        if not info:
            return
        if status is not None:
            info["status"].configure(text=status, text_color=color or MUTED)
        if pct is not None:
            info["bar"].set(pct)
        self._queue_upd()

    # ── worker body ───────────────────────────────────────────────────────

    def _ui(self, fn, *args):
        """Safely hop back to the UI thread (no-op if the window is gone)."""
        try:
            self.after(0, fn, *args)
        except Exception:
            pass

    def _run_job(self, job):
        jb = f"#{job['id']}"
        pct_re = re.compile(r'\[download\]\s+([\d.]+)%')
        spd_re = re.compile(r'\b([\d.]+\s*[KMG]?i?B/s)', re.I)
        eta_re = re.compile(r'\bETA\W*(\d{1,2}:\d{2}(?::\d{2})?)')
        item_re = re.compile(r'\[download\] Downloading item (\d+) of (\d+)')
        lyric_targets = []
        self._ui(self._job_ui, job["id"], "connecting...", MUTED)
        try:
            proc = subprocess.Popen(
                job["cmd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                **NO_WINDOW
            )
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if line.startswith(LYRICS_MARKER):
                    payload = line[len(LYRICS_MARKER):]
                    parts = payload.split("::", 3)
                    if len(parts) == 4:
                        filepath, title, artist, dur = parts
                        try:
                            dur = int(float(dur))
                        except ValueError:
                            dur = None
                        lyric_targets.append((filepath, title, artist, dur))
                    continue
                m = item_re.search(line)
                if m:
                    self._ui(self._job_ui, job["id"],
                               f"item {m.group(1)}/{m.group(2)}", TEXT, None)
                    continue
                m = pct_re.search(line)
                if m:
                    pct = float(m.group(1)) / 100.0
                    extra = ""
                    ms = spd_re.search(line)
                    me = eta_re.search(line)
                    if ms:
                        extra += f"  \u00b7  {ms.group(1).replace(chr(32), '')}"
                    if me:
                        extra += f"  \u00b7  ETA {me.group(1)}"
                    self._ui(self._job_ui, job["id"],
                             f"downloading  {pct*100:4.1f}%{extra}", TEXT, pct)
                    continue
                self._ui(self._log, f"{jb}  {line}")

            proc.wait()

            if proc.returncode != 0:
                self._ui(self._job_ui, job["id"],
                           f"\u2717 failed (exit {proc.returncode})", RED, 0.0)
                self._ui(self._log,
                           f"{jb}  \u2717 download failed (exit {proc.returncode})")
                return

            self._ui(self._job_ui, job["id"], "processing...", YELLOW, 1.0)
            self._ui(self._log, f"{jb}  \u2713 saved to {job['out']}")

            # synced lyrics
            if job["lyrics"]:
                self._ui(self._job_ui, job["id"], "lyrics...", YELLOW, 1.0)
                found, missing = 0, 0
                for filepath, title, artist, dur in lyric_targets:
                    if not os.path.exists(filepath):
                        continue
                    try:
                        lrc = fetch_synced_lyrics(title, artist, duration=dur)
                        if lrc:
                            save_lyrics(filepath, lrc)
                            self._ui(self._log,
                                       f"{jb}  \u2713 lyrics: {Path(filepath).name}")
                            found += 1
                        else:
                            self._ui(self._log,
                                       f"{jb}  \u26a0 no synced lyrics: {title}")
                            missing += 1
                    except Exception as e:
                        self._ui(self._log,
                                   f"{jb}  \u26a0 lyrics failed: {title}: {e}")
                        missing += 1
                self._ui(self._log,
                           f"{jb}  \u2192 lyrics done: {found} found, {missing} missing")
                self._ui(self._job_ui, job["id"], "\u2713 saved + lyrics",
                           ACCENT, 1.0)
            else:
                self._ui(self._job_ui, job["id"], "\u2713 saved", ACCENT, 1.0)
        except Exception as e:
            self._ui(self._job_ui, job["id"], f"\u2717 {e}", RED, 0.0)
            self._ui(self._log, f"{jb}  \u2717 {e}")

if __name__ == "__main__":
    app = App()
    app.mainloop()

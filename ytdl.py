#!/usr/bin/env python3
"""
ytdl.py — Proximity  ·  YouTube downloader GUI
pip install customtkinter
"""

import json, os, re, sys, subprocess, urllib.parse, urllib.request, threading, platform, time, tempfile
from pathlib import Path
from tkinter import filedialog, Canvas
import customtkinter as ctk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── design tokens (control-room palette) ─────────────────────────────────────

BG       = "#090a0a"
SURFACE  = "#101212"
SURFACE2 = "#191b1b"
BORDER   = "#242625"
BORDERL  = "#242625"
PRIMARY  = "#c82a34"
PRIMARYH = "#db3440"
PRIMARYD = "#591c21"
GOLD     = "#d5a449"
GREEN    = "#80a079"
GREENL   = "#88ad7d"
TEXT     = "#e5e5df"
TEXT2    = "#dbdcd4"
MUTED    = "#737970"
DIM      = "#525951"
INPBG    = "#090b0b"
TERMBG   = "#070909"
TICKERBG = "#0c0e0e"
MONO     = "Consolas"
NO_WINDOW = dict(creationflags=0x08000000) if platform.system() == "Windows" else {}

LRCLIB_BASE  = "https://lrclib.net/api"
LYRICS_MARKER = "LYRICSPATH::"

TICKER_ITEMS = [
    "MP4 UP TO 4K", "MP3 320KBPS", "PLAYLISTS", "YOUTUBE MUSIC",
]
TICKER_STR = "  \u25c6  ".join(TICKER_ITEMS) + "  \u25c6  " + "  \u25c6  ".join(TICKER_ITEMS)

# ── backend ───────────────────────────────────────────────────────────────────

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
    # fallback to --print if --dump-json fails
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
    """Download a thumbnail image from a URL."""
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

# ── GUI ───────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("proximity")
        self.geometry("640x900")
        self.minsize(540, 700)
        self.configure(fg_color=BG)

        self.ytdlp   = find_ytdlp()
        self.ffmpeg  = check_ffmpeg()
        self.out_dir = str(Path(__file__).parent / "downloads")
        self._unlocked = False
        self._busy = False
        self._ticker_offset = 0
        self._last_info = None
        self._last_qualities = None
        self._last_url = None
        self._pct = 0.0
        self._thumb_path = None
        self._thumb_img = None  # prevent GC

        self._build()
        self.after(200, self._check_deps)
        self.after(600, self._start_ticker)
        self.after(1000, self._tick_clock)

    # ── build ─────────────────────────────────────────────────────────────

    def _build(self):
        # ── topbar ────────────────────────────────────────────────────────
        topbar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=64)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        brand = ctk.CTkFrame(topbar, fg_color="transparent")
        brand.pack(side="left", padx=(20, 0), fill="y")
        brand.pack_propagate(False)

        brand_row = ctk.CTkFrame(brand, fg_color="transparent")
        brand_row.pack(anchor="w", pady=(10, 0))

        # red square brand mark
        mark = ctk.CTkFrame(brand_row, fg_color=PRIMARY, width=30, height=30,
                            corner_radius=2)
        mark.pack(side="left", padx=(0, 10))
        mark.pack_propagate(False)
        ctk.CTkLabel(mark, text="\u25b6", font=(MONO, 12), text_color="#ffffff"
                     ).pack(expand=True)

        name_frame = ctk.CTkFrame(brand_row, fg_color="transparent")
        name_frame.pack(side="left")
        ctk.CTkLabel(name_frame, text="PROXIMITY", font=(MONO, 13, "bold"),
                     text_color="#fafaf2").pack(anchor="w")
        ctk.CTkLabel(name_frame, text="LOCAL MEDIA EXTRACTION CONSOLE",
                     font=(MONO, 7), text_color=MUTED).pack(anchor="w")

        # right side: status + clock
        right = ctk.CTkFrame(topbar, fg_color="transparent")
        right.pack(side="right", padx=20, fill="y")
        right.pack_propagate(False)

        stat_row = ctk.CTkFrame(right, fg_color="transparent")
        stat_row.pack(anchor="e", pady=(10, 0))

        # LED indicators
        self._led_ytdlp = self._make_led(stat_row, "yt-dlp")
        self._led_ffmpeg = self._make_led(stat_row, "ffmpeg")
        self._led_lrclib = self._make_led(stat_row, "lrclib")

        # clock
        self._clock_lbl = ctk.CTkLabel(stat_row, text="00:00:00",
                                         font=(MONO, 9), text_color=TEXT2)
        self._clock_lbl.pack(side="left", padx=(16, 0))

        # red accent line under topbar
        ctk.CTkFrame(self, fg_color=PRIMARY, corner_radius=0, height=2).pack(fill="x")

        # ── ticker ────────────────────────────────────────────────────────
        self._ticker_var = ctk.StringVar(value=TICKER_STR)
        ticker_frame = ctk.CTkFrame(self, fg_color=TICKERBG, corner_radius=0, height=28)
        ticker_frame.pack(fill="x")
        ticker_frame.pack_propagate(False)
        self._ticker_lbl = ctk.CTkLabel(
            ticker_frame, textvariable=self._ticker_var,
            font=(MONO, 8), text_color="#777d74", fg_color=TICKERBG,
            anchor="w"
        )
        self._ticker_lbl.pack(fill="both", expand=True)

        # ── scrollable body ───────────────────────────────────────────────
        body = ctk.CTkScrollableFrame(self, fg_color=BG, scrollbar_button_color=BORDER,
                                       scrollbar_button_hover_color="#2a2a2a")
        body.pack(fill="both", expand=True, padx=0, pady=(0, 0))

        # ── 01 SOURCE SIGNAL ──────────────────────────────────────────────
        self._panel(body, "01", "SOURCE SIGNAL", "INPUT REQUIRED",
                    note_color=PRIMARY, note_pulse=True)

        src_inner = ctk.CTkFrame(body, fg_color="transparent")
        src_inner.pack(fill="x", padx=18, pady=(0, 14))

        input_row = ctk.CTkFrame(src_inner, fg_color="transparent")
        input_row.pack(fill="x")

        self._url_var = ctk.StringVar()
        self._url_entry = ctk.CTkEntry(
            input_row, textvariable=self._url_var,
            placeholder_text="paste youtube url here...",
            font=(MONO, 11), height=40, fg_color=INPBG,
            border_color=BORDERL, border_width=1,
            text_color="#dadbd4", placeholder_text_color=MUTED,
            corner_radius=2
        )
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._url_entry.bind("<Return>", lambda e: self._lookup())

        self._look_btn = ctk.CTkButton(
            input_row, text="LOOK UP", width=100, height=40,
            font=(MONO, 9, "bold"), fg_color="#272a29",
            hover_color="#343735", text_color="#e3e4dc",
            corner_radius=2, command=self._lookup,
            cursor="hand2"
        )
        self._look_btn.pack(side="right")

        # hints
        hints = ctk.CTkFrame(src_inner, fg_color="transparent")
        hints.pack(fill="x", pady=(8, 0))
        for txt in ["YouTube", "Playlists", "No credentials required"]:
            ctk.CTkLabel(hints, text=f"\u2022 {txt}", font=(MONO, 8),
                         text_color="#666e65").pack(side="left", padx=(0, 16))

        # ── 02 SOURCE PREVIEW ─────────────────────────────────────────────
        self._prev_panel = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=2,
                                    border_width=1, border_color=BORDERL)
        self._prev_panel.pack(fill="x", padx=18, pady=(0, 14))

        self._panel_heading(self._prev_panel, "02", "SOURCE PREVIEW", "STANDBY")

        self._prev_body = ctk.CTkFrame(self._prev_panel, fg_color="transparent")
        self._prev_body.pack(fill="both", expand=True, padx=14, pady=14)

        # empty state
        self._prev_empty = ctk.CTkLabel(
            self._prev_body, text="no source resolved",
            font=(MONO, 9), text_color=DIM, anchor="center"
        )
        self._prev_empty.pack(expand=True)

        # populated state (hidden)
        self._prev_content = ctk.CTkFrame(self._prev_body, fg_color="transparent")

        # thumbnail display (using CTkImage for proper scaling)
        self._prev_thumb_label = ctk.CTkLabel(
            self._prev_content, text="", height=180,
            fg_color="#1a0a0c", corner_radius=2
        )
        self._prev_thumb_label.pack(fill="x", pady=(0, 10))

        self._prev_title = ctk.CTkLabel(
            self._prev_content, text="", font=(MONO, 13, "bold"),
            text_color=TEXT, anchor="w", wraplength=520, justify="left"
        )
        self._prev_title.pack(anchor="w")

        self._prev_channel = ctk.CTkLabel(
            self._prev_content, text="", font=(MONO, 9),
            text_color="#b7bbb2", anchor="w"
        )
        self._prev_channel.pack(anchor="w", pady=(4, 0))

        self._prev_meta = ctk.CTkLabel(
            self._prev_content, text="", font=(MONO, 8),
            text_color="#777f76", anchor="w"
        )
        self._prev_meta.pack(anchor="w", pady=(8, 0))

        # quality strip at bottom
        self._prev_quality = ctk.CTkLabel(
            self._prev_content, text="", font=(MONO, 8),
            text_color="#687068", anchor="w"
        )
        self._prev_quality.pack(anchor="w", pady=(10, 0))

        # ── 03 OUTPUT CONFIG ──────────────────────────────────────────────
        cfg_panel = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=2,
                                  border_width=1, border_color=BORDERL)
        cfg_panel.pack(fill="x", padx=18, pady=(0, 14))

        self._panel_heading(cfg_panel, "03", "OUTPUT CONFIG", None)

        cfg_inner = ctk.CTkFrame(cfg_panel, fg_color="transparent")
        cfg_inner.pack(fill="both", expand=True, padx=14, pady=14)

        # FORMAT label
        ctk.CTkLabel(cfg_inner, text="FORMAT", font=(MONO, 8),
                     text_color="#737a71", anchor="w").pack(anchor="w", pady=(0, 6))

        # format switcher (two card buttons)
        fmt_row = ctk.CTkFrame(cfg_inner, fg_color="transparent")
        fmt_row.pack(fill="x", pady=(0, 14))
        fmt_row.columnconfigure(0, weight=1)
        fmt_row.columnconfigure(1, weight=1)

        self._fmt_var = ctk.StringVar(value="mp4")

        self._mp4_card = ctk.CTkFrame(fmt_row, fg_color="#0d0f0f", corner_radius=2,
                                       border_width=1, border_color=BORDERL, height=58)
        self._mp4_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._mp4_card.grid_propagate(False)
        self._mp4_card_inner = ctk.CTkFrame(self._mp4_card, fg_color="transparent")
        self._mp4_card_inner.pack(expand=True)
        self._mp4_lbl = ctk.CTkLabel(self._mp4_card_inner, text="MP4",
                                      font=(MONO, 12, "bold"), text_color="#888e85")
        self._mp4_lbl.pack()
        self._mp4_sub = ctk.CTkLabel(self._mp4_card_inner, text="VIDEO",
                                      font=(MONO, 7), text_color="#777f76")
        self._mp4_sub.pack()
        self._mp4_card.bind("<Button-1>", lambda e: self._set_fmt("mp4"))
        self._mp4_card.configure(cursor="hand2")
        self._mp4_card_inner.configure(cursor="hand2")

        self._mp3_card = ctk.CTkFrame(fmt_row, fg_color="#0d0f0f", corner_radius=2,
                                       border_width=1, border_color=BORDERL, height=58)
        self._mp3_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._mp3_card.grid_propagate(False)
        self._mp3_card_inner = ctk.CTkFrame(self._mp3_card, fg_color="transparent")
        self._mp3_card_inner.pack(expand=True)
        self._mp3_lbl = ctk.CTkLabel(self._mp3_card_inner, text="MP3",
                                      font=(MONO, 12, "bold"), text_color="#888e85")
        self._mp3_lbl.pack()
        self._mp3_sub = ctk.CTkLabel(self._mp3_card_inner, text="AUDIO",
                                      font=(MONO, 7), text_color="#777f76")
        self._mp3_sub.pack()
        self._mp3_card.bind("<Button-1>", lambda e: self._set_fmt("mp3"))
        self._mp3_card.configure(cursor="hand2")
        self._mp3_card_inner.configure(cursor="hand2")

        # QUALITY
        ctk.CTkLabel(cfg_inner, text="QUALITY / BITRATE", font=(MONO, 8),
                     text_color="#737a71", anchor="w").pack(anchor="w", pady=(0, 6))
        self._q_var = ctk.StringVar(value="\u2014")
        self._q_menu = ctk.CTkOptionMenu(
            cfg_inner, variable=self._q_var, values=["\u2014"],
            font=(MONO, 10), dropdown_font=(MONO, 10), height=34,
            fg_color=INPBG, button_color=BORDER, button_hover_color="#2a2a2a",
            text_color="#dbdcd4", corner_radius=2
        )
        self._q_menu.pack(fill="x", pady=(0, 12))

        # checkboxes
        self._meta_var = ctk.BooleanVar(value=True)
        self._meta_row, self._meta_chk = self._make_check(cfg_inner, "Embed metadata",
                                           "title, artist, album, cover art",
                                           self._meta_var)
        self._meta_row.pack(fill="x", pady=(0, 2))

        self._lyrics_var = ctk.BooleanVar(value=False)
        self._lyrics_row, self._lyrics_chk = self._make_check(cfg_inner, "Synced lyrics",
                                             "time-synced .lrc file",
                                             self._lyrics_var)
        self._lyrics_row.pack(fill="x")

        # output profile bar
        self._profile_bar = ctk.CTkFrame(cfg_inner, fg_color=INPBG, corner_radius=2,
                                          border_width=1, border_color=BORDERL, height=32)
        self._profile_bar.pack(fill="x", pady=(12, 0))
        self._profile_bar.pack_propagate(False)
        prof_inner = ctk.CTkFrame(self._profile_bar, fg_color="transparent")
        prof_inner.pack(fill="x", padx=10, expand=True)
        ctk.CTkLabel(prof_inner, text="OUTPUT PROFILE", font=(MONO, 7),
                     text_color="#666e65").pack(side="left")
        self._profile_val = ctk.CTkLabel(prof_inner, text="MP4 \u00b7 BEST",
                                          font=(MONO, 8, "bold"), text_color=GOLD)
        self._profile_val.pack(side="right")

        # ── 04 DESTINATION ────────────────────────────────────────────────
        dest_panel = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=2,
                                   border_width=1, border_color=BORDERL)
        dest_panel.pack(fill="x", padx=18, pady=(0, 14))

        self._panel_heading(dest_panel, "04", "DESTINATION", "LOCAL FILESYSTEM")

        dest_inner = ctk.CTkFrame(dest_panel, fg_color="transparent")
        dest_inner.pack(fill="x", padx=14, pady=14)

        folder_row = ctk.CTkFrame(dest_inner, fg_color="transparent")
        folder_row.pack(fill="x")

        self._fold_lbl = ctk.CTkLabel(
            folder_row, text=self.out_dir, font=(MONO, 9),
            text_color="#b7bbb2", anchor="w", fg_color=INPBG,
            corner_radius=2, height=36, padx=10
        )
        self._fold_lbl.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            folder_row, text="BROWSE", width=70, height=36,
            font=(MONO, 8), fg_color="#272a29",
            hover_color="#343735", text_color="#90968d",
            corner_radius=2, command=self._browse,
            cursor="hand2"
        ).pack(side="left", padx=(0, 8))

        # download button with hard shadow (simulated via stacked frames)
        dl_wrap = ctk.CTkFrame(folder_row, fg_color="transparent")
        dl_wrap.pack(side="right")

        # shadow layer
        self._dl_shadow = ctk.CTkFrame(dl_wrap, fg_color=PRIMARYD,
                                        width=130, height=36, corner_radius=2)
        self._dl_shadow.place(x=4, y=4)
        self._dl_shadow.pack_propagate(False)

        self._dl_btn = ctk.CTkButton(
            dl_wrap, text="\u25b6  START", width=130, height=36,
            font=(MONO, 9, "bold"), fg_color=PRIMARY,
            hover_color=PRIMARYH, text_color="#ffffff",
            corner_radius=2, command=self._start_download,
            state="disabled", cursor="hand2"
        )
        self._dl_btn.pack()

        # hints
        hints2 = ctk.CTkFrame(dest_inner, fg_color="transparent")
        hints2.pack(fill="x", pady=(8, 0))
        for txt in ["Local filesystem only", "Restricted filenames", "No cloud upload"]:
            ctk.CTkLabel(hints2, text=f"\u2022 {txt}", font=(MONO, 7),
                         text_color="#666e65").pack(side="left", padx=(0, 14))

        # ── 05 TRANSFER ACTIVITY ──────────────────────────────────────────
        act_panel = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=2,
                                  border_width=1, border_color=BORDERL)
        act_panel.pack(fill="x", padx=18, pady=(0, 18))

        # heading row with percentage
        hdr_frame = ctk.CTkFrame(act_panel, fg_color="transparent", height=40)
        hdr_frame.pack(fill="x", padx=14, pady=(10, 0))
        hdr_frame.pack_propagate(False)

        hdr_left = ctk.CTkFrame(hdr_frame, fg_color="transparent")
        hdr_left.pack(side="left", fill="y")
        row_h = ctk.CTkFrame(hdr_left, fg_color="transparent")
        row_h.pack(anchor="w")
        ctk.CTkLabel(row_h, text="05", font=(MONO, 9),
                     text_color=PRIMARY).pack(side="left")
        ctk.CTkLabel(row_h, text="  TRANSFER ACTIVITY", font=(MONO, 9, "bold"),
                     text_color="#dbdcd4").pack(side="left")

        self._transfer_state = ctk.CTkLabel(hdr_frame, text="STANDBY",
                                             font=(MONO, 8), text_color=DIM)
        self._transfer_state.pack(side="left", padx=(16, 0))

        self._pct_lbl = ctk.CTkLabel(hdr_frame, text="",
                                      font=(MONO, 12, "bold"), text_color=TEXT2)
        self._pct_lbl.pack(side="right")

        # progress bar (canvas)
        prog_frame = ctk.CTkFrame(act_panel, fg_color="transparent")
        prog_frame.pack(fill="x", padx=14, pady=(8, 0))
        self._prog_canvas = Canvas(prog_frame, height=8, bg="#080a0a",
                                    highlightthickness=0, bd=0)
        self._prog_canvas.pack(fill="x")

        # terminal window
        term_border = ctk.CTkFrame(act_panel, fg_color=BORDERL, corner_radius=2)
        term_border.pack(fill="x", padx=14, pady=(10, 14))

        term_hdr = ctk.CTkFrame(term_border, fg_color="transparent", height=28)
        term_hdr.pack(fill="x")
        term_hdr.pack_propagate(False)
        term_hdr_inner = ctk.CTkFrame(term_hdr, fg_color="transparent")
        term_hdr_inner.pack(fill="both", expand=True, padx=8)
        ctk.CTkLabel(term_hdr_inner, text="LIVE LOG OUTPUT",
                     font=(MONO, 7), text_color="#697169").pack(side="left")
        ctk.CTkLabel(term_hdr_inner, text="\u25cf",
                     font=(MONO, 7), text_color=GREEN).pack(side="right")
        ctk.CTkLabel(term_hdr_inner, text="  STDOUT",
                     font=(MONO, 7), text_color="#697169").pack(side="right")

        self._log_box = ctk.CTkTextbox(
            term_border, font=(MONO, 9), fg_color=TERMBG,
            text_color="#92998e", wrap="word",
            border_width=0, height=120,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#2a2a2a"
        )
        self._log_box.pack(fill="x", padx=1, pady=(0, 1))
        self._log_box.configure(state="disabled")

        # blinking cursor row
        cursor_row = ctk.CTkFrame(term_border, fg_color="transparent", height=18)
        cursor_row.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkLabel(cursor_row, text=">", font=(MONO, 9),
                     text_color=PRIMARY).pack(side="left")
        self._cursor_block = ctk.CTkLabel(cursor_row, text=" ",
                                           font=(MONO, 9), text_color="#7e867b",
                                           bg_color="#7e867b", width=2)
        self._cursor_block.pack(side="left", padx=(4, 0))
        self._blink_on = True
        self._blink_cursor()

        # ── footer ────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=32)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        ft = ctk.CTkFrame(footer, fg_color="transparent")
        ft.pack(fill="both", expand=True, padx=20)
        ctk.CTkLabel(ft, text="PROXIMITY  v2.6.1", font=(MONO, 7),
                     text_color=DIM).pack(side="left")
        ctk.CTkLabel(ft, text="STATUS: OPERATIONAL",
                     font=(MONO, 7), text_color=GREEN).pack(side="right")

        # ── format init ───────────────────────────────────────────────────
        self._update_fmt_ui()

    # ── helper: LED ───────────────────────────────────────────────────────

    def _make_led(self, parent, label):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(side="left", padx=(0, 14))
        dot = ctk.CTkLabel(frame, text="\u25cf", font=(MONO, 8), text_color=DIM)
        dot.pack(side="left", padx=(0, 4))
        lbl = ctk.CTkLabel(frame, text=f"{label.upper()} \u2014", font=(MONO, 8),
                           text_color=DIM)
        lbl.pack(side="left")
        return {"dot": dot, "label": lbl}

    def _set_led(self, led_obj, state):
        """state: 'ok', 'err', 'loading'"""
        colors = {"ok": GREENL, "err": PRIMARY, "loading": GOLD}
        c = colors.get(state, DIM)
        led_obj["dot"].configure(text_color=c)
        led_obj["label"].configure(text_color="#d7d8cf" if state == "ok" else DIM)

    # ── helper: panel heading ─────────────────────────────────────────────

    def _panel(self, parent, idx, title, note, note_color=None, note_pulse=False):
        frame = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=2,
                              border_width=1, border_color=BORDERL)
        frame.pack(fill="x", padx=18, pady=(14, 14))
        self._panel_heading(frame, idx, title, note, note_color, note_pulse)
        return frame

    def _panel_heading(self, panel, idx, title, note, note_color=None, note_pulse=False):
        hdr = ctk.CTkFrame(panel, fg_color="transparent", height=40)
        hdr.pack(fill="x", padx=14, pady=(10, 0))
        hdr.pack_propagate(False)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left", fill="y")
        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(anchor="w")
        ctk.CTkLabel(row, text=idx, font=(MONO, 9),
                     text_color=PRIMARY).pack(side="left")
        ctk.CTkLabel(row, text=f"  {title}", font=(MONO, 9, "bold"),
                     text_color="#dbdcd4").pack(side="left")

        if note:
            nc = note_color or MUTED
            note_lbl = ctk.CTkLabel(hdr, text=note, font=(MONO, 8),
                         text_color=nc)
            note_lbl.pack(side="right")
            panel._heading_note = note_lbl

    # ── helper: checkbox row ──────────────────────────────────────────────

    def _make_check(self, parent, label, desc, var):
        row = ctk.CTkFrame(parent, fg_color="transparent", height=44)
        row.pack_propagate(False)

        # custom checkbox square
        box_frame = ctk.CTkFrame(row, fg_color="transparent", width=15, height=15)
        box_frame.pack(side="left", padx=(0, 10))
        box_frame.pack_propagate(False)

        inner = ctk.CTkFrame(box_frame, fg_color="transparent")
        inner.pack(expand=True)

        # use CTkCheckBox but restyle
        chk = ctk.CTkCheckBox(
            row, text="", variable=var, onvalue=True, offvalue=False,
            font=(MONO, 9), fg_color=PRIMARY, hover_color=PRIMARYH,
            checkmark_color="#ffffff", border_color="#606860",
            corner_radius=1, width=15, height=15
        )
        chk.place(x=0, y=0)

        txt_frame = ctk.CTkFrame(row, fg_color="transparent")
        txt_frame.place(x=28, y=4)
        ctk.CTkLabel(txt_frame, text=label, font=(MONO, 9),
                     text_color="#b7bbb2").pack(anchor="w")
        ctk.CTkLabel(txt_frame, text=desc, font=(MONO, 7),
                     text_color="#707970").pack(anchor="w")

        return row, chk

    # ── helper: format switcher ───────────────────────────────────────────

    def _set_fmt(self, val):
        self._fmt_var.set(val)
        self._update_fmt_ui()

    def _update_fmt_ui(self):
        fmt = self._fmt_var.get()
        is_mp4 = (fmt == "mp4")

        # mp4 card
        if is_mp4:
            self._mp4_card.configure(fg_color="#1c0d0e",
                                      border_color="#a8232d")
            self._mp4_lbl.configure(text_color="#f1f1eb")
            self._mp4_sub.configure(text_color="#777f76")
        else:
            self._mp4_card.configure(fg_color="#0d0f0f", border_color=BORDERL)
            self._mp4_lbl.configure(text_color="#888e85")
            self._mp4_sub.configure(text_color="#777f76")

        # mp3 card
        if not is_mp4:
            self._mp3_card.configure(fg_color="#1c0d0e",
                                      border_color="#a8232d")
            self._mp3_lbl.configure(text_color="#f1f1eb")
            self._mp3_sub.configure(text_color="#777f76")
        else:
            self._mp3_card.configure(fg_color="#0d0f0f", border_color=BORDERL)
            self._mp3_lbl.configure(text_color="#888e85")
            self._mp3_sub.configure(text_color="#777f76")

        # quality options
        if is_mp4:
            cur = self._q_menu.cget("values")
            if cur and "kbps" in str(cur[0]):
                self._q_menu.configure(values=["\u2014"])
                self._q_var.set("\u2014")
            self._q_menu.configure(state="normal", fg_color=INPBG, text_color="#dbdcd4")
            self._lyrics_chk.configure(state="disabled")
            self._lyrics_var.set(False)
        else:
            self._q_menu.configure(values=["320kbps", "256kbps", "192kbps", "128kbps"],
                                   state="normal", fg_color=INPBG, text_color="#dbdcd4")
            self._q_var.set("320kbps")
            self._lyrics_chk.configure(state="normal")

        # update profile bar
        qual = self._q_var.get()
        self._profile_val.configure(text=f"{fmt.upper()} \u00b7 {qual}")

    # ── helper: ticker ────────────────────────────────────────────────────

    def _start_ticker(self):
        self._tick_ticker()

    def _tick_ticker(self):
        if self._busy:
            self.after(60, self._tick_ticker)
            return
        self._ticker_offset = (self._ticker_offset + 1) % len(TICKER_STR)
        shifted = TICKER_STR[self._ticker_offset:] + TICKER_STR[:self._ticker_offset]
        self._ticker_var.set(shifted)
        self.after(60, self._tick_ticker)

    # ── helper: clock ─────────────────────────────────────────────────────

    def _tick_clock(self):
        now = time.strftime("%H:%M:%S")
        self._clock_lbl.configure(text=now)
        self.after(1000, self._tick_clock)

    # ── helper: cursor blink ──────────────────────────────────────────────

    def _blink_cursor(self):
        if self._blink_on:
            self._cursor_block.configure(text_color="#7e867b", bg_color="#7e867b")
        else:
            self._cursor_block.configure(text_color=BG, bg_color=BG)
        self._blink_on = not self._blink_on
        self.after(530, self._blink_cursor)

    # ── deps ──────────────────────────────────────────────────────────────

    def _check_deps(self):
        if self.ytdlp:
            self._set_led(self._led_ytdlp, "ok")
        else:
            self._set_led(self._led_ytdlp, "err")
            self._log("\u2717 yt-dlp.exe not found \u2014 put it in the same folder")
        if self.ffmpeg:
            self._set_led(self._led_ffmpeg, "ok")
        else:
            self._set_led(self._led_ffmpeg, "err")
            self._log("\u26a0 ffmpeg not found \u2014 MP3 unavailable")
        # lrclib is always online (no local binary needed)
        self._set_led(self._led_lrclib, "ok")

    # ── ui helpers ────────────────────────────────────────────────────────

    def _log(self, msg, color=None):
        self._log_box.configure(state="normal")
        # color mapping
        tag = ""
        if msg.startswith("\u2713"):
            tag = "green"
        elif msg.startswith("\u2717"):
            tag = "red"
        elif msg.startswith("\u26a0"):
            tag = "amber"

        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _set_busy(self, busy):
        self._busy = busy
        s = "disabled" if busy else "normal"
        self._look_btn.configure(state=s)
        if busy:
            self._dl_btn.configure(state="disabled", text="\u23f3  WORKING...")
            self._transfer_state.configure(text="TRANSFER IN PROGRESS", text_color=GREEN)
            self._set_led(self._led_ytdlp, "loading")
        else:
            if self._unlocked:
                self._dl_btn.configure(state="normal", text="\u25b6  START")
            self._transfer_state.configure(text="STANDBY", text_color=DIM)
            self._set_led(self._led_ytdlp, "ok")
            self._pct = 0.0
            self._draw_progress(0)
            self._pct_lbl.configure(text="")

    def _draw_progress(self, pct):
        """Draw diagonal red stripe progress bar on canvas."""
        self._prog_canvas.update_idletasks()
        w = self._prog_canvas.winfo_width()
        h = 8
        self._prog_canvas.delete("all")
        if w < 10:
            return
        # background
        self._prog_canvas.create_rectangle(0, 0, w, h, fill="#080a0a", outline="")
        # fill with diagonal stripes
        fill_w = int(w * pct)
        if fill_w > 0:
            # clip to fill area using multiple diagonal lines
            stripe_gap = 10
            stripe_w = 7
            for x in range(-h, fill_w + h, stripe_gap):
                self._prog_canvas.create_line(
                    x, h, x + h, 0,
                    fill="#b9232d", width=stripe_w, tags="stripe"
                )
            # second layer for alternating color
            for x in range(-h + stripe_w, fill_w + h, stripe_gap):
                self._prog_canvas.create_line(
                    x, h, x + h, 0,
                    fill="#d43a43", width=stripe_w - 2, tags="stripe2"
                )
            # clip to fill area
            self._prog_canvas.create_rectangle(fill_w, 0, w, h, fill="#080a0a", outline="")
            # glowing tip
            if pct > 0.01:
                tip_x = fill_w
                self._prog_canvas.create_rectangle(
                    tip_x - 1, -3, tip_x + 1, h + 3,
                    fill="#f1d7d5", outline=""
                )
        # border
        self._prog_canvas.create_rectangle(0, 0, w, h, outline="#242625")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.out_dir)
        if d:
            self.out_dir = d
            self._fold_lbl.configure(text=d)

    def _unlock(self):
        if not self._unlocked:
            self._unlocked = True
        self._dl_btn.configure(state="normal")

    def _show_preview(self):
        """Show the current lookup's info in the preview panel."""
        if not self._last_info:
            return
        self._prev_empty.pack_forget()
        self._prev_content.pack(fill="both", expand=True)

        info = self._last_info
        self._prev_title.configure(text=info["title"])
        self._prev_channel.configure(text=info["channel"])
        meta = info["duration"]
        if self._last_url and is_playlist(self._last_url):
            meta += "  \u00b7  playlist"
        self._prev_meta.configure(text=meta)

        if self._last_qualities:
            qstr = "  \u00b7  ".join(f"{q}p" for q in self._last_qualities[:5])
            self._prev_quality.configure(text=f"formats: {qstr}")
        else:
            self._prev_quality.configure(text="formats: best")

        # update panel heading status
        if hasattr(self._prev_panel, '_heading_note'):
            self._prev_panel._heading_note.configure(text="ACTIVE", text_color=GREEN)

        # load thumbnail
        thumb_url = info.get("thumbnail", "")
        if thumb_url:
            self._load_thumbnail(thumb_url)

    def _load_thumbnail(self, url):
        """Download and display thumbnail in background thread."""
        def _bg():
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            if download_thumbnail(url, tmp.name):
                self._thumb_path = tmp.name
                self.after(0, self._set_thumbnail, tmp.name)
            else:
                os.unlink(tmp.name)
        threading.Thread(target=_bg, daemon=True).start()

    def _set_thumbnail(self, path):
        """Load the downloaded thumbnail into the preview label."""
        if not HAS_PIL:
            return
        try:
            img = Image.open(path)
            img = img.convert("RGB")
            # scale to fit width ~500, keep aspect ratio
            target_w = 500
            ratio = target_w / img.width
            target_h = int(img.height * ratio)
            img = img.resize((target_w, target_h), Image.LANCZOS)
            self._thumb_img = ctk.CTkImage(light_image=img, dark_image=img,
                                            size=(target_w, target_h))
            self._prev_thumb_label.configure(image=self._thumb_img, text="")
        except Exception:
            pass

    # ── lookup ────────────────────────────────────────────────────────────

    def _lookup(self):
        if not self.ytdlp:
            self._log("\u2717 yt-dlp not found"); return
        url = self._url_var.get().strip()
        if not url: return
        url = clean_url(url)
        self._url_var.set(url)
        self._set_busy(True)
        # show looking-up state in preview panel
        if hasattr(self._prev_panel, '_heading_note'):
            self._prev_panel._heading_note.configure(text="LOOKING UP...", text_color=GOLD)
        self._log(f"\n\u2192 looking up {url}")
        threading.Thread(target=self._lookup_bg, args=(url,), daemon=True).start()

    def _lookup_bg(self, url):
        try:
            info = fetch_info(self.ytdlp, url)
            qs = [] if is_playlist(url) else fetch_qualities(self.ytdlp, url, self.ffmpeg)
            self.after(0, self._lookup_done, info, qs, url)
        except Exception as e:
            self.after(0, self._log, f"\u2717 {e}")
            # reset preview heading on error
            if hasattr(self, '_prev_panel') and hasattr(self._prev_panel, '_heading_note'):
                self._prev_panel._heading_note.configure(text="STANDBY", text_color=DIM)
            self.after(0, self._set_busy, False)

    def _lookup_done(self, info, qualities, url):
        # store current lookup data
        self._last_info = info
        self._last_qualities = qualities
        self._last_url = url

        # show current lookup in preview
        self._show_preview()

        # update quality dropdown
        if qualities:
            vals = [f"{q}p" for q in qualities]
            self._q_menu.configure(values=vals)
            self._q_var.set(vals[0])
        else:
            self._q_menu.configure(values=["best"])
            self._q_var.set("best")

        self._unlock()
        self._log(f"\u2713 {info['title']}  [{info['duration']}]")
        self._set_busy(False)
        self._update_fmt_ui()

    # ── download ──────────────────────────────────────────────────────────

    def _start_download(self):
        url = self._url_var.get().strip()
        fmt = self._fmt_var.get()
        qual = self._q_var.get().replace("p", "")
        out  = self.out_dir
        want_lyrics = (fmt == "mp3") and self._lyrics_var.get()
        want_meta = self._meta_var.get()

        if fmt == "mp3" and not self.ffmpeg:
            self._log("\u2717 MP3 requires ffmpeg"); return

        Path(out).mkdir(parents=True, exist_ok=True)
        playlist = is_playlist(url)

        outtmpl = str(Path(out) / (
            "%(playlist_title)s/%(title)s.%(ext)s"
            if playlist else "%(title)s.%(ext)s"
        ))

        cmd = [self.ytdlp, "--no-warnings", "--progress", "-o", outtmpl]

        if fmt == "mp3":
            bitrate = qual.replace("kbps", "") if "kbps" in qual else "320"
            cmd += ["-x", "--audio-format", "mp3", "--audio-quality", bitrate]
        else:
            h = int(qual) if qual.isdigit() else 1080
            if self.ffmpeg:
                fs = f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best"
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

        self._set_busy(True)
        label = fmt.upper() + (f" @ {qual}p" if fmt == "mp4" and qual.isdigit() else "")
        self._log(f"\n\u2192 downloading {label}")
        threading.Thread(target=self._dl_bg, args=(cmd, out, want_lyrics), daemon=True).start()

    def _dl_bg(self, cmd, out, want_lyrics):
        lyric_targets = []
        pct_re = re.compile(r'\[download\]\s+([\d.]+)%')
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=0x08000000
            )
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if line.startswith(LYRICS_MARKER):
                    payload = line[len(LYRICS_MARKER):]
                    parts = payload.split("::", 3)
                    if len(parts) == 4:
                        filepath, title, artist, duration = parts
                        try:
                            duration = int(float(duration))
                        except ValueError:
                            duration = None
                        lyric_targets.append((filepath, title, artist, duration))
                    continue
                m = pct_re.search(line)
                if m:
                    pct = float(m.group(1)) / 100.0
                    self.after(0, self._update_progress, pct)
                    continue
                self.after(0, self._log, line)

            proc.wait()

            if proc.returncode == 0:
                self.after(0, self._log, f"\n\u2713 Saved to: {out}")
                if want_lyrics:
                    self._fetch_all_lyrics(lyric_targets)
            else:
                self.after(0, self._log, f"\n\u2717 Failed (exit {proc.returncode})")
        except Exception as e:
            self.after(0, self._log, f"\u2717 {e}")
        finally:
            self.after(0, self._set_busy, False)

    def _update_progress(self, pct):
        self._pct = pct
        self._draw_progress(pct)
        self._pct_lbl.configure(text=f"{pct*100:.1f}%")
        self._transfer_state.configure(text="WRITING TO DISK" if pct > 0.95 else "TRANSFER IN PROGRESS",
                                        text_color=PRIMARY if pct > 0.95 else GREEN)

    def _fetch_all_lyrics(self, targets):
        if not targets:
            self.after(0, self._log, "\u26a0 Lyrics: no tracks to match")
            return
        self.after(0, self._log, f"\n\u2192 looking up synced lyrics for {len(targets)} track(s)...")
        found, missing = 0, 0
        for filepath, title, artist, duration in targets:
            if not os.path.exists(filepath):
                continue
            try:
                lrc = fetch_synced_lyrics(title, artist, duration=duration)
                if lrc:
                    lrc_path = save_lyrics(filepath, lrc)
                    self.after(0, self._log, f"\u2713 lyrics: {Path(lrc_path).name}")
                    found += 1
                else:
                    self.after(0, self._log, f"\u26a0 no synced lyrics: {title}")
                    missing += 1
            except Exception as e:
                self.after(0, self._log, f"\u26a0 lyrics failed: {title}: {e}")
                missing += 1
        self.after(0, self._log, f"\u2192 lyrics done: {found} found, {missing} missing")

if __name__ == "__main__":
    app = App()
    app.mainloop()

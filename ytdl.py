#!/usr/bin/env python3
"""
ytdl.py — Proximity  ·  YouTube downloader GUI
pip install customtkinter
"""

import json, os, re, sys, subprocess, urllib.parse, urllib.request, threading, platform, time
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── design tokens ─────────────────────────────────────────────────────────────

BG      = "#0a0a0a"
CARD    = "#111111"
BORDER  = "#1e1e1e"
ACCENT  = "#ff3333"
ACCENTD = "#cc2929"
SUCCESS = "#c8f557"
MUTED   = "#4a4a4a"
TEXT    = "#e8ebeb"
LOGTXT  = "#888888"
MONO    = "Consolas"
SANS    = "Segoe UI"
NO_WINDOW = dict(creationflags=0x08000000) if platform.system() == "Windows" else {}

LRCLIB_BASE  = "https://lrclib.net/api"
LYRICS_MARKER = "LYRICSPATH::"

TICKER_MSG = (
    "  MP4 UP TO 4K  \u00b7  MP3 320KBPS  \u00b7  PLAYLISTS  \u00b7  "
    "YOUTUBE MUSIC  \u00b7  SYNCED LYRICS  \u00b7  EMBEDDED METADATA  \u00b7  "
    "NO ACCOUNT REQUIRED  \u00b7  OPEN SOURCE  "
)

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
    r = subprocess.run(
        [ytdlp, "--no-warnings", "--print",
         "%(title)s\n%(channel)s\n%(duration_string)s",
         "--playlist-items", "1", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        **NO_WINDOW
    )
    lines = r.stdout.strip().splitlines()
    if not lines or not lines[0]:
        raise RuntimeError(r.stderr[:300] or "Could not fetch video info")
    return {
        "title":    lines[0],
        "channel":  lines[1] if len(lines) > 1 else "",
        "duration": lines[2] if len(lines) > 2 else "",
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
        self.geometry("560x780")
        self.minsize(560, 780)
        self.configure(fg_color=BG)

        self.ytdlp   = find_ytdlp()
        self.ffmpeg  = check_ffmpeg()
        self.out_dir = str(Path(__file__).parent / "downloads")
        self._unlocked = False
        self._busy = False
        self._ticker_offset = 0

        self._build()
        self.after(200, self._check_deps)
        self.after(600, self._start_ticker)

    # ── build ─────────────────────────────────────────────────────────────

    def _build(self):
        # ── header ────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="proximity.", font=(MONO, 20, "bold"),
                     text_color=ACCENT).pack(side="left", padx=20)

        # status pills
        stat_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        stat_frame.pack(side="right", padx=20)

        self._ytdlp_dot = ctk.CTkLabel(hdr, text="", font=(MONO, 9), text_color=MUTED)
        self._ytdlp_dot.pack(side="right", padx=(0, 4))

        self._ffmpeg_dot = ctk.CTkLabel(hdr, text="", font=(MONO, 9), text_color=MUTED)
        self._ffmpeg_dot.pack(side="right", padx=(0, 16))

        # red accent line
        ctk.CTkFrame(self, fg_color=ACCENT, corner_radius=0, height=2).pack(fill="x")

        # ── ticker ────────────────────────────────────────────────────────
        self._ticker_var = ctk.StringVar(value=TICKER_MSG)
        self._ticker = ctk.CTkLabel(
            self, textvariable=self._ticker_var,
            font=(MONO, 9), text_color=MUTED, fg_color=BG,
            height=24, anchor="w"
        )
        self._ticker.pack(fill="x", padx=0)
        self._ticker.pack_propagate(False)

        # ── bottom bar ────────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color=BG)
        bot.pack(fill="x", side="bottom", padx=20, pady=(16, 20))

        self._prog = ctk.CTkProgressBar(bot, fg_color=BORDER, progress_color=ACCENT,
                                         height=3, corner_radius=2)
        self._dl_btn = ctk.CTkButton(
            bot, text="\u2193  download", height=46,
            font=(MONO, 13, "bold"), fg_color=ACCENT,
            hover_color=ACCENTD, text_color="#ffffff",
            corner_radius=23, command=self._start_download,
            state="disabled"
        )
        self._dl_btn.pack(fill="x")

        # ── scrollable body ───────────────────────────────────────────────
        body = ctk.CTkScrollableFrame(self, fg_color=BG, scrollbar_button_color=BORDER,
                                       scrollbar_button_hover_color="#2a2a2a")
        body.pack(fill="both", expand=True, padx=20, pady=(12, 0))

        # url card
        uc = self._card(body)
        ctk.CTkLabel(uc, text="URL", font=(MONO, 10), text_color=MUTED).pack(
            anchor="w", padx=16, pady=(12, 4))
        row = ctk.CTkFrame(uc, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        self._url_var = ctk.StringVar()
        self._url_entry = ctk.CTkEntry(
            row, textvariable=self._url_var,
            placeholder_text="https://youtu.be/...",
            font=(MONO, 12), height=40, fg_color=BG,
            border_color=BORDER, border_width=1,
            text_color=TEXT, placeholder_text_color=MUTED, corner_radius=8
        )
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._url_entry.bind("<Return>", lambda e: self._lookup())

        self._look_btn = ctk.CTkButton(
            row, text="look up", width=88, height=40,
            font=(MONO, 12, "bold"), fg_color=ACCENT,
            hover_color=ACCENTD, text_color="#ffffff",
            corner_radius=8, command=self._lookup
        )
        self._look_btn.pack(side="right")

        # preview card (hidden until lookup)
        self._prev_card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12,
                                        border_width=0)
        # red left accent stripe via inner frame
        stripe_wrap = ctk.CTkFrame(self._prev_card, fg_color="transparent")
        stripe_wrap.pack(fill="x")
        ctk.CTkFrame(stripe_wrap, fg_color=ACCENT, width=3, corner_radius=2).pack(
            side="left", fill="y", padx=(0, 0))
        prev_inner = ctk.CTkFrame(stripe_wrap, fg_color="transparent")
        prev_inner.pack(side="left", fill="both", expand=True)
        self._prev_title = ctk.CTkLabel(
            prev_inner, text="", font=(SANS, 13, "bold"),
            text_color=TEXT, wraplength=460, justify="left", anchor="w")
        self._prev_title.pack(anchor="w", padx=14, pady=(12, 2))
        self._prev_meta = ctk.CTkLabel(
            prev_inner, text="", font=(MONO, 11),
            text_color=MUTED, anchor="w")
        self._prev_meta.pack(anchor="w", padx=14, pady=(0, 12))
        self._prev_card.pack_forget()

        # options card (hidden until lookup)
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
            unselected_color=BORDER, unselected_hover_color="#2a2a2a",
            text_color="#ffffff", corner_radius=8
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
            fg_color=BG, button_color=BORDER, button_hover_color="#2a2a2a",
            text_color=TEXT, corner_radius=8
        )
        self._q_menu.pack(fill="x", pady=(6, 0))

        # checkboxes row
        chk_frame = ctk.CTkFrame(inner, fg_color="transparent")
        chk_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        chk_frame.columnconfigure(0, weight=1)
        chk_frame.columnconfigure(1, weight=1)

        # embed metadata toggle — always visible
        self._meta_var = ctk.BooleanVar(value=True)
        self._meta_chk = ctk.CTkCheckBox(
            chk_frame, text="embed metadata & cover art", variable=self._meta_var,
            font=(MONO, 11), text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENTD, checkmark_color="#ffffff",
            border_color=BORDER, corner_radius=4
        )
        self._meta_chk.grid(row=0, column=0, sticky="w")

        # synced lyrics toggle — shown/hidden by _on_fmt
        self._lyrics_var = ctk.BooleanVar(value=False)
        self._lyrics_chk = ctk.CTkCheckBox(
            chk_frame, text="synced lyrics (.lrc)", variable=self._lyrics_var,
            font=(MONO, 11), text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENTD, checkmark_color="#ffffff",
            border_color=BORDER, corner_radius=4
        )
        self._lyrics_chk.grid(row=0, column=1, sticky="w")
        self._lyrics_chk.grid_remove()

        self._opts_card.pack_forget()

        # folder card (hidden until lookup)
        self._fold_card = self._card(body)
        ctk.CTkLabel(self._fold_card, text="SAVE TO", font=(MONO, 10),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(12, 4))
        frow = ctk.CTkFrame(self._fold_card, fg_color="transparent")
        frow.pack(fill="x", padx=16, pady=(0, 14))
        self._fold_lbl = ctk.CTkLabel(
            frow, text=self.out_dir, font=(MONO, 11),
            text_color=MUTED, anchor="w", wraplength=400)
        self._fold_lbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            frow, text="browse", width=76, height=30,
            font=(MONO, 11), fg_color=BORDER,
            hover_color="#2a2a2a", text_color=TEXT,
            corner_radius=6, command=self._browse
        ).pack(side="right")
        self._fold_card.pack_forget()

        # log card (always visible)
        lc = self._card(body)
        ctk.CTkLabel(lc, text="LOG", font=(MONO, 10),
                     text_color=MUTED).pack(anchor="w", padx=16, pady=(12, 4))
        self._log_box = ctk.CTkTextbox(
            lc, font=(MONO, 11), fg_color=BG,
            text_color=LOGTXT, wrap="word",
            border_width=0, height=160,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#2a2a2a"
        )
        self._log_box.pack(fill="x", padx=8, pady=(0, 8))
        self._log_box.configure(state="disabled")

    def _card(self, parent):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12)
        f.pack(fill="x", pady=(0, 12))
        return f

    # ── ticker ────────────────────────────────────────────────────────────

    def _start_ticker(self):
        self._tick_ticker()

    def _tick_ticker(self):
        if self._busy:
            self.after(80, self._tick_ticker)
            return
        self._ticker_offset = (self._ticker_offset + 1) % len(TICKER_MSG)
        shifted = TICKER_MSG[self._ticker_offset:] + TICKER_MSG[:self._ticker_offset]
        self._ticker_var.set(shifted)
        self.after(80, self._tick_ticker)

    # ── deps ──────────────────────────────────────────────────────────────

    def _check_deps(self):
        if self.ytdlp:
            self._ytdlp_dot.configure(text=f"yt-dlp \u2713", text_color=SUCCESS)
        else:
            self._ytdlp_dot.configure(text="yt-dlp \u2717", text_color=ACCENT)
            self._log("\u2717 yt-dlp.exe not found \u2014 put it in the same folder as this script")
        if self.ffmpeg:
            self._ffmpeg_dot.configure(text=f"ffmpeg \u2713", text_color=SUCCESS)
        else:
            self._ffmpeg_dot.configure(text="ffmpeg \u2717", text_color=ACCENT)
            self._log("\u26a0 ffmpeg not found \u2014 MP3 unavailable")

    # ── ui helpers ────────────────────────────────────────────────────────

    def _log(self, msg):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _set_busy(self, busy):
        self._busy = busy
        s = "disabled" if busy else "normal"
        self._look_btn.configure(state=s)
        if busy:
            self._dl_btn.configure(state="disabled", text="\u23f3  working...")
            self._prog.pack(fill="x", pady=(0, 8), before=self._dl_btn)
            self._prog.configure(mode="indeterminate")
            self._prog.start()
        else:
            self._prog.stop()
            self._prog.pack_forget()
            if self._unlocked:
                self._dl_btn.configure(state="normal", text="\u2193  download")

    def _set_progress(self, pct):
        """Set determinate progress (0.0-1.0) and update button text."""
        try:
            self._prog.stop()
            self._prog.configure(mode="determinate", value=pct)
            self._dl_btn.configure(text=f"\u2193  {pct*100:.1f}%")
        except Exception:
            pass

    def _on_fmt(self, val):
        if val == "mp3":
            self._q_menu.configure(values=["320kbps", "256kbps", "192kbps", "128kbps"],
                                   state="normal", fg_color=BG, text_color=TEXT)
            self._q_var.set("320kbps")
            self._lyrics_chk.grid()
        else:
            cur = self._q_menu.cget("values")
            if cur and "kbps" in cur[0]:
                self._q_menu.configure(values=["\u2014"])
                self._q_var.set("\u2014")
            self._q_menu.configure(state="normal", fg_color=BG, text_color=TEXT)
            self._lyrics_chk.grid_remove()
            self._lyrics_var.set(False)

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

    # ── lookup ────────────────────────────────────────────────────────────

    def _lookup(self):
        if not self.ytdlp:
            self._log("\u2717 yt-dlp not found"); return
        url = self._url_var.get().strip()
        if not url: return
        url = clean_url(url)
        self._url_var.set(url)
        self._set_busy(True)
        self._log(f"\n\u2192 looking up {url}")
        threading.Thread(target=self._lookup_bg, args=(url,), daemon=True).start()

    def _lookup_bg(self, url):
        try:
            info = fetch_info(self.ytdlp, url)
            qs = [] if is_playlist(url) else fetch_qualities(self.ytdlp, url, self.ffmpeg)
            self.after(0, self._lookup_done, info, qs, url)
        except Exception as e:
            self.after(0, self._log, f"\u2717 {e}")
            self.after(0, self._set_busy, False)

    def _lookup_done(self, info, qualities, url):
        self._prev_title.configure(text=info["title"])
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

        self._unlock()
        self._log(f"\u2713 {info['title']}  [{info['duration']}]")
        self._set_busy(False)

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
            "%(playlist_title)s/%(playlist_index)s - %(title)s.%(ext)s"
            if playlist else "%(title)s.%(ext)s"
        ))

        cmd = [self.ytdlp, "--no-warnings", "--restrict-filenames", "-o", outtmpl]

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

        # metadata + thumbnail embedding
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
                line = line.rstrip("\n")
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
                # parse download progress
                m = pct_re.search(line)
                if m:
                    self.after(0, self._set_progress, float(m.group(1)) / 100.0)
                    continue  # don't spam raw progress lines
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
                    self.after(0, self._log, f"\u26a0 no synced lyrics found: {title}")
                    missing += 1
            except Exception as e:
                self.after(0, self._log, f"\u26a0 lyrics lookup failed for {title}: {e}")
                missing += 1
        self.after(0, self._log, f"\u2192 lyrics done: {found} found, {missing} missing")

if __name__ == "__main__":
    app = App()
    app.mainloop()

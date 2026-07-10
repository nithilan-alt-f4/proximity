import os
import re
import subprocess
import urllib.parse
from flask import Flask, request, Response, stream_with_context, jsonify

app = Flask(__name__)

YTDLP = "yt-dlp"
COOKIES_PATH = "/tmp/cookies.txt"

_raw_cookies = os.environ.get("YT_COOKIES")
if _raw_cookies:
    with open(COOKIES_PATH, "w") as f:
        f.write(_raw_cookies)


def cookie_args():
    return ["--cookies", COOKIES_PATH] if os.path.exists(COOKIES_PATH) else []

PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>proximity</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap" rel="stylesheet" />
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0a0a0a;
    --surface:  #111111;
    --border:   #222222;
    --border2:  #333333;
    --text:     #e8e8e8;
    --muted:    #666666;
    --accent:   #c8f557;
    --accent2:  #a8d93a;
    --red:      #ff5555;
    --mono:     'IBM Plex Mono', monospace;
    --sans:     'IBM Plex Sans', sans-serif;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
  }

  .wrap { width: 100%; max-width: 540px; }

  .header { margin-bottom: 2.5rem; }
  .header h1 {
    font-family: var(--mono);
    font-size: 1.5rem;
    font-weight: 500;
    letter-spacing: -0.02em;
    color: var(--accent);
  }
  .header p {
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 0.3rem;
    font-family: var(--mono);
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
  }

  .url-row { display: flex; gap: 0.5rem; }
  .url-row input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border2);
    border-radius: 8px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 0.82rem;
    padding: 0.65rem 0.9rem;
    outline: none;
    transition: border-color 0.15s;
  }
  .url-row input::placeholder { color: var(--muted); }
  .url-row input:focus { border-color: var(--accent); }

  .btn-look {
    background: var(--accent);
    color: #0a0a0a;
    border: none;
    border-radius: 8px;
    font-family: var(--mono);
    font-size: 0.82rem;
    font-weight: 500;
    padding: 0 1.1rem;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s, transform 0.1s;
  }
  .btn-look:hover { background: var(--accent2); }
  .btn-look:active { transform: scale(0.97); }
  .btn-look:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

  .preview {
    display: none;
    margin-top: 1rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    animation: fadein 0.2s ease;
  }
  .preview.show { display: flex; }
  .preview img {
    width: 120px;
    min-width: 120px;
    object-fit: cover;
    background: var(--bg);
  }
  .preview-info {
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 0.25rem;
    overflow: hidden;
  }
  .preview-title {
    font-size: 0.85rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .preview-meta {
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--muted);
  }
  .preview-flag {
    font-family: var(--mono);
    font-size: 0.68rem;
    color: var(--accent);
    margin-top: 0.1rem;
  }

  .options {
    display: none;
    margin-top: 1.25rem;
    gap: 0.75rem;
    animation: fadein 0.2s ease;
  }
  .options.show { display: grid; grid-template-columns: 1fr 1fr; }

  .field label {
    display: block;
    font-family: var(--mono);
    font-size: 0.7rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.4rem;
  }
  .field select {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border2);
    border-radius: 8px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 0.82rem;
    padding: 0.6rem 0.8rem;
    outline: none;
    cursor: pointer;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23666' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 0.75rem center;
    transition: border-color 0.15s;
  }
  .field select:focus { border-color: var(--accent); }

  .btn-dl {
    display: none;
    width: 100%;
    margin-top: 1.25rem;
    background: var(--accent);
    color: #0a0a0a;
    border: none;
    border-radius: 8px;
    font-family: var(--mono);
    font-size: 0.9rem;
    font-weight: 500;
    padding: 0.8rem;
    cursor: pointer;
    transition: background 0.15s, transform 0.1s;
    animation: fadein 0.2s ease;
  }
  .btn-dl.show { display: block; }
  .btn-dl:hover { background: var(--accent2); }
  .btn-dl:active { transform: scale(0.98); }
  .btn-dl:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

  .status {
    margin-top: 1rem;
    font-family: var(--mono);
    font-size: 0.78rem;
    min-height: 1.2rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .status.err  { color: var(--red); }
  .status.ok   { color: var(--accent); }
  .status.info { color: var(--muted); }

  .spin {
    width: 12px; height: 12px;
    border: 2px solid var(--border2);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    flex-shrink: 0;
  }

  .progress-wrap {
    display: none;
    margin-top: 0.75rem;
    height: 3px;
    background: var(--border);
    border-radius: 99px;
    overflow: hidden;
  }
  .progress-wrap.show { display: block; }
  .progress-bar {
    height: 100%;
    width: 40%;
    background: var(--accent);
    border-radius: 99px;
    animation: slide 1s ease-in-out infinite alternate;
  }

  .footer {
    margin-top: 2rem;
    font-family: var(--mono);
    font-size: 0.7rem;
    color: var(--muted);
    text-align: center;
  }
  .footer a { color: var(--muted); text-decoration: underline; }

  @keyframes fadein { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
  @keyframes spin    { to { transform: rotate(360deg); } }
  @keyframes slide   { from { margin-left: 0; } to { margin-left: 60%; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>proximity.</h1>
    <p>paste a youtube url. pick a format. get the file.</p>
  </div>

  <div class="card">
    <div class="url-row">
      <input id="urlInput" type="text" placeholder="https://youtu.be/..." autocomplete="off" spellcheck="false" />
      <button class="btn-look" id="lookBtn" onclick="lookupVideo()">look up</button>
    </div>

    <div class="preview" id="preview">
      <img id="thumb" src="" alt="thumbnail" />
      <div class="preview-info">
        <div class="preview-title" id="previewTitle"></div>
        <div class="preview-meta" id="previewMeta"></div>
        <div class="preview-flag" id="previewFlag"></div>
      </div>
    </div>

    <div class="options" id="options">
      <div class="field">
        <label>Format</label>
        <select id="fmtSelect" onchange="onFmtChange()">
          <option value="mp4">MP4 (video)</option>
          <option value="mp3">MP3 (audio)</option>
          <option value="flac">FLAC (lossless)</option>
        </select>
      </div>
      <div class="field">
        <label id="qualityLabel">Quality</label>
        <select id="qualitySelect"></select>
      </div>
    </div>

    <button class="btn-dl" id="dlBtn" onclick="startDownload()">&#8595; download</button>

    <div class="status info" id="status"></div>

    <div class="progress-wrap" id="progressWrap">
      <div class="progress-bar" id="progressBar"></div>
    </div>
  </div>

  <div class="footer">
    powered by <a href="https://github.com/yt-dlp/yt-dlp" target="_blank">yt-dlp</a>
  </div>
</div>

<script>
  const API = "";

  const AUDIO_QUALITIES = ["320", "256", "192", "128"];
  const DEFAULT_VIDEO_QUALITIES = ["1080", "720", "480", "360", "240", "144"];

  const $ = id => document.getElementById(id);
  let lastQualities = DEFAULT_VIDEO_QUALITIES;

  function setStatus(msg, type = "info", spinner = false) {
    const el = $("status");
    el.className = `status ${type}`;
    el.innerHTML = spinner ? `<div class="spin"></div>${msg}` : msg;
  }

  function showProgress(show) {
    $("progressWrap").classList.toggle("show", show);
  }

  function cleanUrl(url) {
    try {
      const u = new URL(url);
      if (u.hostname === "youtu.be") {
        const id = u.pathname.slice(1).split("?")[0];
        return `https://www.youtube.com/watch?v=${id}`;
      }
      const v = u.searchParams.get("v");
      if (v) return `https://www.youtube.com/watch?v=${v}`;
    } catch {}
    return url;
  }

  function getVideoId(url) {
    try {
      const u = new URL(url);
      if (u.hostname === "youtu.be") return u.pathname.slice(1).split("?")[0];
      return u.searchParams.get("v");
    } catch {
      return null;
    }
  }

  function populateQualitySelect(fmt) {
    const sel = $("qualitySelect");
    sel.innerHTML = "";

    if (fmt === "flac") {
      $("qualityLabel").textContent = "Quality";
      const opt = document.createElement("option");
      opt.value = "lossless";
      opt.textContent = "lossless";
      sel.appendChild(opt);
      return;
    }

    $("qualityLabel").textContent = fmt === "mp3" ? "Bitrate" : "Quality";
    const opts = fmt === "mp3" ? AUDIO_QUALITIES : lastQualities;
    opts.forEach(q => {
      const opt = document.createElement("option");
      opt.value = q;
      opt.textContent = fmt === "mp3" ? `${q} kbps` : (q === "2160" ? "4K" : `${q}p`);
      sel.appendChild(opt);
    });
  }

  function onFmtChange() {
    populateQualitySelect($("fmtSelect").value);
  }

  async function lookupVideo() {
    const raw = $("urlInput").value.trim();
    if (!raw) return;

    const url = cleanUrl(raw);
    $("urlInput").value = url;

    $("lookBtn").disabled = true;
    $("preview").classList.remove("show");
    $("options").classList.remove("show");
    $("dlBtn").classList.remove("show");
    setStatus("fetching video info…", "info", true);
    showProgress(true);

    try {
      const res = await fetch(`${API}/api/info?url=${encodeURIComponent(url)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "could not fetch video");

      const vid = getVideoId(url);
      $("thumb").src = vid ? `https://i.ytimg.com/vi/${vid}/hqdefault.jpg` : "";
      $("previewTitle").textContent = data.title;
      $("previewMeta").textContent = [data.channel, data.duration].filter(Boolean).join("  ·  ");
      $("previewFlag").textContent = data.playlist ? "⚠ playlist url — this backend downloads a single video" : "";

      lastQualities = (data.qualities && data.qualities.length)
        ? data.qualities.map(String)
        : DEFAULT_VIDEO_QUALITIES;
      populateQualitySelect($("fmtSelect").value);

      $("preview").classList.add("show");
      $("options").classList.add("show");
      $("dlBtn").classList.add("show");
      setStatus("", "info");
      showProgress(false);
    } catch (e) {
      setStatus(e.message, "err");
      showProgress(false);
    } finally {
      $("lookBtn").disabled = false;
    }
  }

  async function startDownload() {
    const url     = $("urlInput").value.trim();
    const fmt     = $("fmtSelect").value;
    const quality = $("qualitySelect").value;

    $("dlBtn").disabled = true;
    setStatus("preparing download… (this can take a moment)", "info", true);
    showProgress(true);

    try {
      const endpoint = `${API}/api/download?url=${encodeURIComponent(url)}&fmt=${fmt}&quality=${quality}`;
      const res = await fetch(endpoint);
      if (!res.ok) {
        let msg = "download failed";
        try { msg = (await res.json()).error || msg; } catch {}
        throw new Error(msg);
      }

      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const nameMatch = disposition.match(/filename="?([^"]+)"?/);
      const filename = nameMatch ? nameMatch[1] : `download.${fmt}`;

      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);

      setStatus("✓ download started", "ok");
      showProgress(false);
    } catch (e) {
      setStatus(e.message, "err");
      showProgress(false);
    } finally {
      $("dlBtn").disabled = false;
    }
  }

  $("urlInput").addEventListener("keydown", e => {
    if (e.key === "Enter") lookupVideo();
  });

  populateQualitySelect("mp4");
</script>
</body>
</html>
"""


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


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/api/info")
def info():
    url = clean_url(request.args.get("url", "").strip())
    if not url:
        return jsonify(error="no url"), 400

    cmd = [YTDLP, "--no-warnings", "--print",
           "%(title)s\n%(channel)s\n%(duration_string)s",
           "--playlist-items", "1"] + cookie_args() + [url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    lines = r.stdout.strip().splitlines()
    if not lines or not lines[0]:
        return jsonify(error=(r.stderr[-500:] or "lookup failed")), 400

    q_cmd = [YTDLP, "--list-formats", "--no-warnings", "--playlist-items", "1"] + cookie_args() + [url]
    qr = subprocess.run(q_cmd, capture_output=True, text=True, timeout=30)
    heights = sorted({int(m.group(1)) for m in re.finditer(r"\b(\d{3,4})p\b", qr.stdout)}, reverse=True)

    return jsonify(
        title=lines[0],
        channel=lines[1] if len(lines) > 1 else "",
        duration=lines[2] if len(lines) > 2 else "",
        playlist=is_playlist(url),
        qualities=heights,
    )


@app.route("/api/download")
def download():
    url = clean_url(request.args.get("url", "").strip())
    fmt = request.args.get("fmt", "mp4")
    quality = request.args.get("quality", "1080")
    if not url:
        return jsonify(error="no url"), 400

    cmd = [YTDLP, "--no-warnings", "--restrict-filenames"] + cookie_args() + ["-o", "-"]

    if fmt == "mp3":
        bitrate = quality if quality.isdigit() else "320"
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", bitrate]
        ext = "mp3"
    elif fmt == "flac":
        cmd += ["-x", "--audio-format", "flac"]
        ext = "flac"
    else:
        h = quality if quality.isdigit() else "1080"
        fs = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
        cmd += ["-f", fs, "--merge-output-format", "mp4"]
        ext = "mp4"

    cmd.append(url)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Peek at the first chunk BEFORE committing to a streamed response.
    # If yt-dlp failed, stdout will be empty and stderr will have the reason —
    # this is what was causing silent 0B downloads before.
    first_chunk = proc.stdout.read(65536)
    if not first_chunk:
        proc.wait()
        err_msg = proc.stderr.read().decode(errors="replace")[-800:]
        return jsonify(error=err_msg or "yt-dlp produced no output"), 500

    def generate():
        try:
            yield first_chunk
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
            proc.wait()

    headers = {
        "Content-Disposition": f'attachment; filename="download.{ext}"',
        "Content-Type": "application/octet-stream",
    }
    return Response(stream_with_context(generate()), headers=headers)


@app.route("/health")
def health():
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

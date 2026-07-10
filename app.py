import os
import re
import subprocess
import urllib.parse
from flask import Flask, request, Response, stream_with_context, jsonify, render_template_string

app = Flask(__name__)

YTDLP = "yt-dlp"
COOKIES_PATH = "/tmp/cookies.txt"


def cookie_args():
    return ["--cookies", COOKIES_PATH] if os.path.exists(COOKIES_PATH) else []

PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>proximity.</title>
<style>
  :root {
    --bg: #0d0d0d; --card: #1a1a1a; --border: #2a2a2a;
    --accent: #c8f557; --accentd: #a8d93a; --muted: #555;
    --text: #ebebeb; --red: #ff5555;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg); color: var(--text);
    font-family: 'Courier New', monospace;
    max-width: 560px; margin: 0 auto; padding: 24px;
  }
  h1 { color: var(--accent); font-size: 22px; margin-bottom: 24px; }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 16px; margin-bottom: 12px;
  }
  label { display: block; font-size: 10px; color: var(--muted); margin-bottom: 6px; letter-spacing: 1px; }
  input, select {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: 10px; border-radius: 8px; font-family: inherit;
    font-size: 13px;
  }
  .row { display: flex; gap: 8px; }
  .row > div { flex: 1; }
  button {
    width: 100%; background: var(--accent); color: var(--bg); border: none;
    padding: 14px; border-radius: 8px; font-family: inherit; font-weight: bold;
    font-size: 13px; cursor: pointer; margin-top: 8px;
  }
  button:hover { background: var(--accentd); }
  button:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }
  #meta { font-size: 12px; color: var(--muted); margin-top: 8px; white-space: pre-wrap; }
  #err { color: var(--red); font-size: 12px; margin-top: 8px; white-space: pre-wrap; }
</style>
</head>
<body>
  <h1>proximity.</h1>

  <div class="card">
    <label>URL</label>
    <input id="url" placeholder="https://youtu.be/...">
    <button id="lookupBtn" onclick="lookup()">look up</button>
    <div id="meta"></div>
    <div id="err"></div>
  </div>

  <div class="card" id="opts" style="display:none">
    <div class="row">
      <div>
        <label>FORMAT</label>
        <select id="fmt" onchange="onFmtChange()">
          <option value="mp4">mp4</option>
          <option value="mp3">mp3</option>
          <option value="flac">flac</option>
        </select>
      </div>
      <div>
        <label>QUALITY</label>
        <select id="quality"></select>
      </div>
    </div>
    <button id="dlBtn" onclick="download()">download</button>
  </div>

<script>
let qualities = [];

async function lookup() {
  const url = document.getElementById('url').value.trim();
  const meta = document.getElementById('meta');
  const err = document.getElementById('err');
  const btn = document.getElementById('lookupBtn');
  err.textContent = ''; meta.textContent = '';
  if (!url) return;

  btn.disabled = true; btn.textContent = 'looking up...';
  try {
    const r = await fetch('/api/info?url=' + encodeURIComponent(url));
    const data = await r.json();
    if (!r.ok) { err.textContent = data.error || 'lookup failed'; return; }

    meta.textContent = data.title + '\\n' + data.channel + '  ·  ' + data.duration;
    qualities = data.qualities || [];
    onFmtChange();
    document.getElementById('opts').style.display = 'block';
  } catch (e) {
    err.textContent = 'network error: ' + e;
  } finally {
    btn.disabled = false; btn.textContent = 'look up';
  }
}

function onFmtChange() {
  const fmt = document.getElementById('fmt').value;
  const q = document.getElementById('quality');
  q.innerHTML = '';
  let opts;
  if (fmt === 'mp3') {
    opts = ['320kbps', '256kbps', '192kbps', '128kbps'];
  } else if (fmt === 'flac') {
    opts = ['lossless'];
  } else {
    opts = qualities.length ? qualities.map(h => h + 'p') : ['1080p'];
  }
  opts.forEach(o => {
    const el = document.createElement('option');
    el.value = o; el.textContent = o;
    q.appendChild(el);
  });
}

function download() {
  const url = document.getElementById('url').value.trim();
  const fmt = document.getElementById('fmt').value;
  const quality = document.getElementById('quality').value.replace('p', '');
  if (!url) return;
  const link = '/api/download?url=' + encodeURIComponent(url) +
               '&fmt=' + fmt + '&quality=' + encodeURIComponent(quality);
  window.location.href = link;
}
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
    return render_template_string(PAGE)


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
        bitrate = quality.replace("kbps", "") if "kbps" in quality else "320"
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", bitrate]
        ext = "mp3"
    elif fmt == "flac":
        cmd += ["-x", "--audio-format", "flac"]
        ext = "flac"
    else:
        h = quality if quality.isdigit() else "1080"
        fs = f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best"
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

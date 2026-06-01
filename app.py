import yt_dlp
import os
import sys
from datetime import datetime
from flask import Flask, render_template, request, send_file, jsonify, after_this_request
import threading
import uuid

app = Flask(__name__)
app.config['DOWNLOAD_FOLDER'] = 'downloads'

# Create download folder
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

def format_size(bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024
    return f"{bytes:.2f} GB"

def progress_hook(d, progress_dict):
    if d['status'] == 'downloading':
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        if total:
            percentage = (downloaded / total) * 100
            progress_dict['progress'] = round(percentage, 1)
            progress_dict['speed'] = format_size(d.get('speed', 0)) + '/s'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    url = request.form.get('url')
    quality = request.form.get('quality', '720p')

    if not url:
        return jsonify({"error": "URL is required"}), 400

    # Generate unique ID for this download
    download_id = str(uuid.uuid4())
    progress = {'progress': 0, 'status': 'starting'}

    def start_download():
        try:
            ydl_opts = {
                'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], f'{download_id}_%(title)s.%(ext)s'),
                'progress_hooks': [lambda d: progress_hook(d, progress)],
                'quiet': True,
            }

            height = int(quality.replace('p', ''))
            ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                progress['title'] = info.get('title', 'Video')
                ydl.download([url])

            # Find downloaded file
            files = [f for f in os.listdir(app.config['DOWNLOAD_FOLDER']) if f.startswith(download_id)]
            if files:
                progress['file'] = files[0]
                progress['status'] = 'completed'
            else:
                progress['status'] = 'failed'

        except Exception as e:
            progress['status'] = 'failed'
            progress['error'] = str(e)

    # Run download in background
    thread = threading.Thread(target=start_download)
    thread.daemon = True
    thread.start()

    return jsonify({
        "download_id": download_id,
        "message": "Download started",
        "title": progress.get('title')
    })

@app.route('/progress/<download_id>')
def get_progress(download_id):
    # In production, use Redis/Cache. This is simplified.
    # For demo, we'll skip real-time progress tracking complexity
    return jsonify({"progress": 50})  # Placeholder

if __name__ == '__main__':
    app.run(debug=True)

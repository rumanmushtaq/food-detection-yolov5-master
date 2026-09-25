import os
import argparse
import ipaddress
import requests
import cv2
import numpy as np
import tldextract
import yt_dlp
import hashlib
import time
import base64
from urllib.parse import urlparse

from PIL import Image
from flask import Flask, request, render_template, redirect, make_response, jsonify
from pathlib import Path
from werkzeug.utils import secure_filename
from modules import get_prediction, get_video_prediction
from flask_cors import CORS, cross_origin
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app, resources={r"/api/*": {"origins": "*"}})
limiter = Limiter(get_remote_address, app=app, default_limits=["60 per minute"])

app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 1
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))


def _is_safe_url(url):
    """Reject URLs pointing to private/internal networks (SSRF protection)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        import socket
        hostname = parsed.hostname
        if not hostname:
            return False
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                return False
    except Exception:
        return False
    return True


UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'assets', 'uploads')
CSV_FOLDER = os.path.join(BASE_DIR, 'static', 'csv')
VIDEO_FOLDER = os.path.join(BASE_DIR, 'static', 'assets', 'videos')
DETECTION_FOLDER = os.path.join(BASE_DIR, 'static', 'assets', 'detections')
METADATA_FOLDER = os.path.join(BASE_DIR, 'static', 'metadata')

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CSV_FOLDER'] = CSV_FOLDER
app.config['DETECTION_FOLDER'] = DETECTION_FOLDER
app.config['VIDEO_FOLDER'] = VIDEO_FOLDER

IMAGE_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
VIDEO_ALLOWED_EXTENSIONS = {'mp4', 'avi', '3gpp', '3gp'}


def allowed_file_image(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in IMAGE_ALLOWED_EXTENSIONS


def allowed_file_video(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in VIDEO_ALLOWED_EXTENSIONS


def make_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def file_type(path):
    filename = os.path.basename(path)
    if allowed_file_image(filename):
        filetype = 'image'
    elif allowed_file_video(filename):
        filetype = 'video'
    else:
        filetype = 'invalid'
    return filetype


def download_yt(url):
    """
    Download youtube video by url and save to video folder
    """
    ydl_opts = {
        'outtmpl': os.path.join(app.config['VIDEO_FOLDER'], '%(id)s.%(ext)s'),
        'format': 'best[ext=mp4]/best',
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

    return path


def hash_video(video_path):
    """
    Hash a frame in video and use as a filename
    """
    _, ext = os.path.splitext(video_path)
    stream = cv2.VideoCapture(video_path)
    success, ori_frame = stream.read()
    stream.release()
    stream = None
    if not success or ori_frame is None:
        raise ValueError(f"Failed to read video frame from {video_path}")
    image_bytes = cv2.imencode('.jpg', ori_frame)[1].tobytes()
    filename = hashlib.sha256(image_bytes).hexdigest() + f'{ext}'
    return filename


def download(url):
    """
    Handle input url from client
    """

    ext = tldextract.extract(url)
    if ext.domain == 'youtube':

        make_dir(app.config['VIDEO_FOLDER'])

        print('Youtube')
        ori_path = download_yt(url)
        filename = hash_video(ori_path)

        path = os.path.join(app.config['VIDEO_FOLDER'], filename)

        Path(ori_path).rename(path)

    else:
        if not _is_safe_url(url):
            raise ValueError("URL points to a private or disallowed network address")

        make_dir(app.config['UPLOAD_FOLDER'])
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_2)',
                   'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                   'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
                   'Accept-Encoding': 'none',
                   'Accept-Language': 'en-US,en;q=0.8',
                   'Connection': 'keep-alive'}
        r = requests.get(url, stream=True, headers=headers, timeout=30)
        print('Image Url')

        # Get cache name by hashing image
        data = r.content
        ori_filename = url.split('/')[-1]
        _, ext = os.path.splitext(ori_filename)
        filename = hashlib.sha256(data).hexdigest() + f'{ext}'

        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        with open(path, "wb") as file:
            file.write(r.content)

    return filename, path


def save_upload(file):
    """
    Save uploaded image and video if its format is allowed
    """
    filename = secure_filename(file.filename)
    if allowed_file_image(filename):
        make_dir(app.config['UPLOAD_FOLDER'])
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    elif allowed_file_video(filename):
        make_dir(app.config['VIDEO_FOLDER'])
        path = os.path.join(app.config['VIDEO_FOLDER'], filename)

    else:
        raise ValueError(f"Unsupported file format: {filename}")

    file.save(path)

    return path


@app.route('/')
def homepage():
    return render_template("upload-file.html")


@app.route('/about')
def about_page():
    return render_template("about-page.html")


@app.route('/url')
def detect_by_url_page():
    return render_template("input-url.html")


@app.route('/webcam')
def detect_by_webcam_page():
    return render_template("webcam-capture.html")


@app.route('/analyze', methods=['POST', 'GET'])
@limiter.limit("10 per minute")
def analyze():
    if request.method == 'POST':
        try:
            out_name = None
            filepath = None
            filename = None
            filetype = None
            csv_name1 = None
            csv_name2 = None

            print("File: ", request.files)

            if 'webcam-button' in request.form:
                # Get webcam capture

                f = request.files['blob-file']
                ori_file_name = secure_filename(f.filename)
                filetype = file_type(ori_file_name)

                filename = time.strftime("%Y%m%d-%H%M%S") + '.png'
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                # save file to /static/uploads
                img = Image.open(f.stream)
                # img.show()
                img.save(filepath)

            elif 'url-button' in request.form:
                # Get image/video from input url

                url = request.form['url_link']
                filename, filepath = download(url)

                filetype = file_type(filename)

            elif 'upload-button' in request.form:
                # Get uploaded file

                f = request.files['file']
                ori_file_name = secure_filename(f.filename)
                _, ext = os.path.splitext(ori_file_name)

                filetype = file_type(ori_file_name)

                if filetype == 'image':
                    # Get cache name by hashing image
                    data = f.read()
                    filename = hashlib.sha256(data).hexdigest() + f'{ext}'

                    # Save file to /static/uploads
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    np_img = np.frombuffer(data, np.uint8)
                    img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
                    cv2.imwrite(filepath, img)

                elif filetype == 'video':
                    temp_filepath = os.path.join(
                        app.config['UPLOAD_FOLDER'], ori_file_name)
                    f.save(temp_filepath)
                    filename = hash_video(temp_filepath)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    os.rename(temp_filepath, filepath)

            # Get all inputs in form with defaults
            iou = request.form.get('threshold-range', '50')
            confidence = request.form.get('confidence-range', '25')
            model_types = request.form.get('model-types', 'yolov5s')
            enhanced = request.form.get('enhanced')
            ensemble = request.form.get('ensemble')
            ensemble = True if ensemble == 'on' else False
            enhanced = True if enhanced == 'on' else False
            model_types = model_types.lower() if model_types else 'yolov5s'
            min_conf = float(confidence)/100
            min_iou = float(iou)/100

            if filetype == 'image':
                # Get filename of detected image

                out_name = "Image Result"
                output_path = os.path.join(
                    app.config['DETECTION_FOLDER'], filename)

                filename = get_prediction(
                    filepath,
                    output_path,
                    model_name=model_types,
                    ensemble=ensemble,
                    min_conf=min_conf,
                    min_iou=min_iou,
                    enhance_labels=enhanced)

            elif filetype == 'video':
                # Get filename of detected video

                out_name = "Video Result"
                output_path = os.path.join(
                    app.config['DETECTION_FOLDER'], filename)

                filename = get_video_prediction(
                    filepath,
                    output_path,
                    model_name=model_types,
                    min_conf=min_conf,
                    min_iou=min_iou,
                    enhance_labels=enhanced)
            else:
                error_msg = "Invalid input url!!!"
                return render_template('detect-input-url.html', error_msg=error_msg)

            filename = os.path.basename(filename)
            csv_name, _ = os.path.splitext(filename)

            csv_name1 = os.path.join(
                app.config['CSV_FOLDER'], csv_name + '_info.csv')
            csv_name2 = os.path.join(
                app.config['CSV_FOLDER'], csv_name + '_info2.csv')

            if 'url-button' in request.form:
                return render_template('detect-input-url.html', out_name=out_name, fname=filename, filetype=filetype, csv_name=csv_name1, csv_name2=csv_name2)

            elif 'webcam-button' in request.form:
                return render_template('detect-webcam-capture.html', out_name=out_name, fname=filename, filetype=filetype, csv_name=csv_name1, csv_name2=csv_name2)

            return render_template('detect-upload-file.html', out_name=out_name, fname=filename, filetype=filetype, csv_name=csv_name1, csv_name2=csv_name2)

        except Exception as e:
            print(f"Error in /analyze: {e}")
            return render_template('detect-input-url.html', error_msg=f"An error occurred: {str(e)}")

    return redirect('/')


@app.route('/api', methods=['POST'])
@limiter.limit("20 per minute")
def api_call():
    if request.method == 'POST':
        response = {}
        if not request.json or 'url' not in request.json:
            response['code'] = 404
            return jsonify(response)
        else:
            # get the base64 encoded string
            url = request.json['url']
            filename, filepath = download(url)

            model_types = request.json.get('model_types', 'yolov5s')
            ensemble = request.json.get('ensemble', False)
            min_conf = request.json.get('min_conf', 0.25)
            min_iou = request.json.get('min_iou', 0.5)
            enhanced = request.json.get('enhanced', False)

            output_path = os.path.join(
                app.config['DETECTION_FOLDER'], filename)

            get_prediction(
                filepath,
                output_path,
                model_name=model_types,
                ensemble=ensemble,
                min_conf=min_conf,
                min_iou=min_iou,
                enhance_labels=enhanced)

            with open(output_path, "rb") as f:
                res_im_bytes = f.read()
            res_im_b64 = base64.b64encode(res_im_bytes).decode("utf8")
            response['res_image'] = res_im_b64
            response['filename'] = filename
            response['code'] = 200
            return jsonify(response)

    return jsonify({"code": 400})


@app.after_request
def add_header(response):
    # Prevent the client from caching the response
    if 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = 'public, no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    return response


if __name__ == '__main__':
    parser = argparse.ArgumentParser('YOLOv5 Online Food Recognition')
    parser.add_argument('--ngrok', action='store_true',
                        default=False, help="Run on local or ngrok")
    parser.add_argument('--host',  type=str,
                        default='localhost:8000', help="Local IP")
    parser.add_argument('--debug', action='store_true',
                        default=False, help="Run app in debug mode")

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    if not os.path.exists(DETECTION_FOLDER):
        os.makedirs(DETECTION_FOLDER, exist_ok=True)
    if not os.path.exists(VIDEO_FOLDER):
        os.makedirs(VIDEO_FOLDER, exist_ok=True)
    if not os.path.exists(CSV_FOLDER):
        os.makedirs(CSV_FOLDER, exist_ok=True)
    if not os.path.exists(METADATA_FOLDER):
        os.makedirs(METADATA_FOLDER, exist_ok=True)

    args = parser.parse_args()

    os.environ['CUDA_VISIBLE_DEVICES'] = '0'

    if args.ngrok:
        try:
            from flask_ngrok import run_with_ngrok
            run_with_ngrok(app)
        except ImportError:
            print("flask_ngrok not installed, running locally instead")
        app.run()
    else:
        hostname = str.split(args.host, ':')
        if len(hostname) == 1:
            port = 4000
        else:
            port = hostname[1]
        host = hostname[0]

        debug = args.debug and os.environ.get('FLASK_ENV') != 'production'
        app.run(host=host, port=port, debug=debug, use_reloader=False)

# Run: python app.py --host localhost:8000

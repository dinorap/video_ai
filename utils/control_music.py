import os
import shutil
import subprocess
from typing import List, Dict, Tuple


def _win_subprocess_kwargs():
    if os.name != 'nt':
        return {}
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    except Exception:
        si = None
    kw = {}
    try:
        kw['creationflags'] = subprocess.CREATE_NO_WINDOW
    except Exception:
        pass
    if si is not None:
        kw['startupinfo'] = si
    return kw

import sys

from flask import jsonify, send_from_directory, request
from werkzeug.utils import secure_filename


BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(BASE_DIR, "config", "Music")
UPLOAD_TMP_DIR = os.path.join(BASE_DIR, "tmp_uploads")

os.makedirs(MUSIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_TMP_DIR, exist_ok=True)

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm")


def list_music_handler():
    """
    Flask view: trả về danh sách file nhạc trong config/Music.
    """
    files: List[Dict[str, str]] = []

    if os.path.isdir(MUSIC_DIR):
        for name in os.listdir(MUSIC_DIR):
            lower = name.lower()
            if lower.endswith(AUDIO_EXTS):
                files.append(
                    {
                        "name": name,
                        "url": f"/music/{name}",
                    }
                )

    return jsonify(files)


def serve_music_handler(filename: str):
    """
    Flask view: phục vụ file nhạc cho việc "Nghe thử".
    """
    return send_from_directory(MUSIC_DIR, filename, as_attachment=False)


def delete_music_handler():
    """
    Flask view: xóa file nhạc được chọn trong config/Music.
    """
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"ok": False, "error": "missing name"}), 400

    # Không cho path traversal
    if "/" in name or "\\" in name:
        return jsonify({"ok": False, "error": "invalid name"}), 400

    path = os.path.join(MUSIC_DIR, name)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": "not found"}), 404

    try:
        os.remove(path)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True})


def add_music_handler():
    """
    Flask view: thêm nhạc vào thư mục config/Music.

    Body JSON:
    {
      "path": "/absolute/or/relative/path/to/file.(mp3|wav|mp4|...)"
    }

    - Nếu là file audio: copy thẳng vào MUSIC_DIR.
    - Nếu là file video: dùng ffmpeg tách audio ra (mp3) rồi lưu vào MUSIC_DIR.
    """
    data = request.get_json(silent=True) or {}
    src_path = data.get("path")

    if not src_path:
        return jsonify({"ok": False, "error": "missing path"}), 400

    src_path = os.path.expanduser(src_path)
    if not os.path.isabs(src_path):
        src_path = os.path.join(BASE_DIR, src_path)

    if not os.path.isfile(src_path):
        return jsonify({"ok": False, "error": "source file not found"}), 404

    ok, payload, status = _process_source_to_music(src_path)
    if not ok:
        return jsonify({"ok": False, "error": payload}), status

    return jsonify({"ok": True, **payload}), status


def upload_music_handler():
    """
    Flask view: upload file (audio hoặc video) rồi đưa vào thư mục config/Music.

    Form-data:
      file: <audio|video>
      desired_name: <optional string>
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "missing file"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"ok": False, "error": "empty filename"}), 400

    desired_name_raw = request.form.get("desired_name", "")
    desired_name = secure_filename(desired_name_raw) if desired_name_raw else ""

    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({"ok": False, "error": "invalid filename"}), 400

    temp_path = os.path.join(UPLOAD_TMP_DIR, filename)
    file.save(temp_path)

    try:
        ok, payload, status = _process_source_to_music(temp_path, desired_name=desired_name)
    finally:
        # luôn cố gắng xóa file tạm
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass

    if not ok:
        return jsonify({"ok": False, "error": payload}), status

    return jsonify({"ok": True, **payload}), status


def _process_source_to_music(
    src_path: str, *, desired_name: str = ""
) -> Tuple[bool, str | Dict[str, str], int]:
    """
    Xử lý file nguồn (audio hoặc video) thành file audio trong MUSIC_DIR.

    Trả về:
      (True, {"name": ..., "url": ...}, 200) nếu thành công
      (False, "error message", http_status) nếu lỗi
    """
    _, ext = os.path.splitext(src_path)
    ext_lower = ext.lower()

    base_name = os.path.basename(src_path)
    name_without_ext, _ = os.path.splitext(base_name)

    desired_base, desired_ext = ("", "")
    if desired_name:
        desired_base, desired_ext = os.path.splitext(desired_name)
        if desired_base:
            name_without_ext = desired_base

    # Audio: copy trực tiếp
    if ext_lower in AUDIO_EXTS:
        target_ext = desired_ext.lower() if desired_ext else ext_lower
        target_name = f"{name_without_ext}{target_ext}"
        target_path = os.path.join(MUSIC_DIR, target_name)

        counter = 1
        while os.path.exists(target_path):
            target_name = f"{name_without_ext}_{counter}{target_ext}"
            target_path = os.path.join(MUSIC_DIR, target_name)
            counter += 1

        try:
            shutil.copy2(src_path, target_path)
        except OSError as exc:
            return False, str(exc), 500

        return True, {"name": target_name, "url": f"/music/{target_name}"}, 200

    # Video: dùng ffmpeg tách audio
    if ext_lower in VIDEO_EXTS:
        target_name = f"{name_without_ext}.mp3"
        target_path = os.path.join(MUSIC_DIR, target_name)

        counter = 1
        while os.path.exists(target_path):
            target_name = f"{name_without_ext}_{counter}.mp3"
            target_path = os.path.join(MUSIC_DIR, target_name)
            counter += 1

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            src_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            target_path,
        ]

        try:
            result = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, **_win_subprocess_kwargs()
            )
        except FileNotFoundError:
            return False, "ffmpeg not found in PATH", 500

        if result.returncode != 0:
            return False, result.stderr.strip(), 500

        return True, {"name": target_name, "url": f"/music/{target_name}"}, 200

    return False, "unsupported file type", 400


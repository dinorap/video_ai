import os
import json
import uuid
import asyncio
from datetime import datetime
from flask import jsonify, request
from werkzeug.utils import secure_filename
from utils.clone_video import generate_prompt_json

import sys

from utils.path_helper import (
    BASE_DIR as _BASE,
    CONFIG_FILE,
    SCRIPT_DIR as _SCRIPT,
    TASKS_FILE,
    TEMP_DIR,
    TEMP_VIDEO_DIR as _TEMP_VIDEO,
    pstr,
)

BASE_DIR = pstr(_BASE)
SCRIPT_DIR = pstr(_SCRIPT)
TEMP_VIDEO_DIR = pstr(_TEMP_VIDEO)
TEMP_DIR = pstr(TEMP_DIR)
CONFIG_FILE_PATH = pstr(CONFIG_FILE)
TASKS_FILE_PATH = pstr(TASKS_FILE)
os.makedirs(SCRIPT_DIR, exist_ok=True)
os.makedirs(TEMP_VIDEO_DIR, exist_ok=True)


def _read_json_file(path: str):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json_file(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_task_status(task_id, status, error=None, result_file=None, **extra_fields):
    """
    Cập nhật trạng thái task trong config/tasks.json
    """
    tasks_file = TASKS_FILE_PATH
    try:
        tasks = _read_json_file(tasks_file)
        if not isinstance(tasks, list):
            tasks = []
        
        for task in tasks:
            if task.get("id") == task_id:
                task["status"] = status
                if error:
                    task["error"] = error
                if result_file:
                    task["result_file"] = result_file
                if extra_fields:
                    for k, v in extra_fields.items():
                        if not k:
                            continue
                        task[str(k)] = v
                break
        
        _write_json_file(tasks_file, tasks)
    except Exception as e:
        print(f"Error updating task status: {e}")

def create_image_task(task_name, model):
    """
    Tạo một task mới trong config/tasks.json
    """
    tasks_file = TASKS_FILE_PATH
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "name": task_name,
        "model": model,
        "status": "processing",
        "created_at": datetime.now().isoformat(),
    }
    
    try:
        tasks = _read_json_file(tasks_file)
        if not isinstance(tasks, list):
            tasks = []
        tasks.append(task)
        _write_json_file(tasks_file, tasks)
    except Exception as e:
        print(f"Error creating task: {e}")
        
    return task_id


def create_video_task(task_name, model):
    tasks_file = TASKS_FILE_PATH
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "name": task_name,
        "model": model,
        "status": "processing",
        "created_at": datetime.now().isoformat(),
    }

    try:
        tasks = _read_json_file(tasks_file)
        if not isinstance(tasks, list):
            tasks = []
        tasks.append(task)
        _write_json_file(tasks_file, tasks)
    except Exception as e:
        print(f"Error creating task: {e}")

    return task_id
def upload_temp_video_handler():
    """
    Flask view: upload/copy selected video into temp_video folder.
    Multipart: file=<video>
    Keeps only one file, always overwrites.
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    original_name = secure_filename(file.filename)
    _, ext = os.path.splitext(original_name)
    ext = ext or ".mp4"

    target_name = f"temp_video{ext.lower()}"
    target_path = os.path.join(TEMP_VIDEO_DIR, target_name)

    try:
        for name in os.listdir(TEMP_VIDEO_DIR):
            try:
                os.remove(os.path.join(TEMP_VIDEO_DIR, name))
            except Exception:
                pass

        file.save(target_path)
        return jsonify(
            {
                "ok": True,
                "filename": target_name,
                "video_path": target_path,
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def clear_tasks_handler():
    tasks_file = TASKS_FILE_PATH
    try:
        _write_json_file(tasks_file, [])
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def list_scripts_handler():
    """
    Flask view: trả về danh sách tên file .txt trong config/KichBan (bao gồm cả .txt để phân biệt)
    """
    files = []
    if os.path.isdir(SCRIPT_DIR):
        for name in os.listdir(SCRIPT_DIR):
            if name.lower().endswith(".txt"):
                files.append(name)  # giữ nguyên tên có .txt
    return jsonify(files)


def load_script_handler():
    """
    Flask view: đọc nội dung file .txt và parse JSON scenes.
    Query param: ?name=<filename_with_ext>
    """
    name = request.args.get("name")
    if not name:
        return jsonify({"ok": False, "error": "Missing name"}), 400
    
    # Đảm bảo tên file có .txt
    if not name.lower().endswith(".txt"):
        name += ".txt"
    
    path = os.path.join(SCRIPT_DIR, name)
    
    # Đảm bảo file nằm trong SCRIPT_DIR (ngăn path traversal)
    if not os.path.abspath(path).startswith(os.path.abspath(SCRIPT_DIR)):
        return jsonify({"ok": False, "error": "Invalid name"}), 400
    
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "File not found"}), 404
    
    try:
        # Read file with BOM handling
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        
        # Remove BOM if present
        if content.startswith('\ufeff'):
            content = content[1:]
        
        scenes = json.loads(content)
        try:
            from utils.video_reference_prompts import strip_legacy_reference_block
            if isinstance(scenes, list):
                for sc in scenes:
                    if isinstance(sc, dict) and sc.get("prompt"):
                        sc["prompt"] = strip_legacy_reference_block(str(sc.get("prompt") or ""))
        except Exception:
            pass
        return jsonify({"ok": True, "scenes": scenes})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def save_script_handler():
    """
    Flask view: lưu scenes vào file .txt.
    Body JSON: {"name": "filename", "scenes": [...]}
    """
    data = request.get_json() or {}
    name = data.get("name")
    scenes = data.get("scenes")
    
    if not name or not isinstance(scenes, list):
        return jsonify({"ok": False, "error": "Invalid request"}), 400

    # Nếu tên chưa có .txt thì thêm vào
    if not name.lower().endswith(".txt"):
        filename = name + ".txt"
    else:
        filename = name
    path = os.path.join(SCRIPT_DIR, filename)

    # Đảm bảo file nằm trong SCRIPT_DIR (ngăn path traversal)
    if not os.path.abspath(path).startswith(os.path.abspath(SCRIPT_DIR)):
        return jsonify({"ok": False, "error": "Invalid name"}), 400

    try:
        # Write JSON without BOM
        json_content = json.dumps(scenes, ensure_ascii=False, indent=2)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json_content)

        # If user saved successfully, remove temporary prompt file
        try:
            temp_prompt_path = os.path.join(SCRIPT_DIR, "_temp_prompt.txt")
            if os.path.exists(temp_prompt_path):
                os.remove(temp_prompt_path)
        except Exception:
            pass
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def delete_script_handler():
    """
    Flask view: xóa file script
    Body JSON: {"name": "filename.txt"}
    """
    data = request.get_json() or {}
    name = data.get("name")
    if not name:
        return jsonify({"ok": False, "error": "Missing name"}), 400
    
    # Đảm bảo tên file có .txt
    if not name.lower().endswith(".txt"):
        name += ".txt"
    
    file_path = os.path.join(SCRIPT_DIR, name)
    
    if not os.path.exists(file_path):
        return jsonify({"ok": False, "error": "File not found"}), 404
    
    try:
        os.remove(file_path)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def generate_script_handler():
    """
    Flask view: generate script from video using clone_video.py
    Body JSON: {
        "video_path": "path/to/video",
        "model": "gpt-4.1-mini",
        "api_key": "your-api-key",
        "target_product": "product name",
        "language": "Vietnamese"
    }
    """
    data = request.get_json() or {}
    video_path = data.get("video_path")
    model = data.get("model", "gemini-2.5-flash")
    api_key = data.get("api_key")
    target_product = data.get("target_product", "Video Clone")
    language = data.get("language", "Vietnamese")
    cleanup_temp = bool(data.get("cleanup_temp", False))

    # Always persist model + api_key to config/config.json (even if generation fails)
    try:
        config_file = CONFIG_FILE_PATH
        cfg = _read_json_file(config_file)
        cfg["cloneVideoModel"] = model
        cfg["cloneVideoApiKey"] = api_key
        _write_json_file(config_file, cfg)
    except Exception:
        pass
    
    if not video_path:
        return jsonify({"ok": False, "error": "Missing video_path"}), 400

    # Normalize: allow sending just filename (e.g. temp_video.mp4) and resolve into TEMP_VIDEO_DIR
    try:
        video_path = str(video_path or '').strip()
    except Exception:
        video_path = video_path
    try:
        if video_path and not os.path.isabs(video_path) and ('/' not in video_path) and ('\\' not in video_path):
            candidate = os.path.join(TEMP_VIDEO_DIR, video_path)
            if os.path.exists(candidate):
                video_path = candidate
    except Exception:
        pass
    
    if not api_key:
        return jsonify({"ok": False, "error": "Missing API key"}), 400
    
    if not os.path.exists(video_path):
        return jsonify({"ok": False, "error": "Video file not found"}), 400

    tasks_file = TASKS_FILE_PATH
    tasks = []
    try:
        tasks = _read_json_file(tasks_file)
        if not isinstance(tasks, list):
            tasks = []
    except Exception:
        tasks = []

    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "name": f"Clone Video - {os.path.basename(video_path)}",
        "model": model,
        "video_path": video_path,
        "status": "processing",
        "created_at": datetime.now().isoformat(),
    }
    tasks.append(task)
    try:
        _write_json_file(tasks_file, tasks)
    except Exception:
        pass

    def _safe_remove_video(path: str):
        try:
            if not path:
                return
            abs_path = os.path.abspath(path)
            abs_temp_dir = os.path.abspath(TEMP_VIDEO_DIR)
            if abs_path.startswith(abs_temp_dir) and os.path.isfile(abs_path):
                os.remove(abs_path)
        except Exception:
            pass

    try:
        result = generate_prompt_json(
            api_key=api_key,
            model=model,
            video_path=video_path,
            target_product=target_product,
            language=language,
            audio_mode="silent"
        )

        parsed = json.loads(result)

        scenes = []
        if isinstance(parsed, list):
            scenes = parsed
        elif isinstance(parsed, dict):
            if parsed.get("ok") is False:
                task["status"] = "failed"
                task["error"] = parsed.get("error", "Unknown error")
                try:
                    _write_json_file(tasks_file, tasks)
                except Exception:
                    pass
                return jsonify({"ok": False, "error": task["error"]}), 500

            # Try multiple possible keys
            for k in ("scenes", "Scenes", "SCENES", "data", "items"):
                v = parsed.get(k)
                if isinstance(v, list):
                    scenes = v
                    break

            # Fallback: pick first list-like value in dict
            if not scenes:
                try:
                    for _k, _v in parsed.items():
                        if isinstance(_v, list):
                            scenes = _v
                            break
                except Exception:
                    scenes = []
        else:
            task["status"] = "failed"
            task["error"] = "Invalid AI response format"
            try:
                _write_json_file(tasks_file, tasks)
            except Exception:
                pass
            return jsonify({"ok": False, "error": task["error"]}), 500

        if not scenes:
            task["status"] = "failed"
            task["error"] = "AI returned empty scenes"
            try:
                dbg_dir = TEMP_DIR
                os.makedirs(dbg_dir, exist_ok=True)
                dbg_path = os.path.join(dbg_dir, f"clone_video_ai_empty_{task_id}.txt")
                with open(dbg_path, "w", encoding="utf-8") as f:
                    f.write(str(result or ""))
                task["debug_file"] = dbg_path
            except Exception:
                pass
            try:
                _write_json_file(tasks_file, tasks)
            except Exception:
                pass
            return jsonify({"ok": False, "error": task["error"]}), 500

        temp_prompt_path = ""
        try:
            temp_prompt_path = os.path.join(SCRIPT_DIR, "_temp_prompt.txt")
            with open(temp_prompt_path, "w", encoding="utf-8") as f:
                json.dump(scenes, f, ensure_ascii=False, indent=2)
        except Exception:
            temp_prompt_path = ""

        task["status"] = "completed"
        if temp_prompt_path:
            task["result_file"] = temp_prompt_path
        try:
            _write_json_file(tasks_file, tasks)
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "task_id": task_id,
            "scenes": scenes
        })
    except Exception as exc:
        task["status"] = "failed"
        task["error"] = str(exc)
        try:
            _write_json_file(tasks_file, tasks)
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        if cleanup_temp:
            _safe_remove_video(video_path)


def list_tasks_handler():
    """
    Flask view: trả về danh sách tác vụ từ config/tasks.json
    """
    tasks_file = TASKS_FILE_PATH
    
    if not os.path.exists(tasks_file):
        return jsonify({"ok": True, "tasks": []})
    
    try:
        with open(tasks_file, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        
        # Sort by created_at descending
        tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return jsonify({"ok": True, "tasks": tasks})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def save_config_handler():
    """
    Flask view: save additional config to config.json
    Body JSON: {"cloneVideoModel": "...", "cloneVideoApiKey": "..."}
    """
    data = request.get_json() or {}
    
    try:
        config_file = CONFIG_FILE_PATH
        
        # Read existing config
        config = {}
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        
        # Update with new values (version chi o version.py, khong luu trong config)
        config.update(data)
        config.pop("VERSION", None)

        # Save back
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def cleanup_temp_handler():
    """
    Flask view: delete temp file
    Body JSON: {"temp_file": "path/to/temp_file.json"}
    """
    data = request.get_json() or {}
    temp_file = data.get("temp_file")
    
    if not temp_file:
        return jsonify({"ok": False, "error": "Missing temp_file"}), 400
    
    try:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

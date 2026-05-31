from flask import Flask, jsonify, send_from_directory, request, make_response

import asyncio
import base64
import uuid
import os
import sys
import subprocess
import threading
import tempfile
from typing import Dict, Any

import json
import time
import hashlib

from utils.path_helper import (
    BASE_DIR,
    BUNDLE_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    GENERATED_DIR,
    ICO_DIR,
    MUSIC_DIR,
    TASKS_FILE,
    TEMP_VIDEO_DIR,
    TEMPLACES_DIR,
    THEME_IMG_DIR,
    ensure_runtime_dirs,
    get_paths_diagnostic,
    init_frozen_flag,
    is_running_as_exe,
    migrate_legacy_paths,
    pstr,
    setup_runtime_cwd,
)

init_frozen_flag()
setup_runtime_cwd()
migrate_legacy_paths()
ensure_runtime_dirs()

# ============================================================================
# LOG SUPPRESS SETUP
# ============================================================================
from utils.log_suppress import install_print_hook, load_suppress_from_settings
install_print_hook()

try:
    load_suppress_from_settings()
except Exception:
    pass
# ============================================================================

# ============================================================================
# OTA UPDATE SETUP
# ============================================================================
from version import (
    CURRENT_VERSION,
    GITHUB_REPO,
    GITHUB_USER,
    LICENSE_PRODUCT_ID,
    UPDATE_ZIP_NAME,
)
from utils import license_service as lic_svc

# OTA: GitHub release (VideoCreator.zip + update.json) — không phụ thuộc fastapi
from utils.ota_install import cleanup_old_update_artifacts, download_and_install, is_updating

cleanup_old_update_artifacts()
UPDATER_AVAILABLE = True
updater = None


def _github_check_for_update() -> Dict[str, Any]:
    """Cần đủ VideoCreator.zip + update.json trên GitHub release (tag = CURRENT_VERSION trong version.py)."""
    import requests
    from packaging import version as pkg_version

    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return {"has_update": False, "error": f"github_status_{resp.status_code}"}
        data = resp.json()
        latest_tag = str(data.get("tag_name") or "").strip()
        if not latest_tag:
            return {"has_update": False, "error": "no_tag_name"}

        try:
            if pkg_version.parse(latest_tag) <= pkg_version.parse(CURRENT_VERSION):
                return {
                    "has_update": False,
                    "current_version": CURRENT_VERSION,
                    "latest_version": latest_tag,
                }
        except Exception:
            pass

        zip_url = None
        json_url = None
        found_assets: list[str] = []
        for asset in data.get("assets") or []:
            name = str((asset or {}).get("name") or "")
            if name:
                found_assets.append(name)
            if name == UPDATE_ZIP_NAME:
                zip_url = (asset or {}).get("browser_download_url")
            elif name == "update.json":
                json_url = (asset or {}).get("browser_download_url")

        if zip_url and not json_url:
            fallback = (
                f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/download/"
                f"{latest_tag}/update.json"
            )
            try:
                head = requests.head(fallback, timeout=10, allow_redirects=True)
                if head.status_code == 200:
                    json_url = fallback
            except Exception:
                pass

        if zip_url and json_url:
            return {
                "has_update": True,
                "version": latest_tag,
                "current_version": CURRENT_VERSION,
                "download_url": zip_url,
                "meta_url": json_url,
                "body": data.get("body", "") or "",
            }

        return {
            "has_update": False,
            "error": "missing_release_assets",
            "expected": [UPDATE_ZIP_NAME, "update.json"],
            "found_assets": found_assets,
            "current_version": CURRENT_VERSION,
            "latest_version": latest_tag,
            "hint": "Chay: python pack_release_update.py roi upload VideoCreator.zip + update.json len GitHub Release (tag phai trung version.py).",
        }
    except Exception as exc:
        return {"has_update": False, "error": str(exc)}

try:
    from utils.runtime_paths import init_runtime_environment
    init_runtime_environment()
except Exception:
    pass
# ============================================================================

try:
    os.environ.setdefault('NODE_OPTIONS', '--no-warnings')
except Exception:
    pass

from utils.control_music import (
    list_music_handler,
    serve_music_handler,
    delete_music_handler,
    add_music_handler,
    upload_music_handler,
)

from utils.control_ffmpeg import (
    serve_transcoded_handler,
    transcode_video_handler,
    transcode_video_from_path_handler,
    extract_frame_handler,
    apply_background_music,
)

from utils.control_script import (
    list_scripts_handler,
    load_script_handler,
    save_script_handler,
    delete_script_handler,
    generate_script_handler,
    list_tasks_handler,
    clear_tasks_handler,
    save_config_handler,
    cleanup_temp_handler,
    upload_temp_video_handler,
)

EXE_DIR = pstr(BASE_DIR)
MUSIC_DIR = pstr(MUSIC_DIR)
THEME_IMG_DIR = pstr(THEME_IMG_DIR)
GENERATED_DIR = pstr(GENERATED_DIR)
CONFIG_FILE_PATH = pstr(CONFIG_FILE)
TASKS_FILE_PATH = pstr(TASKS_FILE)
TEMP_VIDEO_DIR_PATH = pstr(TEMP_VIDEO_DIR)

app = Flask(__name__, static_folder=EXE_DIR, static_url_path="/static")

# ============================================================================
# OTA UPDATE FLASK ROUTES
# ============================================================================
# dinorap-updater trả về FastAPI router, không tương thích với Flask
# Tạo Flask routes thủ công để wrap các phương thức của updater

@app.route('/api/version', methods=['GET'])
def get_version():
    """Phiên bản từ version.py (build vào exe), không đọc config.json."""
    return jsonify({
        "version": CURRENT_VERSION,
        "source": "version.py",
        "exe": bool(is_running_as_exe()),
        "mode": "exe" if is_running_as_exe() else "dev",
    })

@app.route('/api/update/check', methods=['GET'])
def check_for_update():
    """Kiểm tra update mới (VideoCreator.zip + update.json)"""
    try:
        return jsonify(_github_check_for_update())
    except Exception as e:
        return jsonify({"has_update": False, "error": str(e)}), 500


@app.route('/api/update/perform', methods=['POST'])
def perform_update():
    """Tải ZIP, verify SHA256 từ update.json, xcopy ghi đè file có trong bản mới, restart."""
    try:
        if not is_running_as_exe():
            return jsonify({
                "success": False,
                "error": "Cập nhật OTA chỉ chạy trên bản EXE đã build",
            }), 400

        info = _github_check_for_update()
        if not info.get("has_update"):
            err = info.get("error") or "Không có bản cập nhật"
            return jsonify({"success": False, "error": err}), 400

        if is_updating():
            return jsonify({"success": False, "error": "Đang cập nhật, vui lòng chờ..."}), 409

        def _run_install():
            try:
                download_and_install(info)
            except Exception as exc:
                print(f"[Updater] Install failed: {exc}")

        threading.Thread(target=_run_install, daemon=True).start()
        return jsonify({
            "success": True,
            "message": "Đang tải và cài đặt. Ứng dụng sẽ tự khởi động lại...",
            "version": info.get("version"),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LICENSE ROUTES
# ============================================================================

@app.before_request
def _license_gate():
    return lic_svc.license_middleware()


@app.route('/api/license/status', methods=['GET'])
def license_status():
    return jsonify(lic_svc.get_license_status())


@app.route('/api/license/config', methods=['GET'])
def license_config():
    return jsonify({
        'product_id': LICENSE_PRODUCT_ID,
        'server_url': lic_svc.get_license_server_url(),
    })


@app.route('/api/license/activate', methods=['POST'])
def license_activate():
    data = request.get_json(silent=True) or {}
    key = (data.get('license_key') or data.get('key') or '').strip()
    ok, msg, status = lic_svc.activate_license_key(key)
    body = {'ok': ok, 'message': msg, **(status or {})}
    return jsonify(body), (200 if ok else 400)


# Exception handler cho PermissionError
@app.errorhandler(PermissionError)
def handle_permission_error(e):
    return jsonify({
        "error": "Permission denied",
        "message": str(e),
        "hint": "Try running as administrator or check file permissions"
    }), 403

# ============================================================================


def _run_coro_blocking(coro):
    try:
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            try:
                loop.close()
            except Exception:
                pass
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
    except Exception:
        raise


_CREATE_IMAGES_CANCEL = threading.Event()
_CREATE_IMAGES_CANCEL_LOCK = threading.Lock()

_ASYNC_IMAGE_BATCHES_LOCK = threading.Lock()
_ASYNC_IMAGE_BATCHES: Dict[str, Any] = {}

_CREATE_VIDEOS_CANCEL = threading.Event()
_CREATE_VIDEOS_CANCEL_LOCK = threading.Lock()

_ASYNC_VIDEO_BATCHES_LOCK = threading.Lock()
_ASYNC_VIDEO_BATCHES: Dict[str, Any] = {}

_ASYNC_SINGLE_VIDEO_TASKS_LOCK = threading.Lock()
_ASYNC_SINGLE_VIDEO_TASKS: Dict[str, Any] = {}

# Client heartbeat: used to shutdown the server when the UI window is closed
_LAST_CLIENT_PING_TS = 0.0
_CLIENT_PING_LOCK = threading.Lock()


def _force_exit_later(delay_sec: float = 0.4) -> None:
    try:
        delay = float(delay_sec or 0.0)
    except Exception:
        delay = 0.4

    def _kill():
        try:
            time.sleep(max(0.0, delay))
        except Exception:
            pass
        try:
            from utils.control_profile import close_global_browser
            try:
                close_global_browser('video')
            except Exception:
                pass
            try:
                close_global_browser('image')
            except Exception:
                pass
            try:
                close_global_browser('default')
            except Exception:
                pass
        except Exception:
            pass
        try:
            os._exit(0)
        except Exception:
            pass

    try:
        threading.Thread(target=_kill, daemon=True).start()
    except Exception:
        try:
            os._exit(0)
        except Exception:
            pass


def _mark_tasks_cancelled_best_effort(task_ids=None):
    try:
        tasks_file = TASKS_FILE_PATH
        if not os.path.exists(tasks_file):
            return

        with open(tasks_file, 'r', encoding='utf-8') as f:
            raw = f.read()
        try:
            import json
            tasks_data = json.loads(raw) if raw else []
        except Exception:
            tasks_data = []

        if not isinstance(tasks_data, list):
            return

        wanted = None
        if isinstance(task_ids, (list, tuple, set)):
            wanted = {str(x) for x in task_ids if str(x)}

        changed = False
        for t in tasks_data:
            try:
                tid = str(t.get('id') or '')
                if wanted is not None and tid not in wanted:
                    continue
                st = str(t.get('status') or '').lower()
                if st in ('processing', 'pending'):
                    t['status'] = 'cancelled'
                    t['error'] = 'Đã hủy'
                    changed = True
            except Exception:
                pass

        if changed:
            with open(tasks_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _safe_folder_name(name: str) -> str:
    name = (name or '').strip()
    if not name:
        return 'default'
    # keep it simple and filesystem-safe
    allowed = []
    for ch in name:
        if ch.isalnum() or ch in ('-', '_'):
            allowed.append(ch)
        elif ch.isspace():
            allowed.append('-')
    out = ''.join(allowed).strip('-')
    return out or 'default'


def _music_url_to_abs_path(music_url: str) -> str:
    u = str(music_url or '').strip()
    if not u:
        return ''
    if u.startswith('/music/'):
        name = u[len('/music/'):]
        if not name or '/' in name or '\\' in name:
            return ''
        p = os.path.join(MUSIC_DIR, name)
        return p if os.path.isfile(p) else ''
    return ''


def _parse_volume_percent(value, default: int = 60) -> int:
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, v))


def _write_data_url_to_file(data_url: str, out_path: str) -> None:
    if not data_url or not data_url.startswith('data:image'):
        raise ValueError('Only data:image/* base64 is supported')
    try:
        header, b64 = data_url.split(',', 1)
        content = base64.b64decode(b64)
    except Exception as exc:
        raise ValueError('Invalid base64 image') from exc

    with open(out_path, 'wb') as f:
        f.write(content)


@app.route("/")
def index():
    # Phục vụ giao diện chính
    return send_from_directory(os.path.join(pstr(TEMPLACES_DIR), 'html'), "index.html")


@app.route('/templaces/<path:filename>')
def serve_templates(filename: str):
    return send_from_directory(pstr(TEMPLACES_DIR), filename)


@app.route('/config/<path:filename>')
def serve_config(filename: str):
    return send_from_directory(pstr(CONFIG_DIR), filename)


@app.route('/generated/<path:filename>')
def serve_generated(filename: str):
    return send_from_directory(GENERATED_DIR, filename)


@app.route('/ico/<path:filename>')
def serve_ico(filename: str):
    try:
        p1 = pstr(ICO_DIR)
        if os.path.exists(os.path.join(p1, filename)):
            resp = make_response(send_from_directory(p1, filename))
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            return resp

        p2 = os.path.join(pstr(BUNDLE_DIR), 'ico')
        if os.path.exists(os.path.join(p2, filename)):
            resp = make_response(send_from_directory(p2, filename))
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            return resp
    except Exception:
        pass
    return ('', 404)


@app.route('/favicon.ico')
def favicon():
    return serve_ico('logo.ico')


@app.route('/api/debug/runtime')
def get_runtime_debug():
    """Debug endpoint để xác minh app đang chạy từ đâu (hữu ích khi OTA update)"""
    info = get_paths_diagnostic()
    info.update({
        "version": CURRENT_VERSION,
        "updater_available": UPDATER_AVAILABLE,
    })
    return jsonify(info)


@app.route('/debug_browser', methods=['GET'])
def debug_browser():
    try:
        from utils.grok.profile import PROFILE_DIR
        from utils.control_profile import _GLOBAL_BROWSER, init_global_browser

        init_global_browser()

        def _safe_int(x):
            try:
                return int(x)
            except Exception:
                return 0

        async def _info():
            ctx = await _GLOBAL_BROWSER.get_context_async()
            pages = 0
            try:
                pages = len(ctx.pages) if ctx else 0
            except Exception:
                pages = 0
            return {
                'profile_dir': PROFILE_DIR,
                'has_context': ctx is not None,
                'pages': pages,
                'cdp_connected': _GLOBAL_BROWSER._browser is not None,
            }

        info = _GLOBAL_BROWSER.run(_info(), timeout=10)
        return jsonify({'ok': True, 'info': info})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/debug_routes', methods=['GET'])
def debug_routes():
    try:
        items = []
        for r in app.url_map.iter_rules():
            try:
                items.append({'rule': str(r.rule), 'methods': sorted([m for m in (r.methods or set()) if m])})
            except Exception:
                pass
        items.sort(key=lambda x: x.get('rule', ''))
        return jsonify({'ok': True, 'routes': items})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


# Exception handler cho Access Denied errors từ update
@app.errorhandler(PermissionError)
def access_denied_handler(exc: PermissionError):
    """Catch Access Denied errors từ update và trả về thông báo hữu ích"""
    error_msg = str(exc)
    
    if request and "/api/update/" in str(request.url):
        if "Access is denied" in error_msg or "WinError 5" in error_msg:
            return jsonify({
                "error": "Access Denied",
                "message": "Không thể update vì file đang được sử dụng. Vui lòng đóng ứng dụng và thử lại.",
                "solution": "Đóng ứng dụng hoàn toàn, chờ vài giây, rồi chạy lại và thử update.",
                "original_error": error_msg
            }), 500
    
    # Nếu không phải update endpoint, raise lại exception
    raise exc


@app.route('/api/log/verify_password', methods=['POST'])
def verify_log_password():
    """Xác thực mật khẩu để truy cập cài đặt log"""
    try:
        payload = request.get_json(silent=True) or {}
        password = str(payload.get('password') or '').strip()
        
      
        correct_hash = '0554a5df02ee12f1ae36a51caaef34a31deb9458a48b629da554a2b322466f4a'
        input_hash = hashlib.sha256(password.encode()).hexdigest()
        
        if input_hash == correct_hash:
            return jsonify({'ok': True, 'verified': True})
        else:
            return jsonify({'ok': True, 'verified': False, 'error': 'Mật khẩu không đúng'})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/api/log/status', methods=['GET'])
def get_log_status():
    """Lấy trạng thái hiện tại của log suppression"""
    try:
        from utils.log_suppress import is_suppress_all_logs
        
        config_path = CONFIG_FILE_PATH
        suppress_enabled = False
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            suppress_enabled = bool(data.get('SUPPRESS_ALL_LOGS', False))
        
        return jsonify({
            'ok': True,
            'suppress_enabled': suppress_enabled,
            'runtime_status': is_suppress_all_logs()
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/api/log/toggle', methods=['POST'])
def toggle_log_suppression():
    """Bật/tắt log suppression"""
    try:
        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get('enabled', False))
        
        from utils.log_suppress import set_suppress_all_logs
        
        # Update runtime
        set_suppress_all_logs(enabled)
        
        # Update config file
        config_path = CONFIG_FILE_PATH
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}
        
        data['SUPPRESS_ALL_LOGS'] = enabled
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            'ok': True,
            'suppress_enabled': enabled,
            'message': 'Đã tắt log' if enabled else 'Đã bật log'
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/task_video', methods=['GET'])
def task_video():
    try:
        task_id = str(request.args.get('task_id') or '').strip()
        if not task_id:
            return jsonify({'ok': False, 'error': 'Missing task_id'}), 400

        tasks_file = TASKS_FILE_PATH
        if not os.path.exists(tasks_file):
            return jsonify({'ok': False, 'error': 'tasks.json not found'}), 404

        with open(tasks_file, 'r', encoding='utf-8') as f:
            raw = f.read()

        try:
            import json
            tasks_data = json.loads(raw) if raw else []
        except Exception:
            tasks_data = []

        task = None
        for t in tasks_data if isinstance(tasks_data, list) else []:
            if str(t.get('id') or '') == task_id:
                task = t
                break

        if not task:
            return jsonify({'ok': False, 'error': 'Task not found'}), 404

        status = str(task.get('status') or '')
        out = {
            'ok': True,
            'status': status,
            'error': task.get('error'),
            'progress_percent': task.get('progress_percent'),
            'scene_index': task.get('scene_index'),
            'total_scenes': task.get('total_scenes'),
            'phase': task.get('phase'),
            'result_url': task.get('result_url'),
        }

        return jsonify(out)
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/task_image', methods=['GET'])
def task_image():
    try:
        task_id = str(request.args.get('task_id') or '').strip()
        if not task_id:
            return jsonify({'ok': False, 'error': 'Missing task_id'}), 400

        tasks_file = TASKS_FILE_PATH
        if not os.path.exists(tasks_file):
            return jsonify({'ok': False, 'error': 'tasks.json not found'}), 404

        with open(tasks_file, 'r', encoding='utf-8') as f:
            tasks = f.read()
        try:
            import json
            tasks_data = json.loads(tasks) if tasks else []
        except Exception:
            tasks_data = []

        task = None
        for t in tasks_data if isinstance(tasks_data, list) else []:
            if str(t.get('id') or '') == task_id:
                task = t
                break

        if not task:
            return jsonify({'ok': False, 'error': 'Task not found'}), 404

        status = str(task.get('status') or '')
        if status != 'completed':
            return jsonify({'ok': True, 'status': status, 'error': task.get('error')})

        result_file = str(task.get('result_file') or '')
        if not result_file or not os.path.exists(result_file):
            return jsonify({'ok': True, 'status': status, 'error': 'Result file not found'})

        try:
            if os.path.getsize(result_file) <= 0:
                return jsonify({'ok': True, 'status': 'failed', 'error': 'Result file is empty'})
        except Exception as exc:
            return jsonify({'ok': True, 'status': 'failed', 'error': str(exc)})

        with open(result_file, 'rb') as f:
            b64_data = base64.b64encode(f.read()).decode('utf-8')
        return jsonify({'ok': True, 'status': status, 'url': f'data:image/png;base64,{b64_data}'})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/remerge_video', methods=['POST'])
def remerge_video():
    try:
        payload = request.get_json(silent=True) or {}
        task_id = str(payload.get('task_id') or '').strip()
        effect_key = str(payload.get('effect_key') or '').strip()
        music_url = str(payload.get('music_url') or '').strip()
        music_name = str(payload.get('music_name') or '').strip()
        music_path = _music_url_to_abs_path(music_url)
        music_volume = _parse_volume_percent(payload.get('music_volume'), 60)
        video_audio_volume = _parse_volume_percent(payload.get('video_audio_volume'), 100)

        if not task_id:
            return jsonify({'ok': False, 'error': 'Missing task_id'}), 400

        tasks_file = TASKS_FILE_PATH
        if not os.path.exists(tasks_file):
            return jsonify({'ok': False, 'error': 'tasks.json not found'}), 404

        try:
            import json
            with open(tasks_file, 'r', encoding='utf-8') as f:
                raw = f.read()
            tasks_data = json.loads(raw) if raw else []
        except Exception:
            tasks_data = []

        task = None
        for it in (tasks_data if isinstance(tasks_data, list) else []):
            if str((it or {}).get('id') or '') == task_id:
                task = it
                break
        if not task:
            return jsonify({'ok': False, 'error': 'Task not found'}), 404

        out_clips = task.get('out_clips')
        merged_out = str(task.get('merged_out') or '').strip()
        scenes_dir = str(task.get('scenes_dir') or '').strip()

        def _newest_mp4_in_dir(d: str) -> str:
            try:
                if not d or not os.path.isdir(d):
                    return ''
                items = [os.path.join(d, fn) for fn in os.listdir(d) if fn and fn.lower().endswith('.mp4')]
                if not items:
                    return ''
                items.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0.0, reverse=True)
                return items[0]
            except Exception:
                return ''

        resolved = []
        for p in (out_clips if isinstance(out_clips, list) else []):
            s = str(p or '').strip()
            if not s:
                continue
            if os.path.isdir(s):
                map_path = os.path.join(s, 'scene_map.json')
                if os.path.exists(map_path):
                    try:
                        import json
                        with open(map_path, 'r', encoding='utf-8') as f:
                            mp = json.load(f) or {}
                        keys = sorted([int(k) for k in mp.keys() if str(k).isdigit()])
                        added = False
                        for k in keys:
                            fp = str(mp.get(str(k)) or '').strip()
                            if fp and os.path.exists(fp):
                                resolved.append(fp)
                                added = True
                        if added:
                            continue
                    except Exception:
                        pass

                cand = _newest_mp4_in_dir(s)
                if cand:
                    resolved.append(cand)
                continue

            if os.path.exists(s):
                resolved.append(s)

        if not resolved and scenes_dir and os.path.isdir(scenes_dir):
            cand = _newest_mp4_in_dir(scenes_dir)
            if cand:
                resolved.append(cand)

        if not resolved:
            return jsonify({'ok': False, 'error': 'Không tìm thấy clip để ghép lại'}), 400

        if not merged_out:
            base_dir = os.path.dirname(os.path.abspath(resolved[0]))
            merged_out = os.path.join(base_dir, f'remerge_{task_id.replace("-", "")[:8]}.mp4')

        from utils.control_ffmpeg import merge_video_clips, TRANSCODE_DIR, apply_background_music
        from utils.control_script import update_task_status

        update_task_status(task_id, 'processing', phase='merging', effect_key=effect_key, music_url=music_url, music_name=music_name)

        merged_path = merge_video_clips(resolved, merged_out, effect_key=effect_key)

        try:
            tmp_audio_out = os.path.join(TRANSCODE_DIR, f"music_{task_id.replace('-', '')[:12]}_{os.path.basename(merged_out)}")
            applied = apply_background_music(
                merged_path,
                music_path if music_path and os.path.exists(music_path) else "",
                tmp_audio_out,
                music_volume=music_volume,
                video_audio_volume=video_audio_volume,
            )
            import shutil
            shutil.copy2(applied, merged_out)
            merged_path = merged_out
            try:
                if os.path.exists(tmp_audio_out) and os.path.abspath(tmp_audio_out) != os.path.abspath(merged_out):
                    os.remove(tmp_audio_out)
            except Exception:
                pass
        except Exception:
            pass

        out_name = os.path.basename(merged_path)
        trans_name = f"{task_id.replace('-', '')[:12]}__{out_name}"
        trans_path = os.path.join(TRANSCODE_DIR, trans_name)
        try:
            if os.path.abspath(os.path.dirname(merged_path)) != os.path.abspath(TRANSCODE_DIR):
                import shutil
                shutil.copy2(merged_path, trans_path)
            else:
                trans_name = os.path.basename(merged_path)
        except Exception:
            trans_name = os.path.basename(merged_path)

        result_url = f"/transcoded/{trans_name}"
        update_task_status(
            task_id,
            'completed',
            result_file=merged_path,
            result_url=result_url,
            effect_key=effect_key,
            out_clips=list(out_clips) if isinstance(out_clips, list) else out_clips,
            merged_out=str(merged_out),
            scenes_dir=scenes_dir,
        )

        return jsonify({'ok': True, 'result_url': result_url})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/save_video_results', methods=['POST'])
def save_video_results():
    try:
        payload = request.get_json(silent=True) or {}
        task_ids = payload.get('task_ids')
        if not isinstance(task_ids, list) or len(task_ids) == 0:
            return jsonify({'ok': False, 'error': 'Missing task_ids'}), 400

        task_ids = [str(x).strip() for x in task_ids if str(x).strip()]
        if not task_ids:
            return jsonify({'ok': False, 'error': 'Missing task_ids'}), 400

        tasks_file = TASKS_FILE_PATH
        if not os.path.exists(tasks_file):
            return jsonify({'ok': False, 'error': 'tasks.json not found'}), 404

        try:
            import json
            with open(tasks_file, 'r', encoding='utf-8') as f:
                raw = f.read()
            tasks_data = json.loads(raw) if raw else []
        except Exception:
            tasks_data = []

        by_id = {}
        for it in (tasks_data if isinstance(tasks_data, list) else []):
            tid = str((it or {}).get('id') or '').strip()
            if tid:
                by_id[tid] = it

        def _unique_path(dir_path: str, filename: str) -> str:
            base, ext = os.path.splitext(filename)
            cand = os.path.join(dir_path, filename)
            if not os.path.exists(cand):
                return cand
            for i in range(1, 1000):
                alt = os.path.join(dir_path, f"{base} ({i}){ext}")
                if not os.path.exists(alt):
                    return alt
            return os.path.join(dir_path, f"{base}_{uuid.uuid4().hex[:6]}{ext}")

        result_urls = {}
        changed = False
        batch_dirs_to_remove = set()

        import shutil

        for tid in task_ids:
            t = by_id.get(tid)
            if not t:
                continue

            # Keep transcoded URL for playback in UI
            result_urls[tid] = str((t or {}).get('result_url') or '').strip()

            merged_out = str((t or {}).get('merged_out') or '').strip()
            result_file = str((t or {}).get('result_file') or '').strip()
            scenes_dir = str((t or {}).get('scenes_dir') or '').strip()

            src = ''
            if result_file and os.path.exists(result_file):
                src = result_file
            elif merged_out and os.path.exists(merged_out):
                src = merged_out

            if not src:
                continue

            # Determine batch dir: parent of scenes_dir is video_batch_* folder
            batch_dir = ''
            out_root = ''
            try:
                if scenes_dir:
                    batch_dir = os.path.dirname(os.path.abspath(scenes_dir))
                    out_root = os.path.dirname(os.path.abspath(batch_dir))
                else:
                    # Fallback: infer from src path: ...\video_batch_xxx\<file>
                    p = os.path.dirname(os.path.abspath(src))
                    if os.path.basename(os.path.normpath(p)).startswith('video_batch_'):
                        batch_dir = p
                        out_root = os.path.dirname(os.path.abspath(batch_dir))
            except Exception:
                batch_dir = ''
                out_root = ''

            if out_root and os.path.isdir(out_root):
                dst = _unique_path(out_root, os.path.basename(src))
                try:
                    shutil.move(src, dst)
                except Exception:
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        dst = ''

                if dst:
                    t['saved_file'] = dst
                    changed = True

            # Schedule deletion of temp batch folder
            if batch_dir:
                base = os.path.basename(os.path.normpath(batch_dir))
                if base.startswith('video_batch_'):
                    batch_dirs_to_remove.add(batch_dir)

        # Remove temp batch folders
        for d in sorted(batch_dirs_to_remove, key=lambda x: len(str(x)), reverse=True):
            try:
                if os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

        if changed:
            try:
                import json
                with open(tasks_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        return jsonify({'ok': True, 'result_urls': result_urls})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/discard_video_results', methods=['POST'])
def discard_video_results():
    try:
        payload = request.get_json(silent=True) or {}
        task_ids = payload.get('task_ids')
        if task_ids is None:
            task_ids = []

        if not isinstance(task_ids, list):
            return jsonify({'ok': False, 'error': 'task_ids must be a list'}), 400

        task_ids = [str(x).strip() for x in task_ids if str(x).strip()]
        if not task_ids:
            return jsonify({'ok': True, 'deleted': 0})

        tasks_file = TASKS_FILE_PATH
        if not os.path.exists(tasks_file):
            return jsonify({'ok': True, 'deleted': 0})

        try:
            import json
            with open(tasks_file, 'r', encoding='utf-8') as f:
                raw = f.read()
            tasks_data = json.loads(raw) if raw else []
        except Exception:
            tasks_data = []

        by_id = {}
        for it in (tasks_data if isinstance(tasks_data, list) else []):
            tid = str((it or {}).get('id') or '').strip()
            if tid:
                by_id[tid] = it

        batch_dirs_to_remove = set()
        for tid in task_ids:
            t = by_id.get(tid)
            if not t:
                continue

            merged_out = str((t or {}).get('merged_out') or '').strip()
            result_file = str((t or {}).get('result_file') or '').strip()
            scenes_dir = str((t or {}).get('scenes_dir') or '').strip()

            src = ''
            if result_file and os.path.exists(result_file):
                src = result_file
            elif merged_out and os.path.exists(merged_out):
                src = merged_out

            batch_dir = ''
            try:
                if scenes_dir:
                    batch_dir = os.path.dirname(os.path.abspath(scenes_dir))
                elif src:
                    p = os.path.dirname(os.path.abspath(src))
                    if os.path.basename(os.path.normpath(p)).startswith('video_batch_'):
                        batch_dir = p
            except Exception:
                batch_dir = ''

            if batch_dir:
                base = os.path.basename(os.path.normpath(batch_dir))
                if base.startswith('video_batch_'):
                    batch_dirs_to_remove.add(batch_dir)

        import shutil
        deleted = 0
        for d in sorted(batch_dirs_to_remove, key=lambda x: len(str(x)), reverse=True):
            try:
                if os.path.isdir(d):
                    shutil.rmtree(d, ignore_errors=True)
                    deleted += 1
            except Exception:
                pass

        return jsonify({'ok': True, 'deleted': deleted})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/exit_app', methods=['POST'])
def exit_app():
    """Server-side exit: optionally save or discard video temp, then shutdown app."""
    try:
        payload = request.get_json(silent=True) or {}
        action = str(payload.get('action') or '').strip().lower()
        task_ids = payload.get('task_ids')
        if task_ids is None:
            task_ids = []
        if not isinstance(task_ids, list):
            task_ids = []
        task_ids = [str(x).strip() for x in task_ids if str(x).strip()]

        # Perform requested action best-effort
        if action == 'save' and task_ids:
            # Inline minimal copy of save_video_results behavior
            tasks_file = TASKS_FILE_PATH
            if os.path.exists(tasks_file):
                try:
                    import json
                    with open(tasks_file, 'r', encoding='utf-8') as f:
                        raw = f.read()
                    tasks_data = json.loads(raw) if raw else []
                except Exception:
                    tasks_data = []

                by_id = {}
                for it in (tasks_data if isinstance(tasks_data, list) else []):
                    tid = str((it or {}).get('id') or '').strip()
                    if tid:
                        by_id[tid] = it

                def _unique_path(dir_path: str, filename: str) -> str:
                    base, ext = os.path.splitext(filename)
                    cand = os.path.join(dir_path, filename)
                    if not os.path.exists(cand):
                        return cand
                    for i in range(1, 1000):
                        alt = os.path.join(dir_path, f"{base} ({i}){ext}")
                        if not os.path.exists(alt):
                            return alt
                    return os.path.join(dir_path, f"{base}_{uuid.uuid4().hex[:6]}{ext}")

                changed = False
                batch_dirs_to_remove = set()
                import shutil

                for tid in task_ids:
                    t = by_id.get(tid)
                    if not t:
                        continue

                    merged_out = str((t or {}).get('merged_out') or '').strip()
                    result_file = str((t or {}).get('result_file') or '').strip()
                    scenes_dir = str((t or {}).get('scenes_dir') or '').strip()

                    src = ''
                    if result_file and os.path.exists(result_file):
                        src = result_file
                    elif merged_out and os.path.exists(merged_out):
                        src = merged_out

                    batch_dir = ''
                    out_root = ''
                    try:
                        if scenes_dir:
                            batch_dir = os.path.dirname(os.path.abspath(scenes_dir))
                            out_root = os.path.dirname(os.path.abspath(batch_dir))
                        else:
                            # Fallback: infer from src path: ...\video_batch_xxx\<file>
                            p = os.path.dirname(os.path.abspath(src))
                            if os.path.basename(os.path.normpath(p)).startswith('video_batch_'):
                                batch_dir = p
                                out_root = os.path.dirname(os.path.abspath(batch_dir))
                    except Exception:
                        batch_dir = ''
                        out_root = ''

                    if out_root and os.path.isdir(out_root):
                        dst = _unique_path(out_root, os.path.basename(src))
                        try:
                            shutil.move(src, dst)
                        except Exception:
                            try:
                                shutil.copy2(src, dst)
                            except Exception:
                                dst = ''
                        if dst:
                            t['saved_file'] = dst
                            changed = True

                    # Schedule deletion of temp batch folder
                    if batch_dir:
                        base = os.path.basename(os.path.normpath(batch_dir))
                        if base.startswith('video_batch_'):
                            batch_dirs_to_remove.add(batch_dir)

                for d in sorted(batch_dirs_to_remove, key=lambda x: len(str(x)), reverse=True):
                    try:
                        if os.path.isdir(d):
                            shutil.rmtree(d, ignore_errors=True)
                    except Exception:
                        pass

                if changed:
                    try:
                        import json
                        with open(tasks_file, 'w', encoding='utf-8') as f:
                            json.dump(tasks_data, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

        elif action == 'discard' and task_ids:
            # Reuse discard logic by calling it inline
            try:
                tasks_file = TASKS_FILE_PATH
                if os.path.exists(tasks_file):
                    try:
                        import json
                        with open(tasks_file, 'r', encoding='utf-8') as f:
                            raw = f.read()
                        tasks_data = json.loads(raw) if raw else []
                    except Exception:
                        tasks_data = []

                    by_id = {}
                    for it in (tasks_data if isinstance(tasks_data, list) else []):
                        tid = str((it or {}).get('id') or '').strip()
                        if tid:
                            by_id[tid] = it

                    batch_dirs_to_remove = set()
                    for tid in task_ids:
                        t = by_id.get(tid)
                        if not t:
                            continue

                        merged_out = str((t or {}).get('merged_out') or '').strip()
                        result_file = str((t or {}).get('result_file') or '').strip()
                        scenes_dir = str((t or {}).get('scenes_dir') or '').strip()

                        src = ''
                        if result_file and os.path.exists(result_file):
                            src = result_file
                        elif merged_out and os.path.exists(merged_out):
                            src = merged_out

                        batch_dir = ''
                        try:
                            if scenes_dir:
                                batch_dir = os.path.dirname(os.path.abspath(scenes_dir))
                            elif src:
                                p = os.path.dirname(os.path.abspath(src))
                                if os.path.basename(os.path.normpath(p)).startswith('video_batch_'):
                                    batch_dir = p
                        except Exception:
                            batch_dir = ''

                        if batch_dir:
                            base = os.path.basename(os.path.normpath(batch_dir))
                            if base.startswith('video_batch_'):
                                batch_dirs_to_remove.add(batch_dir)

                    import shutil
                    for d in sorted(batch_dirs_to_remove, key=lambda x: len(str(x)), reverse=True):
                        try:
                            if os.path.isdir(d):
                                shutil.rmtree(d, ignore_errors=True)
                        except Exception:
                            pass
            except Exception:
                pass

        if not is_running_as_exe():
            return jsonify({
                'ok': True,
                'dev_mode': True,
                'server_keeps_running': True,
                'message': 'Dev mode: server vẫn chạy. Dừng bằng Ctrl+C trong terminal.',
            })

        _perform_app_cleanup()
        _force_exit_later(0.4)
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


def _perform_app_cleanup():
    """Logic dọn dẹp chuẩn: đóng trình duyệt, dọn dẹp task và đẩy log."""
    try:
        from utils.control_profile import close_global_browser
        for kind in ['video', 'image', 'default']:
            try:
                close_global_browser(kind)
            except Exception:
                pass
    except Exception:
        pass

    try:
        # Đảm bảo đẩy hết dữ liệu log ra terminal trước khi đóng
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass


@app.route('/uninstall', methods=['POST'])
def uninstall():
    try:
        if not is_running_as_exe():
            return jsonify({'ok': False, 'error': 'Chỉ hỗ trợ khi chạy bản build (EXE)'}), 400
        if os.name != 'nt':
            return jsonify({'ok': False, 'error': 'Only supported on Windows'}), 400

        base_dir = EXE_DIR
        pid = os.getpid()

        bat_path = os.path.join(tempfile.gettempdir(), f"video_creator_self_uninstall_{uuid.uuid4().hex[:8]}.bat")

        bat_content = f"""@echo off
setlocal
timeout /t 1 /nobreak > nul
taskkill /f /pid {pid} > nul 2>&1
timeout /t 1 /nobreak > nul

del /f /q "%USERPROFILE%\Desktop\VideoCreator.lnk" > nul 2>&1
del /f /q "%PUBLIC%\Desktop\VideoCreator.lnk" > nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\VideoCreator.lnk" > nul 2>&1
del /f /q "%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\VideoCreator.lnk" > nul 2>&1

rmdir /s /q "{base_dir}" > nul 2>&1
del "%~f0" > nul 2>&1
"""
        with open(bat_path, 'w', encoding='utf-8') as f:
            f.write(bat_content)

        subprocess.Popen(["cmd", "/c", bat_path], creationflags=subprocess.CREATE_NO_WINDOW)
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/shutdown', methods=['POST'])
def shutdown_app():
    try:
        if not is_running_as_exe():
            return jsonify({
                'ok': True,
                'dev_mode': True,
                'server_keeps_running': True,
            })

        import os
        import threading

        # Best-effort: close Playwright/Chrome
        try:
            from utils.control_profile import close_global_browser
            try:
                close_global_browser('video')
            except Exception:
                pass
            try:
                close_global_browser('image')
            except Exception:
                pass
            try:
                close_global_browser('default')
            except Exception:
                pass
        except Exception:
            pass

        # Stop werkzeug dev server (if running under it)
        func = request.environ.get('werkzeug.server.shutdown')
        if callable(func):
            try:
                func()
            except Exception:
                pass

        # Ensure stdout/stderr are flushed and available for console
        sys.stdout.flush()
        sys.stderr.flush()

        # Force-exit the process to ensure the app closes (debug server may keep running)
        _force_exit_later(0.4)
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/create_images_batch_start', methods=['POST'])
def create_images_batch_start():
    try:
        payload = request.get_json(silent=True) or {}
        provider = str(payload.get('provider') or '').strip()
        if 'Veo3' in provider or 'veo3' in provider.lower():
            return create_images_veo3_handler()

        from utils.control_creat_video import is_grok_chain_provider
        if is_grok_chain_provider(provider):
            return jsonify({
                'ok': False,
                'error': 'Grok Chain chỉ dùng cho Tạo video. Chọn Grok (X-AI) hoặc Veo3 (Google).',
            }), 400

        return create_images_batch()
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/create_videos_batch_start', methods=['POST'])
def create_videos_batch_start():
    try:
        with _CREATE_VIDEOS_CANCEL_LOCK:
            _CREATE_VIDEOS_CANCEL.clear()

        payload = request.get_json(silent=True) or {}
        provider = str(payload.get('provider') or '').strip()
        
        # 🔥 Route to Veo3 handler if provider contains "Veo3"
        if 'Veo3' in provider or 'veo3' in provider.lower():
            print(f"[create_videos_batch_start] ✅ Routing to Veo3 handler (provider: '{provider}')...")
            return create_videos_veo3_handler()

        from utils.control_creat_video import is_grok_chain_provider, is_grok_provider
        if not is_grok_provider(provider):
            return jsonify({
                'ok': False,
                'error': 'Model không hỗ trợ tạo video qua Grok. Chọn Grok (X-AI) hoặc Grok Chain (X-AI).',
            }), 400

        grok_chain = is_grok_chain_provider(provider)
        out_dir_label = str(payload.get('out_dir_label') or '')
        # Normalize common issues from UI labels (quotes/hidden chars/newlines)
        out_dir_label = out_dir_label.replace('\u200e', '').replace('\u200f', '').replace('\ufeff', '')
        out_dir_label = out_dir_label.strip().strip('"').strip("'").strip()
        try:
            out_dir_label = os.path.normpath(out_dir_label)
        except Exception:
            out_dir_label = str(out_dir_label).strip()
        max_tabs = payload.get('max_tabs', 5)
        ratio = str(payload.get('ratio') or '9:16').strip()
        quality = str(payload.get('quality') or '1080p').strip()
        music_url = str(payload.get('music_url') or '').strip()
        music_name = str(payload.get('music_name') or '').strip()
        music_path = _music_url_to_abs_path(music_url)
        music_volume = _parse_volume_percent(payload.get('music_volume'), 60)
        video_audio_volume = _parse_volume_percent(payload.get('video_audio_volume'), 100)
        grok_duration = str(payload.get('grok_duration') or '6s').strip()
        tasks = payload.get('tasks')

        if not isinstance(tasks, list) or len(tasks) == 0:
            return jsonify({'ok': False, 'error': 'No tasks provided'}), 400

        # Validate scenes: prompt + ảnh tham chiếu (cảnh 1 bắt buộc; cảnh 2+ chỉ khi không phải Grok Chain)
        try:
            from utils.video_reference_prompts import prepare_scene_references
            for t in tasks:
                scenes = (t or {}).get('scenes')
                if not isinstance(scenes, list) or len(scenes) == 0:
                    continue
                for idx, scene in enumerate(scenes):
                    prompt = str((scene or {}).get('prompt') or '').strip()
                    if not prompt:
                        return jsonify({'ok': False, 'error': f'Thiếu prompt ở cảnh {idx + 1}'}), 400
                    if grok_chain and idx > 0:
                        continue
                    ref_urls, _, _ = prepare_scene_references(
                        scene_prompt=prompt,
                        ref_product=str((scene or {}).get('ref_product') or (t or {}).get('ref_product') or ''),
                        ref_character=str((scene or {}).get('ref_character') or (t or {}).get('ref_character') or ''),
                        ref_combined=str(
                            (scene or {}).get('ref_combined')
                            or (scene or {}).get('image')
                            or (t or {}).get('ref_combined')
                            or ''
                        ),
                        default_image=str((t or {}).get('default_image') or ''),
                    )
                    if not ref_urls:
                        return jsonify({
                            'ok': False,
                            'error': f'Thiếu ảnh tham chiếu ở cảnh {idx + 1} (sản phẩm / nhân vật / kết hợp)',
                        }), 400
        except Exception:
            pass

        if grok_chain:
            max_tabs = 1

        if os.path.isabs(out_dir_label):
            try:
                os.makedirs(out_dir_label, exist_ok=True)
            except Exception:
                pass
        if not (os.path.isabs(out_dir_label) and os.path.isdir(out_dir_label)):
            return jsonify({'ok': False, 'error': 'Vui lòng chọn thư mục lưu kết quả'}), 400

        from utils.control_profile import init_global_browser, get_global_browser
        from utils.control_script import create_video_task
        from utils.control_creat_video import run_video_tasks

        runner_tasks = []
        mapping = []

        batch_id = uuid.uuid4().hex[:8]
        out_folder_abs = os.path.join(out_dir_label, f'video_batch_{batch_id}')
        os.makedirs(out_folder_abs, exist_ok=True)

        for t in tasks:
            form_id = str((t or {}).get('form_id') or '').strip()
            scenes = (t or {}).get('scenes')
            effect_key = str((t or {}).get('effect_key') or '').strip()

            if not form_id:
                continue
            if not isinstance(scenes, list) or len(scenes) == 0:
                continue

            out_name = f'{form_id}_{uuid.uuid4().hex[:4]}.mp4'
            merged_out = os.path.join(out_folder_abs, out_name)

            clips_dir = os.path.join(out_folder_abs, f'{form_id}_scenes')
            os.makedirs(clips_dir, exist_ok=True)
            out_clips = [clips_dir for _ in range(len(scenes))]

            task_id = create_video_task(f'Tạo video: {out_name}', provider)
            mapping.append({'form_id': form_id, 'task_id': task_id})
            runner_tasks.append({
                'task_id': task_id,
                'form_id': form_id,
                'scenes': scenes,
                'out_clips': out_clips,
                'merged_out': merged_out,
                'effect_key': effect_key,
                'ratio': ratio,
                'quality': quality,
                'music_url': music_url,
                'music_name': music_name,
                'music_path': music_path,
                'music_volume': music_volume,
                'video_audio_volume': video_audio_volume,
                'ref_product': str((t or {}).get('ref_product') or ''),
                'ref_character': str((t or {}).get('ref_character') or ''),
                'ref_combined': str((t or {}).get('ref_combined') or ''),
                'default_image': str((t or {}).get('default_image') or ''),
            })

        if len(runner_tasks) == 0:
            return jsonify({'ok': False, 'error': 'No valid tasks'}), 400

        init_global_browser(provider=provider, kind='video')
        gb = get_global_browser('video')

        async def _run_on_global_ctx_async():
            ctx = await gb.get_context_async()
            if ctx is None:
                raise RuntimeError('Global browser context is not initialized')
            await run_video_tasks(
                context=ctx,
                provider=provider,
                tasks=runner_tasks,
                max_tabs=max_tabs,
                cancel_event=_CREATE_VIDEOS_CANCEL,
                grok_duration=grok_duration,
                grok_chain=grok_chain,
            )

        future = asyncio.run_coroutine_threadsafe(_run_on_global_ctx_async(), gb._loop)
        batch_key = uuid.uuid4().hex[:10]
        with _ASYNC_VIDEO_BATCHES_LOCK:
            _ASYNC_VIDEO_BATCHES[batch_key] = {
                'provider': provider,
                'future': future,
                'mapping': mapping,
                'out_folder_abs': out_folder_abs,
            }

        return jsonify({
            'ok': True,
            'batch_id': batch_key,
            'tasks': mapping,
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/cancel_video_task', methods=['POST'])
def cancel_video_task_handler():
    try:
        payload = request.get_json(silent=True) or {}
        task_id = str(payload.get('task_id') or '').strip()
        if not task_id:
            return jsonify({'ok': False, 'error': 'Missing task_id'}), 400

        from utils.control_creat_video import cancel_video_task as cancel_grok_video_task
        from utils.control_creat_video_veo3_batch import cancel_video_task as cancel_veo3_video_task

        cancel_grok_video_task(task_id)
        cancel_veo3_video_task(task_id)
        _mark_tasks_cancelled_best_effort([task_id])
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/cancel_create_videos_batch', methods=['POST'])
def cancel_create_videos_batch():
    try:
        with _CREATE_VIDEOS_CANCEL_LOCK:
            _CREATE_VIDEOS_CANCEL.set()

        task_ids = []
        batch_folders = []
        try:
            with _ASYNC_VIDEO_BATCHES_LOCK:
                for b in (_ASYNC_VIDEO_BATCHES or {}).values():
                    try:
                        ce = (b or {}).get('cancel_event')
                        if ce is not None and getattr(ce, 'set', None):
                            ce.set()
                    except Exception:
                        pass
                    for m in (b or {}).get('mapping') or []:
                        if m and m.get('task_id'):
                            task_ids.append(str(m.get('task_id')))
                    for t in (b or {}).get('tasks') or []:
                        tid = str((t or {}).get('task_id') or '').strip()
                        if tid:
                            task_ids.append(tid)
                    of = (b or {}).get('out_folder_abs')
                    if of:
                        batch_folders.append(str(of))
        except Exception:
            task_ids = []
            batch_folders = []

        try:
            from utils.control_creat_video import cancel_video_task as cancel_grok_video_task
            from utils.control_creat_video_veo3_batch import cancel_video_task as cancel_veo3_video_task

            for tid in {str(x).strip() for x in task_ids if str(x).strip()}:
                cancel_grok_video_task(tid)
                cancel_veo3_video_task(tid)
        except Exception:
            pass

        # Fallback: infer batch folder from tasks.json scenes_dir (works even if server lost _ASYNC_VIDEO_BATCHES)
        try:
            if task_ids:
                tasks_file = TASKS_FILE_PATH
                if os.path.exists(tasks_file):
                    import json
                    with open(tasks_file, 'r', encoding='utf-8') as f:
                        raw = f.read()
                    try:
                        tasks_data = json.loads(raw) if raw else []
                    except Exception:
                        tasks_data = []
                    wanted = {str(x) for x in task_ids if str(x).strip()}
                    for it in (tasks_data or []):
                        tid = str((it or {}).get('id') or '')
                        if tid not in wanted:
                            continue
                        scenes_dir = str((it or {}).get('scenes_dir') or '').strip()
                        if not scenes_dir:
                            continue
                        try:
                            parent = os.path.dirname(os.path.abspath(scenes_dir))
                            base = os.path.basename(os.path.normpath(parent))
                            if base.startswith('video_batch_'):
                                batch_folders.append(parent)
                        except Exception:
                            pass
        except Exception:
            pass

        _mark_tasks_cancelled_best_effort(task_ids if task_ids else None)

        # Best-effort: clear stored async batches so UI doesn't keep polling stale jobs
        try:
            with _ASYNC_VIDEO_BATCHES_LOCK:
                _ASYNC_VIDEO_BATCHES.clear()
        except Exception:
            pass

        # Cleanup temp scenes folders for cancelled tasks
        try:
            tasks_file = TASKS_FILE_PATH
            if os.path.exists(tasks_file) and task_ids:
                import json
                with open(tasks_file, 'r', encoding='utf-8') as f:
                    raw = f.read()
                try:
                    tasks_data = json.loads(raw) if raw else []
                except Exception:
                    tasks_data = []
                wanted = {str(x) for x in task_ids if str(x).strip()}
                for it in tasks_data if isinstance(tasks_data, list) else []:
                    tid = str((it or {}).get('id') or '')
                    if tid not in wanted:
                        continue
                    scenes_dir = str((it or {}).get('scenes_dir') or '').strip()
                    if scenes_dir and os.path.isdir(scenes_dir):
                        import shutil
                        shutil.rmtree(scenes_dir, ignore_errors=True)
                        it['scenes_dir'] = ''
                with open(tasks_file, 'w', encoding='utf-8') as f:
                    json.dump(tasks_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # Cleanup batch output folders created by the last Start (video_batch_xxx)
        try:
            import shutil
            for folder in (batch_folders or []):
                p = str(folder or '').strip()
                if not p:
                    continue
                base = os.path.basename(os.path.normpath(p))
                if not base.startswith('video_batch_'):
                    continue
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass

        # Close browser immediately when stopping video batch
        try:
            from utils.control_profile import close_global_browser
            close_global_browser(kind='video')
        except Exception:
            pass

        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/reset_browser_profile', methods=['POST'])
def reset_browser_profile():
    try:
        from utils.control_profile import reset_global_browser
        reset_global_browser(kind='default')
        return jsonify({'ok': True, 'message': 'Trình duyệt đã được khởi động lại (Dữ liệu profile vẫn giữ nguyên).'})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/open_grok_login', methods=['POST'])
def open_grok_login():
    try:
        from utils.control_profile import open_profile
        open_profile('grok')
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/pick_result_folder', methods=['POST'])
def pick_result_folder():
    try:
        import os
        import subprocess
        from flask import jsonify

        if os.name != 'nt':
            return jsonify({'ok': False, 'error': 'Only supported on Windows'}), 400

        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dlg = New-Object System.Windows.Forms.OpenFileDialog; "

            # 🔒 Không cho chọn file thật
            "$dlg.ValidateNames = $false; "
            "$dlg.CheckFileExists = $false; "
            "$dlg.CheckPathExists = $true; "
            "$dlg.FileName = 'Chọn thư mục'; "

            # 👇 filter ẩn file
            "$dlg.Filter = 'Folders|*.'; "

            "$dlg.Title = 'Chọn thư mục lưu kết quả'; "
            "$dlg.InitialDirectory = [Environment]::GetFolderPath('Desktop'); "

            "if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "  Split-Path $dlg.FileName "
            "}"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            **(lambda: (
                __import__('utils.control_profile', fromlist=['_win_subprocess_kwargs'])
                ._win_subprocess_kwargs() if os.name == 'nt' else {}
            ))(),
        )

        path = (result.stdout or "").strip()

        if not path:
            return jsonify({'ok': False, 'error': 'No folder selected'}), 200

        return jsonify({'ok': True, 'path': os.path.abspath(path)})

    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route("/listmusic")
def list_music():
    return list_music_handler()


@app.route("/music/<path:filename>")
def serve_music(filename: str):
    return serve_music_handler(filename)


@app.route("/deletemusic", methods=["POST"])
def delete_music():
    return delete_music_handler()


@app.route("/addmusic", methods=["POST"])
def add_music():
    return add_music_handler()


@app.route("/uploadmusic", methods=["POST"])
def upload_music():
    return upload_music_handler()


@app.route("/transcoded/<path:filename>")
def serve_transcoded(filename: str):
    return serve_transcoded_handler(filename)


@app.route("/transcode_video", methods=["POST"])
def transcode_video():
    return transcode_video_handler()


@app.route("/extract_frame", methods=["POST"])
def extract_frame():
    return extract_frame_handler()


@app.route("/upload_temp_video", methods=["POST"])
def upload_temp_video():
    return upload_temp_video_handler()


@app.route("/temp_video/<filename>")
def serve_temp_video(filename):
    """Serve video files from temp_video directory"""
    temp_video_dir = TEMP_VIDEO_DIR_PATH
    return send_from_directory(temp_video_dir, filename)


@app.route("/listscripts")
def list_scripts():
    return list_scripts_handler()


@app.route("/load_script")
def load_script():
    return load_script_handler()


@app.route("/save_script", methods=["POST"])
def save_script():
    return save_script_handler()


@app.route("/transcode_for_web", methods=["POST"])
def transcode_for_web():
    return transcode_video_handler()


@app.route("/transcode_from_path", methods=["POST"])
def transcode_from_path():
    return transcode_video_from_path_handler()


@app.route("/delete_script", methods=["POST"])
def delete_script():
    return delete_script_handler()


@app.route("/generate_script", methods=["POST"])
def generate_script():
    return generate_script_handler()


@app.route("/list_tasks")
def list_tasks():
    return list_tasks_handler()


@app.route("/clear_tasks", methods=["POST"])
def clear_tasks():
    return clear_tasks_handler()


@app.route("/save_config", methods=["POST"])
def save_config():
    return save_config_handler()


@app.route("/cleanup_temp", methods=["POST"])
def cleanup_temp():
    return cleanup_temp_handler()


@app.route("/listthemes")
def list_themes():
    """
    Trả về danh sách file ảnh theme trong templaces/img
    dạng:
    [
      {"name": "Default", "file": "Default.png", "url": "/templaces/img/Default.png"},
      ...
    ]
    """
    items = []

    if os.path.isdir(THEME_IMG_DIR):
        files = [f for f in os.listdir(THEME_IMG_DIR)
                 if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]

        # Chỉ giữ lại 4 theme: Default, Hacker, Tech, Princess (nếu tồn tại), theo đúng thứ tự này
        ordered_basenames = ["default", "hacker", "tech", "princess"]

        for base in ordered_basenames:
            # tìm file khớp basename (không phân biệt hoa thường)
            match = next(
                (
                    name for name in files
                    if os.path.splitext(name)[0].lower() == base
                ),
                None,
            )
            if not match:
                continue

            title = os.path.splitext(match)[0]

            # map basename -> class CSS
            if base == "default":
                theme_class = "theme-default"
            elif base == "hacker":
                theme_class = "theme-hacker"
            elif base == "tech":
                theme_class = "theme-tech"
            elif base == "princess":
                theme_class = "theme-princess"
            else:
                theme_class = "theme-default"

            items.append(
                {
                    "name": title,
                    "file": match,
                    "url": f"/templaces/img/{match}",
                    "theme": theme_class,
                }
            )

    return jsonify(items)


@app.route('/setup_profile', methods=['POST'])
def setup_profile():
    try:
        data = request.get_json()
        if not data or 'model' not in data:
            return jsonify({'success': False, 'error': 'Missing model parameter'})

        model = data['model']
        from utils.control_profile import open_profile

        supported = {
            'Grok (X-AI)': 'Grok (X-AI)',
            'Grok Chain (X-AI)': 'Grok Chain (X-AI)',
            'Veo3 (Google)': 'Veo3 (Google)',
        }
        if model in supported:
            open_profile(supported[model])
            return jsonify({'success': True, 'message': f'Profile setup completed for {model}'})
        if model == 'Kling AI':
            return jsonify({'success': False, 'error': 'Kling AI profile setup not implemented yet'})
        return jsonify({'success': False, 'error': f'Unknown model: {model}'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/create_images_batch', methods=['POST'])
def create_images_batch():
    try:
        payload = request.get_json(silent=True) or {}
        provider = str(payload.get('provider') or '').strip()
        out_dir_label = str(payload.get('out_dir_label') or '')
        max_tabs = payload.get('max_tabs', 5)
        ratio = str(payload.get('ratio') or '9:16').strip()
        tasks = payload.get('tasks')
        
        # Veo3-specific parameters
        veo3_image_model = str(payload.get('veo3_image_model') or '').strip()

        if not isinstance(tasks, list) or len(tasks) == 0:
            return jsonify({'ok': False, 'error': 'No tasks provided'}), 400

        # Ưu tiên dùng đường dẫn tuyệt đối từ label nếu nó là một thư mục hợp lệ
        # Nếu không thì mới dùng thư mục generated mặc định
        if os.path.isabs(out_dir_label) and os.path.isdir(out_dir_label):
            out_folder_abs = out_dir_label
            # Với thư mục ngoài, ta không có URL /generated/ tiện lợi,
            # nên ta sẽ phục vụ nó qua một route tạm hoặc trả về path tuyệt đối (tùy frontend xử lý)
            is_custom_dir = True
        else:
            folder = _safe_folder_name(out_dir_label)
            batch_id = uuid.uuid4().hex[:8]
            out_folder_rel = os.path.join(folder, batch_id)
            out_folder_abs = os.path.join(GENERATED_DIR, out_folder_rel)
            os.makedirs(out_folder_abs, exist_ok=True)
            is_custom_dir = False

        runner_tasks = []
        mapping = []

        for t in tasks:
            form_id = str((t or {}).get('form_id') or '').strip()
            img1 = str((t or {}).get('image1') or '')
            img2 = str((t or {}).get('image2') or '')
            prompt = str((t or {}).get('prompt') or '')

            if not form_id:
                continue

            if not img1 or not prompt:
                continue

            out_name = f'{form_id}_{uuid.uuid4().hex[:4]}.png'
            out_abs = os.path.join(out_folder_abs, out_name)

            try:
                from utils.control_script import create_image_task
                task_id = create_image_task(f'Tạo ảnh: {out_name}', provider)
            except Exception:
                task_id = ''

            if task_id:
                mapping.append({'form_id': form_id, 'task_id': task_id})

            runner_tasks.append({
                'form_id': form_id,
                'task_id': task_id,
                'image1_data': img1, # Truyền data url trực tiếp
                'image2_data': img2,
                'prompt': prompt,
                'out': out_abs,
                'ratio': ratio,
                'is_custom_dir': is_custom_dir,
                'out_name': out_name,
                'out_folder_rel': out_folder_rel if not is_custom_dir else None
            })

        if len(runner_tasks) == 0:
            return jsonify({'ok': False, 'error': 'No valid tasks'}), 400

        from utils.control_creat_image import run_tasks
        from utils.control_profile import init_global_browser, get_global_browser

        # Each batch gets its own cancel event so batches are independent.
        cancel_event = threading.Event()

        init_global_browser(provider=provider, kind='image')
        gb = get_global_browser('image')

        async def _run_on_global_ctx_async():
            ctx = await gb.get_context_async()
            if ctx is None:
                raise RuntimeError('Global browser context is not initialized')
            await run_tasks(
                context=ctx,
                provider=provider,
                tasks=runner_tasks,
                max_tabs=max_tabs,
                aspect_ratio=ratio,
                cancel_event=cancel_event,
            )

        future = asyncio.run_coroutine_threadsafe(_run_on_global_ctx_async(), gb._loop)
        batch_key = uuid.uuid4().hex[:10]
        with _ASYNC_IMAGE_BATCHES_LOCK:
            _ASYNC_IMAGE_BATCHES[batch_key] = {
                'provider': provider,
                'future': future,
                'mapping': mapping,
                'cancel_event': cancel_event,
            }

        return jsonify({'ok': True, 'batch_id': batch_key, 'tasks': mapping})

    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/cancel_create_images_batch', methods=['POST'])
def cancel_create_images_batch():
    try:
        payload = request.get_json(silent=True) or {}
        batch_id = str(payload.get('batch_id') or '').strip()

        task_ids = []
        batches_to_cancel = []

        with _ASYNC_IMAGE_BATCHES_LOCK:
            if batch_id:
                b = _ASYNC_IMAGE_BATCHES.get(batch_id)
                if b:
                    batches_to_cancel = [(batch_id, b)]
            else:
                batches_to_cancel = list((_ASYNC_IMAGE_BATCHES or {}).items())

        for bid, b in batches_to_cancel:
            try:
                ce = (b or {}).get('cancel_event')
                if ce is not None and getattr(ce, 'set', None):
                    ce.set()
            except Exception:
                pass

            for m in (b or {}).get('mapping') or []:
                if m and m.get('task_id'):
                    task_ids.append(str(m.get('task_id')))

        _mark_tasks_cancelled_best_effort(task_ids if task_ids else None)

        # Remove cancelled batches so UI doesn't keep polling
        with _ASYNC_IMAGE_BATCHES_LOCK:
            if batch_id:
                try:
                    _ASYNC_IMAGE_BATCHES.pop(batch_id, None)
                except Exception:
                    pass
            else:
                _ASYNC_IMAGE_BATCHES.clear()

        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/cancel_image_task', methods=['POST'])
def cancel_image_task():
    """
    Hủy 1 task tạo ảnh (nút Hủy từng form).
    Frontend đang gọi endpoint này trong `templaces/js/tao_anh.js`.
    """
    try:
        payload = request.get_json(silent=True) or {}
        task_id = str(payload.get('task_id') or '').strip()
        if not task_id:
            return jsonify({'ok': False, 'error': 'Missing task_id'}), 400

        # Tìm batch Veo3 chứa task_id và set cancel_event.
        cancelled = False
        with _ASYNC_IMAGE_BATCHES_LOCK:
            for _, b in (_ASYNC_IMAGE_BATCHES or {}).items():
                try:
                    provider = str((b or {}).get('provider') or '')
                    if provider.lower() != 'veo3':
                        continue
                    mappings = (b or {}).get('mapping') or []
                    if any(str(m.get('task_id') or '').strip() == task_id for m in mappings if isinstance(m, dict)):
                        ce = (b or {}).get('cancel_event')
                        if ce is not None and getattr(ce, 'set', None):
                            ce.set()
                        cancelled = True
                        break
                except Exception:
                    continue

        # Mark UI task status best-effort (giống cancel_create_images_batch).
        if cancelled:
            try:
                _mark_tasks_cancelled_best_effort([task_id])
            except Exception:
                pass
            return jsonify({'ok': True})

        # Không tìm thấy batch: vẫn trả ok để UI dừng polling (task có thể đã xong).
        return jsonify({'ok': True, 'warning': 'task_not_found_or_already_finished'})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/client_ping', methods=['POST'])
def client_ping():
    """Client heartbeat from the UI (dùng cho watchdog tự thoát khi chạy EXE)."""
    try:
        import time
        with _CLIENT_PING_LOCK:
            global _LAST_CLIENT_PING_TS
            _LAST_CLIENT_PING_TS = float(time.time())
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


import webbrowser
import threading

def open_browser():
    webbrowser.open("http://127.0.0.1:5555")


def _start_client_watchdog(timeout_sec: float = 12.0, check_interval: float = 2.0) -> None:
    """Chỉ tự thoát khi chạy EXE (đóng cửa sổ UI). Dev `py app.py` không tự tắt."""
    if not is_running_as_exe():
        return

    def _loop():
        import time
        while True:
            try:
                time.sleep(float(check_interval))
                with _CLIENT_PING_LOCK:
                    last = float(_LAST_CLIENT_PING_TS or 0.0)
                if last <= 0:
                    continue
                if (time.time() - last) > float(timeout_sec):
                    try:
                        _force_exit_later(0.4)
                    finally:
                        return
            except Exception:
                pass

    try:
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
    except Exception:
        pass


def _disable_windows_console_quickedit() -> None:
    try:
        if os.name != 'nt':
            return
        import ctypes

        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_EXTENDED_FLAGS = 0x0080
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_INSERT_MODE = 0x0020

        h = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if not h:
            return
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            return
        new_mode = mode.value
        new_mode |= ENABLE_EXTENDED_FLAGS
        new_mode &= ~ENABLE_QUICK_EDIT_MODE
        new_mode &= ~ENABLE_INSERT_MODE
        kernel32.SetConsoleMode(h, new_mode)
    except Exception:
        pass


# ============================================================================
# VEO3 API ENDPOINTS
# ============================================================================

@app.route('/veo3_profiles', methods=['GET'])
def veo3_profiles_handler():
    """Lấy danh sách profiles Veo3 từ config/veo_auth.json"""
    try:
        from utils.veo3_profile import load_veo3_profiles
        profiles = load_veo3_profiles()
        
        # Trả về danh sách profiles (ẩn thông tin nhạy cảm)
        safe_profiles = []
        for profile in profiles:
            safe_profiles.append({
                'name': profile.get('name', 'unknown'),
                'project_url': profile.get('project_url', ''),
                'updated_at': profile.get('updated_at', 0),
                'has_auth': bool(profile.get('sessionId') and profile.get('projectId') and profile.get('access_token')),
            })
        
        return jsonify({'ok': True, 'profiles': safe_profiles})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/create_images_veo3', methods=['POST'])
def create_images_veo3_handler():
    """Tạo ảnh qua Veo3 API - tương tự create_images_batch nhưng dùng Veo3"""
    try:
        payload = request.get_json(silent=True) or {}
        out_dir_label = str(payload.get('out_dir_label') or '')
        max_tabs = payload.get('max_tabs', 3)
        ratio = str(payload.get('ratio') or '16:9').strip()
        tasks = payload.get('tasks')
        profile_name = payload.get('profile_name')  # Optional: chọn profile cụ thể
        veo3_image_model = str(payload.get('veo3_image_model') or 'Nano Banana pro').strip()

        if not isinstance(tasks, list) or len(tasks) == 0:
            return jsonify({'ok': False, 'error': 'No tasks provided'}), 400

        out_dir_label = out_dir_label.replace('\u200e', '').replace('\u200f', '').replace('\ufeff', '')
        out_dir_label = out_dir_label.strip().strip('"').strip("'").strip()
        try:
            out_dir_label = os.path.normpath(out_dir_label)
        except Exception:
            out_dir_label = str(out_dir_label).strip()
        if os.path.isabs(out_dir_label):
            try:
                os.makedirs(out_dir_label, exist_ok=True)
            except Exception:
                pass
        if not (os.path.isabs(out_dir_label) and os.path.isdir(out_dir_label)):
            return jsonify({'ok': False, 'error': 'Vui lòng chọn thư mục lưu kết quả'}), 400
        
        # CRITICAL: Đảm bảo Chrome đã được khởi động với CDP trước khi tạo ảnh Veo3
        # Veo3 cần kết nối qua CDP để điều khiển browser
        from utils.control_profile import init_global_browser
        try:
            print("[Veo3 API] 🚀 Đảm bảo Chrome đã khởi động với CDP...")
            init_global_browser(provider='Veo3', kind='default')
            print("[Veo3 API] ✅ Chrome đã sẵn sàng (Google Flow)")
        except Exception as e:
            return jsonify({'ok': False, 'error': f'Không thể khởi động Chrome với CDP: {str(e)}'}), 500

        # Xác định thư mục output
        if os.path.isabs(out_dir_label) and os.path.isdir(out_dir_label):
            out_folder_abs = out_dir_label
            is_custom_dir = True
        else:
            folder = _safe_folder_name(out_dir_label)
            batch_id = uuid.uuid4().hex[:8]
            out_folder_rel = os.path.join(folder, batch_id)
            out_folder_abs = os.path.join(GENERATED_DIR, out_folder_rel)
            os.makedirs(out_folder_abs, exist_ok=True)
            is_custom_dir = False

        runner_tasks = []
        mapping = []

        for t in tasks:
            form_id = str((t or {}).get('form_id') or '').strip()
            prompt = str((t or {}).get('prompt') or '')
            # 🔥 FIX: Frontend gửi image1/image2, không phải reference_image
            image1_data = str((t or {}).get('image1') or '')
            image2_data = str((t or {}).get('image2') or '')

            if not form_id or not prompt:
                continue

            out_name = f'{form_id}_{uuid.uuid4().hex[:4]}.png'
            out_abs = os.path.join(out_folder_abs, out_name)

            # Tạo task tracking
            try:
                from utils.control_script import create_image_task
                task_id = create_image_task(f'Tạo ảnh Veo3: {out_name}', 'Veo3')
            except Exception:
                task_id = ''

            if task_id:
                mapping.append({'form_id': form_id, 'task_id': task_id})

            # Xử lý reference image từ image1 (ưu tiên) hoặc image2
            reference_image_path = None
            reference_data = image1_data if image1_data else image2_data
            
            if reference_data and reference_data.startswith('data:image'):
                try:
                    # Decode base64 và lưu vào file tạm
                    import base64
                    b64_part = reference_data.split(',', 1)[1]
                    img_bytes = base64.b64decode(b64_part)
                    
                    temp_ref = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                    temp_ref.write(img_bytes)
                    temp_ref.close()
                    reference_image_path = temp_ref.name
                    print(f"[Veo3] ✅ Đã decode reference image từ localStorage: {len(img_bytes)} bytes")
                except Exception as e:
                    print(f"[Veo3] ⚠️ Lỗi xử lý reference image: {e}")

            # 🔥 FIX: Upload CẢ 2 ảnh nếu có (image1 VÀ image2)
            reference_images = []
            
            # Xử lý image1
            if image1_data and image1_data.startswith('data:image'):
                try:
                    import base64
                    b64_part = image1_data.split(',', 1)[1]
                    img_bytes = base64.b64decode(b64_part)
                    
                    temp_ref1 = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                    temp_ref1.write(img_bytes)
                    temp_ref1.close()
                    reference_images.append(temp_ref1.name)
                    print(f"[Veo3] ✅ Đã decode image1: {len(img_bytes)} bytes")
                except Exception as e:
                    print(f"[Veo3] ⚠️ Lỗi xử lý image1: {e}")
            
            # Xử lý image2
            if image2_data and image2_data.startswith('data:image'):
                try:
                    import base64
                    b64_part = image2_data.split(',', 1)[1]
                    img_bytes = base64.b64decode(b64_part)
                    
                    temp_ref2 = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                    temp_ref2.write(img_bytes)
                    temp_ref2.close()
                    reference_images.append(temp_ref2.name)
                    print(f"[Veo3] ✅ Đã decode image2: {len(img_bytes)} bytes")
                except Exception as e:
                    print(f"[Veo3] ⚠️ Lỗi xử lý image2: {e}")
            
            print(f"[Veo3] 📊 Tổng số ảnh reference: {len(reference_images)}")

            runner_tasks.append({
                'form_id': form_id,
                'task_id': task_id,
                'prompt': prompt,
                'out': out_abs,
                'ratio': ratio,
                'reference_images': reference_images,  # 🔥 Đổi từ reference_image (singular) sang reference_images (plural list)
                'profile_name': profile_name or t.get('profile_name'),
                'model': veo3_image_model,
                'is_custom_dir': is_custom_dir,
                'out_name': out_name,
                'out_folder_rel': out_folder_rel if not is_custom_dir else None
            })

        if len(runner_tasks) == 0:
            return jsonify({'ok': False, 'error': 'No valid tasks'}), 400

        from utils.control_creat_image_veo3 import run_tasks_veo3

        # Each batch gets its own cancel event
        cancel_event = threading.Event()

        async def _run_veo3_async():
            try:
                await run_tasks_veo3(
                    context={},  # Veo3 không cần global browser context
                    tasks=runner_tasks,
                    max_tabs=max_tabs,
                    cancel_event=cancel_event,
                )
            finally:
                for task in runner_tasks:
                    for ref_path in (task.get('reference_images') or []):
                        try:
                            if ref_path and os.path.exists(ref_path):
                                os.remove(ref_path)
                        except Exception:
                            pass
                    ref_path = task.get('reference_image')
                    try:
                        if ref_path and os.path.exists(ref_path):
                            os.remove(ref_path)
                    except Exception:
                        pass

        # Run in new event loop (Veo3 tự quản lý browser)
        def _run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_run_veo3_async())
            finally:
                loop.close()

        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()

        batch_key = uuid.uuid4().hex[:10]
        # Store batch info (simplified - không cần future vì chạy trong thread riêng)
        with _ASYNC_IMAGE_BATCHES_LOCK:
            _ASYNC_IMAGE_BATCHES[batch_key] = {
                'provider': 'Veo3',
                'thread': thread,
                'cancel_event': cancel_event,
                'tasks': runner_tasks,
                'mapping': mapping,
            }

        return jsonify({
            'ok': True,
            'batch_id': batch_key,
            'tasks': mapping,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/create_videos_veo3', methods=['POST'])
def create_videos_veo3_handler():
    """Tạo video qua Veo3 API - format task giống create_videos_batch (Grok)."""
    try:
        payload = request.get_json(silent=True) or {}
        out_dir_label = str(payload.get('out_dir_label') or '')
        out_dir_label = out_dir_label.replace('\u200e', '').replace('\u200f', '').replace('\ufeff', '')
        out_dir_label = out_dir_label.strip().strip('"').strip("'").strip()
        try:
            out_dir_label = os.path.normpath(out_dir_label)
        except Exception:
            out_dir_label = str(out_dir_label).strip()

        max_tabs = payload.get('max_tabs', 2)
        ratio = str(payload.get('ratio') or '9:16').strip()
        account_type = str(payload.get('account_type') or 'ULTRA').strip()
        tasks = payload.get('tasks')
        profile_name = payload.get('profile_name')
        music_url = str(payload.get('music_url') or '').strip()
        music_name = str(payload.get('music_name') or '').strip()
        music_path = _music_url_to_abs_path(music_url)
        music_volume = _parse_volume_percent(payload.get('music_volume'), 60)
        video_audio_volume = _parse_volume_percent(payload.get('video_audio_volume'), 100)

        from utils.veo3.veo_reference_video_api import (
            normalize_frontend_veo_video_model_label,
            DEFAULT_FRONTEND_VEO_VIDEO_MODEL_LABEL,
        )
        raw_veo_model = (
            payload.get('veo3_video_quality')
            or payload.get('veo_model_label')
            or payload.get('veo_model')
        )
        veo3_video_quality = normalize_frontend_veo_video_model_label(
            raw_veo_model or DEFAULT_FRONTEND_VEO_VIDEO_MODEL_LABEL
        )
        print(f"[create_videos_veo3] 🎛️ model UI → {veo3_video_quality} (raw={raw_veo_model!r})")

        if not isinstance(tasks, list) or len(tasks) == 0:
            return jsonify({'ok': False, 'error': 'No tasks provided'}), 400

        try:
            from utils.video_reference_prompts import prepare_scene_references
            for t in tasks:
                scenes = (t or {}).get('scenes')
                if not isinstance(scenes, list) or len(scenes) == 0:
                    continue
                for idx, scene in enumerate(scenes):
                    prompt = str((scene or {}).get('prompt') or '').strip()
                    if not prompt:
                        return jsonify({'ok': False, 'error': f'Thiếu prompt ở cảnh {idx + 1}'}), 400
                    ref_urls, _, _ = prepare_scene_references(
                        scene_prompt=prompt,
                        ref_product=str((scene or {}).get('ref_product') or (t or {}).get('ref_product') or ''),
                        ref_character=str((scene or {}).get('ref_character') or (t or {}).get('ref_character') or ''),
                        ref_combined=str(
                            (scene or {}).get('ref_combined')
                            or (scene or {}).get('image')
                            or (t or {}).get('ref_combined')
                            or ''
                        ),
                        default_image=str((t or {}).get('default_image') or ''),
                    )
                    if not ref_urls:
                        return jsonify({
                            'ok': False,
                            'error': f'Thiếu ảnh tham chiếu ở cảnh {idx + 1} (sản phẩm / nhân vật / kết hợp)',
                        }), 400
        except Exception:
            pass

        if os.path.isabs(out_dir_label):
            try:
                os.makedirs(out_dir_label, exist_ok=True)
            except Exception:
                pass
        if not (os.path.isabs(out_dir_label) and os.path.isdir(out_dir_label)):
            return jsonify({'ok': False, 'error': 'Vui lòng chọn thư mục lưu kết quả'}), 400

        from utils.control_profile import init_global_browser
        try:
            print("[Veo3 Video API] 🚀 Đảm bảo Chrome đã khởi động với CDP...")
            init_global_browser(provider='Veo3', kind='default')
            print("[Veo3 Video API] ✅ Chrome đã sẵn sàng (Google Flow)")
        except Exception as e:
            return jsonify({'ok': False, 'error': f'Không thể khởi động Chrome với CDP: {str(e)}'}), 500

        batch_id = uuid.uuid4().hex[:8]
        out_folder_abs = os.path.join(out_dir_label, f'video_batch_{batch_id}')
        os.makedirs(out_folder_abs, exist_ok=True)

        runner_tasks = []
        mapping = []

        for t in tasks:
            form_id = str((t or {}).get('form_id') or '').strip()
            scenes = (t or {}).get('scenes')
            effect_key = str((t or {}).get('effect_key') or '').strip()

            if not form_id:
                continue
            if not isinstance(scenes, list) or len(scenes) == 0:
                continue

            valid_scenes = []
            for scene in scenes:
                prompt = str((scene or {}).get('prompt') or '').strip()
                if not prompt:
                    continue
                valid_scenes.append({
                    'prompt': prompt,
                    'ref_product': str((scene or {}).get('ref_product') or ''),
                    'ref_character': str((scene or {}).get('ref_character') or ''),
                    'ref_combined': str(
                        (scene or {}).get('ref_combined') or (scene or {}).get('image') or ''
                    ),
                })

            if len(valid_scenes) == 0:
                continue

            out_name = f'{form_id}_{uuid.uuid4().hex[:4]}.mp4'
            merged_out = os.path.join(out_folder_abs, out_name)
            clips_dir = os.path.join(out_folder_abs, f'{form_id}_scenes')
            os.makedirs(clips_dir, exist_ok=True)
            out_clips = [clips_dir for _ in range(len(valid_scenes))]

            from utils.control_script import create_video_task
            task_id = create_video_task(f'Tạo video Veo3: {out_name}', 'Veo3')
            mapping.append({'form_id': form_id, 'task_id': task_id})
            runner_tasks.append({
                'task_id': task_id,
                'form_id': form_id,
                'scenes': valid_scenes,
                'out_clips': out_clips,
                'merged_out': merged_out,
                'effect_key': effect_key,
                'ratio': ratio,
                'music_url': music_url,
                'music_name': music_name,
                'music_path': music_path,
                'music_volume': music_volume,
                'video_audio_volume': video_audio_volume,
                'profile_name': profile_name or (t or {}).get('profile_name'),
                'account_type': account_type,
                'ref_product': str((t or {}).get('ref_product') or ''),
                'ref_character': str((t or {}).get('ref_character') or ''),
                'ref_combined': str((t or {}).get('ref_combined') or ''),
                'default_image': str((t or {}).get('default_image') or ''),
            })

        if len(runner_tasks) == 0:
            return jsonify({'ok': False, 'error': 'No valid tasks (thiếu prompt hoặc ảnh tham chiếu)'}), 400

        from utils.control_creat_video_veo3_batch import run_video_tasks_veo3_batch

        cancel_event = threading.Event()

        async def _run_veo3_video_async():
            await run_video_tasks_veo3_batch(
                context={},
                provider='veo3',
                tasks=runner_tasks,
                max_tabs=max_tabs,
                cancel_event=cancel_event,
                veo_model_label=veo3_video_quality,
            )

        def _run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_run_veo3_video_async())
            finally:
                loop.close()

        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()

        batch_key = uuid.uuid4().hex[:10]
        with _ASYNC_VIDEO_BATCHES_LOCK:
            _ASYNC_VIDEO_BATCHES[batch_key] = {
                'provider': 'Veo3',
                'thread': thread,
                'cancel_event': cancel_event,
                'tasks': runner_tasks,
                'mapping': mapping,
                'out_folder_abs': out_folder_abs,
            }

        return jsonify({
            'ok': True,
            'batch_id': batch_key,
            'tasks': mapping,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================================
# END VEO3 API ENDPOINTS
# ============================================================================


if __name__ == "__main__":
    _disable_windows_console_quickedit()

    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", 5555)) == 0:
                try:
                    open_browser()
                except Exception:
                    pass
                raise SystemExit(0)
        finally:
            try:
                s.close()
            except Exception:
                pass
    except SystemExit:
        raise
    except Exception:
        pass
    lic_svc.ensure_license(use_gui=True)

    threading.Timer(1.0, open_browser).start()
    if is_running_as_exe():
        _start_client_watchdog(timeout_sec=120.0, check_interval=5.0)

    app.run(host="127.0.0.1", port=5555, debug=(not is_running_as_exe()), use_reloader=False, threaded=True)

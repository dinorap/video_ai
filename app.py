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

from update_checker import start_background_update_check, check_and_prepare_update_once

EXE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
BUNDLE_DIR = getattr(sys, '_MEIPASS', EXE_DIR)

MUSIC_DIR = os.path.join(EXE_DIR, "config", "Music")
THEME_IMG_DIR = os.path.join(BUNDLE_DIR, "templaces", "img")
GENERATED_DIR = os.path.join(EXE_DIR, "generated")

app = Flask(__name__, static_folder=".", static_url_path="/static")


@app.route('/video', methods=['GET', 'HEAD'])
def video_only_page():
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video</title>

<style>
html,body{
    margin:0;
    padding:0;
    background:#000;
    height:100%;
}
iframe{
    width:100vw;
    height:100vh;
    border:0;
}
</style>

</head>
<body>

<iframe 
src="https://www.youtube.com/embed/Bu_2X1vcev8?autoplay=1&controls=1&loop=1&playlist=Bu_2X1vcev8"
allow="autoplay; encrypted-media"
allowfullscreen>
</iframe>

</body>
</html>"""
    return html


_ACCOUNT_CHECK_CACHE_LOCK = threading.Lock()
_ACCOUNT_CHECK_CACHE: Dict[str, Any] = {
    'ts': 0.0,
    'user_id': '',
    'result': None,
}


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


def _read_account_id_from_config() -> str:
    try:
        cfg_path = os.path.join(EXE_DIR, 'config', 'config.json')
        if not os.path.exists(cfg_path):
            return ''
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f) or {}
        if isinstance(cfg, dict):
            return str(cfg.get('ACCOUNT_ID') or cfg.get('account_id') or '').strip()
    except Exception:
        pass
    return ''


def _cache_check_result(user_id: str, res_obj) -> None:
    try:
        with _ACCOUNT_CHECK_CACHE_LOCK:
            _ACCOUNT_CHECK_CACHE['ts'] = time.time()
            _ACCOUNT_CHECK_CACHE['user_id'] = str(user_id or '')
            _ACCOUNT_CHECK_CACHE['result'] = res_obj
    except Exception:
        pass


def _startup_check_account_async() -> None:
    try:
        from utils.callserver import check_async

        user_id = _read_account_id_from_config()
        if not user_id:
            return

        res = _run_coro_blocking(check_async(user_id))
        _cache_check_result(user_id, res)
    except Exception:
        pass


try:
    threading.Thread(target=_startup_check_account_async, daemon=True).start()
except Exception:
    pass


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
        tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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
    return send_from_directory(os.path.join(BUNDLE_DIR, 'templaces', 'html'), "index.html")


@app.route('/templaces/<path:filename>')
def serve_templates(filename: str):
    return send_from_directory(os.path.join(BUNDLE_DIR, 'templaces'), filename)


@app.route('/config/<path:filename>')
def serve_config(filename: str):
    return send_from_directory(os.path.join(EXE_DIR, 'config'), filename)


@app.route('/generated/<path:filename>')
def serve_generated(filename: str):
    return send_from_directory(GENERATED_DIR, filename)


@app.route('/ico/<path:filename>')
def serve_ico(filename: str):
    try:
        p1 = os.path.join(EXE_DIR, 'ico')
        if os.path.exists(os.path.join(p1, filename)):
            resp = make_response(send_from_directory(p1, filename))
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            return resp

        p2 = os.path.join(BUNDLE_DIR, 'ico')
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


@app.route('/api/check', methods=['POST'])
def api_check_account():
    try:
        payload = request.get_json(silent=True) or {}
        user_id = str(payload.get('user_id') or payload.get('id') or '').strip()
        if not user_id:
            return jsonify({'ok': False, 'error': 'Missing user_id'}), 400

        # Serve cached startup result if it matches (best-effort)
        res_obj = None
        try:
            with _ACCOUNT_CHECK_CACHE_LOCK:
                cached_uid = str(_ACCOUNT_CHECK_CACHE.get('user_id') or '')
                cached_res = _ACCOUNT_CHECK_CACHE.get('result')
                cached_ts = float(_ACCOUNT_CHECK_CACHE.get('ts') or 0.0)
            if cached_uid and cached_uid == user_id and cached_res is not None:
                # cache TTL + avoid reusing cached errors
                is_fresh = (time.time() - cached_ts) < 60.0
                if is_fresh:
                    try:
                        ok_flag = bool(getattr(cached_res, 'success', False))
                        data0 = getattr(cached_res, 'data', None)
                        err_code = str((data0 or {}).get('error_code') or '') if isinstance(data0, dict) else ''
                        if ok_flag:
                            res_obj = cached_res
                        else:
                            # do not reuse error cache for these codes
                            if err_code and err_code.upper() not in ('BROTLI', 'ERROR'):
                                res_obj = cached_res
                    except Exception:
                        res_obj = None
        except Exception:
            res_obj = None

        if res_obj is None:
            from utils.callserver import check_async
            res_obj = _run_coro_blocking(check_async(user_id))
            _cache_check_result(user_id, res_obj)

        data = getattr(res_obj, 'data', None) if res_obj is not None else None
        if not isinstance(data, dict):
            data = {}

        count = data.get('count', 0)
        limit = data.get('limit', 0)

        return jsonify({
            'ok': True,
            'success': bool(getattr(res_obj, 'success', False)),
            'message': str(getattr(res_obj, 'message', '') or ''),
            'redirect_to_payment': bool(getattr(res_obj, 'redirect_to_payment', False)),
            'data': data,
            'count': count,
            'limit': limit,
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/task_video', methods=['GET'])
def task_video():
    try:
        task_id = str(request.args.get('task_id') or '').strip()
        if not task_id:
            return jsonify({'ok': False, 'error': 'Missing task_id'}), 400

        tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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
            'credit_request_id': task.get('credit_request_id'),
            'credit_verified': task.get('credit_verified'),
            'credit_verify_message': task.get('credit_verify_message'),
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

        tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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

        if not task_id:
            return jsonify({'ok': False, 'error': 'Missing task_id'}), 400

        tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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

        if music_path and os.path.exists(music_path):
            try:
                tmp_music_out = os.path.join(TRANSCODE_DIR, f"music_{task_id.replace('-', '')[:12]}_{os.path.basename(merged_out)}")
                applied = apply_background_music(merged_path, music_path, tmp_music_out)
                import shutil
                shutil.copy2(applied, merged_out)
                merged_path = merged_out
                try:
                    if os.path.exists(tmp_music_out):
                        os.remove(tmp_music_out)
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

        tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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

        tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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
            tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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
                tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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

        # Then shutdown
        _perform_app_cleanup()

        # Force-exit the process to ensure the app closes
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
        if not getattr(sys, 'frozen', False):
            return jsonify({'ok': False, 'error': 'Chỉ hỗ trợ khi chạy bản build (EXE)'}), 400
        if os.name != 'nt':
            return jsonify({'ok': False, 'error': 'Only supported on Windows'}), 400

        base_dir = os.path.dirname(sys.executable)
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
        # Backward-compatible alias: reuse the existing /create_images_batch implementation.
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
        grok_duration = str(payload.get('grok_duration') or '6s').strip()
        tasks = payload.get('tasks')

        if not isinstance(tasks, list) or len(tasks) == 0:
            return jsonify({'ok': False, 'error': 'No tasks provided'}), 400

        # Validate scenes content early to avoid creating temp output folders when missing prompt/image
        try:
            for t in tasks:
                scenes = (t or {}).get('scenes')
                if not isinstance(scenes, list) or len(scenes) == 0:
                    continue
                for idx, scene in enumerate(scenes):
                    prompt = str((scene or {}).get('prompt') or '').strip()
                    img_data = str((scene or {}).get('image') or '').strip()
                    if not prompt or not img_data:
                        return jsonify({'ok': False, 'error': f'Thiếu prompt/ảnh ở cảnh {idx + 1}'}), 400
        except Exception:
            pass

        if os.path.isabs(out_dir_label):
            try:
                os.makedirs(out_dir_label, exist_ok=True)
            except Exception:
                pass
        if not (os.path.isabs(out_dir_label) and os.path.isdir(out_dir_label)):
            return jsonify({'ok': False, 'error': 'Vui lòng chọn thư mục lưu kết quả'}), 400

        credit_user_id = ''
        credit_check = None
        credit_count = 0
        credit_limit = 0
        credit_reserved = 0
        credit_remaining = 0
        try:
            credit_user_id = _read_account_id_from_config()
        except Exception:
            credit_user_id = ''

        if credit_user_id:
            try:
                from utils.callserver import check_async

                credit_check = _run_coro_blocking(check_async(credit_user_id))
                data0 = getattr(credit_check, 'data', None)
                if not isinstance(data0, dict):
                    data0 = {}
                try:
                    credit_count = int(data0.get('count') or 0)
                except Exception:
                    credit_count = 0
                try:
                    credit_limit = int(data0.get('limit') or 0)
                except Exception:
                    credit_limit = 0

                try:
                    tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
                    if os.path.exists(tasks_file):
                        import json
                        with open(tasks_file, 'r', encoding='utf-8') as f:
                            raw = f.read()
                        try:
                            tasks_data = json.loads(raw) if raw else []
                        except Exception:
                            tasks_data = []

                        for it in (tasks_data if isinstance(tasks_data, list) else []):
                            try:
                                st = str((it or {}).get('status') or '').lower()
                                if st not in ('processing', 'pending'):
                                    continue
                                name = str((it or {}).get('name') or '')
                                if not name.startswith('Tạo video:'):
                                    continue
                                credit_reserved += 1
                            except Exception:
                                pass
                except Exception:
                    credit_reserved = 0

                credit_remaining = max(0, int(credit_limit - credit_count - credit_reserved))
            except Exception:
                credit_check = None

        if credit_user_id and credit_check is not None and not bool(getattr(credit_check, 'success', False)):
            return jsonify({
                'ok': False,
                'error': str(getattr(credit_check, 'message', '') or '') or 'Không thể kiểm tra lượt',
                'redirect_to_payment': bool(getattr(credit_check, 'redirect_to_payment', False)),
                'count': credit_count,
                'limit': credit_limit,
                'reserved': credit_reserved,
                'remaining': credit_remaining,
            }), 400

        if credit_user_id and credit_limit > 0:
            if credit_remaining <= 0:
                return jsonify({
                    'ok': False,
                    'error': 'Đã hết lượt',
                    'redirect_to_payment': True,
                    'count': credit_count,
                    'limit': credit_limit,
                    'reserved': credit_reserved,
                    'remaining': credit_remaining,
                }), 402

            if len(tasks) > credit_remaining:
                tasks = list(tasks)[:credit_remaining]

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
            'count': credit_count,
            'limit': credit_limit,
            'reserved': credit_reserved,
            'remaining': max(0, credit_remaining - len(mapping)) if (credit_user_id and credit_limit > 0) else None,
        })
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
                    for m in (b or {}).get('mapping') or []:
                        if m and m.get('task_id'):
                            task_ids.append(str(m.get('task_id')))
                    of = (b or {}).get('out_folder_abs')
                    if of:
                        batch_folders.append(str(of))
        except Exception:
            task_ids = []
            batch_folders = []

        # Fallback: infer batch folder from tasks.json scenes_dir (works even if server lost _ASYNC_VIDEO_BATCHES)
        try:
            if task_ids:
                tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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
            tasks_file = os.path.join(EXE_DIR, 'config', 'tasks.json')
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
        
        # Import and run control_profile.py
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), 'utils'))
        
       
        from control_profile import setting_grok_profile, setting_veo3_profile
        
        # Map model names to functions
        model_functions = {
            'Grok (X-AI)': setting_grok_profile,
            'Veo3 (Google)': setting_veo3_profile,
            'Kling AI': lambda: print("Kling AI profile setup not implemented yet")
        }
        
        if model in model_functions:
            result = model_functions[model]()
            return jsonify({'success': True, 'message': f'Profile setup completed for {model}'})
        else:
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


@app.route('/client_ping', methods=['POST'])
def client_ping():
    """Client heartbeat from the UI. When UI closes, heartbeat stops and watchdog will exit the process."""
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
    webbrowser.open("http://127.0.0.1:5000")


def _start_client_watchdog(timeout_sec: float = 12.0, check_interval: float = 2.0) -> None:
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
                # Never crash watchdog
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


def _maybe_check_and_apply_update_on_startup() -> None:
    try:
        if not getattr(sys, 'frozen', False):
            return
        if os.name != 'nt':
            return

        # Apply if already prepared
        ready_path = os.path.join(EXE_DIR, 'temp', 'update_ready.json')
        if os.path.isfile(ready_path):
            _maybe_apply_silent_update_on_startup()
            return

        # Startup immediate check (blocking, best-effort)
        try:
            prepared = bool(check_and_prepare_update_once(app_dir=EXE_DIR))
        except Exception:
            prepared = False

        if not prepared:
            return

        if os.path.isfile(ready_path):
            _maybe_apply_silent_update_on_startup()
    except Exception:
        pass


def _maybe_apply_silent_update_on_startup() -> None:
    try:
        if not getattr(sys, 'frozen', False):
            return
        if os.name != 'nt':
            return

        ready_path = os.path.join(EXE_DIR, 'temp', 'update_ready.json')
        if not os.path.isfile(ready_path):
            return

        updater = os.path.join(EXE_DIR, 'update.exe')
        if not os.path.isfile(updater):
            return

        try:
            subprocess.Popen(
                [updater, '--apply-ready', ready_path, '--app', sys.executable],
                cwd=EXE_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except Exception:
            return

        _force_exit_later(0.4)
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
        
        # CRITICAL: Đảm bảo Chrome đã được khởi động với CDP trước khi tạo ảnh Veo3
        # Veo3 cần kết nối qua CDP để điều khiển browser
        from utils.control_profile import init_global_browser
        try:
            print("[Veo3 API] 🚀 Đảm bảo Chrome đã khởi động với CDP...")
            init_global_browser(provider='grok', kind='default')
            print("[Veo3 API] ✅ Chrome đã sẵn sàng")
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
                # Cleanup temp reference images
                for task in runner_tasks:
                    ref_path = task.get('reference_image')
                    if ref_path and os.path.exists(ref_path):
                        try:
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
    """Tạo video qua Veo3 API - tương tự create_videos_batch nhưng dùng Veo3"""
    try:
        payload = request.get_json(silent=True) or {}
        out_dir_label = str(payload.get('out_dir_label') or '')
        max_tabs = payload.get('max_tabs', 2)
        ratio = str(payload.get('ratio') or '16:9').strip()
        duration = str(payload.get('duration') or '6s').strip()
        account_type = str(payload.get('account_type') or 'ULTRA').strip()
        tasks = payload.get('tasks')
        profile_name = payload.get('profile_name')
        
        # Veo3-specific parameters
        veo3_video_quality = str(payload.get('veo3_video_quality') or 'fast').strip()

        if not isinstance(tasks, list) or len(tasks) == 0:
            return jsonify({'ok': False, 'error': 'No tasks provided'}), 400
        
        # 🔥 CRITICAL: Đảm bảo Chrome đã được khởi động với CDP trước khi tạo video Veo3
        # Veo3 cần kết nối qua CDP để điều khiển browser
        from utils.control_profile import init_global_browser
        try:
            print("[Veo3 Video API] 🚀 Đảm bảo Chrome đã khởi động với CDP...")
            init_global_browser(provider='grok', kind='default')
            print("[Veo3 Video API] ✅ Chrome đã sẵn sàng")
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
            scenes = t.get('scenes', [])

            if not form_id or not isinstance(scenes, list) or len(scenes) == 0:
                continue

            # Veo3 video: mỗi scene = 1 video riêng
            for idx, scene in enumerate(scenes):
                image_data = str((scene or {}).get('image') or '')
                prompt = str((scene or {}).get('prompt') or '')

                if not image_data or not prompt:
                    continue

                out_name = f'{form_id}_scene{idx}_{uuid.uuid4().hex[:4]}.mp4'
                out_abs = os.path.join(out_folder_abs, out_name)

                # Tạo task tracking
                try:
                    from utils.control_script import create_video_task
                    task_id = create_video_task(f'Tạo video Veo3: {out_name}', 'Veo3')
                except Exception:
                    task_id = ''

                if task_id:
                    mapping.append({'form_id': form_id, 'scene_idx': idx, 'task_id': task_id})

                # Decode image data và lưu vào file tạm
                image_path = None
                if image_data.startswith('data:image'):
                    try:
                        import base64
                        b64_part = image_data.split(',', 1)[1]
                        img_bytes = base64.b64decode(b64_part)
                        
                        temp_img = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                        temp_img.write(img_bytes)
                        temp_img.close()
                        image_path = temp_img.name
                    except Exception as e:
                        print(f"[Veo3] ⚠️ Lỗi xử lý image: {e}")
                        continue

                runner_tasks.append({
                    'form_id': form_id,
                    'scene_idx': idx,
                    'task_id': task_id,
                    'image_path': image_path,
                    'prompt': prompt,
                    'out': out_abs,
                    'ratio': ratio,
                    'duration': duration,
                    'quality': veo3_video_quality,
                    'account_type': account_type,
                    'profile_name': profile_name or t.get('profile_name'),
                    'is_custom_dir': is_custom_dir,
                    'out_name': out_name,
                    'out_folder_rel': out_folder_rel if not is_custom_dir else None
                })

        if len(runner_tasks) == 0:
            return jsonify({'ok': False, 'error': 'No valid tasks'}), 400

        from utils.control_creat_video_veo3 import run_video_tasks_veo3

        cancel_event = threading.Event()

        async def _run_veo3_video_async():
            try:
                await run_video_tasks_veo3(
                    context={},
                    tasks=runner_tasks,
                    max_tabs=max_tabs,
                    cancel_event=cancel_event,
                )
            finally:
                # Cleanup temp image files
                for task in runner_tasks:
                    img_path = task.get('image_path')
                    if img_path and os.path.exists(img_path):
                        try:
                            os.remove(img_path)
                        except Exception:
                            pass

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

    _maybe_check_and_apply_update_on_startup()

    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", 5000)) == 0:
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
    threading.Timer(1.0, open_browser).start()
    _start_client_watchdog(timeout_sec=120.0, check_interval=5.0)

    app.run(host="127.0.0.1", port=5000, debug=(not getattr(sys, 'frozen', False)), use_reloader=False, threaded=True)
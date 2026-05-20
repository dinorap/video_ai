# backend/services/nst_flow.py

import json
import base64
import os
import shutil
import time
import threading
import asyncio
import glob
import random
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pathlib import Path
import requests
import warnings
import re
from functools import wraps
from typing import Tuple
from services.nst_browser import NSTBrowserManager
from services.config_loader import get_settings, SETTINGS_FILE
from services.browser_engine import register_profile_api_key_map_builder
from services.grok_frame import extract_first_frame_ffmpeg
from asyncio.proactor_events import _ProactorBasePipeTransport
import asyncio
from services.flow_actions import (
    connect_and_get_page,
    goto_flow_and_open_project,
    is_flow_setup_ready,
    FlowStoppedError,
    select_mode,
    setup_render_settings,
    clamp_aspect_ratio_for_flow_video,
    send_prompt_text,
    upload_master_image_playwright,
    UploadPolicyViolationError,
    click_add_next_scene_playwright,
    cleanup_browser,
    cleanup_all_browsers,
    detach_browser_session,
    random_delay_before_action,
    reset_flow_delay_counter,
    move_mouse_randomly,
    run_human_like_mouse_until,
    _BROWSER_CACHE,
    wait_for_project_ready,
    open_settings_and_select_batch,
)
from services_api.veo_get_token import (  # type: ignore
    auto_collect_veo_auth_on_project_creation,
    load_veo_auth_config,
)
_STOP_SIGNAL = threading.Event()
_CURRENT_LOOP = None
_RUNNING_LOOPS: set = set()
_RUNNING_LOOPS_LOCK = threading.Lock()
FLOW_URL = "https://labs.google/fx/vi/tools/flow"
file_write_lock = threading.Lock()
PROFILE_PROJECT_MAX_AGE_SEC = 24 * 60 * 60


def _is_flow_project_url(url: str) -> bool:
    """Kiểm tra URL có phải link project Flow hợp lệ không."""
    return isinstance(url, str) and "https://labs.google/fx/vi/tools/flow/project/" in url


def _load_profile_project_url(profile_id: str) -> Optional[str]:
    """
    Đọc URL project Flow đã cache cho từng profile từ backend/config/veo_auth.json.
    - Lấy projectId + project_url (nếu có) từ load_veo_auth_config.
    - Nếu thiếu project_url thì tự build từ FLOW_URL + projectId.
    """
    try:
        auth = load_veo_auth_config(str(profile_id))
        if not auth:
            return None
        project_id = str(auth.get("projectId") or "").strip()
        if not project_id:
            return None

        url = (auth.get("project_url") or "").strip()
        if not url:
            url = f"{FLOW_URL.rstrip('/')}/project/{project_id}"

        if not _is_flow_project_url(url):
            return None

        return url
    except Exception:
        return None


def _save_profile_project_url(profile_id: str, url: str) -> None:
    """
    Không còn lưu project URL vào settings.json nữa.
    URL đã được lưu kèm theo auth trong backend/config/veo_auth.json bởi auto_collect_veo_auth_on_project_creation.
    Hàm này giữ lại để backward compat nhưng không làm gì.
    """
    return


async def _goto_flow_with_profile_cache(page, profile_id: str, flow_url: str = FLOW_URL, *, stop_check=None) -> None:
    """
    Điều hướng Flow theo từng profile:
    - Nếu đã có URL project hợp lệ < 1 ngày → goto thẳng URL đó rồi setup.
    - Nếu chưa có / lỗi / quá hạn → tạo project mới rồi lưu URL vào cache.
    """
    if stop_check and stop_check():
        raise FlowStoppedError("Stopped by user")

    saved_url = _load_profile_project_url(profile_id)
    if saved_url:
        try:
            # Nếu page hiện tại đã ở đúng URL project cached thì không cần goto lại nữa
            try:
                current_url = (page.url or "").split("?", 1)[0].rstrip("/")
            except Exception:
                current_url = ""
            target_url = str(saved_url).split("?", 1)[0].rstrip("/")

            await page.bring_to_front()
            if current_url != target_url:
                print(f"[NST Setup] 🌍 Profile {profile_id[-4:]}: goto project cached...")
                await page.goto(saved_url, wait_until="domcontentloaded", timeout=30_000)

            if stop_check and stop_check():
                raise FlowStoppedError("Stopped by user")
            # Đợi UI project sẵn sàng + mở Cài đặt -> Batch giống flow tạo mới
            await wait_for_project_ready(page)
            await open_settings_and_select_batch(page)
            print(f"[NST Setup] ✅ Profile {profile_id[-4:]}: dùng lại project cached.")
            return
        except FlowStoppedError:
            raise
        except Exception as e:
            print(f"[NST Setup] ⚠️ Profile {profile_id[-4:]}: lỗi goto project cached ({e}), sẽ tạo mới...")

    # Fallback: Flow mới → tạo project mới + auto-collect veo_auth cho profile rồi cache URL
    await auto_collect_veo_auth_on_project_creation(
        page,
        profile_id=profile_id,
        flow_url=flow_url,
        timeout_s=60,
        stop_check=stop_check,
    )
    try:
        current_url = page.url or ""
        if _is_flow_project_url(current_url):
            _save_profile_project_url(profile_id, current_url)
    except Exception:
        pass

# Timeout chờ phản hồi theo tab
YT_SCENE_WAIT_TIMEOUT_SEC = 60   # YouTube tab: 1 phút
AI_SCENE_WAIT_TIMEOUT_SEC = 180  # AI tab: 3 phút
MAX_PROFILE_RESTARTS_PER_RUN = 2  # Mỗi profile chỉ được tắt-bật tối đa 2 lần trong 1 phiên chạy

def _build_profile_api_key_map() -> Dict[str, str]:
    settings = get_settings() or {}
    accounts = settings.get("NST_ACCOUNTS") or []
    mapping: Dict[str, str] = {}
    if isinstance(accounts, list):
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            api_key = str(acc.get("API_KEY", "") or "").strip()
            for pid in acc.get("PROFILE_IDS", []) or []:
                pid = str(pid).strip()
                if pid and api_key and pid not in mapping:
                    mapping[pid] = api_key
    if not mapping:
        api_key = str(settings.get("API_KEY", "") or "").strip()
        for pid in settings.get("PROFILE_IDS", []) or []:
            pid = str(pid).strip()
            if pid and api_key and pid not in mapping:
                mapping[pid] = api_key
    return mapping


register_profile_api_key_map_builder(_build_profile_api_key_map)


def _list_active_profiles(nst: NSTBrowserManager, api_key_map: Dict[str, str]) -> set[str]:
    from services.browser_engine import list_active_profile_ids

    return list_active_profile_ids(nst, api_key_map)


def _ensure_profiles_started(nst: NSTBrowserManager, profile_ids: List[str], api_key_map: Dict[str, str]) -> None:
    from services.browser_engine import ensure_profiles_started as _ensure_u

    if not profile_ids or _STOP_SIGNAL.is_set():
        return
    _ensure_u(nst, profile_ids, api_key_map, stop_check=lambda: _STOP_SIGNAL.is_set())

def _stop_profiles_by_key(nst: NSTBrowserManager, profile_ids: List[str], api_key_map: Dict[str, str]) -> None:
    if not profile_ids:
        return
    from services.browser_engine import is_chrome_local
    from services import chrome_local_browser as clb

    if is_chrome_local(get_settings() or {}):
        for pid in profile_ids:
            clb.stop_profile(str(pid).strip())
        return
    grouped: Dict[str, List[str]] = {}
    for pid in profile_ids:
        api_key = api_key_map.get(pid) or ""
        grouped.setdefault(api_key, []).append(pid)
    for api_key, ids in grouped.items():
        nst.stop_profiles(ids, api_key_override=api_key or None)

def _list_browsers_by_key(nst: NSTBrowserManager, api_key: Optional[str]) -> List[Dict[str, Any]]:
    return nst.list_browsers(api_key_override=api_key) or []


async def _cleanup_connected_session(ws: Optional[str], settings: Optional[Dict[str, Any]] = None) -> None:
    if not ws:
        return
    try:
        from services.browser_engine import is_chrome_local as _is_chrome_local
        if _is_chrome_local(settings or get_settings() or {}):
            await detach_browser_session(ws)
            return
    except Exception:
        pass
    await cleanup_browser(ws)


async def _wait_for_profiles_ready(
    nst: NSTBrowserManager,
    profile_ids: List[str],
    api_key_map: Dict[str, str],
    timeout_sec: float = 30.0,
    poll_interval: float = 0.8,
) -> bool:
    """Poll list_browsers cho đến khi tất cả profile có remoteDebuggingPort. Trả True nếu sẵn sàng."""
    from services.browser_engine import wait_for_profiles_ready_unified

    return await wait_for_profiles_ready_unified(
        nst, profile_ids, api_key_map, timeout_sec, poll_interval
    )


# ==============================================================================
# 1. CÁC HÀM HỖ TRỢ (HELPER)
# ==============================================================================
# [THÊM VÀO ĐẦU FILE backend/services/nst_flow.py]

async def move_browser_offscreen(page):
    """Sử dụng CDP để cưỡng ép di chuyển cửa sổ trình duyệt"""
    try:
        # 1. Tạo kết nối CDP cấp thấp
        cdp = await page.context.new_cdp_session(page)

        # 2. Lấy ID của cửa sổ hiện tại
        window_details = await cdp.send("Browser.getWindowForTarget")
        window_id = window_details.get("windowId")

        # 3. Gửi lệnh thay đổi vị trí
        if window_id:
            await cdp.send("Browser.setWindowBounds", {
                "windowId": window_id,
                "bounds": {
                    "left": -3000,      # Tọa độ X (Ra khỏi màn hình)
                    "top": 0,           # Tọa độ Y
                    "windowState": "normal" # 🔥 Quan trọng: Phải đưa về 'normal' mới di chuyển được (nếu đang maximize sẽ bị kẹt)
                }
            })
            print(f"[NST] 👻 Đã đá Browser sang thế giới bên kia (-3000px).")
        
        # 4. Ngắt kết nối CDP cho nhẹ
        await cdp.detach()
        
    except Exception as e:
        print(f"[NST] ⚠️ Lỗi di chuyển cửa sổ (CDP): {e}")

async def set_fake_fullscreen_offscreen(page):
    """
    Set kích thước Full HD (1920x1080) nhưng giấu đi chỗ khác.
    Giúp web load giao diện PC đầy đủ mà không vướng mắt.
    """
    try:
        cdp = await page.context.new_cdp_session(page)
        window_details = await cdp.send("Browser.getWindowForTarget")
        window_id = window_details.get("windowId")

        if window_id:
            await cdp.send("Browser.setWindowBounds", {
                "windowId": window_id,
                "bounds": {
                    "windowState": "normal", # 🔥 Bắt buộc là 'normal' để chỉnh được tọa độ
                    "left": -3000,           # Vứt ra xa tít mù tắp
                    "top": 0,
                    "width": 1920,           # Chiều rộng Full HD
                    "height": 1080           # Chiều cao Full HD
                }
            })
            print(f"[NST] 👻 Browser đã bật chế độ: Full HD + Tàng hình.")
        
        await cdp.detach()
    except Exception as e:
        print(f"[NST] ⚠️ Lỗi set fake fullscreen: {e}")

async def inject_keep_alive(page):
    """Tiêm code chống ngủ đông vào Page"""
    try:
        from services.browser_engine import is_chrome_local as _is_chrome_local
        if _is_chrome_local(get_settings() or {}):
            return
    except Exception:
        pass
    try:
        await page.evaluate("""() => {
            if (window._keepAliveInjected) return;
            window._keepAliveInjected = true;
            console.log("⚡ [NST] Injecting Keep-Alive...");
            
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            
            const ctx = new AudioContext();
            const oscillator = ctx.createOscillator();
            const gainNode = ctx.createGain();
            
            gainNode.gain.value = 0.00001; // Âm thanh siêu nhỏ
            
            oscillator.connect(gainNode);
            gainNode.connect(ctx.destination);
            oscillator.start();
            
            setInterval(() => {
                document.title = document.title.startsWith("⚡") ? document.title.substring(2) : "⚡ " + document.title;
            }, 2000);
        }""")
    except: pass


def _should_move_windows() -> bool:
    """Đọc setting MOVE để quyết định có đẩy browser ra ngoài màn hình hay không."""
    try:
        settings = get_settings()
        return bool(settings.get("MOVE", False))
    except Exception:
        return False


async def _maybe_move_window(page):
    """Đẩy browser ra ngoài màn hình nếu MOVE = true."""
    if not page:
        return
    if not _should_move_windows():
        return
    try:
        await set_fake_fullscreen_offscreen(page)
    except Exception as e:
        print(f"[NST] ⚠️ Không thể di chuyển cửa sổ: {e}")


async def update_scene_status(script_path: str, scene_id: int, new_status: str, file_path: str = None):
    """Cập nhật trạng thái cảnh (Có khóa an toàn)"""
    if not script_path: return
    
    # Resolve đường dẫn trước khi sử dụng
    abs_path = _resolve_script_path(script_path)
    if not abs_path or not os.path.exists(abs_path):
        return

    # 🔥 Bọc khóa: Chỉ 1 người được vào đây tại 1 thời điểm
    with file_write_lock:
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            scenes = data.get("scenes", [])
            updated = False
            for s in scenes:
                if s["scene_id"] == scene_id:
                    s["status"] = new_status
                    # Lưu đường dẫn file nếu có
                    if file_path:
                            # Chuyển về chữ thường để so sánh cho chắc ăn
                            lower_path = file_path.lower() 
                            
                            # Cú pháp endswith với tuple (gọn hơn dùng or)
                            if lower_path.endswith(('.mp4', '.avi', '.mov', '.mkv')):
                                s["video_url"] = file_path
                               
                                
                            elif lower_path.endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                s["image_url"] = file_path
                                
                    updated = True
                    break
            
            if updated:
                with open(abs_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Lỗi ghi file status: {e}")

def _resolve_script_path(script_path: str) -> str:
    """Helper function để resolve đường dẫn script_path (tương đối/tuyệt đối)"""
    if not script_path:
        return None
    
    # Nếu là đường dẫn tuyệt đối, dùng trực tiếp
    if os.path.isabs(script_path):
        return os.path.normpath(script_path)
    
    # Xử lý đường dẫn tương đối
    from utils.path_helper import BASE_DIR, STORAGE_DIR
    normalized = script_path.replace("/", os.sep).replace("\\", os.sep)
    
    # Xử lý đường dẫn bắt đầu bằng ../storage/
    if normalized.startswith(".." + os.sep + "storage" + os.sep):
        rel_path = normalized[len(".." + os.sep + "storage" + os.sep):]
        return os.path.normpath(str(STORAGE_DIR / rel_path))
    elif normalized.startswith("storage" + os.sep):
        rel_path = normalized[len("storage" + os.sep):]
        return os.path.normpath(str(STORAGE_DIR / rel_path))
    elif normalized.startswith(".." + os.sep):
        normalized = normalized[3:]  # Bỏ "../"
        return os.path.normpath(str(BASE_DIR / normalized))
    else:
        return os.path.normpath(str(BASE_DIR / normalized))

async def set_setup_state(script_path: str, is_setting_up: bool):
    """Cập nhật trạng thái Setup (Có khóa an toàn)"""
    if not script_path: return
    
    # Resolve đường dẫn trước khi sử dụng
    abs_path = _resolve_script_path(script_path)
    if not abs_path:
        return
    
    with file_write_lock:
        try:
            if os.path.exists(abs_path):
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                print(f"⚠️ File không tồn tại: {abs_path} (từ script_path: {script_path})")
                return

            data["is_setting_up"] = is_setting_up
            
            # Reset luôn timestamp để frontend cập nhật
            import time
            data["last_updated"] = time.time()

            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Lỗi set_setup_state: {e}")

async def set_script_running_state(script_path: str, is_running: bool):
    """Cập nhật trạng thái Đang chạy (Có khóa an toàn)"""
    if not script_path: return

    # Resolve đường dẫn trước khi sử dụng
    abs_path = _resolve_script_path(script_path)
    if not abs_path:
        return

    with file_write_lock:
        try:
            if os.path.exists(abs_path):
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                print(f"⚠️ File không tồn tại: {abs_path} (từ script_path: {script_path})")
                return

            data["is_running"] = is_running
            # 🔥 RESET FLAGS: Khi bắt đầu chạy (is_running = true), reset các flags hoàn thành
            if is_running:
                data["tts_completed"] = False
                data["video_completed"] = False
            data["last_updated"] = time.time()

            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Lỗi set_script_running_state: {e}")


async def set_script_run_finished(script_path: str):
    """Cập nhật script khi chạy xong tất cả: is_running=False, is_setting_up=False, is_retrying=False, last_updated=now. Frontend dựa vào đó để phát chuông."""
    if not script_path:
        return
    abs_path = _resolve_script_path(script_path)
    if not abs_path:
        return
    with file_write_lock:
        try:
            if os.path.exists(abs_path):
                with open(abs_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                return
            data["is_running"] = False
            data["is_setting_up"] = False
            data["is_retrying"] = False
            data["last_updated"] = time.time()
            with open(abs_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Lỗi set_script_run_finished: {e}")


async def set_script_retry_state(script_path: str, is_retrying: bool):
    """Cập nhật trạng thái Retry (Có khóa an toàn)"""
    if not script_path:
        return
    abs_path = _resolve_script_path(script_path)
    if not abs_path:
        return
    with file_write_lock:
        try:
            if os.path.exists(abs_path):
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                print(f"⚠️ File không tồn tại: {abs_path} (từ script_path: {script_path})")
                return
            data["is_retrying"] = is_retrying
            import time
            data["last_updated"] = time.time()
            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Lỗi set_script_retry_state: {e}")


async def set_script_run_error(script_path: str, message: str):
    """Log lỗi runtime ra console; KHÔNG ghi vào file script nữa (theo yêu cầu user)."""
    try:
        print(f"[SCRIPT RUN ERROR] ({script_path}): {message}")
    except Exception as e:
        print(f"❌ Lỗi set_script_run_error: {e}")


    
def silence_event_loop_closed(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (RuntimeError, ValueError, OSError, ConnectionResetError):
            return
    return wrapper

def stop_all_tasks():
    """
    Hàm cưỡng chế dừng toàn bộ quy trình:
    1. Bật cờ _STOP_SIGNAL để các vòng lặp tự thoát.
    2. Hủy các task async đang chờ.
    (ĐÓNG BROWSER sẽ do caller quyết định: stop_all_profiles hoặc stop_profiles_by_ids)
    """
    global _CURRENT_LOOP
    print("[System] 🛑 NHẬN LỆNH STOP KHẨN CẤP!")

    result_msg = []

    # 1. Bật cờ dừng
    _STOP_SIGNAL.set()

    # 2. Hủy TẤT CẢ Event Loop đang chạy (run, open, setup, master gen...)
    with _RUNNING_LOOPS_LOCK:
        loops_to_stop = list(_RUNNING_LOOPS)
    for loop in loops_to_stop:
        try:
            if loop.is_running():
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                loop.call_soon_threadsafe(loop.stop)
        except Exception as e:
            result_msg.append(f"Lỗi hủy loop: {e}")
    if loops_to_stop:
        result_msg.append("Đã hủy các tác vụ Async nền.")
    
    _CURRENT_LOOP = None
    
    print(f"[System] 🏁 Kết quả Stop: {', '.join(result_msg)}")
    return {"success": True, "message": "Đã thực hiện dừng khẩn cấp quy trình."}

def _agent_host(agent_url: str) -> str:
    parsed = urlparse(agent_url)
    return parsed.hostname or "127.0.0.1"

def _get_browser_ws_endpoint(host: str, port: int) -> Optional[str]:
    try:
        r = requests.get(f"http://{host}:{int(port)}/json/version", timeout=5)
        return r.json().get("webSocketDebuggerUrl")
    except Exception:
        return None

# ==============================================================================
# 2. QUẢN LÝ BROWSER
# ==============================================================================

def open_flow_first_background(count: int, *, flow_url: str = FLOW_URL, wait_seconds: float = 2.0) -> int:
    from services.browser_engine import profile_pool_for_run, get_ws_endpoint_for_profile

    # Có thể vừa bấm Stop trước đó (F5/pagehide). Reset cờ để lệnh Open thực sự chạy.
    _STOP_SIGNAL.clear()

    settings = get_settings() or {}
    nst = NSTBrowserManager()
    api_key_map = _build_profile_api_key_map()
    ids = profile_pool_for_run(count, settings)

    def _run():
        """Wrapper function để chạy async code trong thread"""
        if not ids:
            return
        if _STOP_SIGNAL.is_set():
            return
        print(f"[Browser Open] 🚀 Đang khởi động {len(ids)} profiles (song song)...")
        with ThreadPoolExecutor(max_workers=max(1, len(ids))) as ex:
            futs = [
                ex.submit(_ensure_profiles_started, nst, [pid], api_key_map)
                for pid in ids
            ]
            for fu in futs:
                try:
                    fu.result()
                except Exception as e:
                    print(f"[Browser Open] ⚠️ ensure profile: {e}")
            ex.shutdown(wait=True)

        if _STOP_SIGNAL.is_set():
            return

        async def _open_tabs():
            if _STOP_SIGNAL.is_set():
                return
            await _wait_for_profiles_ready(nst, ids, api_key_map)

            async def _open_one(pid: str) -> None:
                ws = get_ws_endpoint_for_profile(
                    nst, pid, api_key_map.get(pid), settings=settings
                )
                if not ws:
                    print(f"[Browser Open] ⚠️ Profile {pid[-6:]} chưa sẵn sàng / không lấy được WS.")
                    return
                page = await connect_and_get_page(ws)
                if not page:
                    return
                try:
                    await _maybe_move_window(page)
                    print(f"[Browser Open] 🌍 Profile {pid[-6:]} -> Truy cập: {flow_url}")
                    last_err: Optional[Exception] = None
                    for attempt in range(2):
                        try:
                            await page.goto(flow_url, wait_until="domcontentloaded", timeout=30_000)
                            last_err = None
                            break
                        except Exception as e:
                            last_err = e
                            if attempt == 0:
                                await asyncio.sleep(1.2)
                            else:
                                raise
                except Exception as e:
                    print(f"⚠️ Lỗi điều hướng Profile {pid[-6:]}: {e}")
                finally:
                    try:
                        await detach_browser_session(ws)
                    except Exception:
                        pass

            await asyncio.gather(*[_open_one(pid) for pid in ids])
        
        try:
            if os.name == 'nt':
                _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with _RUNNING_LOOPS_LOCK:
                _RUNNING_LOOPS.add(loop)
            try:
                loop.run_until_complete(_open_tabs())
            finally:
                with _RUNNING_LOOPS_LOCK:
                    _RUNNING_LOOPS.discard(loop)
                loop.close()
            print("[Browser Open] ✅ Đã xử lý xong lệnh mở.")
        except Exception as e:
            print(f"[Browser Open] ❌ Lỗi: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return len(ids)

def stop_all_profiles() -> bool:
    """
    ⚠️ Chính sách mới: KHÔNG BAO GIỜ stop_all().
    Chỉ dừng theo danh sách `PROFILE_IDS_ACTIVE` trong settings.json.
    Nếu không có `PROFILE_IDS_ACTIVE` thì không đóng browser nào.
    """
    try:
        asyncio.run(cleanup_all_browsers())
    except Exception:
        pass

    settings: Dict[str, Any] = {}
    try:
        settings = get_settings() or {}
        ids = settings.get("PROFILE_IDS_ACTIVE") or []
        ids = [str(x).strip() for x in ids if str(x).strip()]
    except Exception:
        ids = []

    if not ids:
        print("[NST Stop] ℹ️ PROFILE_IDS_ACTIVE rỗng → không stop browser nào (không dùng stop_all).")
        try:
            from services.browser_engine import is_chrome_local
            from services import chrome_local_browser as clb

            if is_chrome_local(settings):
                clb.stop_all_tracked()
        except Exception:
            pass
        return False

    print(f"[NST Stop] 🛑 Dừng profiles theo PROFILE_IDS_ACTIVE: {ids}")
    return bool(stop_profiles_by_ids(ids))


def stop_profiles_by_ids(profile_ids: List[str]) -> bool:
    """
    Dừng CHỈ các profile_id được truyền vào (theo từng API Key).
    Không đụng tới các profile khác đang chạy.
    """
    from services.browser_engine import stop_profiles_by_ids_unified

    return stop_profiles_by_ids_unified(profile_ids)


def _ws_endpoint_for_profile(
    nst: NSTBrowserManager,
    profile_id: str,
    api_key_map: Dict[str, str],
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    from services.browser_engine import get_ws_endpoint_for_profile

    s = settings if settings is not None else (get_settings() or {})
    return get_ws_endpoint_for_profile(
        nst, profile_id, api_key_map.get(profile_id), settings=s
    )


def _resolve_flow_mode_from_script(abs_script_path: str) -> Optional[str]:
    """Đọc script, xác định mode: có master_cast_image_prompt → video, không → text_to_video."""
    try:
        with open(abs_script_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        prompt = (data.get("master_cast_image_prompt") or "").strip()
        return "video" if prompt else "text_to_video"
    except Exception:
        return None


def _is_vertical_ratio(ratio_value: Optional[str]) -> bool:
    """
    Map ratio theo đúng frontend:
    - '9:16'  -> Dọc
    - '16:9'  -> Ngang
    """
    raw = str(ratio_value or "").strip().lower().replace(" ", "")
    return raw == "9:16"


def _flow_setup_aspect_ratio(ratio_value: Optional[str], flow_mode: str) -> str:
    """Chuỗi tỉ lệ cho setup_render_settings (video Flow chỉ có 16:9/9:16)."""
    fm = (flow_mode or "").strip().lower()
    if fm == "video":
        return clamp_aspect_ratio_for_flow_video(ratio_value)
    return str(ratio_value or "16:9")


def run_flow_with_settings_background(
    count: int, 
    mode: str, 
    model: str, 
    ratio: str, 
    script_path: str = None, 
    *, 
    flow_url: str = FLOW_URL,
    yt_use_reference_image: bool = False,
) -> int:
    # Quan trọng: nếu vừa bấm Stop trước đó thì phải reset cờ,
    # nếu không vòng setup sẽ break ngay và không goto Flow.
    _STOP_SIGNAL.clear()

    # Chuẩn hóa mode setup theo tab mới của frontend:
    # - YouTube tab: luôn image
    # - AI tab: luôn video (không dùng text_to_video ở setup mới)
    requested_mode = (mode or "").strip().lower()
    mode_hint_path = (_resolve_script_path(script_path) or script_path or "").replace("\\", "/").lower()
    if "/youtube_" in mode_hint_path:
        mode = "image"
    elif "/ai_" in mode_hint_path:
        mode = "video"
    elif requested_mode == "text_to_video":
        mode = "video"
    elif requested_mode in {"image", "video"}:
        mode = requested_mode
    else:
        mode = "image"
    print(f"[NST Setup] 🎯 Mode setup đã chuẩn hóa: {mode} (request='{requested_mode or 'empty'}')")

    # Chuẩn hóa model setup theo mode để tránh lấy nhầm model giữa AI/Youtube.
    requested_model = str(model or "").strip()
    normalized_model = requested_model
    if mode == "video":
        # AI setup dùng nhóm Veo; nếu nhận model Banana (thường do state cũ), ép về default Veo.
        normalized_model_lower = normalized_model.lower()
        if (
            "veo 3.1 - fast" in normalized_model_lower
            and "priority" in normalized_model_lower
        ):
            normalized_model = "Veo 3.1 - Lite [Lower Priority]"
        elif (not normalized_model) or ("banana" in normalized_model_lower):
            normalized_model = "Veo 3.1 - Lite [Lower Priority]"
    else:
        # YouTube/image: fallback model Banana Pro khi thiếu model.
        if not normalized_model:
            normalized_model = "🍌 Nano Banana Pro"
    print(f"[NST Setup] 🎛️ Model setup đã chuẩn hóa: {normalized_model} (request='{requested_model or 'empty'}')")

    # YouTube + ảnh tham chiếu: chỉ upload/crop, không đổi mode.
    if mode == "image" and yt_use_reference_image and script_path:
        abs_path = _resolve_script_path(script_path)
        if abs_path and os.path.exists(abs_path):
            try:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                has_master = bool((data.get("master_cast_image_prompt") or "").strip())
                rel_path = data.get("master_image_url")
                if has_master and rel_path:
                    script_dir = os.path.dirname(abs_path)
                    mode_dir = os.path.dirname(script_dir)
                    full_path = os.path.join(mode_dir, rel_path)
                    if os.path.exists(full_path):
                        # Chỉ log để debug, KHÔNG đổi mode.
                        print(f"[NST Setup] 📌 YouTube ảnh tham chiếu: tìm thấy master ở {full_path} (mode: image)")
            except Exception:
                pass

    def _run():
        if os.name == 'nt':
            _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        # Tạo Event Loop riêng cho Thread này
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with _RUNNING_LOOPS_LOCK:
            _RUNNING_LOOPS.add(loop)

        # Định nghĩa luồng chính (Async)
        async def _main():
            # 1. BẬT TRẠNG THÁI (Async + Lock)
            # Chuyển vào đây để dùng await, tránh xung đột file
            if script_path: 
                print(f"[NST Setup] 🔒 Lock file: is_setting_up = True")
                await set_setup_state(script_path, True)

            try:
                # 2. Khởi tạo NST & Lấy ID
                from services.browser_engine import profile_pool_for_run

                nst = NSTBrowserManager()
                api_key_map = _build_profile_api_key_map()
                settings_snap = get_settings() or {}
                ids = profile_pool_for_run(count, settings_snap)

                # Nếu không có profile nào -> Return luôn (Finally sẽ lo việc tắt state)
                if not ids:
                    print("[NST Setup] ⚠️ Không tìm thấy profile nào để chạy.")
                    return

                # Chỉ start browsers, KHÔNG connect/setup. Run sẽ connect 1 lần và làm hết (goto + setup + work).
                print(f"[NST Setup] 🚀 Khởi động {len(ids)} browser (warm-up, Run sẽ connect + setup)...")
                await asyncio.gather(
                    *[
                        asyncio.to_thread(
                            _ensure_profiles_started,
                            nst,
                            [pid],
                            api_key_map,
                        )
                        for pid in ids
                    ]
                )
                await _wait_for_profiles_ready(nst, ids, api_key_map)
                print(f"[NST Setup] ✅ Đã start {len(ids)} browser. Đang goto Flow + chọn mode + setup...")

                # 3. Connect từng profile → goto Flow + select mode + setup_render.
                # Chạy song song để setup đa luồng ngay từ đầu.
                async def _setup_one_profile(pid: str):
                    if _STOP_SIGNAL.is_set():
                        return
                    ws = _ws_endpoint_for_profile(
                        nst, pid, api_key_map, settings=settings_snap
                    )
                    if not ws:
                        print(f"[NST Setup] ⚠️ Profile {pid[-4:]} chưa sẵn sàng / không lấy được WS, bỏ qua.")
                        return
                    page = await connect_and_get_page(ws)
                    if not page:
                        print(f"[NST Setup] ⚠️ Profile {pid[-4:]} không kết nối được, bỏ qua.")
                        return
                    try:
                        await _maybe_move_window(page)
                        print(f"[NST Setup] 🌍 Profile {pid[-4:]}: goto Flow (không cache)...")
                        await goto_flow_and_open_project(page, flow_url, stop_check=lambda: _STOP_SIGNAL.is_set())
                        await inject_keep_alive(page)
                        print(f"[NST Setup] 📌 Profile {pid[-4:]}: chọn mode {mode}...")
                        ok = await select_mode(page, mode, stop_check=lambda: _STOP_SIGNAL.is_set())
                        if not ok:
                            print(f"[NST Setup] ⚠️ Profile {pid[-4:]}: không chọn được mode {mode}.")
                        else:
                            # ✅ Setup settings phải thành công thì mới được báo "setup xong".
                            settings_ok = await setup_render_settings(
                                page,
                                output_count=1,
                                aspect_ratio=_flow_setup_aspect_ratio(ratio, mode),
                                model=normalized_model,
                                select_ingredients=(mode == "video"),
                            )
                            if settings_ok:
                                print(f"[NST Setup] ✅ Profile {pid[-4:]}: goto Flow + setup xong.")
                            else:
                                print(
                                    f"[NST Setup] ⚠️ Profile {pid[-4:]}: setup_render_settings lỗi, "
                                    "KHÔNG đánh dấu setup xong (hãy thử Setup lại)."
                                )
                    except FlowStoppedError:
                        return
                    except Exception as e:
                        print(f"[NST Setup] ⚠️ Profile {pid[-4:]}: {e}")
                    # Không đóng page, để browser mở sẵn cho Run dùng

                await asyncio.gather(*[_setup_one_profile(pid) for pid in ids], return_exceptions=True)

                print(f"[NST Setup] ✅ Hoàn tất. Bấm Run để chạy tạo ảnh/video.")
            
            except Exception as e:
                print(f"[NST Setup] ❌ Lỗi quá trình setup: {e}")
            
            finally:
                # 4. TẮT TRẠNG THÁI (Async + Lock)
                # Chạy xong hết (hoặc lỗi) thì mới chốt hạ về False
                if script_path: 
                    print(f"[NST Setup] 🔓 Unlock file: is_setting_up = False")
                    await set_setup_state(script_path, False)

        # Kích hoạt chạy
        try:
            loop.run_until_complete(_main())
        finally:
            with _RUNNING_LOOPS_LOCK:
                _RUNNING_LOOPS.discard(loop)
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return count


def start_flow_on_startup_background():
    if os.getenv("NST_AUTO_OPEN_FLOW", "0") != "1": return None
    pass


# ==========================================================
# 3. LOGIC GENERATE ẢNH (YOUTUBE) - ĐÃ FIX PENDING_SCENES
# ==========================================================
def execute_youtube_generation(
    count: int,
    script_path: str,
    delay_seconds: float = 0.0,
    max_scenes: Optional[int] = None,
    start_scene: Optional[int] = None,
    end_scene: Optional[int] = None,
    yt_video_resolution: Optional[str] = None,
    yt_use_reference_image: bool = False,
    mode: Optional[str] = None,
    ratio: Optional[str] = None,
    model: Optional[str] = None,
    use_auto_switch_profile: bool = False,
    batch_k: Optional[int] = None,
    max_scenes_per_profile: Optional[int] = None,
    batch_retry: Optional[int] = None,
) -> Dict[str, Any]:
    _STOP_SIGNAL.clear()
    abs_script_path = _resolve_script_path(script_path)
    if not abs_script_path or not os.path.exists(abs_script_path):
        return {"error": f"File không tồn tại: {script_path} (resolved: {abs_script_path})"}

    try:
        with open(abs_script_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            scenes = data.get("scenes", [])
    except Exception as e:
        return {"error": f"Lỗi đọc file kịch bản: {e}"}

    # 🔥 Xác định mode: YouTube luôn chạy FLOW mode = image.
    # Ảnh tham chiếu chỉ dùng để upload/crop/click Add Next Scene, KHÔNG đổi sang mode video.
    effective_mode = "image"
    master_image_path = None
    if yt_use_reference_image:
        relative_img = data.get("master_image_url")
        if relative_img:
            script_dir = os.path.dirname(abs_script_path)
            mode_dir = os.path.dirname(script_dir)
            full_path = os.path.join(mode_dir, relative_img)
            if os.path.exists(full_path):
                master_image_path = full_path
                # Vẫn log ra cho dễ debug, nhưng giữ mode=image
                print(f"[Youtube] ✅ Ảnh tham chiếu: {master_image_path} (mode: image)")
            else:
                print(f"[Youtube] ⚠️ Bật ảnh tham chiếu nhưng không tìm thấy file: {full_path}. Chạy mode image.")
        else:
            print(f"[Youtube] 📝 Bật ảnh tham chiếu nhưng script chưa có master_image_url. Chạy mode image.")
    else:
        print(f"[Youtube] 📝 Không dùng ảnh tham chiếu (mode: image)")
    print(f"[Youtube] 📌 yt_use_reference_image={yt_use_reference_image}, master_image_path={'set' if master_image_path else 'None'} (để debug nếu khách báo mất đồng bộ)")

    nst = NSTBrowserManager()
    api_key_map = _build_profile_api_key_map()
    settings_snap = get_settings() or {}
    from services.browser_engine import profile_pool_for_run

    use_batch_mode = use_auto_switch_profile and (batch_k or 0) > 0
    if use_batch_mode:
        from services.nst_flow_auto_switch import get_auto_switch_profile_pool, compute_batch_assignments
        profile_pool = get_auto_switch_profile_pool(nst, get_settings)
        if not profile_pool:
            return {"error": "Thiếu danh sách profile (PROFILE_IDS_ACTIVE hoặc NST profiles)"}
        K = min(batch_k or 4, len(profile_pool))
        print(f"[Youtube] 🔄 Batch mode: N={len(profile_pool)} profiles, K={K} luồng, max_cảnh/profile={max_scenes_per_profile or 0}")
    elif use_auto_switch_profile:
        from services.nst_flow_auto_switch import get_auto_switch_profile_pool, get_active_ids_for_attempt
        profile_pool = get_auto_switch_profile_pool(nst, get_settings)
        active_ids = get_active_ids_for_attempt(profile_pool, count, set())
        print(f"[Youtube] 🔄 Auto-switch profile: pool={len(profile_pool)} profiles, active={[p[-4:] for p in active_ids]}")
    else:
        profile_pool = profile_pool_for_run(count, settings_snap)
        active_ids = profile_pool

    scenes_to_consider = _filter_scenes_by_range(
        scenes,
        start_scene,
        end_scene,
        max_scenes
    )
    tasks_to_run = []
    for s in scenes_to_consider:
        status = s.get("status")
        if status != "done":
            tasks_to_run.append({
                "scene_id": s["scene_id"],
                "prompt": s.get("image_prompt") or s.get("video_prompt") or ""
            })

    if not tasks_to_run:
        return {"success": True, "message": "Tất cả đã hoàn thành!"}

    if use_batch_mode:
        active_ids = profile_pool
    else:
        if not scenes or not active_ids:
            return {"error": "Thiếu dữ liệu scenes hoặc profiles"}
        assignments = {}
        for i, pid in enumerate(active_ids):
            assignments[pid] = []
        for i, task in enumerate(tasks_to_run):
            pid = active_ids[i % len(active_ids)]
            assignments[pid].append(task)

    # Reset delay counter cho batch mới
    reset_flow_delay_counter()

    async def _worker(pid, tasks, attempt: int = 0, upload_master_first_scene: bool = False) -> Tuple[bool, List[Dict[str, Any]]]:
        """Trả về (completed, remaining_tasks). upload_master_first_scene=True khi vừa setup xong (phiên NST mới) → cảnh đầu upload ảnh master; cùng browser chạy tiếp thì Add Next Scene."""
        completed = False
        remaining_tasks_early: List[Dict[str, Any]] = []  # Luôn khởi tạo để return trong finally an toàn
        if not tasks:
            return (completed, [])
        if _STOP_SIGNAL.is_set():
            return (completed, [])
        ws = _ws_endpoint_for_profile(nst, pid, api_key_map, settings=settings_snap)
        if not ws:
            print(f"[Youtube] ⚠️ Profile {pid[-4:]} không còn kết nối hoặc chưa sẵn sàng. Bỏ qua, coi như hoàn thành lượt này. Vòng retry sẽ bật lại nếu cần.")
            return (completed, list(tasks))

        page = await connect_and_get_page(ws)
        if not page:
            print(f"[Youtube] ⚠️ Không kết nối được profile {pid[-4:]}. Bỏ qua, vòng retry sẽ bật lại.")
            return (completed, list(tasks))
        await _maybe_move_window(page)

        # Nếu vừa setup xong và UI còn nguyên thì tái sử dụng luôn, tránh goto lần 2.
        try:
            reused_setup = False
            if await is_flow_setup_ready(page):
                reused_setup = True
                print(
                    f"[Youtube] ♻️ Profile {pid[-4:]}: Flow đã sẵn sau Setup — "
                    "bỏ qua goto và không lặp chọn mode/model."
                )
                await inject_keep_alive(page)
            else:
                print(f"[Youtube] 🚀 Profile {pid[-4:]}: goto Flow, setup, rồi chạy...")
                await goto_flow_and_open_project(page, FLOW_URL, stop_check=lambda: _STOP_SIGNAL.is_set())
                await inject_keep_alive(page)

            # Chỉ chạy select_mode + setup_render khi vừa mở project mới (chưa qua NST Setup cùng tab).
            did_setup = False
            if reused_setup:
                did_setup = True
            else:
                for setup_attempt in range(2):
                    ok = await select_mode(page, effective_mode, stop_check=lambda: _STOP_SIGNAL.is_set())
                    if not ok:
                        print(
                            f"[Youtube] ❌ Profile {pid[-4:]}: Không chọn được mode {effective_mode} "
                            f"(attempt {setup_attempt+1}/2)."
                        )
                        if setup_attempt == 0:
                            await asyncio.sleep(0.8)
                            continue
                        return (completed, list(tasks))

                    settings_ok = await setup_render_settings(
                        page,
                        output_count=1,
                        aspect_ratio=_flow_setup_aspect_ratio(ratio, effective_mode),
                        model=model,
                        select_ingredients=(effective_mode == "video"),
                    )
                    if settings_ok:
                        did_setup = True
                        break

                    print(
                        f"[Youtube] ⚠️ Profile {pid[-4:]}: setup_render_settings lỗi (attempt {setup_attempt+1}/2). "
                        "Sẽ mở lại combobox preset và thử lại toàn bộ setup."
                    )
                    if setup_attempt == 0:
                        await asyncio.sleep(0.8)
                        continue
                    return (completed, list(tasks))

            if reused_setup and not did_setup:
                return (completed, list(tasks))
        except FlowStoppedError:
            return (completed, list(tasks))
        except Exception as e:
            print(f"[Youtube] ❌ Setup profile {pid[-4:]}: {e}")
            return (completed, list(tasks))

        # --- CHUẨN BỊ MÔI TRƯỜNG ---
        prompt_map: Dict[str, int] = {}
        
        # 🔥 [FIXED] KHỞI TẠO PENDING_SCENES
        pending_scenes = set() 
        scene_events: Dict[int, asyncio.Event] = {}
        scene_results: Dict[int, str] = {}
        
        # Dùng abs_script_path đã resolve
        project_dir = os.path.dirname(os.path.dirname(abs_script_path))
        images_output_dir = os.path.join(project_dir, "images")
        os.makedirs(images_output_dir, exist_ok=True)
        
        # Truyền pending_scenes vào setup_cdp_image_listener
        cdp_session = await setup_cdp_image_listener(
            page,
            prompt_map,
            images_output_dir,
            abs_script_path,
            pending_scenes,
            scene_events,
            scene_results,
            yt_video_resolution=yt_video_resolution
        )

        # 🔥 Ảnh tham chiếu: CDP listener cho crop event (giống AI tab / test_upload_image_flow)
        cdp_crop = None
        crop_success_event = None
        # Dùng master_image_path để nhận biết đang dùng ảnh tham chiếu, KHÔNG dựa vào FLOW mode.
        if yt_use_reference_image and master_image_path:
            try:
                crop_success_event = asyncio.Event()
                cdp_crop = await page.context.new_cdp_session(page)
                await cdp_crop.send("Network.enable")

                def _on_crop(ev):
                    rq = ev.get("request", {})
                    if "submitBatchLog" in rq.get("url", "") and "PINHOLE_CROP_IMAGE" in (rq.get("postData") or ""):
                        crop_success_event.set()

                cdp_crop.on("Network.requestWillBeSent", _on_crop)
            except Exception as e:
                print(f"[Youtube] ⚠️ Không setup được CDP crop listener: {e}")
                cdp_crop = None

        print(f"[Youtube] 🚀 Driver {pid[-4:]} bắt đầu gửi lệnh...")
        consecutive_restart_errors = 0
        upload_master_on_next_scene = False  # Sau captcha restart (page mới) → upload lại ở cảnh tiếp
        first_scene_retry_done = False  # Cảnh đầu lỗi sau khi gửi prompt -> retry lại CHÍNH cảnh đầu 1 lần
        try:
            is_first_prompt = True
            idx = 0
            retry_same_scene = False
            while idx < len(tasks):
                item = tasks[idx]
                if _STOP_SIGNAL.is_set():
                    print(f"[Youtube] 🛑 Worker {pid} dừng gửi lệnh do có tín hiệu Stop.")
                    remaining_tasks_early = list(tasks[idx:])
                    break
                scene_id = item["scene_id"]
                raw_prompt = item["prompt"].strip()

                norm_key = normalize_text(raw_prompt)
                prompt_map[norm_key] = scene_id

                # 🔥 [FIXED] THÊM SCENE VÀO DANH SÁCH CHỜ
                pending_scenes.add(scene_id)
                scene_event = asyncio.Event()
                scene_events[scene_id] = scene_event
                scene_results.pop(scene_id, None)

                # 🔥 Random delay trước khi gửi prompt/ảnh (3–10s để giảm pattern bot)
                if is_first_prompt:
                    await random_delay_before_action(min_seconds=1, max_seconds=3)
                    is_first_prompt = False
                else:
                    await random_delay_before_action(min_seconds=1, max_seconds=3)

                # 🔥 Ảnh tham chiếu: upload master CHỈ khi phiên NST mới; cùng browser chạy cảnh 2,3... thì Add Next Scene (giống AI tab).
                if yt_use_reference_image and master_image_path:
                    should_upload_reference = (
                        (idx == 0 and (upload_master_first_scene or attempt == 0 or upload_master_on_next_scene))
                    )
                    if should_upload_reference:
                        print(f"[Youtube] 📤 Phiên mới (upload_first={upload_master_first_scene}, attempt={attempt}) → Upload ảnh tham chiếu (Scene {scene_id}) - Driver {pid[-4:]}...")
                        upload_master_on_next_scene = False
                        try:
                            upload_ok = await upload_master_image_playwright(page, master_image_path)
                        except UploadPolicyViolationError as e:
                            policy_msg = str(e) or "Ảnh tham chiếu vi phạm chính sách Google. Vui lòng đổi ảnh khác."
                            print(f"[Youtube] ⛔ {policy_msg}")
                            await set_script_run_error(abs_script_path, policy_msg)
                            stop_all_tasks()
                            remaining_tasks_early = list(tasks[idx:])
                            break
                        if not upload_ok:
                            print(f"[Youtube] ❌ Upload ảnh tham chiếu thất bại (Scene {scene_id}) - Driver {pid[-4:]}.")
                            await update_scene_status(abs_script_path, scene_id, "captcha_error")
                            remaining_tasks_early = list(tasks[idx + 1:])
                            idx += 1
                            continue
                        # Upload mới đã tự đợi API log upload; không chờ crop event nữa để tránh treo.
                        if _STOP_SIGNAL.is_set():
                            remaining_tasks_early = list(tasks[idx:])
                            break
                        await asyncio.sleep(2)
                    elif (idx > 0 or not (upload_master_first_scene or attempt == 0 or upload_master_on_next_scene)) and (not retry_same_scene):
                        # Cảnh 2+ hoặc cùng browser chạy tiếp (retry) → Add Next Scene, không upload lại
                        print(f"[Youtube] ➕ Cùng browser tiếp (upload_first={upload_master_first_scene}, attempt={attempt}) → Add Next Scene (Scene {scene_id}) - Driver {pid[-4:]}...")
                        await click_add_next_scene_playwright(page)
                        await asyncio.sleep(2)

                # Chỉ chạy tới đây khi upload ảnh tham chiếu (nếu có) đã OK và đã thấy API upload.
                print(f"[Youtube] 📤 Gửi Scene {scene_id}...")
                await asyncio.sleep(random.uniform(0.0, 0.3))
                await send_prompt_text(page, raw_prompt)

                await update_scene_status(abs_script_path, scene_id, "processing    ")

                print(f"[Youtube] ⏳ Đợi phản hồi (URL/Lỗi) cho Scene {scene_id}... (timeout {YT_SCENE_WAIT_TIMEOUT_SEC}s)")
                mouse_stop = asyncio.Event()
                mouse_task = asyncio.create_task(run_human_like_mouse_until(page, mouse_stop))
                loop_wait = asyncio.get_running_loop()
                scene_wait_start = loop_wait.time()
                try:
                    while not scene_event.is_set():
                        if _STOP_SIGNAL.is_set():
                            print(f"[Youtube] 🛑 Dừng chờ Scene {scene_id} do lệnh Stop.")
                            break
                        if page.is_closed():
                            print(f"[Youtube] ❌ Browser bị đóng khi chờ Scene {scene_id}.")
                            break
                        if loop_wait.time() - scene_wait_start > YT_SCENE_WAIT_TIMEOUT_SEC:
                            print(f"[Youtube] ⚠️ Scene {scene_id} timeout ({YT_SCENE_WAIT_TIMEOUT_SEC}s). Đánh dấu lỗi và chuyển cảnh kế.")
                            await update_scene_status(abs_script_path, scene_id, "captcha_error")
                            pending_scenes.discard(scene_id)
                            prompt_map.pop(norm_key, None)
                            scene_results[scene_id] = "captcha_error"
                            scene_event.set()
                            break
                        await asyncio.sleep(random.uniform(0.4, 0.6))
                finally:
                    mouse_stop.set()
                    try:
                        await asyncio.wait_for(mouse_task, 1.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        mouse_task.cancel()
                        try:
                            await mouse_task
                        except asyncio.CancelledError:
                            pass

                if _STOP_SIGNAL.is_set() or page.is_closed():
                    remaining_tasks_early = list(tasks[idx + 1:])
                    break

                # 🔥 Phân biệt captcha_error vs lỗi khác
                result_type = scene_results.get(scene_id)

                # Cảnh đầu lỗi sau khi đã gửi prompt: đợi 4-5s rồi upload lại + gửi lại CHÍNH cảnh đầu.
                if (
                    result_type == "captcha_error"
                    and idx == 0
                    and yt_use_reference_image
                    and bool(master_image_path)
                    and not first_scene_retry_done
                ):
                    first_scene_retry_done = True
                    settle_s = random.uniform(4.0, 5.0)
                    print(f"[Youtube] 🔁 Scene đầu lỗi captcha -> đợi {settle_s:.1f}s rồi retry lại Scene {scene_id}...")
                    pending_scenes.discard(scene_id)
                    scene_events.pop(scene_id, None)
                    scene_results.pop(scene_id, None)
                    prompt_map.pop(norm_key, None)
                    upload_master_on_next_scene = True
                    await asyncio.sleep(settle_s)
                    continue

                if result_type == "captcha_error":
                    consecutive_restart_errors += 1
                else:
                    consecutive_restart_errors = 0
                # Nếu đã tạo cảnh thành công thì reset chuỗi restart liên tiếp của profile.
                if result_type == "done":
                    profile_restart_attempts[pid] = 0

                if result_type == "captcha_error" and consecutive_restart_errors >= 2:
                    if _STOP_SIGNAL.is_set():
                        print(f"[Youtube] 🛑 Nhận STOP khi chuẩn bị restart profile {pid[-4:]} – bỏ qua restart.")
                        remaining_tasks_early = list(tasks[idx:])
                        break
                    restart_used = int(profile_restart_attempts.get(pid, 0))
                    if restart_used >= MAX_PROFILE_RESTARTS_PER_RUN:
                        print(
                            f"[Youtube] ⛔ Profile {pid[-4:]} đã restart đủ {MAX_PROFILE_RESTARTS_PER_RUN} lần. "
                            f"Tắt hẳn profile khỏi phiên chạy hiện tại."
                        )
                        permanently_disabled_profiles.add(pid)
                        try:
                            if cdp_session:
                                await cdp_session.detach()
                                cdp_session = None
                        except Exception:
                            pass
                        try:
                            if cdp_crop:
                                await cdp_crop.detach()
                                cdp_crop = None
                        except Exception:
                            pass
                        await _cleanup_connected_session(ws, settings_snap)
                        _stop_profiles_by_key(nst, [pid], api_key_map)
                        remaining_tasks_early = list(tasks[idx:])
                        break

                    profile_restart_attempts[pid] = restart_used + 1
                    try:
                        if cdp_session:
                            await cdp_session.detach()
                            cdp_session = None
                    except Exception:
                        pass
                    await _cleanup_connected_session(ws, settings_snap)
                    _stop_profiles_by_key(nst, [pid], api_key_map)
                    await asyncio.sleep(4)
                    print(
                        f"[Youtube] 🧱 Lỗi liên tiếp {consecutive_restart_errors} lần "
                        f"(type={result_type}) - restart profile {pid[-4:]} "
                        f"({profile_restart_attempts[pid]}/{MAX_PROFILE_RESTARTS_PER_RUN})..."
                    )
                    _ensure_profiles_started(nst, [pid], api_key_map)
                    if _STOP_SIGNAL.is_set():
                        print(f"[Youtube] 🛑 STOP sau khi ensure_profiles_started, không chờ profile ready nữa.")
                        remaining_tasks_early = list(tasks[idx:])
                        break
                    await _wait_for_profiles_ready(nst, [pid], api_key_map)
                    ws = _ws_endpoint_for_profile(nst, pid, api_key_map, settings=settings_snap)
                    if not ws:
                        print(f"[Youtube] ❌ Không tìm thấy profile {pid[-4:]} sau khi bật lại.")
                        remaining_tasks_early = list(tasks[idx:])
                        break
                    page = await connect_and_get_page(ws)
                    if not page:
                        print(f"[Youtube] ❌ Không kết nối được page profile {pid[-4:]}")
                        remaining_tasks_early = list(tasks[idx:])
                        break
                    await _maybe_move_window(page)
                    print(f"[Youtube] 🔄 Profile {pid[-4:]}: setup lại Flow sau lỗi liên tiếp...")
                    try:
                        await goto_flow_and_open_project(page, FLOW_URL, stop_check=lambda: _STOP_SIGNAL.is_set())
                        await inject_keep_alive(page)
                        ok = await select_mode(page, effective_mode, stop_check=lambda: _STOP_SIGNAL.is_set())
                        if not ok:
                            print(f"[Youtube] ❌ Profile {pid[-4:]}: Không chọn được mode sau restart.")
                            break
                        await setup_render_settings(
                            page,
                            output_count=1,
                            aspect_ratio=_flow_setup_aspect_ratio(ratio, effective_mode),
                            model=model,
                            select_ingredients=(effective_mode == "video"),
                        )
                    except Exception as e:
                        print(f"[Youtube] ⚠️ Setup Flow sau restart: {e}")
                    prompt_map.clear()
                    pending_scenes.clear()
                    scene_events.clear()
                    scene_results.clear()
                    for t in tasks[idx:]:
                        prompt_map[normalize_text(t["prompt"])] = t["scene_id"]
                    cdp_session = await setup_cdp_image_listener(
                        page, prompt_map, images_output_dir, abs_script_path,
                        pending_scenes, scene_events, scene_results,
                        yt_video_resolution=yt_video_resolution
                    )
                    # 🔥 Tạo lại cdp_crop cho ảnh tham chiếu (page mới sau restart)
                    if yt_use_reference_image and master_image_path:
                        try:
                            if cdp_crop:
                                try:
                                    await cdp_crop.detach()
                                except Exception:
                                    pass
                            crop_success_event = asyncio.Event()

                            def _on_crop2(ev):
                                rq = ev.get("request", {})
                                if "submitBatchLog" in rq.get("url", "") and "PINHOLE_CROP_IMAGE" in (rq.get("postData") or ""):
                                    crop_success_event.set()

                            cdp_crop = await page.context.new_cdp_session(page)
                            await cdp_crop.send("Network.enable")
                            cdp_crop.on("Network.requestWillBeSent", _on_crop2)
                        except Exception as e:
                            print(f"[Youtube] ⚠️ Không setup lại CDP crop: {e}")
                            cdp_crop = None
                    tasks = list(tasks[idx:])
                    idx = 0
                    is_first_prompt = True
                    upload_master_on_next_scene = True  # Page mới sau restart → upload lại ở cảnh tiếp
                    consecutive_restart_errors = 0
                    await random_delay_before_action(min_seconds=3.0, max_seconds=10.0)
                    continue

                # Quy tắc mới: captcha_error thì giữ nguyên cảnh hiện tại để gửi lại.
                # content_error thì đi cảnh tiếp theo (xử lý ở đoạn idx += 1 bên dưới).
                if result_type == "captcha_error":
                    settle_s = random.uniform(4.0, 5.0)
                    print(f"[Youtube] 🔁 Captcha ở Scene {scene_id} -> đợi {settle_s:.1f}s rồi gửi lại CHÍNH cảnh này.")
                    retry_same_scene = True
                    pending_scenes.discard(scene_id)
                    scene_events.pop(scene_id, None)
                    scene_results.pop(scene_id, None)
                    prompt_map.pop(norm_key, None)
                    if idx == 0 and yt_use_reference_image and bool(master_image_path):
                        upload_master_on_next_scene = True
                    await asyncio.sleep(settle_s)
                    continue

                # content_error / error: đã ghi lỗi vào script, gửi prompt mới (không cooldown, không dừng)

                scene_events.pop(scene_id, None)
                scene_results.pop(scene_id, None)
                retry_same_scene = False
                idx += 1

            if remaining_tasks_early:
                print(f"[Youtube] 🛑 Đã dừng sớm. Còn {len(pending_scenes)} ảnh đang chờ, {len(remaining_tasks_early)} cảnh chưa gửi.")
            else:
                print(f"[Youtube] 🛑 Đã gửi hết lệnh. Đang chờ {len(pending_scenes)} ảnh về...")

            if not remaining_tasks_early:
                MAX_WAIT = 60
                loop = asyncio.get_running_loop()
                start_wait = loop.time()
                while pending_scenes:
                    if _STOP_SIGNAL.is_set():
                        print("[Youtube] 🛑 Dừng chờ kết quả.")
                        break
                    if loop.time() - start_wait > MAX_WAIT:
                        print(f"[Youtube] ⚠️ Hết thời gian chờ kết quả (Timeout).")
                        break
                    if page.is_closed():
                        print("[Youtube] ❌ Browser bị đóng đột ngột.")
                        break
                    await asyncio.sleep(2.0)

            print(f"[Youtube] ✅ Worker hoàn tất.")
            completed = (
                len(pending_scenes) == 0
                and not remaining_tasks_early
                and not _STOP_SIGNAL.is_set()
                and not page.is_closed()
            )

            # 🔥 Cleanup CDP monitoring sau khi hoàn thành
            try:
                if 'cdp_session' in locals() and cdp_session:
                    await cdp_session.send("Network.disable")
                    print("[YouTube Image] 🔌 Đã disable Network monitoring")
            except Exception as e:
                print(f"[YouTube Image] ⚠️ Lỗi cleanup CDP: {e}")

        except asyncio.CancelledError:
            print("Stop signal received.")
            raise
        except Exception as e:
            # Nếu stop_all_tasks giết browser, Playwright sẽ throw lỗi ở đây.
            # Ta bắt lỗi và bỏ qua nhẹ nhàng để thread không bị crash xấu xí
            if _STOP_SIGNAL.is_set():
                print(f"[Youtube] ⚠️ Worker {pid} bị ngắt kết nối do lệnh Stop.")
            else:
                print(f"[Youtube] ❌ Lỗi worker {pid}: {e}")
        
        finally:
            try:
                if cdp_session: await cdp_session.detach()
            except: pass
            try:
                if cdp_crop: await cdp_crop.detach()
            except: pass
            try:
                # Nếu danh sách chờ trống rỗng (tức là đã xong hết 100%) -> Đóng
                if len(pending_scenes) == 0:
                    print(f"[Youtube] ✅ Đã hoàn thành task lượt này. (GIỮ BROWSER ĐỂ RETRY).")
                    # await page.close()
                else:
                    # Nếu còn cảnh đang treo (lỗi/timeout) -> Giữ lại để Vòng 2 chạy tiếp (hoặc để debug)
                    print(f"[Youtube] ⚠️ Vẫn còn {len(pending_scenes)} cảnh chưa có kết quả. GIỮ browser {pid[-4:]} lại.")
            except: pass
            # try: await page.close()
            # except: pass
        return (completed, remaining_tasks_early)

    failed_profiles_this_run: set = set()
    profile_restart_attempts: Dict[str, int] = {}
    permanently_disabled_profiles: set = set()

    async def _runner_with_retry():
        nonlocal active_ids
        reset_flow_delay_counter()
        MAX_RETRIES = 2
        for attempt in range(MAX_RETRIES):
            if _STOP_SIGNAL.is_set():
                print("[Youtube] 🛑 Dừng retry do tín hiệu Stop.")
                break
            print(f"\n🔄 --- YOUTUBE VÒNG {attempt + 1}/{MAX_RETRIES} ---\n")
            # 🔄 Auto-switch: mỗi lượt dùng profile chưa lỗi từ pool
            if use_auto_switch_profile:
                alive_pool = [p for p in profile_pool if p not in permanently_disabled_profiles]
                active_ids = get_active_ids_for_attempt(alive_pool, count, failed_profiles_this_run)
                if not active_ids:
                    print("[Youtube] ⚠️ Auto-switch: không còn profile nào. Dừng.")
                    break
                print(f"[Youtube] 🔄 Auto-switch: lượt này dùng {[p[-4:] for p in active_ids]} (đã loại {[p[-4:] for p in failed_profiles_this_run]})")
            else:
                active_ids = [p for p in active_ids if p not in permanently_disabled_profiles]
                if not active_ids:
                    print("[Youtube] ⚠️ Không còn profile sống sau khi loại profile lỗi nặng. Dừng.")
                    break
            # Nếu vừa nhận STOP trong lúc tính pool/active_ids thì tuyệt đối không start/reconnect lại NST.
            if _STOP_SIGNAL.is_set():
                print("[Youtube] 🛑 Đã nhận Stop trước khi start profiles (bỏ qua retry vòng này).")
                break
            _ensure_profiles_started(nst, active_ids, api_key_map)
            # Chặn thêm lần nữa vì STOP có thể đến ngay sau khi start_profiles được gọi.
            if _STOP_SIGNAL.is_set():
                print("[Youtube] 🛑 Đã nhận Stop ngay sau khi start profiles (không chờ ready nữa).")
                break
            await _wait_for_profiles_ready(nst, active_ids, api_key_map)
            if _STOP_SIGNAL.is_set():
                print("[Youtube] 🛑 Đã nhận Stop sau khi chờ profiles ready, kết thúc ngay.")
                break

            try:
                with file_write_lock:
                    if os.path.exists(abs_script_path):
                        with open(abs_script_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            scenes = data.get("scenes", [])
                    else:
                        scenes = []
            except Exception as e:
                print(f"❌ Lỗi đọc file: {e}")
                scenes = []

            scenes_to_retry = _filter_scenes_by_range(
                scenes,
                start_scene,
                end_scene,
                max_scenes
            )
            tasks_retry = []
            for s in scenes_to_retry:
                st = (s.get("status") or "").strip()
                # content_error không retry (lỗi nội dung cấm, sửa prompt rồi chạy tay)
                if st not in ("done", "content_error"):
                    tasks_retry.append({
                        "scene_id": s["scene_id"],
                        "prompt": s.get("image_prompt") or s.get("video_prompt") or ""
                    })

            if not tasks_retry:
                print("✅ Tất cả task đã hoàn thành (hoặc chỉ còn content_error). STOP.")
                break

            new_assignments = {pid: [] for pid in active_ids}
            for i, task in enumerate(tasks_retry):
                pid = active_ids[i % len(active_ids)]
                new_assignments[pid].append(task)
            ordered_pids = list(new_assignments.keys())
            results = await asyncio.gather(*[
                _worker(pid, tasks, attempt, upload_master_first_scene=(attempt == 0))
                for pid, tasks in new_assignments.items()
            ])
            if use_auto_switch_profile:
                for idx, (completed, rem) in enumerate(results):
                    if rem and idx < len(ordered_pids):
                        failed_profiles_this_run.add(ordered_pids[idx])
            if _STOP_SIGNAL.is_set():
                print("[Youtube] 🛑 Đã nhận Stop sau vòng chạy, kết thúc ngay.")
                break
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(5)

    def _read_remaining_tasks():
        """Đọc file, trả về list task (cảnh chưa done/content_error) theo start_scene/end_scene/max_scenes."""
        try:
            with file_write_lock:
                if os.path.exists(abs_script_path):
                    with open(abs_script_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        scenes = data.get("scenes", [])
                else:
                    scenes = []
        except Exception as e:
            print(f"❌ Lỗi đọc file: {e}")
            return []
        scenes_to_retry = _filter_scenes_by_range(scenes, start_scene, end_scene, max_scenes)
        tasks_retry = []
        for s in scenes_to_retry:
            if (s.get("status") or "").strip() not in ("done", "content_error"):
                tasks_retry.append({
                    "scene_id": s["scene_id"],
                    "prompt": s.get("image_prompt") or s.get("video_prompt") or ""
                })
        return tasks_retry

    async def _runner_batch():
        """Xoay tự động: giống chạy bình thường (setup, captcha đóng/mở lại). Mỗi batch đợi đủ K profile xong (hoặc bị đóng captcha 2 lần) rồi đóng hết, mở batch tiếp. Sau mỗi batch đọc lại file, chia cảnh còn lại cho batch tiếp. Retry=2 → chạy xong 1-4,5-8 rồi quay lại 1-4,5-8 với cảnh còn lỗi. Không dùng vòng retry của chạy bình thường."""
        reset_flow_delay_counter()
        retry_count = max(1, min(10, batch_retry or 1))
        N = len(profile_pool)
        for retry_round in range(retry_count):
            if _STOP_SIGNAL.is_set():
                print("[Youtube] 🛑 Dừng theo lệnh Stop.")
                break
            alive_pool = [p for p in profile_pool if p not in permanently_disabled_profiles]
            if not alive_pool:
                print("[Youtube] ⛔ Không còn profile sống. Dừng batch retry.")
                break
            remaining = _read_remaining_tasks()
            if not remaining:
                print(f"[Youtube] ✅ Vòng {retry_round + 1}: Tất cả đã hoàn thành. Dừng retry.")
                break
            print(f"\n🔄 --- YOUTUBE RETRY VÒNG {retry_round + 1}/{retry_count} ({len(remaining)} cảnh chưa xong) ---\n")
            batch_start = 0
            N = len(alive_pool)
            while batch_start < N:
                if _STOP_SIGNAL.is_set():
                    break
                remaining = _read_remaining_tasks()
                if not remaining:
                    break
                pids_in_batch = alive_pool[batch_start : batch_start + K]
                batches_this = compute_batch_assignments(
                    pids_in_batch, len(pids_in_batch), remaining,
                    max_per_profile=max_scenes_per_profile or 0,
                )
                if not batches_this or not any(t for _, t in batches_this[0]):
                    batch_start += K
                    continue
                batch = batches_this[0]
                pids_in_batch = [pid for pid, _ in batch]
                print(f"\n📦 --- BATCH {batch_start // K + 1} (profiles {[p[-4:] for p in pids_in_batch]}, {sum(len(t) for _, t in batch)} cảnh) ---\n")
                # STOP đến trong lúc batch đang xoay thì không được start/reconnect profiles nữa.
                if _STOP_SIGNAL.is_set():
                    break
                _ensure_profiles_started(nst, pids_in_batch, api_key_map)
                if _STOP_SIGNAL.is_set():
                    break
                await _wait_for_profiles_ready(nst, pids_in_batch, api_key_map)
                if _STOP_SIGNAL.is_set():
                    break
                await asyncio.gather(*[
                    _worker(pid, tasks, 0, upload_master_first_scene=True)
                    for pid, tasks in batch
                ])
                _stop_profiles_by_key(nst, pids_in_batch, api_key_map)
                batch_start += K
                if batch_start < N:
                    await asyncio.sleep(3)
            if retry_round < retry_count - 1:
                await asyncio.sleep(5)

    def run_safe():
        global _CURRENT_LOOP 
        
        # Setup Event Loop cho Windows
        if os.name == 'nt':
            _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _CURRENT_LOOP = loop
        with _RUNNING_LOOPS_LOCK:
            _RUNNING_LOOPS.add(loop)
        
        # 🔥 TẠO WRAPPER ĐỂ GỌI HÀM ASYNC
        async def _wrapper():
            # 1. Bật trạng thái Running (Có khóa Lock)
            print(f"[Thread] 🔒 Lock file: is_running = True")
            await set_script_retry_state(abs_script_path, True)
            await set_script_running_state(abs_script_path, True)
            
            try:
                if use_batch_mode:
                    await _runner_batch()
                else:
                    await _runner_with_retry()
                
            except asyncio.CancelledError:
                print("[Thread] Đã dừng theo lệnh Stop.")
            except Exception as e:
                print(f"[Thread Error] {e}")
            finally:
                await set_script_retry_state(abs_script_path, False)
                # 3. Tắt trạng thái Running (Có khóa Lock)
                # Dù chạy xong hay lỗi thì cũng phải vào đây để mở khóa file
                print("[System] 🏁 Thread đã đóng hoàn toàn. Unlock file.")
                await set_script_running_state(abs_script_path, False)
                
                # 4. Đóng trình duyệt dọn dẹp
                print("[System] 🛑 Quy trình kết thúc. Đóng NST Profiles...")
                stop_all_profiles()

        # 🔥 CHẠY WRAPPER TRONG LOOP
        try:
            loop.run_until_complete(_wrapper())
        except Exception as e:
            print(f"[Run Loop Error] {e}")
        finally:
            with _RUNNING_LOOPS_LOCK:
                _RUNNING_LOOPS.discard(loop)
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except: pass
            _CURRENT_LOOP = None

    t = threading.Thread(target=run_safe, daemon=True)
    t.start()

    return {"success": True, "count": len(tasks_to_run), "message": "Đang chạy (Kèm cơ chế Retry)..."}

# ==========================================================
# CÁC HÀM XỬ LÝ VIDEO VÀ DOWNLOAD
# ==========================================================

def parse_google_video_response(text_content: str) -> List[Dict]:
    results = []
    try:
        clean_text = text_content.strip()
        if clean_text.startswith(")]}'"):
            clean_text = clean_text.split("\n", 1)[1]
        data = json.loads(clean_text)

        # ===== Format cũ: operations[] =====
        operations = data.get("operations", [])
        for op_wrapper in operations:
            metadata = op_wrapper.get("operation", {}).get("metadata", {})
            video_info = metadata.get("video", {})
            fife_url = (
                video_info.get("fifeUrl")
                or video_info.get("url")
                or video_info.get("downloadUrl")
                or video_info.get("uri")
            )
            prompt = video_info.get("prompt")
            media_id = video_info.get("mediaGenerationId") or op_wrapper.get("sceneId")
            status = (op_wrapper.get("operation", {}).get("done") and "MEDIA_GENERATION_STATUS_SUCCESSFUL") or None
            if prompt and (fife_url or media_id):
                results.append({"url": fife_url, "prompt": prompt, "id": media_id, "status": status})

        # ===== Format mới: media[] (video:batchCheckAsyncVideoGenerationStatus) =====
        medias = data.get("media", [])
        for item in medias:
            media_meta = item.get("mediaMetadata", {}) or {}
            req_data = media_meta.get("requestData", {}) or {}
            v_obj = item.get("video", {}) or {}
            gen_v = v_obj.get("generatedVideo", {}) or {}

            # Prompt ưu tiên theo payload requestData, fallback mediaTitle / generatedVideo.prompt
            prompt = None
            try:
                prompt = (
                    req_data.get("promptInputs", [{}])[0]
                    .get("structuredPrompt", {})
                    .get("parts", [{}])[0]
                    .get("text")
                )
            except Exception:
                prompt = None
            prompt = prompt or media_meta.get("mediaTitle") or gen_v.get("prompt")

            status = (media_meta.get("mediaStatus", {}) or {}).get("mediaGenerationStatus")
            media_id = item.get("name") or (v_obj.get("operation", {}) or {}).get("name")

            # URL có thể xuất hiện khác key tùy backend
            video_url = (
                gen_v.get("fifeUrl")
                or gen_v.get("url")
                or gen_v.get("downloadUrl")
                or gen_v.get("uri")
                or (v_obj.get("operation", {}) or {}).get("url")
                or item.get("url")
            )

            if prompt and (video_url or media_id):
                results.append({"url": video_url, "prompt": prompt, "id": media_id, "status": status})
    except: pass
    return results

def download_video_robust(url, save_path, max_retries=3, timeout=30):
    import time
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, timeout=timeout)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024): 
                        if chunk: f.write(chunk)
                return True
        except Exception: pass
        if attempt < max_retries - 1: time.sleep(5)
    return False


# ----- Cách tải Veo3 mới: CDP bắt URL video (không thumbnail) rồi requests.get (thay cho download_video_by_media_id) -----
VEO3_REDIRECT_URL = "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}"


def _is_file_video(path: str) -> bool:
    """Kiểm tra file có phải video (MP4 ftyp hoặc WebM EBML) hay không."""
    try:
        with open(path, "rb") as f:
            header = f.read(12)
        if len(header) >= 8:
            # MP4: offset 4 = "ftyp"
            if header[4:8] == b"ftyp":
                return True
            # WebM/Matroska: EBML 0x1A 0x45 0xDF 0xA3
            if header[:4] == b"\x1a\x45\xdf\xa3":
                return True
    except Exception:
        pass
    return False


def _is_file_image(path: str) -> bool:
    """Kiểm tra file có phải ảnh (JPEG/PNG/WebP/GIF) hay không."""
    try:
        with open(path, "rb") as f:
            header = f.read(12)
        if len(header) >= 3:
            # JPEG: FF D8 FF
            if header[:3] == b"\xff\xd8\xff":
                return True
            # PNG: 89 50 4E 47 0D 0A 1A 0A
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                return True
            # GIF: GIF87a hoặc GIF89a
            if header[:6] in (b"GIF87a", b"GIF89a"):
                return True
            # WebP: RIFF....WEBP
            if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                return True
    except Exception:
        pass
    return False


def _download_veo3_video_by_url(video_url: str, save_path: str, max_retries: int = 3, timeout: int = 60) -> bool:
    """Tải video từ URL signed (sau khi đã lấy qua CDP redirect). Xác minh file là MP4, xóa nếu là ảnh."""
    import time
    for attempt in range(max_retries):
        try:
            r = requests.get(video_url, stream=True, timeout=timeout)
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            # Xác minh: nếu là ảnh thì xóa và báo lỗi (tránh tải nhầm thumbnail)
            if _is_file_image(save_path):
                try:
                    os.remove(save_path)
                except Exception:
                    pass
                print(f"[AI Video] ❌ URL trả về ảnh thay vì video, bỏ qua: {video_url[:80]}...")
                return False
            if not _is_file_video(save_path):
                try:
                    os.remove(save_path)
                except Exception:
                    pass
                print(f"[AI Video] ❌ File tải về không phải video hợp lệ (MP4/WebM): {video_url[:80]}...")
                return False
            return True
        except Exception as e:
            if attempt >= max_retries - 1:
                print(f"[AI Video] ❌ Tải theo URL thất bại: {e}")
                return False
            time.sleep(3)
    return False


async def _get_veo3_final_video_url_via_cdp(page, redirect_url: str) -> Optional[str]:
    """
    Load redirect URL trong iframe, CDP bắt request sau 302 → trả về URL video thật (video/mp4 hoặc /video/),
    bỏ qua thumbnail (image, /image/). Giống logic veo3_video_stream_downloader.
    """
    cdp = await page.context.new_cdp_session(page)
    await cdp.send("Network.enable", {})
    requests_list: List[Tuple[str, str]] = []
    responses: Dict[str, Any] = {}

    def on_request(event):
        rid = event.get("requestId")
        u = (event.get("request") or {}).get("url", "")
        if rid and u:
            requests_list.append((rid, u))

    def on_response(event):
        rid = event.get("requestId")
        resp = event.get("response", {})
        if rid:
            responses[rid] = {
                "url": resp.get("url"),
                "status": resp.get("status"),
                "mimeType": resp.get("mimeType"),
            }

    cdp.on("Network.requestWillBeSent", on_request)
    cdp.on("Network.responseReceived", on_response)

    try:
        requests_list.clear()
        responses.clear()
        await page.evaluate(
            """(url) => {
                return new Promise((resolve) => {
                    const iframe = document.createElement('iframe');
                    iframe.style.cssText = 'position:absolute;width:0;height:0;border:0';
                    iframe.src = url;
                    const done = () => { try { iframe.remove(); } catch(e){} resolve(); };
                    iframe.onload = () => setTimeout(done, 2000);
                    iframe.onerror = () => setTimeout(done, 2000);
                    document.body.appendChild(iframe);
                    setTimeout(done, 3500);
                });
            }""",
            redirect_url,
        )
        await asyncio.sleep(0.5)
    finally:
        cdp.remove_listener("Network.requestWillBeSent", on_request)
        cdp.remove_listener("Network.responseReceived", on_response)

    candidates = [
        (rid, u)
        for rid, u in requests_list
        if u != redirect_url and u.startswith("http") and "labs.google/fx" not in u
    ]
    final_url: Optional[str] = None
    u_lower = ""
    for rid, u in candidates:
        mime = (responses.get(rid) or {}).get("mimeType") or ""
        u_lower = u.lower()
        # Chắc chắn là video: mime video/* hoặc path /video/ hoặc .mp4/.webm
        is_video = (
            mime.startswith("video/")
            or "/video/" in u_lower
            or u_lower.endswith(".mp4")
            or ".mp4?" in u_lower
            or u_lower.endswith(".webm")
            or ".webm?" in u_lower
        )
        # Chắc chắn là ảnh: bỏ qua
        is_image = (
            "image" in mime
            or "/image/" in u_lower
            or "/img/" in u_lower
            or u_lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
            or any(f".{ext}?" in u_lower for ext in ("jpg", "jpeg", "png", "webp", "gif"))
        )
        if is_image:
            continue
        if is_video:
            final_url = u
            break
        # Không dùng URL không rõ (mime trống, path không có /video/) — tránh tải nhầm ảnh
    return final_url


async def setup_video_result_listener_logic_moi(
    page,
    prompt_map: Dict[str, int],
    output_dir: str,
    script_path: str,
    pending_scenes: set,
    scene_events: Dict[int, asyncio.Event],
    scene_results: Dict[int, str],
    n_limit: int,
    ai_video_resolution: Optional[str] = None,
):
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable", {
            "maxTotalBufferSize": 10000000,
            "maxResourceBufferSize": 5000000
        })

        state = {"tempt": 0, "stop_triggered": False}

        # 720p hay 1080p (ưu tiên 1080p nếu được chọn)
        want_1080p = (ai_video_resolution or "").lower() == "1080p"
        
        # 📒 SỔ TAY 1: Request ID -> Prompt (Dùng cho lỗi 403/400)
        req_id_to_prompt_map = {} 
        
        # 📒 SỔ TAY 2: Google UUID -> Prompt (Dùng cho lỗi Code 3)
        google_id_to_prompt_map = {}

        watched_request_ids = set()
        processed_media_ids = set()
        success_no_url_logged = set()
        script_name = os.path.splitext(os.path.basename(script_path))[0]
        specific_output_dir = os.path.join(output_dir, script_name)
        os.makedirs(specific_output_dir, exist_ok=True)

        # Dùng cookie/user-agent thật từ browser để tải video theo media-id (tránh CORS/redirect inline)
        ctx_cookies: Dict[str, str] = {}
        browser_ua = "Mozilla/5.0"
        try:
            cookie_items = await page.context.cookies()
            ctx_cookies = {
                c.get("name"): c.get("value")
                for c in cookie_items
                if c.get("name") and c.get("value")
            }
        except Exception:
            ctx_cookies = {}
        try:
            browser_ua = await page.evaluate("() => navigator.userAgent")
        except Exception:
            browser_ua = "Mozilla/5.0"

        # --- DOWNLOAD 1080p (nếu bật) ---
        download_event: asyncio.Event = asyncio.Event()
        download_state: Dict[str, Any] = {"guid": None, "filename": None, "state": None}

        # JS thao tác mới cho video:
        # Hover tile -> mở 3 chấm -> Tải xuống -> 1080p Upscaled
        CLICK_UPSCALE_1080P_JS = r"""
        async function () {
            console.log("🔍 Đang chạy chuỗi Auto: Hover -> Mở Menu -> Tải xuống -> 1080p Upscaled...");

            const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
            const simulateEnterClick = async (el) => {
                el.focus();
                el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                await wait(50);
            };

            const tile = document.querySelector('div[data-tile-id]');
            if (!tile) {
                return { ok: false, reason: "Không tìm thấy vùng chứa video (data-tile-id)." };
            }
            tile.scrollIntoView({ behavior: 'smooth', block: 'center' });

            const hoverTarget = tile.querySelector('a') || tile;
            ['mouseenter', 'mouseover', 'mousemove'].forEach(name => {
                hoverTarget.dispatchEvent(new MouseEvent(name, { bubbles: true, cancelable: true, view: window }));
            });
            await wait(400);

            const threeDotBtn = Array.from(tile.querySelectorAll('button')).find(btn =>
                (btn.innerText.includes('Tạo thêm') || btn.innerHTML.includes('more_vert')) &&
                btn.querySelector('i')?.getAttribute('font-size') === '1.15rem'
            );
            if (!threeDotBtn) {
                return { ok: false, reason: "Hover rồi nhưng không tóm được nút 3 chấm nhỏ." };
            }

            console.log("✅ Bước 1: Đang mở menu 3 chấm...");
            await simulateEnterClick(threeDotBtn);

            await wait(350);
            const menuItems = Array.from(document.querySelectorAll('[role="menuitem"], div[class*="goZcMY"]'));
            const downloadBtn = menuItems.find(el => el.innerText.includes('Tải xuống'));
            if (!downloadBtn) {
                return { ok: false, reason: "Menu đã mở nhưng không tìm thấy nút 'Tải xuống'." };
            }

            console.log("✅ Bước 2: Đã thấy 'Tải xuống', đang bấm để mở menu con...");
            await simulateEnterClick(downloadBtn);

            await wait(400);
            const currentItems = Array.from(document.querySelectorAll('[role="menuitem"], button'));
            const fullHdBtn = currentItems.find(el => el.innerText.includes('1080p') && el.innerText.includes('Upscaled'));
            if (!fullHdBtn) {
                return { ok: false, reason: "Bấm 'Tải xuống' rồi nhưng không thấy mục '1080p Upscaled'." };
            }

            console.log("🎯 Bước 3: Đã tóm được '1080p Upscaled', chốt hạ...");
            await simulateEnterClick(fullHdBtn);

            return { ok: true, reason: "HOÀN TẤT QUY TRÌNH tải 1080p Upscaled." };
        }
        """

        # Cấu hình download cho 1080p: để Chrome tự tải, mình chỉ đổi tên & lưu map như 720p
        if want_1080p:
            try:
                await cdp.send(
                    "Browser.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": os.path.abspath(specific_output_dir),
                        "eventsEnabled": True,
                    },
                )
                print(f"[AI Video] Download path (1080p) = {specific_output_dir}")
            except Exception as e:
                print(f"[AI Video] WARN setDownloadBehavior failed: {e}")
                want_1080p = False  # fallback về 720p nếu cấu hình fail

        def _mark_scene_result(scene_id, result_type: str):
            if not scene_id:
                return
            scene_results[scene_id] = result_type
            scene_event = scene_events.get(scene_id)
            if scene_event and not scene_event.is_set():
                scene_event.set()

        def _extract_prompt_from_media_item(media_item: Dict[str, Any]) -> Optional[str]:
            try:
                media_meta = (media_item or {}).get("mediaMetadata", {}) or {}
                req_data = media_meta.get("requestData", {}) or {}
                prompt = (
                    req_data.get("promptInputs", [{}])[0]
                    .get("structuredPrompt", {})
                    .get("parts", [{}])[0]
                    .get("text")
                )
                return (prompt or "").strip() or None
            except Exception:
                return None

        def _infer_error_type_from_media_status(
            error_obj: Dict[str, Any],
            failure_reasons: List[Any],
        ) -> str:
            code = (error_obj or {}).get("code")
            status = str((error_obj or {}).get("status") or "").upper()
            message = str((error_obj or {}).get("message") or "").upper()
            reasons_upper = [str(x).upper() for x in (failure_reasons or [])]
            reason_blob = " ".join(reasons_upper)

            # Captcha/anti-bot
            if code == 403 or "CAPTCHA" in status or "CAPTCHA" in message or "CAPTCHA" in reason_blob:
                return "captcha_error"

            # Content policy / unsafe / invalid prompt
            if code in (3, 400) or status == "INVALID_ARGUMENT":
                return "content_error"
            if any(
                key in message or key in reason_blob
                for key in ["PROMINENT_PERSON", "UNSAFE", "SAFETY", "PUBLIC_ERROR_"]
            ):
                return "content_error"

            # Với lỗi linh tinh từ API mới, quy về captcha_error để luôn retry lại.
            return "captcha_error"

        async def trigger_stop_logic():
            if state["stop_triggered"]: return
            state["stop_triggered"] = True
            print(f"\n🛑 [STOP] Đã đủ {n_limit} lượt. Dọn dẹp...")
            # Copy list để tránh lỗi runtime khi modify set
            remaining = list(pending_scenes)
            for sid in remaining:
                await update_scene_status(script_path, sid, "content_error")
                if sid in pending_scenes: pending_scenes.remove(sid)
                _mark_scene_result(sid, "captcha_error")

        async def _download_scene_video(spath: str, media_id: Optional[str]) -> bool:
            """
            Tải video Veo3: CDP bắt URL video (redirect) rồi requests.get (cách mới, thay download_video_by_media_id).
            """
            if not media_id:
                return False
            redirect_url = VEO3_REDIRECT_URL.format(media_id=media_id)
            try:
                final_url = await _get_veo3_final_video_url_via_cdp(page, redirect_url)
                if not final_url:
                    print(f"[AI Video] ❌ Không bắt được URL video (media={media_id}).")
                    return False
                ok = await asyncio.to_thread(
                    _download_veo3_video_by_url,
                    final_url,
                    spath,
                    3,
                    60,
                )
                if not ok:
                    print(f"[AI Video] ❌ Tải theo URL thất bại (media={media_id}).")
                return ok
            except Exception as e:
                print(f"[AI Video] ❌ Lỗi tải video: {e}")
                return False

        async def on_request_will_be_sent(event):
            try:
                req = event.get("request", {})
                url = req.get("url", "")
                rid = event.get("requestId")

                if "video:" in url: 
                    post_data = req.get("postData")
                    if post_data:
                        try:
                            payload = json.loads(post_data)
                            raw_p = None
                            google_sid = None

                            # Format cũ
                            req_list = payload.get("requests", [])
                            if req_list:
                                item = req_list[0] or {}
                                raw_p = (item.get("textInput", {}) or {}).get("prompt")
                                google_sid = (item.get("metadata", {}) or {}).get("sceneId")

                            # Format mới
                            if not raw_p:
                                try:
                                    raw_p = (
                                        payload.get("promptInputs", [{}])[0]
                                        .get("structuredPrompt", {})
                                        .get("parts", [{}])[0]
                                        .get("text")
                                    )
                                except Exception:
                                    raw_p = None
                            if not google_sid:
                                google_sid = payload.get("sceneId") or payload.get("name")

                            if raw_p:
                                req_id_to_prompt_map[rid] = raw_p
                                if google_sid:
                                    google_id_to_prompt_map[google_sid] = raw_p
                        except: pass
            except: pass

        async def on_response_received(event):
            try:
                resp = event.get("response", {})
                url = resp.get("url", "")
                rid = event.get("requestId")
                if "video:" in url:
                    watched_request_ids.add(rid)
            except: pass

        async def on_loading_finished(event):
            rid = event.get("requestId")
            if rid not in watched_request_ids: return
            
            # 🔥 SỬA 1: Không remove ngay, để xử lý xong hãy remove
            # watched_request_ids.remove(rid) 
            
            # 🔥 SỬA 2: Dùng .get() thay vì .pop() để an toàn dữ liệu
            stored_prompt_from_req = req_id_to_prompt_map.get(rid)

            try:
                # Nếu lấy body thất bại, code sẽ nhảy xuống except, map vẫn còn nguyên
                body_data = await cdp.send("Network.getResponseBody", {"requestId": rid})
                content = body_data.get("body")

                # Giờ lấy được body rồi thì mới xóa ID khỏi danh sách theo dõi
                if rid in watched_request_ids: watched_request_ids.remove(rid)

                if not content: return

                # 🔥 Thêm random delay để tránh pattern detection
                await asyncio.sleep(random.uniform(0.1, 0.5))

                is_base64 = body_data.get("base64Encoded", False)
                raw_bytes = base64.b64decode(content) if is_base64 else content.encode("utf-8")
                text = raw_bytes.decode("utf-8", errors="ignore")
                if text.strip().startswith(")]}'"): text = text.split("\n", 1)[1]
                
                try:
                    data = json.loads(text)
                except json.JSONDecodeError: return

                # ==========================================================
                # 🛑 XỬ LÝ LỖI (API MỚI: media[].mediaMetadata.mediaStatus)
                # ==========================================================
                handled_new_media_error = False
                medias = data.get("media", []) or []
                for media_item in medias:
                    media_meta = (media_item or {}).get("mediaMetadata", {}) or {}
                    media_status = media_meta.get("mediaStatus", {}) or {}
                    gen_status = str(media_status.get("mediaGenerationStatus") or "").upper()
                    if gen_status != "MEDIA_GENERATION_STATUS_FAILED":
                        continue

                    err_obj = media_status.get("error", {}) or {}
                    failure_reasons = media_status.get("failureReasons", []) or []
                    error_type = _infer_error_type_from_media_status(err_obj, failure_reasons)
                    target_prompt = _extract_prompt_from_media_item(media_item) or stored_prompt_from_req

                    scene_to_update = None
                    if target_prompt:
                        cand = prompt_map.get(normalize_text(target_prompt))
                        # Chỉ nhận candidate nếu scene đó đang pending của worker này.
                        if cand and (cand in pending_scenes):
                            scene_to_update = cand
                    if not scene_to_update and pending_scenes:
                        scene_to_update = min(pending_scenes)

                    if scene_to_update:
                        print(
                            f"⚠️ [AI New API] Scene {scene_to_update} failed: "
                            f"status={gen_status}, code={err_obj.get('code')}, type={error_type}"
                        )
                        try:
                            await update_scene_status(script_path, scene_to_update, error_type)
                        except Exception as e:
                            print(f"   ❌ Loi khi luu status vao script: {e}")
                        pending_scenes.discard(scene_to_update)
                        _mark_scene_result(scene_to_update, error_type)
                        handled_new_media_error = True

                if handled_new_media_error:
                    if rid in req_id_to_prompt_map:
                        del req_id_to_prompt_map[rid]
                    return

                # ==========================================================
                # 🛑 XỬ LÝ LỖI (API CŨ: root_error / operations)
                # ==========================================================
                root_error = data.get("error", {})
                err_code = root_error.get("code")
                err_status = root_error.get("status")

                target_prompt = None 
                error_type = ""

                # --- CASE A: LỖI CODE 3 ---
                operations = data.get("operations", [])
                for item in operations:
                    op_error = item.get("operation", {}).get("error", {})
                    if op_error.get("code") == 3:
                        google_uuid = item.get("sceneId") 
                        if google_uuid and google_uuid in google_id_to_prompt_map:
                            target_prompt = google_id_to_prompt_map[google_uuid]
                            error_type = "content_error"
                            print(f"⚠️ Code 3 Detected (UUID: {google_uuid}) -> Map được Prompt.")
                        break
                
                # --- CASE B: LỖI 403/400 ---
                if not target_prompt:
                    is_403 = (err_code == 403)
                    is_400 = (err_code == 400 or err_status == "INVALID_ARGUMENT")
                    
                    if is_403 or is_400:
                        # API mới đôi khi không map được prompt theo requestId.
                        # Khi đó vẫn phải fallback sang scene pending để không bị treo chờ timeout.
                        target_prompt = stored_prompt_from_req or "__PENDING_FALLBACK__"
                        error_type = "captcha_error" if is_403 else "content_error"
                        print(f"⚠️ Root Error {err_code} Detected -> Map được Prompt.")

                # -> UPDATE TRẠNG THÁI LỖI
                if target_prompt:
                    state["tempt"] += 1
                    norm_p = normalize_text(target_prompt)
                    local_scene_id = prompt_map.get(norm_p)
                    
                    scene_to_update = None
                    
                    if local_scene_id and (local_scene_id in pending_scenes):
                        scene_to_update = local_scene_id
                        print(f"   -> Tim thay trong prompt_map: Scene {local_scene_id}")
                    elif pending_scenes:
                        # Fallback: Dùng scene đầu tiên đang pending
                        scene_to_update = min(pending_scenes)
                        print(f"   -> Khong tim thay trong prompt_map, dung Scene {scene_to_update} (dang pending)")
                    else:
                        # Fallback cuối: Thử tìm scene đầu tiên trong prompt_map (bất kỳ)
                        if prompt_map:
                            scene_to_update = list(prompt_map.values())[0]
                            print(f"   -> Fallback cuoi: Dung Scene {scene_to_update} (scene dau tien trong prompt_map)")
                        else:
                            print(f"   ⚠️ Khong co scene nao de danh dau loi! (prompt_map rong, pending_scenes rong)")
                    
                    # 🔥 QUAN TRỌNG: LUÔN LUÔN CỐ GẮNG LƯU (kể cả nếu không tìm thấy scene chính xác)
                    if scene_to_update:
                        print(f"   -> Danh dau loi '{error_type}' cho Scene {scene_to_update}")
                        try:
                            await update_scene_status(script_path, scene_to_update, error_type)
                            print(f"   ✅ Da luu '{error_type}' vao script cho Scene {scene_to_update}")
                        except Exception as e:
                            print(f"   ❌ Loi khi luu status vao script: {e}")
                            import traceback
                            traceback.print_exc()
                        
                        if scene_to_update in pending_scenes: 
                            pending_scenes.remove(scene_to_update)
                        # Phân biệt captcha_error vs lỗi khác để worker biết cách xử lý
                        _mark_scene_result(scene_to_update, error_type or "captcha_error")
                    else:
                        # Nếu vẫn không có scene nào, in cảnh báo
                        print(f"   ⚠️ KHONG THE LUU LOI '{error_type}' - Khong co scene nao de danh dau!")
                        print(f"   Debug: prompt_map={len(prompt_map)} entries, pending_scenes={len(pending_scenes)} scenes")
                    
                    if state["tempt"] >= n_limit: await trigger_stop_logic()
                    
                    # Xử lý xong thì dọn map
                    if rid in req_id_to_prompt_map: del req_id_to_prompt_map[rid]
                    return

                # ==========================================================
                # ✅ XỬ LÝ THÀNH CÔNG
                # ==========================================================
                if not state["stop_triggered"]:
                    videos = parse_google_video_response(text)

                    async def handle_1080p_for_scene(scene_id: int, spath: str, rpath: str, media_id: Optional[str] = None):
                        """
                        1080p: ấn Upscale, chờ Chrome tự tải, rồi đổi tên file về đúng fname/spath.
                        Nếu sau timeout vẫn chưa thấy file, fallback dùng base_url (720p) như cũ.
                        """
                        nonlocal want_1080p

                        if not want_1080p:
                            ok = await _download_scene_video(spath, media_id)
                            if ok:
                                await update_scene_status(script_path, scene_id, "done", rpath)
                                try:
                                    thumb_abs = await asyncio.to_thread(
                                        extract_first_frame_ffmpeg, spath
                                    )
                                    if thumb_abs:
                                        thumb_name = Path(thumb_abs).name
                                        thumb_rel = f"videos/{script_name}/{thumb_name}"
                                        await update_scene_status(
                                            script_path, scene_id, "done", thumb_rel
                                        )
                                except Exception as e:
                                    print(
                                        f"[AI Video] ⚠️ Không tạo được thumbnail cho scene {scene_id}: {e}"
                                    )
                                if scene_id in pending_scenes:
                                    pending_scenes.remove(scene_id)
                                _mark_scene_result(scene_id, "done")
                                state["tempt"] += 1
                                if state["tempt"] >= n_limit:
                                    await trigger_stop_logic()
                            return

                        # Reset trạng thái download
                        try:
                            download_event.clear()
                            download_state["filename"] = None
                            download_state["state"] = None
                        except Exception:
                            pass

                        # 1) Click Upscale 1080p trên UI
                        try:
                            try:
                                await page.bring_to_front()
                            except Exception:
                                pass
                            print(f"[AI Video] 🖱️ Đang thao tác menu 3 chấm -> Tải xuống -> 1080p Upscaled (Scene {scene_id})...")
                            js_result = await page.evaluate(CLICK_UPSCALE_1080P_JS)
                            if not (isinstance(js_result, dict) and js_result.get("ok")):
                                reason = (js_result or {}).get("reason") if isinstance(js_result, dict) else "Không rõ lý do."
                                raise Exception(reason)
                            print(f"[AI Video] ✅ Đã bấm 1080p Upscaled (Scene {scene_id}), chờ download event...")
                        except Exception as e:
                            print(f"[AI Video] WARN click Upscale 1080p failed: {e}")
                            ok = await _download_scene_video(spath, media_id)
                            if ok:
                                await update_scene_status(script_path, scene_id, "done", rpath)
                                if scene_id in pending_scenes:
                                    pending_scenes.remove(scene_id)
                                _mark_scene_result(scene_id, "done")
                                state["tempt"] += 1
                                if state["tempt"] >= n_limit:
                                    await trigger_stop_logic()
                            return

                        # 2) Chờ Chrome tải xong (Browser.downloadProgress -> completed)
                        try:
                            await asyncio.wait_for(download_event.wait(), timeout=180)
                        except asyncio.TimeoutError:
                            print(f"[AI Video] ⚠️ 1080p timeout cho Scene {scene_id}, chuyển tải theo media-id.")
                            ok = await _download_scene_video(spath, media_id)
                            if ok:
                                await update_scene_status(script_path, scene_id, "done", rpath)
                                if scene_id in pending_scenes:
                                    pending_scenes.remove(scene_id)
                                _mark_scene_result(scene_id, "done")
                                state["tempt"] += 1
                                if state["tempt"] >= n_limit:
                                    await trigger_stop_logic()
                            return

                        # 3) Đổi tên file Chrome vừa tải -> fname chuẩn (scene_id.mp4)
                        try:
                            src_path = None
                            suggested = download_state.get("filename")
                            if suggested:
                                candidate = os.path.join(specific_output_dir, suggested)
                                if os.path.exists(candidate):
                                    src_path = candidate

                            # Nếu không bắt được tên file, lấy file .mp4 mới nhất trong folder
                            if not src_path or not os.path.exists(src_path):
                                candidates = []
                                try:
                                    for name in os.listdir(specific_output_dir):
                                        if name.lower().endswith(".mp4"):
                                            full = os.path.join(specific_output_dir, name)
                                            candidates.append((os.path.getmtime(full), full))
                                except Exception:
                                    candidates = []
                                candidates.sort(reverse=True)
                                if candidates:
                                    src_path = candidates[0][1]

                            if not src_path or not os.path.exists(src_path):
                                print(f"[AI Video] ⚠️ Không tìm thấy file 1080p đã tải, chuyển tải theo media-id.")
                                ok = await _download_scene_video(spath, media_id)
                                if ok:
                                    await update_scene_status(script_path, scene_id, "done", rpath)
                                    if scene_id in pending_scenes:
                                        pending_scenes.remove(scene_id)
                                    _mark_scene_result(scene_id, "done")
                                    state["tempt"] += 1
                                    if state["tempt"] >= n_limit:
                                        await trigger_stop_logic()
                                return

                            # Đổi tên sang đúng fname/spath
                            if os.path.exists(spath):
                                os.remove(spath)
                            os.rename(src_path, spath)
                            print(f"[AI Video] ✅ 1080p downloaded and renamed -> {spath}")

                            await update_scene_status(script_path, scene_id, "done", rpath)
                            try:
                                thumb_abs = await asyncio.to_thread(
                                    extract_first_frame_ffmpeg, spath
                                )
                                if thumb_abs:
                                    thumb_name = Path(thumb_abs).name
                                    thumb_rel = f"videos/{script_name}/{thumb_name}"
                                    await update_scene_status(
                                        script_path, scene_id, "done", thumb_rel
                                    )
                            except Exception as e:
                                print(
                                    f"[AI Video] ⚠️ Không tạo được thumbnail 1080p cho scene {scene_id}: {e}"
                                )
                            if scene_id in pending_scenes:
                                pending_scenes.remove(scene_id)
                            _mark_scene_result(scene_id, "done")
                            state["tempt"] += 1
                            if state["tempt"] >= n_limit:
                                await trigger_stop_logic()
                        except Exception as e:
                            print(f"[AI Video] ⚠️ Lỗi xử lý 1080p cho Scene {scene_id}: {e}")
                            ok = await _download_scene_video(spath, media_id)
                            if ok:
                                await update_scene_status(script_path, scene_id, "done", rpath)
                                try:
                                    thumb_abs = await asyncio.to_thread(
                                        extract_first_frame_ffmpeg, spath
                                    )
                                    if thumb_abs:
                                        thumb_name = Path(thumb_abs).name
                                        thumb_rel = f"videos/{script_name}/{thumb_name}"
                                        await update_scene_status(
                                            script_path, scene_id, "done", thumb_rel
                                        )
                                except Exception as e:
                                    print(
                                        f"[AI Video] ⚠️ Không tạo được thumbnail fallback cho scene {scene_id}: {e}"
                                    )
                                if scene_id in pending_scenes:
                                    pending_scenes.remove(scene_id)
                                _mark_scene_result(scene_id, "done")
                                state["tempt"] += 1
                                if state["tempt"] >= n_limit:
                                    await trigger_stop_logic()

                    # Đảm bảo map đúng media -> scene, tránh tải nhầm video.
                    # Nguyên tắc AN TOÀN: 
                    # - Chỉ map khi tìm được scene_id từ prompt và scene đó vẫn còn pending.
                    # - KHÔNG còn bất kỳ fallback nào theo pending_scenes.
                    # - Mỗi media_id (name) chỉ được dùng đúng 1 lần.
                    new_videos = [v for v in videos if v.get("id") not in processed_media_ids]
                    for v in new_videos:
                        mid = v.get("id")
                        if not mid:
                            continue

                        prompt_text = (v.get("prompt") or "").strip()
                        sid = None
                        if prompt_text:
                            cand = prompt_map.get(normalize_text(prompt_text))
                            # Chỉ chấp nhận nếu scene đó hiện đang pending của worker này.
                            if cand in pending_scenes:
                                sid = cand

                        if sid is None:
                            # Không map được scene rõ ràng -> bỏ qua lượt poll này, đợi lần sau.
                            # Điều này an toàn hơn là đoán sai và tải nhầm video.
                            continue

                        status = (v.get("status") or "").upper()
                        vurl = v.get("url")

                        # Chỉ xử lý khi video đã SUCCESS.
                        if status and status != "MEDIA_GENERATION_STATUS_SUCCESSFUL":
                            continue

                        # API mới có thể chưa trả media-id; cần chờ thêm để tránh tải nhầm.
                        if status == "MEDIA_GENERATION_STATUS_SUCCESSFUL" and not mid:
                            key = str(sid)
                            if key not in success_no_url_logged:
                                print(f"[AI Video] ⏳ Scene {sid} đã SUCCESS nhưng chưa có media-id, chờ poll tiếp...")
                                success_no_url_logged.add(key)
                            continue

                        fname = f"{int(sid):03d}.mp4"
                        spath = os.path.join(specific_output_dir, fname)
                        rpath = f"videos/{script_name}/{fname}"

                        if want_1080p:
                            # 1080p: worker sẽ chỉ được "mở khoá" khi handle_1080p_for_scene
                            # gọi _mark_scene_result(scene_id, "done")
                            await handle_1080p_for_scene(sid, spath, rpath, media_id=mid)
                            processed_media_ids.add(mid)
                        else:
                            # 720p: tải theo media-id, xong mới mở khóa scene tiếp theo.
                            is_downloaded = await _download_scene_video(spath, mid)
                            if is_downloaded:
                                await update_scene_status(script_path, sid, "done", rpath)
                                try:
                                    thumb_abs = await asyncio.to_thread(
                                        extract_first_frame_ffmpeg, spath
                                    )
                                    if thumb_abs:
                                        thumb_name = Path(thumb_abs).name
                                        thumb_rel = f"videos/{script_name}/{thumb_name}"
                                        await update_scene_status(
                                            script_path, sid, "done", thumb_rel
                                        )
                                except Exception as e:
                                    print(
                                        f"[AI Video] ⚠️ Không tạo được thumbnail (720p) cho scene {sid}: {e}"
                                    )
                                if sid in pending_scenes:
                                    pending_scenes.remove(sid)
                                _mark_scene_result(sid, "done")
                                processed_media_ids.add(mid)
                                state["tempt"] += 1
                                if state["tempt"] >= n_limit:
                                    await trigger_stop_logic()
                
                # Xử lý xong thành công cũng dọn map cho nhẹ RAM
                if rid in req_id_to_prompt_map: del req_id_to_prompt_map[rid]

            except Exception as e: 
                # 🔥 SỬA 3: In lỗi ra để biết đường sửa nếu logic sai
                # Suppress lỗi CDP Protocol error (thường xảy ra khi request đã bị đóng)
                error_msg = str(e)
                if "Protocol error" not in error_msg and "No resource with given identifier" not in error_msg:
                    print(f"⚠️ Lỗi trong on_loading_finished: {e}")
                pass

        cdp.on("Network.requestWillBeSent", on_request_will_be_sent)
        cdp.on("Network.responseReceived", on_response_received)
        cdp.on("Network.loadingFinished", on_loading_finished)

        if want_1080p:
            async def on_download_will_begin(event):
                try:
                    download_state["guid"] = event.get("guid")
                    download_state["filename"] = event.get("suggestedFilename")
                    download_state["state"] = "started"
                    download_event.clear()
                    print(
                        f"[AI Video] [DL1080] started guid={download_state['guid']} "
                        f"file={download_state['filename']}"
                    )
                except Exception:
                    pass

            async def on_download_progress(event):
                try:
                    state_val = event.get("state")
                    download_state["guid"] = event.get("guid") or download_state.get("guid")
                    download_state["state"] = state_val
                    if state_val == "completed":
                        print("[AI Video] [DL1080] download completed event fired")
                        download_event.set()
                    elif state_val == "canceled":
                        print("[AI Video] [DL1080] download canceled")
                except Exception:
                    pass

            cdp.on("Browser.downloadWillBegin", on_download_will_begin)
            cdp.on("Browser.downloadProgress", on_download_progress)
        return cdp

    except Exception as e:
        print(f"❌ Lỗi setup listener video: {e}")
        return None
    
def execute_ai_video_generation(
    count: int,
    script_path: str,
    delay_seconds: float = 0.0,
    max_scenes: Optional[int] = None,
    start_scene: Optional[int] = None,
    end_scene: Optional[int] = None,
    ai_video_resolution: Optional[str] = None,
    ai_video_tool: Optional[str] = None,
    grok_video_duration: Optional[str] = None,
    grok_video_resolution: Optional[str] = None,
    ai_use_reference_image: bool = False,
    ai_character_voice_consistency: bool = False,
    ai_character_voice_name: Optional[str] = None,
    grok_use_reference_image: bool = False,
    mode: Optional[str] = None,
    ratio: Optional[str] = None,
    model: Optional[str] = None,
    use_auto_switch_profile: bool = False,
    batch_k: Optional[int] = None,
    max_scenes_per_profile: Optional[int] = None,
    batch_retry: Optional[int] = None,
) -> Dict[str, Any]:
    _STOP_SIGNAL.clear()
    # Resolve đường dẫn trước khi sử dụng
    abs_script_path = _resolve_script_path(script_path)
    if not abs_script_path or not os.path.exists(abs_script_path):
        return {"error": f"File không tồn tại: {script_path} (resolved: {abs_script_path})"}
    
    try:
        with open(abs_script_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            all_scenes = data.get("scenes", [])
            relative_img_path = data.get("master_image_url")
            cast_profiles = data.get("cast_profiles") or []
    except Exception as e:
        return {"error": f"Lỗi đọc file kịch bản: {e}"}

    # ===== NHÁNH GROK VIDEO (AI TAB) =====
    if str(ai_video_tool or "").strip().lower() == "grok":
        # Backward-compatible:
        # - Frontend cũ có thể gửi ai_use_reference_image.
        # - Frontend mới cho Grok nên gửi grok_use_reference_image.
        use_scene_reference_images = bool(grok_use_reference_image or ai_use_reference_image)
        max_scene_id_overall = 0
        for _s in all_scenes:
            try:
                max_scene_id_overall = max(max_scene_id_overall, int(_s.get("scene_id", 0)))
            except Exception:
                continue

        all_scenes = _filter_scenes_by_range(
            all_scenes,
            start_scene,
            end_scene,
            max_scenes
        )
        if not all_scenes:
            return {"error": "Thiếu dữ liệu Scenes"}

        tasks_grok = []
        scene_by_id: dict[int, dict] = {}
        for s in all_scenes:
            try:
                sid = int(s.get("scene_id", 0))
            except Exception:
                sid = 0
            if sid > 0:
                scene_by_id[sid] = s
            scene_status = str(s.get("status") or "").strip().lower()
            # Scene đã done thì bỏ qua hoàn toàn, không chạy lại prompt.
            if scene_status == "done":
                continue
            prompt = (s.get("image_prompt") or s.get("video_prompt") or "").strip()
            tasks_grok.append({
                "scene_id": sid,
                "prompt": prompt,
            })

        if not tasks_grok:
            return {"success": True, "count": 0, "message": "Không có scene cần chạy (tất cả đã done)."}

        nst = NSTBrowserManager()
        api_key_map = _build_profile_api_key_map()
        from services.browser_engine import profile_pool_for_run

        settings_grok = get_settings() or {}
        # Khi bật grok_use_reference_image: cho phép dùng nhiều profile giống Veo.
        # Ngược lại (fallback cũ): chỉ dùng 1 profile.
        if use_scene_reference_images:
            max_profiles = max(1, int(count or 1))
            profile_ids = profile_pool_for_run(max_profiles, settings_grok)
            if not profile_ids:
                return {"error": "Thiếu dữ liệu Profiles"}
        else:
            profile_ids = profile_pool_for_run(1, settings_grok)
            if not profile_ids:
                return {"error": "Thiếu dữ liệu Profiles"}

        async def _run_grok_chain_worker():
            script_dir = os.path.dirname(abs_script_path)
            mode_dir = os.path.dirname(script_dir)
            script_name = os.path.splitext(os.path.basename(abs_script_path))[0]
            specific_output_dir = os.path.join(mode_dir, "videos", script_name)
            os.makedirs(specific_output_dir, exist_ok=True)

            # Mark các scene có prompt trống là content_error ngay.
            valid_tasks: list[dict] = []
            for item in tasks_grok:
                if not item["prompt"]:
                    await update_scene_status(
                        abs_script_path, item["scene_id"], "content_error"
                    )
                else:
                    valid_tasks.append(item)

            if not valid_tasks:
                return

            def _resolve_scene_reference_image_abs(scene_obj: dict) -> Optional[str]:
                """
                Resolve absolute path cho ảnh tham chiếu theo scene.
                Ưu tiên key Grok chuyên biệt, fallback các key generic để tương thích ngược.
                """
                if not isinstance(scene_obj, dict):
                    return None
                for k in (
                    "grok_reference_image_url",
                    "grok_reference_image",
                    "reference_image_url",
                    "reference_image",
                ):
                    raw = str(scene_obj.get(k) or "").strip()
                    if not raw:
                        continue
                    p = Path(raw)
                    if p.is_absolute():
                        candidate = p
                    else:
                        candidate = Path(mode_dir) / raw
                    if candidate.exists():
                        return str(candidate.resolve())
                return None

            reference_image_by_scene: dict[int, str] = {}
            if use_scene_reference_images:
                missing_scene_ids: list[int] = []
                for item in valid_tasks:
                    sid = int(item["scene_id"])
                    ref_abs = _resolve_scene_reference_image_abs(scene_by_id.get(sid) or {})
                    if ref_abs:
                        reference_image_by_scene[sid] = ref_abs
                    else:
                        missing_scene_ids.append(sid)
                if missing_scene_ids:
                    missing_scene_ids = sorted(set(missing_scene_ids))
                    raise RuntimeError(
                        "Đang bật ảnh tham chiếu Grok nhưng thiếu ảnh cho scene: "
                        + ", ".join(str(x) for x in missing_scene_ids)
                        + ". Vui lòng upload ảnh tham chiếu cho từng scene trước khi chạy."
                    )

            settings = get_settings() or {}
            from services.browser_engine import is_chrome_local

            nst_api_key = str(
                settings.get("NST_API_KEY")
                or settings.get("API_KEY")
                or nst.api_key
                or ""
            ).strip()
            if not is_chrome_local(settings) and not nst_api_key:
                raise RuntimeError("Thiếu NST API key để kết nối CDP.")
            # Đảm bảo tất cả profiles Grok cần dùng đã được start + ready.
            await asyncio.to_thread(
                _ensure_profiles_started, nst, profile_ids, api_key_map
            )
            await _wait_for_profiles_ready(nst, profile_ids, api_key_map)

            from services.grok_imagine_nst import run_prompt_chain

            selected_resolution = str(
                grok_video_resolution or ai_video_resolution or "720p"
            ).lower()
            if selected_resolution not in ("480p", "720p"):
                selected_resolution = "720p"

            selected_duration = str(grok_video_duration or "10s").lower()
            if selected_duration not in ("6s", "10s"):
                selected_duration = "10s"

            selected_ratio = str(ratio or "16:9").strip() or "16:9"

            # Chia valid_tasks theo profile_id (round-robin)
            assignments: Dict[str, List[Dict[str, Any]]] = {}
            for idx, item in enumerate(valid_tasks):
                pid = profile_ids[idx % len(profile_ids)]
                assignments.setdefault(pid, []).append(item)

            async def _run_for_profile(pid: str, tasks_for_profile: List[Dict[str, Any]]):
                """Chạy Grok cho 1 profile với subset cảnh riêng."""
                if not tasks_for_profile:
                    return

                async def _on_grok_video_downloaded(round_idx: int, src_path: str):
                    """Callback cho profile cụ thể: map round_idx -> scene_id trong tasks_for_profile."""
                    idx0 = int(round_idx) - 1
                    if idx0 < 0 or idx0 >= len(tasks_for_profile):
                        return
                    scene_id = int(tasks_for_profile[idx0]["scene_id"])
                    src = os.path.normpath(src_path)
                    fname = f"{scene_id:03d}.mp4"
                    spath = os.path.normpath(os.path.join(specific_output_dir, fname))
                    rpath = f"videos/{script_name}/{fname}"

                    try:
                        if os.path.normcase(src) != os.path.normcase(spath):
                            if os.path.exists(spath):
                                os.remove(spath)
                            # Copy (không move) để giữ file gốc cho bước cắt frame ngay sau khi callback chạy.
                            shutil.copy2(src, spath)
                    except Exception as e:
                        print(f"[AI Grok] ⚠️ Không đổi tên/move được video scene {scene_id}: {e}")

                    await update_scene_status(abs_script_path, scene_id, "done", rpath)

                downloaded_videos = await run_prompt_chain(
                    profile_id=pid,
                    api_key=nst_api_key,
                    agent_url=nst.agent_url,
                    target_url="https://grok.com/imagine",
                    prompts=[t["prompt"] for t in tasks_for_profile],
                    output_dir=specific_output_dir,
                    duration=selected_duration,
                    resolution=selected_resolution,
                    ratios=(selected_ratio,),
                    scene_ids=[int(t["scene_id"]) for t in tasks_for_profile],
                    max_scene_id=max_scene_id_overall if max_scene_id_overall > 0 else None,
                    use_reference_image=use_scene_reference_images,
                    reference_image_by_scene=reference_image_by_scene,
                    on_video_downloaded=_on_grok_video_downloaded,
                )

                # Bất kỳ cảnh nào không có video (vd: captcha / lỗi) → set trạng thái captcha_error
                for idx, task in enumerate(tasks_for_profile):
                    scene_id = int(task["scene_id"])
                    if idx >= len(downloaded_videos):
                        await update_scene_status(
                            abs_script_path, scene_id, "captcha_error"
                        )

            # Chạy song song cho tất cả profiles được gán việc
            await asyncio.gather(
                *[
                    _run_for_profile(pid, tasks)
                    for pid, tasks in assignments.items()
                ]
            )

        def run_safe_grok():
            global _CURRENT_LOOP
            if os.name == 'nt':
                _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _CURRENT_LOOP = loop
            with _RUNNING_LOOPS_LOCK:
                _RUNNING_LOOPS.add(loop)

            async def _wrapper():
                print("[Thread AI Grok] 🔒 Lock file: is_running = True")
                await set_script_retry_state(abs_script_path, True)
                await set_script_running_state(abs_script_path, True)
                try:
                    await _run_grok_chain_worker()
                except Exception as e:
                    print(f"[Thread AI Grok Error] {e}")
                    await set_script_run_error(abs_script_path, str(e))
                finally:
                    await set_script_retry_state(abs_script_path, False)
                    print("[System AI Grok] 🏁 Thread đã đóng hoàn toàn. Unlock file.")
                    await set_script_running_state(abs_script_path, False)
                    print("[System AI Grok] 🧹 Đóng tất cả NST Profiles...")
                    stop_all_profiles()

            try:
                loop.run_until_complete(_wrapper())
            except Exception as e:
                print(f"[Run Loop AI Grok Error] {e}")
            finally:
                with _RUNNING_LOOPS_LOCK:
                    _RUNNING_LOOPS.discard(loop)
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()
                except Exception:
                    pass
                _CURRENT_LOOP = None

        t = threading.Thread(target=run_safe_grok, daemon=True)
        t.start()
        return {"success": True, "count": len(tasks_grok), "message": "Đang xử lý Video bằng Grok..."}

    nst = NSTBrowserManager()
    api_key_map = _build_profile_api_key_map()
    settings_snap = get_settings() or {}
    from services.browser_engine import profile_pool_for_run

    use_batch_mode = use_auto_switch_profile and (batch_k or 0) > 0
    if use_batch_mode:
        from services.nst_flow_auto_switch import get_auto_switch_profile_pool, compute_batch_assignments
        profile_pool = get_auto_switch_profile_pool(nst, get_settings)
        if not profile_pool:
            return {"error": "Thiếu danh sách profile (PROFILE_IDS_ACTIVE hoặc NST profiles)"}
        K = min(batch_k or 4, len(profile_pool))
        print(f"[AI Video] 🔄 Batch mode: N={len(profile_pool)} profiles, K={K} luồng, max_cảnh/profile={max_scenes_per_profile or 0}")
    elif use_auto_switch_profile:
        from services.nst_flow_auto_switch import get_auto_switch_profile_pool, get_active_ids_for_attempt
        profile_pool = get_auto_switch_profile_pool(nst, get_settings)
        active_ids = get_active_ids_for_attempt(profile_pool, count, set())
        print(f"[AI Video] 🔄 Auto-switch profile: pool={len(profile_pool)} profiles, active={[p[-4:] for p in active_ids]}")
    else:
        profile_pool = profile_pool_for_run(count, settings_snap)
        active_ids = profile_pool
    all_scenes = _filter_scenes_by_range(
        all_scenes,
        start_scene,
        end_scene,
        max_scenes
    )
    if not all_scenes:
        return {"error": "Thiếu dữ liệu Scenes"}
    if use_batch_mode:
        active_ids = profile_pool
    elif not active_ids:
        return {"error": "Thiếu dữ liệu Profiles"}

    # UI mới: AI tab luôn chạy mode video.
    master_image_path = None
    if ai_use_reference_image and relative_img_path:
        script_dir = os.path.dirname(abs_script_path)
        mode_dir = os.path.dirname(script_dir)
        full_path = os.path.join(mode_dir, relative_img_path)
        if os.path.exists(full_path):
            master_image_path = full_path
            print(f"[AI Video] ✅ Tìm thấy Master Image: {master_image_path} (mode: video)")
        else:
            print(f"[AI Video] ⚠️ Master Image không tồn tại: {full_path}")

    flow_mode = "video"
    print(f"[AI Video] 📌 Mode: {flow_mode} (ai_use_reference_image={ai_use_reference_image}, master_image_path={'set' if master_image_path else 'None'})")

    async def _worker(pid, tasks, attempt=0, upload_master_first_scene: bool = False) -> Tuple[bool, List[Dict[str, Any]]]:
        """Trả về (completed, remaining_tasks). upload_master_first_scene=True khi vừa setup xong (mỗi batch) → cảnh đầu upload ảnh master."""
        completed = False
        remaining_tasks_early: List[Dict[str, Any]] = []
        if not tasks:
            return (completed, [])
        if _STOP_SIGNAL.is_set():
            return (completed, [])
        ws = _ws_endpoint_for_profile(nst, pid, api_key_map, settings=settings_snap)
        if not ws:
            print(f"[AI Video] ⚠️ Profile {pid[-4:]} không còn kết nối hoặc chưa sẵn sàng. Bỏ qua, vòng retry sẽ bật lại.")
            return (completed, list(tasks))

        page = await connect_and_get_page(ws)
        if not page:
            print(f"[AI Video] ⚠️ Không kết nối được profile {pid[-4:]}. Bỏ qua, vòng retry sẽ bật lại.")
            return (completed, list(tasks))
        await _maybe_move_window(page)

        # Nếu vừa setup sẵn từ /api/nst/run thì tái sử dụng session, tránh goto/setup lần 2.
        try:
            if await is_flow_setup_ready(page):
                print(f"[AI Video] ♻️ Profile {pid[-4:]}: dùng lại session setup sẵn, bỏ qua goto/setup.")
                await inject_keep_alive(page)
            else:
                print(f"[AI Video] 🚀 Profile {pid[-4:]}: goto Flow, setup, rồi chạy {len(tasks)} cảnh...")
                await goto_flow_and_open_project(page, FLOW_URL, stop_check=lambda: _STOP_SIGNAL.is_set())
                await inject_keep_alive(page)
                ok = await select_mode(page, flow_mode, stop_check=lambda: _STOP_SIGNAL.is_set())
                if not ok:
                    print(f"[AI Video] ❌ Profile {pid[-4:]}: Không chọn được mode {flow_mode}. Tắt NST, bật lại và chọn đúng mode rồi thử lại.")
                    return (completed, list(tasks))
                await setup_render_settings(
                    page,
                    output_count=1,
                    aspect_ratio=_flow_setup_aspect_ratio(ratio, flow_mode),
                    model=model,
                    select_ingredients=(flow_mode == "video"),
                )
        except FlowStoppedError:
            return (completed, list(tasks))
        except Exception as e:
            print(f"[AI Video] ❌ Setup profile {pid[-4:]}: {e}")
            return (completed, list(tasks))

        print(f"[AI Video] ✅ Profile {pid[-4:]} setup xong, bắt đầu xử lý cảnh...")

        consecutive_restart_errors = 0  # Reset khi cảnh không lỗi restart-worthy.

        prompt_map = {}
        pending_scenes = set()
        scene_events: Dict[int, asyncio.Event] = {}
        scene_results: Dict[int, str] = {}
        # Dùng abs_script_path đã resolve
        project_dir = os.path.dirname(os.path.dirname(abs_script_path)) 
        video_output_dir = os.path.join(project_dir, "videos")
        
        n_limit = len(tasks)

        video_listener = await setup_video_result_listener_logic_moi(
            page,
            prompt_map,
            video_output_dir,
            abs_script_path,
            pending_scenes,
            scene_events,
            scene_results,
            n_limit,
            ai_video_resolution=ai_video_resolution,
        )
        
        crop_success_event = asyncio.Event()
        cdp_crop = None
        try:
            cdp_crop = await page.context.new_cdp_session(page)
            await cdp_crop.send("Network.enable")
            cdp_crop.on("Network.requestWillBeSent", lambda e: crop_success_event.set() if "submitBatchLog" in e.get("request",{}).get("url","") and "PINHOLE_CROP_IMAGE" in e.get("request",{}).get("postData","") else None)

            # 🔥 Random delay trước khi bắt đầu upload/gửi prompt để tránh nhiều luồng gửi cùng lúc
            # 🔥 MỨC AN TOÀN CAO: delay lớn trước vòng cảnh đầu tiên của mỗi profile (3–10s)
            await random_delay_before_action(min_seconds=1, max_seconds=3)

            i = 0
            first_scene_retry_done = False  # Cảnh đầu lỗi sau khi gửi prompt -> retry lại CHÍNH cảnh đầu 1 lần
            retry_same_scene = False
            while i < len(tasks):
                item = tasks[i]
                if _STOP_SIGNAL.is_set():
                    print(f"[AI Video] 🛑 Dừng luồng {pid}...")
                    remaining_tasks_early = list(tasks[i:])
                    break
                scene_id = item['scene_id']
                norm_p = normalize_text(item['prompt'])
                prompt_map[norm_p] = scene_id
                
                # UI mới AI tab luôn mode video.
                # - Khi có ảnh tham chiếu (ai_use_reference_image=True): scene đầu upload, scene sau Add Next Scene.
                # - Khi KHÔNG dùng ảnh tham chiếu: KHÔNG dùng Add Next, chỉ gửi prompt trực tiếp từng scene.
                if flow_mode == "video" and ai_use_reference_image:
                    if master_image_path:
                        should_upload_reference = (
                            (i == 0 and (upload_master_first_scene or attempt == 0))
                        )
                        if should_upload_reference:
                            print(f"[AI Video] 📤 Upload Master Image (Scene {scene_id}) - Driver {pid[-4:]}...")
                            try:
                                upload_ok = await upload_master_image_playwright(
                                    page,
                                    master_image_path,
                                    wait_for_api_log=True,
                                    consistent_voice_enabled=bool(ai_character_voice_consistency and ai_use_reference_image),
                                    consistent_voice_name=ai_character_voice_name,
                                )
                            except UploadPolicyViolationError as e:
                                policy_msg = str(e) or "Ảnh tham chiếu vi phạm chính sách Google. Vui lòng đổi ảnh khác."
                                print(f"[AI Video] ⛔ {policy_msg}")
                                await set_script_run_error(abs_script_path, policy_msg)
                                stop_all_tasks()
                                remaining_tasks_early = list(tasks[i:])
                                break
                            if not upload_ok:
                                print(f"[AI Video] ❌ Upload ảnh tham chiếu thất bại (Scene {scene_id}) - Driver {pid[-4:]}.")
                                await update_scene_status(abs_script_path, scene_id, "captcha_error")
                                remaining_tasks_early = list(tasks[i + 1:])
                                i += 1
                                continue
                            # Upload mới đã tự đợi API log upload; không chờ crop event nữa để tránh treo.
                            if _STOP_SIGNAL.is_set():
                                remaining_tasks_early = list(tasks[i:])
                                break
                            print(f"[AI Video] ⏳ Đợi 3s cho Web ổn định...")
                            await asyncio.sleep(2)
                        elif i == 0:
                            # Cùng browser đang chạy tiếp (retry/batch tiếp) → Add Next Scene, không upload lại
                            print(f"[AI Video] 🔄 Cùng browser tiếp (upload_first={upload_master_first_scene}, attempt={attempt}) → Add Next Scene (Scene {scene_id}) - Driver {pid[-4:]}...")
                            await click_add_next_scene_playwright(
                                page,
                                consistent_voice_enabled=bool(ai_character_voice_consistency and ai_use_reference_image),
                            )
                            await asyncio.sleep(2)
                        elif i > 0 and not retry_same_scene:
                            await click_add_next_scene_playwright(
                                page,
                                consistent_voice_enabled=bool(ai_character_voice_consistency and ai_use_reference_image),
                            )
                            await asyncio.sleep(2)
                    # Nếu ai_use_reference_image=True mà không có master_image_path thì cũng không Add Next.

                scene_event = asyncio.Event()
                scene_events[scene_id] = scene_event
                scene_results.pop(scene_id, None)

                # 🔥 Nghỉ 3–5s giữa các cảnh trước khi nhập prompt mới (giảm pattern bot)
                if i > 0:
                    await random_delay_before_action(min_seconds=3.0, max_seconds=5.0)

                # Chỉ chạy tới đây khi upload ảnh tham chiếu (nếu có) đã OK và đã thấy API upload.
                print(f"[AI Video] ✍️ Gửi prompt Scene {scene_id}...")
                await send_prompt_text(page, item['prompt'])

                await update_scene_status(abs_script_path, scene_id, "processing")
                pending_scenes.add(scene_id)
                
                print(f"[AI Video] ⏳ Đợi phản hồi (URL/Lỗi) cho Scene {scene_id}... (timeout {AI_SCENE_WAIT_TIMEOUT_SEC}s)")
                mouse_stop = asyncio.Event()
                mouse_task = asyncio.create_task(run_human_like_mouse_until(page, mouse_stop))
                loop_wait = asyncio.get_running_loop()
                scene_wait_start = loop_wait.time()
                try:
                    while not scene_event.is_set():
                        if _STOP_SIGNAL.is_set():
                            print(f"[AI Video] 🛑 Dừng chờ Scene {scene_id} do lệnh Stop.")
                            break
                        if page.is_closed():
                            print(f"[AI Video] ❌ Browser bị đóng khi chờ Scene {scene_id}.")
                            break
                        if loop_wait.time() - scene_wait_start > AI_SCENE_WAIT_TIMEOUT_SEC:
                            print(f"[AI Video] ⚠️ Scene {scene_id} timeout ({AI_SCENE_WAIT_TIMEOUT_SEC}s). Đánh dấu lỗi và chuyển cảnh kế.")
                            await update_scene_status(abs_script_path, scene_id, "captcha_error")
                            pending_scenes.discard(scene_id)
                            prompt_map.pop(norm_p, None)
                            scene_results[scene_id] = "captcha_error"
                            scene_event.set()
                            break
                        await asyncio.sleep(random.uniform(0.4, 0.6))
                finally:
                    mouse_stop.set()
                    try:
                        await asyncio.wait_for(mouse_task, 1.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        mouse_task.cancel()
                        try:
                            await mouse_task
                        except asyncio.CancelledError:
                            pass
                
                if _STOP_SIGNAL.is_set() or page.is_closed():
                    remaining_tasks_early = list(tasks[i + 1:])
                    break

                # 🔥 Phân biệt lỗi captcha_error vs lỗi khác
                result_type = scene_results.get(scene_id)

                # Cảnh đầu lỗi sau khi đã gửi prompt: đợi 4-5s rồi upload lại + gửi lại CHÍNH cảnh đầu.
                if (
                    result_type == "captcha_error"
                    and i == 0
                    and flow_mode == "video"
                    and bool(master_image_path)
                    and not first_scene_retry_done
                ):
                    first_scene_retry_done = True
                    settle_s = random.uniform(4.0, 5.0)
                    print(f"[AI Video] 🔁 Scene đầu lỗi captcha -> đợi {settle_s:.1f}s rồi retry lại Scene {scene_id}...")
                    pending_scenes.discard(scene_id)
                    scene_events.pop(scene_id, None)
                    scene_results.pop(scene_id, None)
                    prompt_map.pop(norm_p, None)
                    await asyncio.sleep(settle_s)
                    continue

                if result_type == "captcha_error":
                    consecutive_restart_errors += 1
                else:
                    consecutive_restart_errors = 0
                # Nếu đã tạo cảnh thành công thì reset chuỗi restart liên tiếp của profile.
                if result_type == "done":
                    profile_restart_attempts[pid] = 0

                if result_type == "captcha_error" and consecutive_restart_errors >= 2:
                    restart_used = int(profile_restart_attempts.get(pid, 0))
                    if restart_used >= MAX_PROFILE_RESTARTS_PER_RUN:
                        print(
                            f"[AI Video] ⛔ Profile {pid[-4:]} đã restart đủ {MAX_PROFILE_RESTARTS_PER_RUN} lần. "
                            f"Tắt hẳn profile khỏi phiên chạy hiện tại."
                        )
                        permanently_disabled_profiles.add(pid)
                        try:
                            if cdp_crop:
                                await cdp_crop.detach()
                                cdp_crop = None
                            if video_listener:
                                await video_listener.detach()
                                video_listener = None
                        except Exception:
                            pass
                        await _cleanup_connected_session(ws, settings_snap)
                        _stop_profiles_by_key(nst, [pid], api_key_map)
                        remaining_tasks_early = list(tasks[i:])
                        break

                    profile_restart_attempts[pid] = restart_used + 1
                    try:
                        if cdp_crop:
                            await cdp_crop.detach()
                            cdp_crop = None
                        if video_listener:
                            await video_listener.detach()
                            video_listener = None
                    except Exception:
                        pass
                    await _cleanup_connected_session(ws, settings_snap)
                    _stop_profiles_by_key(nst, [pid], api_key_map)
                    await asyncio.sleep(4)
                    print(
                        f"[AI Video] 🧱 Lỗi liên tiếp {consecutive_restart_errors} lần "
                        f"(type={result_type}) - restart profile {pid[-4:]} "
                        f"({profile_restart_attempts[pid]}/{MAX_PROFILE_RESTARTS_PER_RUN})..."
                    )
                    if _STOP_SIGNAL.is_set():
                        print(f"[AI Video] 🛑 Nhận STOP khi chuẩn bị restart profile {pid[-4:]} – bỏ qua restart.")
                        remaining_tasks_early = list(tasks[i:])
                        break
                    _ensure_profiles_started(nst, [pid], api_key_map)
                    if _STOP_SIGNAL.is_set():
                        print(f"[AI Video] 🛑 STOP sau ensure_profiles_started, không chờ profile ready nữa.")
                        remaining_tasks_early = list(tasks[i:])
                        break
                    await _wait_for_profiles_ready(nst, [pid], api_key_map)
                    ws = _ws_endpoint_for_profile(nst, pid, api_key_map, settings=settings_snap)
                    if not ws:
                        print(f"[AI Video] ❌ Không tìm thấy profile {pid[-4:]} sau khi bật lại.")
                        remaining_tasks_early = list(tasks[i:])
                        break
                    page = await connect_and_get_page(ws)
                    if not page:
                        print(f"[AI Video] ❌ Không kết nối được page profile {pid[-4:]}")
                        remaining_tasks_early = list(tasks[i:])
                        break
                    await _maybe_move_window(page)
                    print(f"[AI Video] 🔄 Profile {pid[-4:]}: setup lại Flow sau lỗi liên tiếp...")
                    try:
                        await goto_flow_and_open_project(page, FLOW_URL, stop_check=lambda: _STOP_SIGNAL.is_set())
                        await inject_keep_alive(page)
                        ok = await select_mode(page, flow_mode, stop_check=lambda: _STOP_SIGNAL.is_set())
                        if not ok:
                            print(f"[AI Video] ❌ Profile {pid[-4:]}: Không chọn được mode sau restart.")
                            break
                        await setup_render_settings(
                            page,
                            output_count=1,
                            aspect_ratio=_flow_setup_aspect_ratio(ratio, flow_mode),
                            model=model,
                            select_ingredients=(flow_mode == "video"),
                        )
                    except Exception as e:
                        print(f"[AI Video] ⚠️ Setup Flow sau restart: {e}")
                    prompt_map.clear()
                    pending_scenes.clear()
                    scene_events.clear()
                    scene_results.clear()
                    for t in tasks[i:]:
                        prompt_map[normalize_text(t["prompt"])] = t["scene_id"]
                    video_listener = await setup_video_result_listener_logic_moi(
                        page, prompt_map, video_output_dir, abs_script_path,
                        pending_scenes, scene_events, scene_results, n_limit,
                        ai_video_resolution=ai_video_resolution,
                    )
                    cdp_crop = await page.context.new_cdp_session(page)
                    await cdp_crop.send("Network.enable")
                    cdp_crop.on("Network.requestWillBeSent", lambda e: crop_success_event.set() if "submitBatchLog" in e.get("request",{}).get("url","") and "PINHOLE_CROP_IMAGE" in e.get("request",{}).get("postData","") else None)
                    tasks = list(tasks[i:])
                    i = 0
                    n_limit = len(tasks)
                    upload_master_first_scene = True
                    consecutive_restart_errors = 0
                    await random_delay_before_action(min_seconds=3.0, max_seconds=10.0)
                    continue

                # Quy tắc mới: captcha_error thì giữ nguyên cảnh hiện tại để gửi lại.
                # content_error thì đi cảnh tiếp theo (xử lý ở đoạn i += 1 bên dưới).
                if result_type == "captcha_error":
                    settle_s = random.uniform(4.0, 5.0)
                    print(f"[AI Video] 🔁 Captcha ở Scene {scene_id} -> đợi {settle_s:.1f}s rồi gửi lại CHÍNH cảnh này.")
                    retry_same_scene = True
                    pending_scenes.discard(scene_id)
                    scene_events.pop(scene_id, None)
                    scene_results.pop(scene_id, None)
                    prompt_map.pop(norm_p, None)
                    await asyncio.sleep(settle_s)
                    continue

                # content_error / error: đã ghi lỗi vào script, gửi prompt mới (không cooldown, không dừng)

                scene_events.pop(scene_id, None)
                scene_results.pop(scene_id, None)
                retry_same_scene = False
                i += 1

            if remaining_tasks_early:
                print(f"[AI Video] 🛑 Đã dừng sớm. Còn {len(pending_scenes)} video đang chờ, {len(remaining_tasks_early)} cảnh chưa gửi.")
            else:
                print(f"[AI Video] 🏁 Driver {pid[-4:]} đã gửi hết lệnh. ĐANG CHỜ KẾT QUẢ...")

            if not remaining_tasks_early:
                MAX_WAIT_TIME = 180
                loop = asyncio.get_running_loop()
                wait_start = loop.time()
                while pending_scenes:
                    if _STOP_SIGNAL.is_set():
                        break
                    if loop.time() - wait_start > MAX_WAIT_TIME:
                        print(f"[AI Video] ⚠️ Hết thời gian chờ.")
                        break
                    if page.is_closed():
                        print(f"[AI Video] ❌ Browser bị đóng đột ngột.")
                        break
                    await asyncio.sleep(5.0)
            print(f"[AI Video] ✅ Driver {pid[-4:]} KẾT THÚC.")
            completed = (
                len(pending_scenes) == 0
                and not remaining_tasks_early
                and not _STOP_SIGNAL.is_set()
                and not page.is_closed()
            )

        
        except asyncio.CancelledError:
            # Không để 1 worker bị cancel làm sập cả vòng chạy AI.
            if _STOP_SIGNAL.is_set():
                print(f"[AI Video] ⚠️ Worker {pid} bị cancel do lệnh Stop.")
            else:
                print(f"[AI Video] ⚠️ Worker {pid} bị cancel ngoài ý muốn, giữ task để retry.")
        except Exception as e:
            if _STOP_SIGNAL.is_set():
                print(f"[AI Video] ⚠️ Worker {pid} dừng đột ngột (Do lệnh Stop).")
            else:
                print(f"[AI Video] ❌ Lỗi worker: {e}")
        finally:
            try:
                if cdp_crop: await cdp_crop.detach()
                if video_listener: await video_listener.detach()
                if len(pending_scenes) == 0:
                    print(f"[AI Video] ✅ Đã hoàn thành task lượt này. (GIỮ BROWSER ĐỂ RETRY).")
                    # await page.close()
                else:
                    # Nếu còn cảnh đang treo (lỗi/timeout) -> Giữ lại để Vòng 2 chạy tiếp (hoặc để debug)
                    print(f"[AI Video] ⚠️ Vẫn còn {len(pending_scenes)} cảnh chưa có kết quả. GIỮ browser {pid[-4:]} lại.")
            except: pass
        return (completed, remaining_tasks_early)

    failed_profiles_this_run: set = set()
    profile_restart_attempts: Dict[str, int] = {}
    permanently_disabled_profiles: set = set()

    async def _runner_with_retry():
        nonlocal active_ids
        reset_flow_delay_counter()
        MAX_RETRIES = 2
        for attempt in range(MAX_RETRIES):
            if _STOP_SIGNAL.is_set():
                print("[AI Video] 🛑 Dừng retry do tín hiệu Stop.")
                break
            print(f"\n🎥 --- AI VIDEO VÒNG {attempt + 1}/{MAX_RETRIES} ---\n")
            # 🔄 Auto-switch: mỗi lượt dùng profile chưa lỗi từ pool
            if use_auto_switch_profile:
                alive_pool = [p for p in profile_pool if p not in permanently_disabled_profiles]
                active_ids = get_active_ids_for_attempt(alive_pool, count, failed_profiles_this_run)
                if not active_ids:
                    print("[AI Video] ⚠️ Auto-switch: không còn profile nào. Dừng.")
                    break
                print(f"[AI Video] 🔄 Auto-switch: lượt này dùng {[p[-4:] for p in active_ids]} (đã loại {[p[-4:] for p in failed_profiles_this_run]})")
            else:
                active_ids = [p for p in active_ids if p not in permanently_disabled_profiles]
                if not active_ids:
                    print("[AI Video] ⚠️ Không còn profile sống sau khi loại profile lỗi nặng. Dừng.")
                    break
            # Nếu vừa nhận STOP trong lúc tính pool/active_ids thì tuyệt đối không start/reconnect lại NST.
            if _STOP_SIGNAL.is_set():
                print("[AI Video] 🛑 Đã nhận Stop trước khi start profiles (bỏ qua retry vòng này).")
                break
            _ensure_profiles_started(nst, active_ids, api_key_map)
            # Chặn thêm lần nữa vì STOP có thể đến ngay sau khi start_profiles được gọi.
            if _STOP_SIGNAL.is_set():
                print("[AI Video] 🛑 Đã nhận Stop ngay sau khi start profiles (không chờ ready nữa).")
                break
            await _wait_for_profiles_ready(nst, active_ids, api_key_map)
            if _STOP_SIGNAL.is_set():
                print("[AI Video] 🛑 Đã nhận Stop sau khi chờ profiles ready, kết thúc ngay.")
                break

            try:
                with file_write_lock:
                    if os.path.exists(abs_script_path):
                        with open(abs_script_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            scenes = data.get("scenes", [])
                    else:
                        scenes = []
            except Exception as e:
                print(f"❌ Lỗi đọc file: {e}")
                scenes = []

            scenes_to_retry = _filter_scenes_by_range(
                scenes,
                start_scene,
                end_scene,
                max_scenes
            )
            tasks_retry = []
            for s in scenes_to_retry:
                st = (s.get("status") or "").strip()
                # content_error không retry (lỗi nội dung cấm, sửa prompt rồi chạy tay)
                if st not in ("done", "content_error"):
                    tasks_retry.append({
                        "scene_id": s["scene_id"],
                        "prompt": s.get("image_prompt") or s.get("video_prompt") or ""
                    })

            if not tasks_retry:
                print("✅ Tất cả video đã xong (hoặc chỉ còn content_error). STOP.")
                break

            new_assignments = {pid: [] for pid in active_ids}
            for i, task in enumerate(tasks_retry):
                pid = active_ids[i % len(active_ids)]
                new_assignments[pid].append(task)
            ordered_pids = list(new_assignments.keys())
            # Luôn setup xong → upload master ở cảnh đầu cho tất cả
            results = await asyncio.gather(*[
                _worker(pid, tasks, attempt, upload_master_first_scene=True)
                for pid, tasks in new_assignments.items()
            ], return_exceptions=True)
            if use_auto_switch_profile:
                for idx, res in enumerate(results):
                    if idx >= len(ordered_pids):
                        continue
                    if isinstance(res, Exception):
                        failed_profiles_this_run.add(ordered_pids[idx])
                        continue
                    completed, rem = res
                    if rem:
                        failed_profiles_this_run.add(ordered_pids[idx])
            if _STOP_SIGNAL.is_set():
                print("[AI Video] 🛑 Đã nhận Stop sau vòng chạy, kết thúc ngay.")
                break
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(10)

    def _read_remaining_tasks_ai():
        """Đọc file, trả về list task (cảnh chưa done/content_error) theo start_scene/end_scene/max_scenes."""
        try:
            with file_write_lock:
                if os.path.exists(abs_script_path):
                    with open(abs_script_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        scenes = data.get("scenes", [])
                else:
                    scenes = []
        except Exception as e:
            print(f"❌ Lỗi đọc file: {e}")
            return []
        scenes_to_retry = _filter_scenes_by_range(scenes, start_scene, end_scene, max_scenes)
        tasks_retry = []
        for s in scenes_to_retry:
            st = (s.get("status") or "").strip()
            if st not in ("done", "content_error"):
                tasks_retry.append({
                    "scene_id": s["scene_id"],
                    "prompt": s.get("image_prompt") or s.get("video_prompt") or ""
                })
        return tasks_retry

    async def _runner_batch():
        """Xoay tự động: giống chạy bình thường (setup, captcha đóng/mở lại). Mỗi batch đợi đủ K profile xong (hoặc bị đóng captcha 2 lần) rồi đóng hết, mở batch tiếp. Sau mỗi batch đọc lại file, chia cảnh còn lại cho batch tiếp. Retry=2 → chạy xong 1-4,5-8 rồi quay lại 1-4,5-8 với cảnh còn lỗi. Không dùng vòng retry của chạy bình thường."""
        reset_flow_delay_counter()
        retry_count = max(1, min(10, batch_retry or 1))
        N = len(profile_pool)
        for retry_round in range(retry_count):
            if _STOP_SIGNAL.is_set():
                print("[AI Video] 🛑 Dừng theo lệnh Stop.")
                break
            alive_pool = [p for p in profile_pool if p not in permanently_disabled_profiles]
            if not alive_pool:
                print("[AI Video] ⛔ Không còn profile sống. Dừng batch retry.")
                break
            remaining = _read_remaining_tasks_ai()
            if not remaining:
                print(f"[AI Video] ✅ Vòng {retry_round + 1}: Tất cả đã hoàn thành. Dừng retry.")
                break
            print(f"\n🔄 --- AI VIDEO RETRY VÒNG {retry_round + 1}/{retry_count} ({len(remaining)} cảnh chưa xong) ---\n")
            batch_start = 0
            N = len(alive_pool)
            while batch_start < N:
                if _STOP_SIGNAL.is_set():
                    break
                remaining = _read_remaining_tasks_ai()
                if not remaining:
                    break
                pids_in_batch = alive_pool[batch_start : batch_start + K]
                batches_this = compute_batch_assignments(
                    pids_in_batch, len(pids_in_batch), remaining,
                    max_per_profile=max_scenes_per_profile or 0,
                )
                if not batches_this or not any(t for _, t in batches_this[0]):
                    batch_start += K
                    continue
                batch = batches_this[0]
                pids_in_batch = [pid for pid, _ in batch]
                print(f"\n📦 --- BATCH {batch_start // K + 1} (profiles {[p[-4:] for p in pids_in_batch]}, {sum(len(t) for _, t in batch)} cảnh) ---\n")
                # STOP đến trong lúc batch đang xoay thì không được start/reconnect profiles nữa.
                if _STOP_SIGNAL.is_set():
                    break
                _ensure_profiles_started(nst, pids_in_batch, api_key_map)
                if _STOP_SIGNAL.is_set():
                    break
                await _wait_for_profiles_ready(nst, pids_in_batch, api_key_map)
                if _STOP_SIGNAL.is_set():
                    break
                await asyncio.gather(*[
                    _worker(pid, tasks, 0, upload_master_first_scene=True)
                    for pid, tasks in batch
                ], return_exceptions=True)
                _stop_profiles_by_key(nst, pids_in_batch, api_key_map)
                batch_start += K
                if batch_start < N:
                    await asyncio.sleep(3)
            if retry_round < retry_count - 1:
                await asyncio.sleep(5)

    def run_safe():
        global _CURRENT_LOOP 
        
        # 1. Setup Event Loop cho Windows (Giữ nguyên)
        if os.name == 'nt':
            _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _CURRENT_LOOP = loop
        with _RUNNING_LOOPS_LOCK:
            _RUNNING_LOOPS.add(loop)
        
        # 2. TẠO WRAPPER ASYNC (Để dùng được await)
        async def _wrapper():
            print(f"[Thread AI] 🔒 Lock file: is_running = True")
            await set_script_retry_state(abs_script_path, True)
            await set_script_running_state(abs_script_path, True)
            
            try:
                if use_batch_mode:
                    await _runner_batch()
                else:
                    await _runner_with_retry()
                
            except asyncio.CancelledError:
                print("[Thread AI] 🛑 Đã dừng theo lệnh Stop.")
            except Exception as e:
                print(f"[Thread AI Error] {e}")
            finally:
                await set_script_retry_state(abs_script_path, False)
                # 🔥 Tắt trạng thái Running (Có await + Lock)
                # Đoạn này đảm bảo dù lỗi hay không cũng trả về False
                print("[System AI] 🏁 Thread đã đóng hoàn toàn. Unlock file.")
                await set_script_running_state(abs_script_path, False)
                
                # Đóng dọn dẹp profile cho sạch RAM
                print("[System AI] 🧹 Đóng tất cả NST Profiles...")
                stop_all_profiles()

        # 3. CHẠY WRAPPER TRONG LOOP
        try:
            loop.run_until_complete(_wrapper())
        except Exception as e:
            print(f"[Run Loop Error] {e}")
        finally:
            with _RUNNING_LOOPS_LOCK:
                _RUNNING_LOOPS.discard(loop)
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except: pass
            _CURRENT_LOOP = None

    t = threading.Thread(target=run_safe, daemon=True)
    t.start()
    return {"success": True, "count": len(all_scenes), "message": "Đang xử lý Video..."}
    
def generate_master_reference_image(
    script_path: str,
    ratio: str,
    # 🔥 Mặc định dùng model chuẩn mới từ UI.
    model: str = "🍌 Nano Banana Pro",
    delay_seconds: float = 0.0
) -> Dict[str, Any]:
    # Nếu trước đó user bấm Stop All, cờ dừng còn treo sẽ làm master-gen vừa mở Flow đã tự thoát.
    _STOP_SIGNAL.clear()
    
    # --- 1. XỬ LÝ ĐƯỜNG DẪN ĐÚNG CÁCH (Giống như render.py) ---
    from utils.path_helper import BASE_DIR, STORAGE_DIR
    
    try:
        # Xử lý đường dẫn tương đối/tuyệt đối
        if not script_path:
            return {"error": "script_path không được để trống."}
        
        # Nếu là đường dẫn tuyệt đối, dùng trực tiếp
        if os.path.isabs(script_path):
            abs_path = os.path.normpath(script_path)
        else:
            # Nếu là đường dẫn tương đối (../storage/...), resolve đúng cách
            normalized = script_path.replace("/", os.sep).replace("\\", os.sep)
            
            # Xử lý đường dẫn bắt đầu bằng ../storage/
            if normalized.startswith(".." + os.sep + "storage" + os.sep):
                # Loại bỏ ../storage/ và dùng STORAGE_DIR trực tiếp
                rel_path = normalized[len(".." + os.sep + "storage" + os.sep):]
                abs_path = os.path.normpath(str(STORAGE_DIR / rel_path))
            elif normalized.startswith("storage" + os.sep):
                # Nếu chỉ có storage/ (không có ../)
                rel_path = normalized[len("storage" + os.sep):]
                abs_path = os.path.normpath(str(STORAGE_DIR / rel_path))
            elif normalized.startswith(".." + os.sep):
                # Nếu chỉ có ../ (không có storage)
                normalized = normalized[3:]  # Bỏ "../"
                abs_path = os.path.normpath(str(BASE_DIR / normalized))
            else:
                # Đường dẫn tương đối bình thường
                abs_path = os.path.normpath(str(BASE_DIR / normalized))
        
        # Kiểm tra file tồn tại
        if not os.path.exists(abs_path):
            return {"error": f"File không tồn tại: {abs_path}. Script path gốc: {script_path}"}
        
        # Đọc nhanh để check lỗi (không cần lock ở đây vì chỉ đọc)
        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        master_prompt = data.get("master_cast_image_prompt")
        
        if not master_prompt:
            return {"error": "Không tìm thấy master_cast_image_prompt trong file."}
            
        script_dir = os.path.dirname(abs_path)
        mode_dir = os.path.dirname(script_dir)
        sample_dir = os.path.join(mode_dir, "sample")
        os.makedirs(sample_dir, exist_ok=True)
        
        script_name = os.path.splitext(os.path.basename(abs_path))[0]
        save_path = os.path.join(sample_dir, f"{script_name}.png")
        
    except Exception as e:
        return {"error": f"Lỗi xử lý file: {str(e)}"}

    nst = NSTBrowserManager()
    api_key_map = _build_profile_api_key_map()
    settings_master = get_settings() or {}
    from services.browser_engine import profile_pool_for_run

    pool_one = profile_pool_for_run(1, settings_master)
    if not pool_one:
        return {"error": "Chưa có Profile IDs."}
    first_driver_id = pool_one[0]

    # --- 2. THIẾT LẬP LUỒNG CHẠY AN TOÀN (FIX LỖI WINDOWS) ---
    def _run():
        # Fix lỗi Event Loop trên Windows (Quan trọng!)
        if os.name == 'nt':
            _ProactorBasePipeTransport.__del__ = silence_event_loop_closed(_ProactorBasePipeTransport.__del__)
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with _RUNNING_LOOPS_LOCK:
            _RUNNING_LOOPS.add(loop)

        # Hàm Main Async
        async def _main():
            page = None
            cdp_session = None
            try:
                _ensure_profiles_started(nst, [first_driver_id], api_key_map)
                await _wait_for_profiles_ready(nst, [first_driver_id], api_key_map)
                ws = _ws_endpoint_for_profile(
                    nst, first_driver_id, api_key_map, settings=settings_master
                )
                if not ws:
                    return
                page = await connect_and_get_page(ws)
                if not page: return
                await _maybe_move_window(page)

                # --- SETUP PAGE MỘT LẦN DUY NHẤT (Ngoài vòng retry) ---
                print(f"[Master Gen] 🚀 Driver 1 bắt đầu setup...")
                try:
                    await goto_flow_and_open_project(page, FLOW_URL, stop_check=lambda: _STOP_SIGNAL.is_set())
                except FlowStoppedError:
                    return
                await inject_keep_alive(page)
                await asyncio.sleep(1.0)
                await select_mode(page, "image", stop_check=lambda: _STOP_SIGNAL.is_set())
                await asyncio.sleep(0.5)

                await setup_render_settings(
                    page,
                    output_count=1,
                    aspect_ratio=_flow_setup_aspect_ratio(ratio, "image"),
                    model=model,
                )
                await asyncio.sleep(0.5)

                # --- SETUP CDP LISTENER MỘT LẦN ---
                cdp_session = await page.context.new_cdp_session(page)
                await cdp_session.send("Network.enable", {
                    "maxTotalBufferSize": 10000000, 
                    "maxResourceBufferSize": 5000000
                })
                
                target_request_ids = set()
                error_detected = asyncio.Event()
                error_status = None

                async def on_request_sent(event):
                    req = event.get("request", {})
                    if "batchGenerateImages" in req.get("url", ""):
                        target_request_ids.add(event["requestId"])

                async def on_loading_finished(event):
                    nonlocal error_status
                    rid = event["requestId"]
                    if rid in target_request_ids:
                        try:
                            body_data = await cdp_session.send("Network.getResponseBody", {"requestId": rid})
                            content = body_data["body"]
                            is_base64 = body_data.get("base64Encoded", False)
                            raw_bytes = base64.b64decode(content) if is_base64 else content.encode('utf-8')

                            try:
                                json_data = json.loads(raw_bytes)
                            except:
                                text_content = raw_bytes.decode('utf-8', errors='ignore')
                                if text_content.startswith(")]}'"):
                                    json_data = json.loads(text_content[5:])
                                else: 
                                    return

                            # ==========================================================
                            # 🛑 XỬ LÝ LỖI (Giống run_youtube_script)
                            # ==========================================================
                            if "error" in json_data:
                                error_obj = json_data.get("error", {})
                                code = error_obj.get("code")
                                status = error_obj.get("status")
                                
                                # Xác định loại lỗi
                                if code == 403:
                                    error_status = "captcha_error"
                                elif code == 400 or status == "INVALID_ARGUMENT":
                                    error_status = "content_error"
                                else:
                                    error_status = "error"
                                
                                print(f"[Master Gen] ⚠️ Phát hiện lỗi: code={code}, status={error_status}")
                                await update_master_image_status(abs_path, error_status)
                                error_detected.set()
                                return

                            # Xử lý lỗi code 3 trong operations
                            operations = json_data.get("operations", [])
                            for item in operations:
                                op_error = item.get("operation", {}).get("error", {})
                                if op_error.get("code") == 3:
                                    error_status = "content_error"
                                    print(f"[Master Gen] ⚠️ Phát hiện lỗi Code 3")
                                    await update_master_image_status(abs_path, error_status)
                                    error_detected.set()
                                    return

                            # ==========================================================
                            # ✅ XỬ LÝ THÀNH CÔNG
                            # ==========================================================
                            media_list = json_data.get("media", [])
                            for item in media_list:
                                gen_img = item.get("image", {}).get("generatedImage", {})
                                fife_url = gen_img.get("fifeUrl")
                                
                                if fife_url:
                                    print(f"[Master Gen] 📸 Bắt được ảnh! Đang tải về: {save_path}")
                                    if await download_image_requests(fife_url, save_path):
                                        print(f"[Master Gen] ✅ Đã lưu ảnh thành công!")
                                        rel_path = f"sample/{script_name}.png"
                                        
                                        # 🔥 QUAN TRỌNG: Dùng abs_path đã resolve
                                        await update_master_image_path(abs_path, rel_path)
                                        error_status = None  # Đánh dấu thành công (không có lỗi)
                                        error_detected.set()  # Đánh dấu đã xong (thành công)
                                        return
                        except Exception as e:
                            print(f"[Master Gen] ⚠️ Lỗi parse response: {e}")
                        finally:
                            if rid in target_request_ids: 
                                target_request_ids.remove(rid)

                cdp_session.on("Network.requestWillBeSent", on_request_sent)
                cdp_session.on("Network.loadingFinished", on_loading_finished)

                # --- CƠ CHẾ RETRY VỚI 2 VÒNG (Chỉ gửi lại prompt) ---
                async def _runner_with_retry():
                    nonlocal error_status
                    MAX_RETRIES = 2
                    # Reset counter cho master gen (chỉ có 1 luồng nhưng vẫn reset để sạch)
                    reset_flow_delay_counter()
                    for attempt in range(MAX_RETRIES):
                        print(f"\n🔄 [Master Gen] --- VÒNG CHẠY THỨ {attempt + 1}/{MAX_RETRIES} ---\n")
                        
                        # Reset error event và status
                        error_detected.clear()
                        error_status = None
                        await update_master_image_status(abs_path, "processing")
                        
                        # 🔥 Random delay trước khi gửi prompt đầu tiên (3–10s)
                        if attempt == 0:
                            await random_delay_before_action(min_seconds=1.0, max_seconds=3.0)
                        
                        # Chỉ gửi lại prompt (không setup lại)
                        print(f"[Master Gen] 🎨 Đang gửi Master Prompt (vòng {attempt + 1})...")
                        await send_prompt_text(page, master_prompt)

                        # 🔥 Sau khi gửi master prompt, di chuột nhẹ trong ~30s (không scroll).
                       
                        
                        print(f"[Master Gen] ⏳ Đang đợi ảnh trả về...")
                        try:
                            await asyncio.wait_for(error_detected.wait(), timeout=60.0)
                            
                            # Kiểm tra xem có lỗi không
                            if error_status:
                                print(f"[Master Gen] ❌ Phát hiện lỗi: {error_status}")
                                if attempt < MAX_RETRIES - 1:
                                    print(f"[Master Gen] ⚠️ Sẽ retry sau 5 giây...")
                                    await asyncio.sleep(5)
                                else:
                                    print(f"[Master Gen] ❌ Đã hết {MAX_RETRIES} vòng retry.")
                                continue
                            else:
                                # Thành công (đã có ảnh)
                                print(f"[Master Gen] ✅ Đã tạo ảnh master thành công ở vòng {attempt + 1}!")
                                return
                        except asyncio.TimeoutError:
                            print(f"[Master Gen] ❌ Hết thời gian chờ ảnh (Timeout).")
                            await update_master_image_status(abs_path, "error")
                            if attempt < MAX_RETRIES - 1:
                                print(f"[Master Gen] ⚠️ Sẽ retry sau 5 giây...")
                                await asyncio.sleep(5)
                            else:
                                print(f"[Master Gen] ❌ Đã hết {MAX_RETRIES} vòng retry.")

                # Chạy với cơ chế retry
                await _runner_with_retry()

            except Exception as e:
                print(f"[Master Gen] ❌ Lỗi luồng chính: {e}")
            finally:
                # Đóng CDP session và page khi hoàn thành
                try:
                    if cdp_session:
                        await cdp_session.detach()
                except:
                    pass
                try:
                    if page:
                        await page.close()
                except:
                    pass

        try:
            loop.run_until_complete(_main())
        finally:
            with _RUNNING_LOOPS_LOCK:
                _RUNNING_LOOPS.discard(loop)
            loop.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"success": True, "message": "Đang xử lý tạo Master Image..."}

def normalize_text(text):
    if not text: return ""
    # Chuẩn hóa: lowercase, bỏ newlines/carriage returns, normalize spaces, strip
    normalized = text.lower()
    # Bỏ tất cả newlines và carriage returns
    normalized = normalized.replace('\n', ' ').replace('\r', ' ')
    # Bỏ non-breaking space và thay bằng space thường
    normalized = normalized.replace('\xa0', ' ')
    # Normalize multiple spaces thành 1 space
    normalized = re.sub(r'\s+', ' ', normalized)
    # Strip đầu và cuối
    normalized = normalized.strip()
    return normalized

import time

def _normalize_scene_range(start_scene: Optional[int], end_scene: Optional[int]):
    start = int(start_scene or 0)
    end = int(end_scene or 0)
    if start <= 0 and end <= 0:
        return None, None
    if start <= 0:
        start = 1
    if end <= 0:
        end = None
    if end is not None and end < start:
        end = start
    return start, end

def _scene_in_range(scene: Dict[str, Any], index: int, start: Optional[int], end: Optional[int]) -> bool:
    scene_num = scene.get("scene_id")
    try:
        scene_num = int(scene_num)
    except Exception:
        scene_num = index + 1
    if start is not None and scene_num < start:
        return False
    if end is not None and scene_num > end:
        return False
    return True

def _filter_scenes_by_range(
    scenes: List[Dict[str, Any]],
    start_scene: Optional[int],
    end_scene: Optional[int],
    max_scenes: Optional[int] = None
) -> List[Dict[str, Any]]:
    if start_scene or end_scene:
        start, end = _normalize_scene_range(start_scene, end_scene)
        return [s for i, s in enumerate(scenes) if _scene_in_range(s, i, start, end)]
    if max_scenes and max_scenes > 0:
        return scenes[:max_scenes]
    return scenes

def _download_image_requests_sync(url, save_path, max_retries=2, timeout=10):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, timeout=timeout)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                return True
            else:
                print(f"⚠️ Lần {attempt + 1}: Lỗi HTTP {response.status_code}")
        except Exception as e:
            print(f"⚠️ Lần {attempt + 1} thất bại: {e}")
        if attempt < max_retries - 1:
            time.sleep(3)
    return False

async def download_image_requests(url, save_path, max_retries=2, timeout=10):
    return await asyncio.to_thread(
        _download_image_requests_sync,
        url,
        save_path,
        max_retries,
        timeout
    )

async def setup_cdp_image_listener(
    page,
    prompt_map,
    output_dir,
    script_path,
    pending_scenes: set,
    scene_events: Dict[int, asyncio.Event],
    scene_results: Dict[int, str],
    yt_video_resolution: Optional[str] = None
):
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable", {
            "maxTotalBufferSize": 10000000, 
            "maxResourceBufferSize": 5000000
        })
        
        target_request_ids = set()
        processed_ids = set()
        request_to_prompt = {} 
        request_to_scene_id = {}  # 🔥 MỚI: Map trực tiếp request_id -> scene_id

        # 1K hay 2K (ưu tiên 2K nếu được chọn)
        want_2k = (yt_video_resolution or "").lower() == "2k"

        def _mark_scene_result(scene_id, result_type: str):
            if not scene_id:
                return
            scene_results[scene_id] = result_type
            scene_event = scene_events.get(scene_id)
            if scene_event and not scene_event.is_set():
                scene_event.set()

        script_name = os.path.splitext(os.path.basename(script_path))[0]
        specific_output_dir = os.path.join(output_dir, script_name)
        os.makedirs(specific_output_dir, exist_ok=True)

        # --- DOWNLOAD 2K (nếu bật) ---
        download_event: asyncio.Event = asyncio.Event()
        download_state: Dict[str, Any] = {"guid": None, "filename": None, "state": None}

        # JS thao tác mới cho ảnh:
        # Hover tile -> mở 3 chấm -> Tải xuống -> 2K Upscaled
        CLICK_DOWNLOAD_2K_JS = r"""
        async function () {
            console.log("🔍 Đang chạy chuỗi Auto: Hover -> Mở Menu -> Tải xuống -> 2K Upscaled...");

            const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

            const simulateEnterClick = async (el) => {
                el.focus();
                el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                await wait(50);
            };

            const tile = document.querySelector('div[data-tile-id]');
            if (!tile) {
                return { ok: false, reason: "Không tìm thấy vùng chứa ảnh (data-tile-id)." };
            }

            tile.scrollIntoView({ behavior: 'smooth', block: 'center' });

            const hoverTarget = tile.querySelector('a') || tile;
            ['mouseenter', 'mouseover', 'mousemove'].forEach(name => {
                hoverTarget.dispatchEvent(new MouseEvent(name, { bubbles: true, cancelable: true, view: window }));
            });

            await wait(400);

            const threeDotBtn = Array.from(tile.querySelectorAll('button')).find(btn =>
                (btn.innerText.includes('Tạo thêm') || btn.innerHTML.includes('more_vert')) &&
                btn.querySelector('i')?.getAttribute('font-size') === '1.15rem'
            );

            if (!threeDotBtn) {
                return { ok: false, reason: "Hover rồi nhưng không tóm được nút 3 chấm nhỏ." };
            }

            console.log("✅ Bước 1: Đang mở menu 3 chấm...");
            await simulateEnterClick(threeDotBtn);
            await wait(350);

            const menuItems = Array.from(document.querySelectorAll('[role="menuitem"], div[class*="goZcMY"]'));
            const downloadBtn = menuItems.find(el => el.innerText.includes('Tải xuống'));

            if (!downloadBtn) {
                return { ok: false, reason: "Menu đã mở nhưng không tìm thấy nút 'Tải xuống'." };
            }

            console.log("✅ Bước 2: Đã thấy 'Tải xuống', đang bấm để mở menu con...");
            await simulateEnterClick(downloadBtn);

            await wait(400);
            const currentItems = Array.from(document.querySelectorAll('[role="menuitem"], button'));
            const twoKBtn = currentItems.find(el => el.innerText.includes('2K') && el.innerText.includes('Upscaled'));

            if (!twoKBtn) {
                return { ok: false, reason: "Bấm 'Tải xuống' rồi nhưng không thấy mục '2K Upscaled'." };
            }

            console.log("🎯 Bước 3: Đã tóm được '2K Upscaled', chốt hạ...");
            await simulateEnterClick(twoKBtn);

            return { ok: true, reason: "HOÀN TẤT QUY TRÌNH tải 2K Upscaled." };
        }
        """

        # Cấu hình download cho 2K: để Chrome tự tải, mình chỉ đổi tên & lưu map như 1K
        if want_2k:
            try:
                await cdp.send(
                    "Browser.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": os.path.abspath(specific_output_dir),
                        "eventsEnabled": True,
                    },
                )
                print(f"[YouTube Image] Download path (2K) = {specific_output_dir}")
            except Exception as e:
                print(f"[YouTube Image] WARN setDownloadBehavior failed: {e}")
                want_2k = False  # fallback về 1K nếu cấu hình fail

        async def on_request_sent(event):
            req = event.get("request", {})
            if "batchGenerateImages" in req.get("url", ""):
                rid = event["requestId"]
                target_request_ids.add(rid)
                print(f"[YouTube Image] 📤 Request sent: requestId={rid}, url={req.get('url', '')[:100]}...")
                try:
                    post_data = req.get("postData")
                    if post_data:
                        payload = json.loads(post_data)
                        req_items = payload.get("requests", [])
                        if req_items:
                            prompt_sent = req_items[0].get("prompt", "")
                            if prompt_sent:
                                normalized_prompt = normalize_text(prompt_sent)
                                request_to_prompt[rid] = normalized_prompt
                                
                                # 🔥 DEBUG: Log prompt từ request
                                print(f"[YouTube Image] 🔍 Mapping: requestId={rid}, normalized_prompt length={len(normalized_prompt)}, first 100 chars: {normalized_prompt[:100]}")
                                
                                # 🔥 Tìm scene_id từ prompt_map
                                scene_id_from_map = prompt_map.get(normalized_prompt)
                                
                                if scene_id_from_map:
                                    print(f"[YouTube Image] ✅ Bước 1 (prompt_map.get): Match Scene {scene_id_from_map}")
                                else:
                                    print(f"[YouTube Image] ⚠️ Bước 1 (prompt_map.get): Không match, prompt_map có {len(prompt_map)} keys")
                                
                                # 🔥 Nếu không tìm thấy bằng .get(), chỉ thử so sánh TOÀN BỘ (full string).
                                # Không dùng fuzzy theo 50 ký tự đầu nữa để tránh map nhầm các scene có phần đầu prompt giống nhau.
                                if not scene_id_from_map and prompt_map:
                                    print(f"[YouTube Image] 🔄 Bước 2: Duyệt {len(prompt_map)} keys để so sánh TOÀN BỘ (full normalized prompt)...")
                                    for map_key, map_scene_id in prompt_map.items():
                                        # So sánh TOÀN BỘ (normalize_text đã có .strip() và .lower())
                                        if normalized_prompt == map_key:
                                            scene_id_from_map = map_scene_id
                                            print(f"[YouTube Image] 🔍 Found match by exact comparison (full text): Scene {map_scene_id}")
                                            break
                                
                                if scene_id_from_map:
                                    request_to_scene_id[rid] = scene_id_from_map
                                    print(f"[YouTube Image] ✅ Saved prompt + scene_id ({scene_id_from_map}) for requestId={rid}")
                                else:
                                    # 🔥 DEBUG: In ra để so sánh
                                    print(f"[YouTube Image] ⚠️ Saved prompt but scene_id not found in prompt_map for requestId={rid}")
                                    print(f"   Normalized prompt length: {len(normalized_prompt)}, first 100 chars: {normalized_prompt[:100]}")
                                    if prompt_map:
                                        print(f"   prompt_map keys (first 3):")
                                        for i, (key, scene_id) in enumerate(list(prompt_map.items())[:3]):
                                            print(f"     [{i}] Scene {scene_id}, length: {len(key)}, first 100 chars: {key[:100]}")
                                            print(f"         Match? {normalized_prompt == key}")
                                    else:
                                        print(f"   prompt_map is EMPTY!")
                            else:
                                print(f"[YouTube Image] ⚠️ No prompt in request[0] for requestId={rid}")
                        else:
                            print(f"[YouTube Image] ⚠️ No requests array in payload for requestId={rid}")
                    else:
                        print(f"[YouTube Image] ⚠️ No postData for requestId={rid}")
                except Exception as e:
                    print(f"[YouTube Image] ❌ Error parsing request payload: {e}")
                    import traceback
                    traceback.print_exc()

        async def on_response_received(event):
            """Bắt response để check status code 403/400"""
            try:
                resp = event.get("response", {})
                rid = event.get("requestId")
                url = resp.get("url", "")
                status = resp.get("status", 0)
                
                if "batchGenerateImages" in url and rid in target_request_ids:
                    print(f"[YouTube Image] 📥 Response received: requestId={rid}, status={status}")
                    if status in (403, 400):
                        print(f"[YouTube Image] ⚠️ Detected HTTP {status} status code!")
            except Exception as e:
                print(f"[YouTube Image] ❌ Error in on_response_received: {e}")

        async def on_loading_finished(event):
            rid = event["requestId"]
            if rid in target_request_ids and rid not in processed_ids:
                print(f"[YouTube Image] 📥 Received response for requestId: {rid}")
                try:
                    processed_ids.add(rid)
                    try:
                        body_data = await cdp.send("Network.getResponseBody", {"requestId": rid})
                    except Exception as get_body_error:
                        # Suppress lỗi "No resource with given identifier" (thường xảy ra với redirect/preflight requests)
                        error_msg = str(get_body_error)
                        if "No resource with given identifier" not in error_msg and "Protocol error" not in error_msg:
                            print(f"[YouTube Image] ⚠️ Lỗi getResponseBody: {get_body_error}")
                        return
                    content = body_data["body"]
                    is_base64 = body_data.get("base64Encoded", False)
                    raw_bytes = base64.b64decode(content) if is_base64 else content.encode('utf-8')

                    # 🔥 Thêm random delay để tránh pattern detection
                    await asyncio.sleep(random.uniform(0.1, 0.5))

                    json_data = None
                    try:
                        json_data = json.loads(raw_bytes)
                        print(f"[YouTube Image] ✅ Parsed JSON successfully")
                    except json.JSONDecodeError as je:
                        text_content = raw_bytes.decode('utf-8', errors='ignore')
                        if text_content.startswith(")]}'"):
                            json_data = json.loads(text_content[5:])
                            print(f"[YouTube Image] ✅ Parsed JSON with prefix strip")
                        else:
                            print(f"[YouTube Image] ❌ Failed to parse JSON, returning. First 200 chars: {text_content[:200]}")
                            return 

                    if json_data is None:
                        print(f"[YouTube Image] ⚠️ json_data is None!")
                        return

                    # 🔥 DEBUG: In ra để kiểm tra structure
                    print(f"[YouTube Image Debug] JSON keys: {list(json_data.keys())}")
                    if "error" in json_data:
                        print(f"[YouTube Image Debug] ✅ Phát hiện error trong response:")
                        print(f"   Error object: {json_data.get('error')}")
                    
                    if "error" in json_data:
                        error_obj = json_data["error"]
                        code = error_obj.get("code")
                        prompt_key = request_to_prompt.get(rid)
                        
                        # 🔥 ƯU TIÊN: Dùng request_to_scene_id trực tiếp (đã map khi gửi request)
                        scene_id = request_to_scene_id.get(rid)
                        if not scene_id:
                            # Fallback: Tìm từ prompt_map
                            scene_id = prompt_map.get(prompt_key) if prompt_key else None
                        
                        # 🔥 DEBUG: In ra để kiểm tra
                        print(f"[YouTube Image Error Debug] requestId={rid}")
                        print(f"   scene_id from request_to_scene_id: {request_to_scene_id.get(rid)}")
                        print(f"   prompt_key from request_to_prompt: {prompt_key}")
                        print(f"   scene_id from prompt_map (fallback): {prompt_map.get(prompt_key) if prompt_key else None}")
                        print(f"   prompt_map size: {len(prompt_map)}")
                        
                        error_type = ""
                        if code == 403:
                            error_type = "captcha_error"
                            print(f"⚠️ Root Error 403 Detected (YouTube Image) -> Map được Prompt.")
                        elif code == 400:
                            error_type = "content_error"
                            print(f"⚠️ Root Error 400 Detected (YouTube Image) -> Map được Prompt.")
                        else:
                            error_type = "captcha_error"
                        
                        scene_to_update = None
                        
                        if scene_id:
                            scene_to_update = scene_id
                            print(f"   ✅ Tim thay scene_id chinh xac: Scene {scene_id}")
                        elif pending_scenes:
                            # FALLBACK: Dùng scene đầu tiên đang pending
                            scene_to_update = min(pending_scenes)
                            if len(pending_scenes) > 1:
                                print(f"   ⚠️ FALLBACK: Khong tim thay scene_id chinh xac, dung Scene {scene_to_update} (scene dau tien trong {len(pending_scenes)} scenes dang pending)")
                                print(f"   ⚠️ CANH BAO: Co {len(pending_scenes)} scenes dang pending, Scene {scene_to_update} co the KHONG phai scene bi loi!")
                            else:
                                print(f"   ✅ FALLBACK: Khong tim thay scene_id chinh xac, dung Scene {scene_to_update} (chi co 1 scene dang pending - CHAC CHAN DUNG)")
                        else:
                            # Fallback cuối: Thử tìm scene đầu tiên trong prompt_map (bất kỳ)
                            if prompt_map:
                                scene_to_update = list(prompt_map.values())[0]
                                print(f"   -> Fallback cuoi: Dung Scene {scene_to_update} (scene dau tien trong prompt_map)")
                            else:
                                print(f"   ⚠️ Khong co scene nao de danh dau loi! (prompt_map rong, pending_scenes rong)")
                        
                        # 🔥 QUAN TRỌNG: LUÔN LUÔN CỐ GẮNG LƯU (kể cả nếu không tìm thấy scene chính xác)
                        if scene_to_update:
                            print(f"   -> Danh dau loi '{error_type}' cho Scene {scene_to_update}")
                            try:
                                await update_scene_status(script_path, scene_to_update, error_type)
                                print(f"   ✅ Da luu '{error_type}' vao script cho Scene {scene_to_update}")
                            except Exception as e:
                                print(f"   ❌ Loi khi luu status vao script: {e}")
                                import traceback
                                traceback.print_exc()
                            
                            if scene_to_update in pending_scenes:
                                pending_scenes.remove(scene_to_update)
                            _mark_scene_result(scene_to_update, error_type or "captcha_error")
                        else:
                            # Nếu vẫn không có scene nào, in cảnh báo
                            print(f"   ⚠️ KHONG THE LUU LOI '{error_type}' - Khong co scene nao de danh dau!")
                            print(f"   Debug: prompt_map={len(prompt_map)} entries, pending_scenes={len(pending_scenes)} scenes")
                        
                        return

                    media_list = json_data.get("media", [])
                    print(f"[YouTube Image] 📥 Received {len(media_list)} media items for requestId={rid}")
                    for item in media_list:
                        try:
                            gen_img = item.get("image", {}).get("generatedImage", {})
                            fife_url = gen_img.get("fifeUrl")
                            request_data = gen_img.get("requestData", {})
                            prompt_inputs = request_data.get("promptInputs", [])
                            text_input = prompt_inputs[0].get("textInput") if prompt_inputs else None

                            print(f"[YouTube Image] 🔍 Processing media item: fife_url={bool(fife_url)}, text_input={bool(text_input)}")
                            
                            if fife_url and text_input:
                                normalized_prompt = normalize_text(text_input)
                                # 🔥 ƯU TIÊN: Dùng request_to_scene_id trực tiếp (đã map khi gửi request)
                                scene_id = request_to_scene_id.get(rid)
                                if not scene_id:
                                    # Fallback: Tìm từ prompt_map
                                    scene_id = prompt_map.get(normalized_prompt)

                                # ❗ Quan trọng: Chỉ fallback sang pending_scenes khi CHỈ CÒN 1 scene pending.
                                # Nếu còn nhiều scene đang pending và không map được chính xác → bỏ qua để tránh gán nhầm
                                if not scene_id:
                                    if pending_scenes:
                                        if len(pending_scenes) == 1:
                                            scene_id = min(pending_scenes)
                                            print(
                                                f"[YouTube Image] ✅ Safe fallback scene_id={scene_id} "
                                                "(only 1 pending scene left)"
                                            )
                                        else:
                                            print(
                                                f"[YouTube Image] ⚠️ Không map được scene_id, "
                                                f"bỏ qua media để tránh gán nhầm (pending_scenes={sorted(pending_scenes)})"
                                            )
                                            continue

                                print(f"[YouTube Image] 🎯 Mapping: scene_id={scene_id}, normalized_prompt (first 50 chars)={normalized_prompt[:50]}")
                                
                                if scene_id:
                                    # 1K: báo "url" ngay để worker có thể gửi prompt tiếp khi link sẵn sàng.
                                    # 2K: chỉ báo "done" sau khi tải xong trong handle_2k_for_scene.
                                    if not want_2k:
                                        _mark_scene_result(scene_id, "url")
                                    
                                    file_name = f"{int(scene_id):03d}.png"
                                    save_path = os.path.join(specific_output_dir, file_name)
                                    rel_path = f"images/{script_name}/{file_name}"
                                    
                                    if want_2k:
                                        # 2K: worker sẽ chỉ được "mở khoá" khi handle_2k_for_scene
                                        # gọi _mark_scene_result(scene_id, "done")
                                        async def handle_2k_for_scene(scene_id: int, base_url: str, spath: str, rpath: str):
                                            """
                                            2K: ấn "Tải xuống 2K", chờ Chrome tự tải, rồi đổi tên file về đúng fname/spath.
                                            Nếu sau timeout vẫn chưa thấy file, fallback dùng base_url (1K) như cũ.
                                            """
                                            nonlocal want_2k

                                            if not want_2k:
                                                # Fallback: tải 1K như luồng hiện tại
                                                ok = await download_image_requests(base_url, spath)
                                                if ok:
                                                    await update_scene_status(script_path, scene_id, "done", rpath)
                                                    if scene_id in pending_scenes:
                                                        pending_scenes.remove(scene_id)
                                                    _mark_scene_result(scene_id, "done")
                                                return

                                            # Reset trạng thái download
                                            try:
                                                download_event.clear()
                                                download_state["filename"] = None
                                                download_state["state"] = None
                                            except Exception:
                                                pass

                                            # 1) Click "Tải xuống 2K" trên UI
                                            try:
                                                try:
                                                    await page.bring_to_front()
                                                except Exception:
                                                    pass
                                                print(f"[YouTube Image] 🖱️ Đang thao tác menu 3 chấm -> Tải xuống -> 2K Upscaled (Scene {scene_id})...")
                                                js_result = await page.evaluate(CLICK_DOWNLOAD_2K_JS)
                                                if not (isinstance(js_result, dict) and js_result.get("ok")):
                                                    reason = (js_result or {}).get("reason") if isinstance(js_result, dict) else "Không rõ lý do."
                                                    raise Exception(reason)
                                                print(f"[YouTube Image] ✅ Đã bấm 2K Upscaled (Scene {scene_id}), chờ download event...")
                                            except Exception as e:
                                                print(f"[YouTube Image] WARN click Tải xuống 2K failed: {e}")
                                                # fallback: dùng base_url
                                                ok = await download_image_requests(base_url, spath)
                                                if ok:
                                                    await update_scene_status(script_path, scene_id, "done", rpath)
                                                    if scene_id in pending_scenes:
                                                        pending_scenes.remove(scene_id)
                                                    _mark_scene_result(scene_id, "done")
                                                return

                                            # 2) Chờ Chrome tải xong (Browser.downloadProgress -> completed)
                                            try:
                                                await asyncio.wait_for(download_event.wait(), timeout=180)
                                            except asyncio.TimeoutError:
                                                print(f"[YouTube Image] ⚠️ 2K timeout cho Scene {scene_id}, fallback về base URL.")
                                                ok = await download_image_requests(base_url, spath)
                                                if ok:
                                                    await update_scene_status(script_path, scene_id, "done", rpath)
                                                    if scene_id in pending_scenes:
                                                        pending_scenes.remove(scene_id)
                                                    _mark_scene_result(scene_id, "done")
                                                return

                                            # 3) Đổi tên file Chrome vừa tải -> fname chuẩn (scene_id.png)
                                            try:
                                                src_path = None
                                                suggested = download_state.get("filename")
                                                if suggested:
                                                    # suggestedFilename có thể là tên file hoặc full path.
                                                    raw_candidate = suggested
                                                    if os.path.isabs(raw_candidate) and os.path.exists(raw_candidate):
                                                        src_path = raw_candidate
                                                    else:
                                                        # Ưu tiên file trong thư mục output hiện tại.
                                                        candidate_local = os.path.join(specific_output_dir, os.path.basename(raw_candidate))
                                                        if os.path.exists(candidate_local):
                                                            src_path = candidate_local

                                                        # Một số máy vẫn tải về Downloads mặc định.
                                                        if not src_path:
                                                            downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
                                                            candidate_downloads = os.path.join(downloads_dir, os.path.basename(raw_candidate))
                                                            if os.path.exists(candidate_downloads):
                                                                src_path = candidate_downloads

                                                # Nếu không bắt được tên file, lấy file .png mới nhất trong folder
                                                if not src_path or not os.path.exists(src_path):
                                                    candidates = []
                                                    try:
                                                        for name in os.listdir(specific_output_dir):
                                                            if name.lower().endswith(".png"):
                                                                full = os.path.join(specific_output_dir, name)
                                                                candidates.append((os.path.getmtime(full), full))
                                                    except Exception:
                                                        candidates = []
                                                    # Fallback thêm: quét cả Downloads
                                                    try:
                                                        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
                                                        for name in os.listdir(downloads_dir):
                                                            if name.lower().endswith(".png"):
                                                                full = os.path.join(downloads_dir, name)
                                                                candidates.append((os.path.getmtime(full), full))
                                                    except Exception:
                                                        pass
                                                    candidates.sort(reverse=True)
                                                    if candidates:
                                                        src_path = candidates[0][1]

                                                if not src_path or not os.path.exists(src_path):
                                                    print(f"[YouTube Image] ⚠️ Không tìm thấy file 2K đã tải, fallback về base URL.")
                                                    ok = await download_image_requests(base_url, spath)
                                                    if ok:
                                                        await update_scene_status(script_path, scene_id, "done", rpath)
                                                        if scene_id in pending_scenes:
                                                            pending_scenes.remove(scene_id)
                                                        _mark_scene_result(scene_id, "done")
                                                    return

                                                # Đổi tên sang đúng fname/spath
                                                if os.path.exists(spath):
                                                    os.remove(spath)
                                                os.rename(src_path, spath)
                                                print(f"[YouTube Image] ✅ 2K downloaded and renamed -> {spath}")

                                                await update_scene_status(script_path, scene_id, "done", rpath)
                                                if scene_id in pending_scenes:
                                                    pending_scenes.remove(scene_id)
                                                _mark_scene_result(scene_id, "done")
                                            except Exception as e:
                                                print(f"[YouTube Image] ⚠️ Lỗi xử lý 2K cho Scene {scene_id}: {e}")
                                                # Fallback cuối: đảm bảo vẫn có image base
                                                ok = await download_image_requests(base_url, spath)
                                                if ok:
                                                    await update_scene_status(script_path, scene_id, "done", rpath)
                                                    if scene_id in pending_scenes:
                                                        pending_scenes.remove(scene_id)
                                                    _mark_scene_result(scene_id, "done")
                                        
                                        await handle_2k_for_scene(scene_id, fife_url, save_path, rel_path)
                                    else:
                                        # 1K: giữ luồng tải như hiện tại
                                        print(f"[YouTube Image] 📥 Downloading image for Scene {scene_id} from {fife_url[:80]}...")
                                        if await download_image_requests(fife_url, save_path):
                                            await update_scene_status(script_path, scene_id, "done", rel_path)
                                            print(f"[YouTube Image] ✅ Downloaded and saved Scene {scene_id} to {rel_path}")
                                            if scene_id in pending_scenes: pending_scenes.remove(scene_id)
                                else:
                                    print(f"[YouTube Image] ⚠️ Cannot find scene_id for prompt (first 50 chars): {normalized_prompt[:50]}")
                            elif not fife_url:
                                print(f"[YouTube Image] ⚠️ Media item missing fifeUrl")
                            elif not text_input:
                                print(f"[YouTube Image] ⚠️ Media item missing textInput")
                        except Exception as e:
                            print(f"[YouTube Image] ⚠️ Lỗi xử lý media item: {e}")
                            import traceback
                            traceback.print_exc()
                except Exception as e:
                    print(f"[YouTube Image] ❌ Lỗi trong on_loading_finished: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    if rid in target_request_ids: target_request_ids.remove(rid)
                    if rid in request_to_prompt: del request_to_prompt[rid]
                    if rid in request_to_scene_id: del request_to_scene_id[rid]

        cdp.on("Network.requestWillBeSent", on_request_sent)
        cdp.on("Network.responseReceived", on_response_received)
        cdp.on("Network.loadingFinished", on_loading_finished)

        if want_2k:
            async def on_download_will_begin(event):
                try:
                    download_state["guid"] = event.get("guid")
                    download_state["filename"] = event.get("suggestedFilename")
                    download_state["state"] = "started"
                    download_event.clear()
                    print(
                        f"[YouTube Image] [DL2K] started guid={download_state['guid']} "
                        f"file={download_state['filename']}"
                    )
                except Exception:
                    pass

            async def on_download_progress(event):
                try:
                    state_val = event.get("state")
                    download_state["guid"] = event.get("guid") or download_state.get("guid")
                    download_state["state"] = state_val
                    if state_val == "completed":
                        print("[YouTube Image] [DL2K] download completed event fired")
                        download_event.set()
                    elif state_val == "canceled":
                        print("[YouTube Image] [DL2K] download canceled")
                except Exception:
                    pass

            cdp.on("Browser.downloadWillBegin", on_download_will_begin)
            cdp.on("Browser.downloadProgress", on_download_progress)
        
        return cdp

    except Exception as e:
        print(f"❌ Lỗi Setup CDP: {e}")
        return None

async def update_master_image_status(script_path: str, new_status: str):
    """Cập nhật trạng thái master image (Có khóa an toàn)"""
    if not script_path: return
    
    # Resolve đường dẫn trước khi sử dụng
    abs_path = _resolve_script_path(script_path)
    if not abs_path or not os.path.exists(abs_path):
        return
    
    # 🔥 Bọc khóa: Chỉ 1 người được vào đây tại 1 thời điểm
    with file_write_lock:
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            data["master_image_status"] = new_status
            
            # Reset timestamp để Frontend biết mà load lại
            import time
            data["last_updated"] = time.time()
            
            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[Master Gen] 💾 Đã cập nhật status: {new_status}")
        except Exception as e:
            print(f"❌ Lỗi update_master_image_status: {e}")

async def update_master_image_path(script_path: str, relative_path: str):
    """Cập nhật đường dẫn ảnh Master (Đã nâng cấp Async + Lock)"""
    if not script_path: return
    
    # Resolve đường dẫn trước khi sử dụng
    abs_path = _resolve_script_path(script_path)
    if not abs_path or not os.path.exists(abs_path):
        return
    
    # 🔥 Dùng Lock để an toàn tuyệt đối
    with file_write_lock:
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            data["master_image_url"] = relative_path
            data["master_image_status"] = "done"  # Đánh dấu thành công
            
            # Reset timestamp để Frontend biết mà load lại ảnh
            import time
            data["last_updated"] = time.time()

            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[Master Gen] 💾 Đã lưu đường dẫn ảnh vào JSON.")
        except Exception as e:
            print(f"❌ Lỗi update_master_image_path: {e}")


# [THÊM VÀO CUỐI FILE backend/services/nst_flow.py]

def force_reset_script_state(script_path: str) -> bool:
    """Hàm cứu hộ: Cưỡng ép reset trạng thái file về False"""
    try:
        if not script_path:
            return False

        # Resolve đường dẫn trước khi sử dụng
        abs_path = _resolve_script_path(script_path)
        if not abs_path or not os.path.exists(abs_path):
            print(f"[Unlock] ❌ Không tìm thấy file: {abs_path} (từ script_path: {script_path})")
            return False

        # 🔥 [FIX RACE CONDITION] Dùng lock để tránh xung đột
        with file_write_lock:
            # 2. Đọc file
            with open(abs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 3. Reset 2 biến trạng thái
            print(f"[Unlock] 🛠️ Đang reset trạng thái cho: {abs_path}")
            data["is_setting_up"] = False
            data["is_running"] = False
            data["is_retrying"] = False

            # 4. Ghi lại file
            with open(abs_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        return True
    except Exception as e:
        print(f"[Unlock] ❌ Lỗi khi reset file: {e}")
        return False


def force_reset_all_scripts() -> int:
    """Reset trạng thái TẤT CẢ file script trong storage. Trả về số file đã reset."""
    from pathlib import Path
    from utils.path_helper import PROJECTS_DIR
    count = 0
    for abs_path in Path(PROJECTS_DIR).rglob("scripts/*.json"):
        if not abs_path.is_file():
            continue
        try:
            with file_write_lock:
                with open(abs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data["is_setting_up"] = False
                data["is_running"] = False
                data["is_retrying"] = False
                with open(abs_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                count += 1
        except Exception as e:
            print(f"[Stop All] ⚠️ Không reset được {abs_path}: {e}")
    if count > 0:
        print(f"[Stop All] 🛠️ Đã reset {count} file script.")
    return count
"""
Module tạo video qua Veo3 API (Google Flow).
Tương tự control_creat_video.py nhưng dùng Veo3 thay vì Grok.
"""

import asyncio
import os
import json
import time
import uuid
from typing import Optional, List, Dict, Any
from pathlib import Path

# Import các module Veo3
from utils.veo3.browser_engine import (
    ensure_profiles_started,
    wait_for_profiles_ready_unified,
    get_ws_endpoint_for_profile,
)
from utils.veo3.flow_actions import (
    connect_and_get_page,
    goto_flow_and_open_project,
    cleanup_browser,
    setup_render_settings,
    select_mode,
    open_settings_and_select_batch,
    wait_for_project_ready,
)
from utils.veo3.veo_reference_video_api import (
    URL_GENERATE_REFERENCE_VIDEO,
    VIDEO_ASPECT_RATIO_LANDSCAPE,
    VIDEO_ASPECT_RATIO_PORTRAIT,
    build_payload_generate_reference_video,
    request_create_reference_video_via_browser,
    request_check_reference_status_via_browser,
    parse_operations_from_reference_response,
    extract_media_from_reference_status_op,
    select_reference_video_model_key,
)
from utils.veo3.veo_video_api_v3_1 import (
    poll_video_status_v3_1,
    download_video_from_encoded_v3_1,
    full_video_workflow_v3_1,
    parse_media_id_from_create_response,
)
from utils.veo3.veo_reference_image_api import (
    build_payload_upload_image,
    request_upload_image_via_browser,
    extract_media_id,
)
from utils.veo3_profile import (
    get_active_veo3_profiles,
    get_veo3_profile_by_name,
)
from utils.veo3.veo_get_token import (
    fetch_recaptcha_token_via_page,
    load_veo_auth_config,
    auto_collect_veo_auth_on_project_creation,
)
from utils.veo3.veo_refresh_token import (
    refresh_access_token_simple,
)
from utils.control_script import create_video_task, update_task_status

from utils.path_helper import BASE_DIR as _BASE, CONFIG_FILE, pstr

BASE_DIR = pstr(_BASE)
CONFIG_FILE_PATH = pstr(CONFIG_FILE)


def _veo3_is_cancelled(
    task_id: Optional[str] = None,
    cancel_event: Any = None,
) -> bool:
    """Hủy theo task_id (nút Hủy từng dòng) hoặc cancel_event (Hủy cả batch)."""
    tid = str(task_id or "").strip()
    if tid:
        try:
            from utils.control_creat_video_veo3_batch import is_video_task_cancelled

            if is_video_task_cancelled(tid):
                return True
        except Exception:
            pass
    if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
        return True
    return False


def _normalize_aspect_ratio(ratio: Optional[str]) -> str:
    """Chuẩn hóa tỷ lệ video sang format Veo3 API."""
    r = str(ratio or "").strip().lower().replace(" ", "").replace("/", ":")
    if r in ("16:9", "169"):
        return VIDEO_ASPECT_RATIO_LANDSCAPE
    if r in ("9:16", "916"):
        return VIDEO_ASPECT_RATIO_PORTRAIT
    # Veo3 chỉ hỗ trợ 16:9 và 9:16, fallback về landscape
    return VIDEO_ASPECT_RATIO_LANDSCAPE


def _resolve_veo3_output_file(
    out_path: str,
    *,
    scene_index: Optional[int] = None,
) -> str:
    """
    Batch truyền thư mục scenes (vd. .../video_1_scenes); API download cần file .mp4.
    """
    raw = str(out_path or "").strip()
    if not raw:
        raise ValueError("Missing out_path")
    if os.path.isdir(raw):
        os.makedirs(raw, exist_ok=True)
        if scene_index is not None:
            name = f"scene_{int(scene_index) + 1}.mp4"
        else:
            name = f"scene_{uuid.uuid4().hex[:8]}.mp4"
        return os.path.join(raw, name)
    _root, ext = os.path.splitext(raw)
    if not ext:
        parent = os.path.dirname(raw) or "."
        os.makedirs(parent, exist_ok=True)
        return raw + ".mp4"
    parent = os.path.dirname(os.path.abspath(raw))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return raw


async def create_video_veo3(
    context: Dict[str, Any],
    image_path: str,
    prompt: str,
    out_path: str,
    ratio: str = "16:9",
    duration: str = "6s",
    quality: str = "fast",
    task_id: Optional[str] = None,
    cancel_event: Optional[asyncio.Event] = None,
    profile_name: Optional[str] = None,
    account_type: str = "ULTRA",
    scene_index: Optional[int] = None,
    *,
    flow_page: Any = None,
    flow_auth: Optional[Dict[str, Any]] = None,
    ws_endpoint_external: Optional[str] = None,
    skip_flow_init: bool = False,
    skip_render_setup: bool = False,
    keep_session_open: bool = False,
    reference_image_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Tạo video qua Veo3 API.
    
    Args:
        context: Context chứa thông tin cấu hình (hiện tại không dùng, để tương thích)
        image_path: Đường dẫn ảnh đầu vào (reference image)
        prompt: Prompt mô tả video cần tạo
        out_path: Đường dẫn lưu video kết quả
        ratio: Tỷ lệ video (16:9, 9:16)
        duration: Độ dài video (6s, 10s) - hiện tại Veo3 API tự động
        quality: Chất lượng (fast, quality)
        task_id: ID của task (để cập nhật trạng thái)
        cancel_event: Event để hủy task
        profile_name: Tên profile cụ thể (nếu không có sẽ dùng profile đầu tiên)
        account_type: Loại tài khoản (NORMAL, PRO, ULTRA)
    
    Returns:
        Dict với thông tin kết quả: {"ok": True/False, "output": path, "error": ...}
    """
    page = flow_page
    ws_endpoint = ws_endpoint_external
    auth_data = dict(flow_auth) if isinstance(flow_auth, dict) else None
    resolved_out = _resolve_veo3_output_file(out_path, scene_index=scene_index)
    profile_id = profile_name or "default"
    frontend_model = quality if quality else "Veo 3.1 - Lite [Lower Priority]"

    def _check_cancel():
        return _veo3_is_cancelled(task_id, cancel_event)

    try:
        # 1. Kiểm tra cancel
        if _veo3_is_cancelled(task_id, cancel_event):
            raise asyncio.CancelledError("Task đã bị hủy")
        
        # 2. Kiểm tra file ảnh đầu vào (hỗ trợ nhiều ảnh tham chiếu)
        images_to_upload: List[str] = []
        if reference_image_paths and isinstance(reference_image_paths, list):
            images_to_upload = [
                p for p in reference_image_paths if p and os.path.exists(str(p))
            ]
        if not images_to_upload and image_path and os.path.exists(image_path):
            images_to_upload = [image_path]
        if not images_to_upload:
            raise ValueError("Không có ảnh tham chiếu hợp lệ để upload")

        if skip_flow_init and page is not None and auth_data:
            scene_no = (int(scene_index) + 1) if scene_index is not None else "?"
            print(f"[Veo3 Video] ♻️ Cảnh {scene_no}: tiếp tục session Flow (bỏ goto/setup lại)")
        else:
            skip_flow_init = False
        
        if not skip_flow_init:
            # 3. Lấy CDP port từ config
            config_path = CONFIG_FILE_PATH
            cdp_port = 9222
            try:
                if os.path.exists(config_path):
                    with open(config_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                        cdp_port = cfg.get('CDP_PORT', 9222)
            except Exception:
                pass
            
            ws_endpoint = f"http://127.0.0.1:{cdp_port}"
            print(f"[Veo3 Video] 🔌 CDP endpoint: {ws_endpoint}")
            
            # 4. Kết nối Playwright qua CDP
            print("[Veo3 Video] 🔌 Kết nối qua CDP...")
            page = await connect_and_get_page(ws_endpoint)
            if not page:
                raise ValueError("Không thể kết nối Playwright qua CDP")
            
            print("[Veo3 Video] ✅ Đã kết nối Playwright")
            
            # 5–6. Auth + mở project Flow (một lần mỗi phiên batch)
            auth_data = load_veo_auth_config(profile_id)
            if not auth_data or not all([
                auth_data.get("sessionId"),
                auth_data.get("projectId"),
                auth_data.get("access_token"),
            ]):
                print("[Veo3 Video] ⚠️ Không tìm thấy auth, bắt đầu setup flow...")
                if _veo3_is_cancelled(task_id, cancel_event):
                    raise asyncio.CancelledError("Task đã bị hủy")
                auth_data = await auto_collect_veo_auth_on_project_creation(
                    page,
                    profile_id=profile_id,
                    flow_url="https://labs.google/fx/vi/tools/flow",
                    timeout_s=60,
                    stop_check=_check_cancel,
                )
                if not auth_data:
                    raise ValueError("Không thể trích xuất auth từ Flow")
                print("[Veo3 Video] ✅ Đã trích xuất và lưu auth")
            else:
                print("[Veo3 Video] ✅ Đã load auth từ veo_auth.json")
                session_id = auth_data.get("sessionId")
                project_id = auth_data.get("projectId")
                access_token = auth_data.get("access_token")
                if not all([session_id, project_id, access_token]):
                    raise ValueError("Thiếu sessionId, projectId hoặc access_token trong auth_data")
                if _veo3_is_cancelled(task_id, cancel_event):
                    raise asyncio.CancelledError("Task đã bị hủy")
                project_url = auth_data.get("project_url") or "https://labs.google/fx/vi/tools/flow"
                print(f"[Veo3 Video] 🌐 Điều hướng tới project: {project_url}")
                try:
                    await page.goto(project_url, wait_until="domcontentloaded", timeout=30_000)
                    print("[Veo3 Video] ✅ Navigate thành công")
                except Exception as nav_error:
                    current_url = page.url
                    print(f"[Veo3 Video] ⚠️ Navigate failed: {nav_error}")
                    print(f"[Veo3 Video] 📍 Current URL: {current_url}")
                    if "flow" in current_url.lower() and "project" in current_url.lower():
                        print("[Veo3 Video] ✅ Page đã ở Flow project, bỏ qua lỗi navigate")
                    else:
                        raise
                print("[Veo3 Video] 🔄 Refresh access_token và cookie...")
                refresh_result = await refresh_access_token_simple(
                    page,
                    old_session_id=session_id,
                    old_project_id=project_id,
                    timeout_seconds=30,
                )
                if refresh_result.get("success"):
                    auth_data["access_token"] = refresh_result["access_token"]
                    auth_data["cookie"] = refresh_result["cookie"]
                    from utils.veo3.veo_get_token import save_veo_auth_config
                    save_veo_auth_config(profile_id, auth_data)
                    print("[Veo3 Video] ✅ Đã refresh và lưu token mới")
                else:
                    print(f"[Veo3 Video] ⚠️ Refresh token failed: {refresh_result.get('error')}, dùng token cũ")
                await wait_for_project_ready(page)
                await open_settings_and_select_batch(page)
                print("[Veo3 Video] ✅ Đã mở project Flow và setup batch tab")
        elif not auth_data or not all([
            auth_data.get("sessionId"),
            auth_data.get("projectId"),
            auth_data.get("access_token"),
        ]):
            raise ValueError("Session Flow không hợp lệ khi tái sử dụng phiên")
        
        # 7. Setup UI: mode Video + tỉ lệ/model (chỉ cảnh đầu hoặc khi đổi cấu hình)
        if _veo3_is_cancelled(task_id, cancel_event):
            raise asyncio.CancelledError("Task đã bị hủy")

        if not skip_render_setup:
            print("[Veo3 Video] ⚙️ Setup: Chọn mode Video...")
            ok = await select_mode(page, "video", stop_check=_check_cancel)
            if not ok:
                raise ValueError("Chọn mode Video thất bại")
            
            await asyncio.sleep(0.5)
            
            print(f"[Veo3 Video] 🔍 DEBUG: quality parameter nhận từ frontend: '{quality}'")
            print(f"[Veo3 Video] 🔍 DEBUG: frontend_model sẽ chọn: '{frontend_model}'")
            print(f"[Veo3 Video] ⚙️ Setup: Chọn tỉ lệ {ratio}, model '{frontend_model}'...")
            
            settings_ok = await setup_render_settings(
                page,
                output_count=1,
                aspect_ratio=ratio,
                model=frontend_model,
                select_ingredients=False,
                mode="video",
            )
            
            print(f"[Veo3 Video] 🔍 DEBUG: setup_render_settings returned: {settings_ok}")
            
            if not settings_ok:
                raise ValueError("Setup render settings thất bại")
            
            print("[Veo3 Video] ✅ Đã setup đầy đủ")
        else:
            print("[Veo3 Video] ♻️ Bỏ qua setup mode/ratio/model (cùng phiên Flow)")
        
        # 8. Upload ảnh tham chiếu (bắt buộc cho video)
        if _veo3_is_cancelled(task_id, cancel_event):
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print(f"[Veo3 Video] 📤 Upload {len(images_to_upload)} ảnh tham chiếu...")
        
        # Lấy thông tin từ auth_data
        session_id = auth_data.get("sessionId")
        project_id = auth_data.get("projectId")
        access_token = auth_data.get("access_token")
        
        if not all([session_id, project_id, access_token]):
            raise ValueError("Thiếu sessionId, projectId hoặc access_token")
        
        reference_media_ids: List[str] = []
        for up_idx, img_path in enumerate(images_to_upload):
            if _veo3_is_cancelled(task_id, cancel_event):
                raise asyncio.CancelledError("Task đã bị hủy")
            print(
                f"[Veo3 Video] 📤 [{up_idx + 1}/{len(images_to_upload)}] "
                f"Upload: {os.path.basename(img_path)}"
            )
            upload_payload = build_payload_upload_image(
                image_path=img_path,
                project_id=project_id,
            )
            upload_response = await request_upload_image_via_browser(
                page,
                upload_payload,
                access_token,
                timeout_ms=60_000,
            )
            if not upload_response.get("ok"):
                error_msg = upload_response.get("error", "Unknown error")
                response_body = upload_response.get("body", "")
                response_status = upload_response.get("status", "")
                print(
                    f"[Veo3 Video] ❌ Upload failed - Status: {response_status}, "
                    f"Body: {response_body[:500]}"
                )
                raise ValueError(
                    f"Upload ảnh tham chiếu thất bại: {error_msg} | Status: {response_status}"
                )
            body = str(upload_response.get("body") or "")
            media_id = extract_media_id(body)
            if not media_id:
                raise ValueError("Upload OK nhưng không parse được mediaId")
            reference_media_ids.append(media_id)
            print(f"[Veo3 Video] ✅ Upload thành công, mediaId: {media_id}")

        if not reference_media_ids:
            raise ValueError("Không upload được ảnh tham chiếu nào")
        
        # 9. Gửi prompt "a" và bắt recaptcha token (SAU KHI UPLOAD XONG)
        if _veo3_is_cancelled(task_id, cancel_event):
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print(f"[Veo3 Video] 🎬 Tạo video với prompt: {prompt[:100]}...")
        
        print(f"[Veo3 Video] 🎯 Gửi prompt 'a' và đợi bắt recaptcha token...")
        
        # Gọi fetch_recaptcha_token_via_page - hàm này sẽ tự động:
        # 1. Setup listeners để bắt token
        # 2. Gửi prompt "a" vào input và nhấn Enter
        # 3. Đợi bắt token từ /recaptcha/enterprise/reload
        # 4. Trả về token
        recaptcha_token = await fetch_recaptcha_token_via_page(
            page,
            prompt_for_token="a",
            timeout=30,
            stop_check=_check_cancel,
        )
        
        if not recaptcha_token:
            raise ValueError("Không thể lấy recaptcha token")
        
        print(f"[Veo3 Video] ✅ Đã bắt được recaptcha token: {len(recaptcha_token)} ký tự")
        print(f"[Veo3 Video] 📋 Token (full): {recaptcha_token}")
        
        # 10. Tạo payload generate reference video (image-to-video)
        aspect_ratio = _normalize_aspect_ratio(ratio)
        
        # Select video model key
        video_model_key = select_reference_video_model_key(
            aspect_ratio=aspect_ratio,
            frontend_model_label=frontend_model,
            account_type=account_type,
        )
        print(f"[Veo3 Video] 🔑 API video_model_key: {video_model_key} (UI model: {frontend_model})")

        video_payload = build_payload_generate_reference_video(
            prompt=prompt,
            session_id=session_id,
            project_id=project_id,
            recaptcha_token=recaptcha_token,
            seed=None,
            video_model_key=video_model_key,
            aspect_ratio=aspect_ratio,
            output_count=1,
            account_type=account_type,
            reference_media_ids=reference_media_ids,
        )
        
        # 11. Gửi request tạo reference video
        print(f"[Veo3 Video] 📡 Gửi request tạo reference video (image-to-video)...")
        print(f"[Veo3 Video] 🔍 DEBUG: Payload keys: {list(video_payload.keys())}")
        
        create_response = await request_create_reference_video_via_browser(
            page,
            video_payload,
            access_token,
        )
        
        print(f"[Veo3 Video] 📥 Response status: {create_response.get('status')}")
        
        if not create_response.get("ok"):
            error_msg = create_response.get("error", f"HTTP {create_response.get('status')}")
            response_body = create_response.get("body", "")
            print(f"[Veo3 Video] ❌ Response body: {response_body}")
            raise ValueError(f"Tạo video thất bại: {error_msg} | Body: {response_body[:500]}")
        
        # 12. Parse mediaId từ response (FORMAT MỚI v3.1+)
        body = create_response.get("body", "")
        
        # 🔍 LOG FULL RESPONSE để debug
        print(f"[Veo3 Video] 🔍 DEBUG: Full response body:")
        print(body)
        try:
            body_json = json.loads(body)
            print(f"[Veo3 Video] 🔍 DEBUG: Response JSON keys: {list(body_json.keys())}")
            print(f"[Veo3 Video] 🔍 DEBUG: Full JSON structure:")
            print(json.dumps(body_json, indent=2, ensure_ascii=False))
        except Exception as parse_err:
            print(f"[Veo3 Video] ⚠️ Không parse được JSON: {parse_err}")
        
        # Parse mediaId từ response format mới (media array)
        media_id = parse_media_id_from_create_response(body)
        
        if not media_id:
            raise ValueError("API trả về thành công nhưng không parse được mediaId từ response")
        
        print(f"[Veo3 Video] ✅ Đã tạo video, media_id: {media_id}")
        
        # 13. Sử dụng workflow mới v3.1+ để poll status và download
        print(f"[Veo3 Video] 🔄 Bắt đầu poll status và download video (format mới v3.1+)...")
        
        from utils.runtime_paths import get_ffmpeg_exe

        ffmpeg_path = get_ffmpeg_exe()
        try:
            config_path = CONFIG_FILE_PATH
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    custom = str(cfg.get('FFMPEG_PATH') or '').strip()
                    if custom:
                        ffmpeg_path = custom
        except Exception:
            pass
        
        # Chạy full workflow v3.1+
        workflow_result = await full_video_workflow_v3_1(
            page=page,
            media_id=media_id,
            project_id=project_id,
            access_token=access_token,
            output_path=resolved_out,
            ffmpeg_path=ffmpeg_path,
            timeout_seconds=420,  # 7 phút
            cancel_check=_check_cancel,
        )
        
        if not workflow_result.get("success"):
            if workflow_result.get("status") == "CANCELLED":
                raise asyncio.CancelledError("Task đã bị hủy")
            error_msg = workflow_result.get("error", "Unknown error")
            raise ValueError(f"Download video thất bại: {error_msg}")
        
        print(f"[Veo3 Video] ✅ Đã lưu video: {workflow_result.get('video_path')}")
        if workflow_result.get("thumbnail_path"):
            print(f"[Veo3 Video] 🖼️ Đã tạo thumbnail: {workflow_result.get('thumbnail_path')}")
        
        saved = str(workflow_result.get("video_path") or resolved_out)
        return {
            "ok": True,
            "output": saved,
            "flow_page": page,
            "flow_auth": auth_data,
            "ws_endpoint": ws_endpoint,
        }
        
    except asyncio.CancelledError:
        print("[Veo3 Video] ⚠️ Task đã bị hủy")
        if task_id:
            update_task_status(task_id, "cancelled", error="Đã hủy")
        raise
    
    except Exception as e:
        print(f"[Veo3 Video] ❌ Lỗi: {e}")
        return {
            "ok": False,
            "error": str(e),
        }
    
    finally:
        if not keep_session_open and page and ws_endpoint:
            try:
                await cleanup_browser(ws_endpoint)
            except Exception as e:
                print(f"[Veo3 Video] ⚠️ Lỗi cleanup: {e}")


async def run_video_tasks_veo3(
    context: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    max_tabs: int = 2,
    cancel_event: Optional[asyncio.Event] = None,
) -> List[Any]:
    """
    Chạy nhiều task tạo video Veo3 TUẦN TỰ (không song song).
    Setup 1 lần đầu, sau đó mỗi video: upload → captcha → tạo → đợi xong → video tiếp.
    
    Args:
        context: Context chứa thông tin cấu hình
        tasks: Danh sách tasks, mỗi task có format:
            {
                "image_path": "path/to/image.png",
                "prompt": "...",
                "out": "path/to/output.mp4",
                "ratio": "16:9",
                "duration": "6s",
                "quality": "fast",
                "task_id": "uuid" (optional),
                "profile_name": "profile1" (optional),
                "account_type": "ULTRA" (optional),
            }
        max_tabs: Không dùng (để tương thích)
        cancel_event: Event để hủy tất cả tasks
    
    Returns:
        List kết quả của từng task
    """
    if not tasks:
        return []
    
    results = []
    page = None
    ws_endpoint = None
    auth_data = None
    
    try:
        # 1. Lấy CDP port từ config
        config_path = CONFIG_FILE_PATH
        cdp_port = 9222
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    cdp_port = cfg.get('CDP_PORT', 9222)
        except Exception:
            pass
        
        ws_endpoint = f"http://127.0.0.1:{cdp_port}"
        print(f"[Veo3 Video Batch] 🔌 CDP endpoint: {ws_endpoint}")
        
        # 2. Kết nối Playwright qua CDP (1 lần duy nhất)
        print("[Veo3 Video Batch] 🔌 Kết nối qua CDP...")
        page = await connect_and_get_page(ws_endpoint)
        if not page:
            raise ValueError("Không thể kết nối Playwright qua CDP")
        
        print("[Veo3 Video Batch] ✅ Đã kết nối Playwright")
        
        # 3. Load auth (1 lần duy nhất)
        profile_id = tasks[0].get("profile_name") or "default"
        auth_data = load_veo_auth_config(profile_id)
        
        if not auth_data or not all([
            auth_data.get("sessionId"),
            auth_data.get("projectId"),
            auth_data.get("access_token")
        ]):
            print("[Veo3 Video Batch] ⚠️ Không tìm thấy auth, bắt đầu setup flow...")
            
            def _check_cancel_batch():
                return _veo3_is_cancelled(None, cancel_event)
            
            auth_data = await auto_collect_veo_auth_on_project_creation(
                page,
                profile_id=profile_id,
                flow_url="https://labs.google/fx/vi/tools/flow",
                timeout_s=60,
                stop_check=_check_cancel_batch,
            )
            
            if not auth_data:
                raise ValueError("Không thể trích xuất auth từ Flow")
            
            print("[Veo3 Video Batch] ✅ Đã trích xuất và lưu auth")
        else:
            print("[Veo3 Video Batch] ✅ Đã load auth từ veo_auth.json")
            
            # Lấy thông tin auth TRƯỚC KHI dùng
            session_id = auth_data.get("sessionId")
            project_id = auth_data.get("projectId")
            access_token = auth_data.get("access_token")
            
            if not all([session_id, project_id, access_token]):
                raise ValueError("Thiếu sessionId, projectId hoặc access_token trong auth_data")
            
            # Navigate tới project
            project_url = auth_data.get("project_url") or "https://labs.google/fx/vi/tools/flow"
            print(f"[Veo3 Video Batch] 🌐 Điều hướng tới project: {project_url}")
            
            try:
                await page.goto(project_url, wait_until="domcontentloaded", timeout=30_000)
                print(f"[Veo3 Video Batch] ✅ Navigate thành công")
            except Exception as nav_error:
                current_url = page.url
                print(f"[Veo3 Video Batch] ⚠️ Navigate failed: {nav_error}")
                print(f"[Veo3 Video Batch] 📍 Current URL: {current_url}")
                if "flow" in current_url.lower() and "project" in current_url.lower():
                    print(f"[Veo3 Video Batch] ✅ Page đã ở Flow project, bỏ qua lỗi navigate")
                else:
                    raise
            
            # Refresh access_token và cookie MỚI sau khi goto Flow
            print("[Veo3 Video Batch] 🔄 Refresh access_token và cookie...")
            refresh_result = await refresh_access_token_simple(
                page,
                old_session_id=session_id,
                old_project_id=project_id,
                timeout_seconds=30
            )
            
            if refresh_result.get("success"):
                # Cập nhật auth_data với token và cookie mới
                auth_data["access_token"] = refresh_result["access_token"]
                auth_data["cookie"] = refresh_result["cookie"]
                access_token = refresh_result["access_token"]
                
                # Lưu lại vào file
                from utils.veo3.veo_get_token import save_veo_auth_config
                save_veo_auth_config(profile_id, auth_data)
                print("[Veo3 Video Batch] ✅ Đã refresh và lưu token mới")
            else:
                print(f"[Veo3 Video Batch] ⚠️ Refresh token failed: {refresh_result.get('error')}, dùng token cũ")
            
            await wait_for_project_ready(page)
            await open_settings_and_select_batch(page)
            print("[Veo3 Video Batch] ✅ Đã mở project Flow và setup batch tab")
        
        # 4. Setup mode Video (1 lần duy nhất)
        print("[Veo3 Video Batch] ⚙️ Setup: Chọn mode Video...")
        
        def _check_cancel_batch():
            return _veo3_is_cancelled(None, cancel_event)
        
        ok = await select_mode(page, "video", stop_check=_check_cancel_batch)
        if not ok:
            raise ValueError("Chọn mode Video thất bại")
        
        await asyncio.sleep(0.5)
        
        # Lấy thông tin chung (đã được extract ở trên trong else block)
        # Nếu đến từ auto_collect thì extract ở đây
        if not all([
            auth_data.get("sessionId"),
            auth_data.get("projectId"),
            auth_data.get("access_token")
        ]):
            raise ValueError("Thiếu sessionId, projectId hoặc access_token")
        
        session_id = auth_data.get("sessionId")
        project_id = auth_data.get("projectId")
        access_token = auth_data.get("access_token")
        
        # 5. Chạy từng video tuần tự
        for idx, task in enumerate(tasks, 1):
            task_id = str(task.get("task_id") or "").strip()
            if _veo3_is_cancelled(task_id, cancel_event):
                raise asyncio.CancelledError("Task đã bị hủy")
            
            if not task_id:
                task_name = f"Tạo video Veo3: {os.path.basename(task['out'])}"
                task_id = create_video_task(task_name, "Veo3")
            
            print(f"\n[Veo3 Video Batch] 🎬 === VIDEO {idx}/{len(tasks)} ===")
            
            try:
                if _veo3_is_cancelled(task_id, cancel_event):
                    raise asyncio.CancelledError("Task đã bị hủy")

                def _scene_cancel():
                    return _veo3_is_cancelled(task_id, cancel_event)

                # Lấy thông tin task
                image_path = task["image_path"]
                prompt = task["prompt"]
                out_path = task["out"]
                ratio = task.get("ratio", "16:9")
                quality = task.get("quality", "fast")
                account_type = task.get("account_type", "ULTRA")
                
                # Setup render settings cho video này
                frontend_model = quality if quality else "Veo 3.1 - Lite [Lower Priority]"
                
                print(f"[Veo3 Video Batch] ⚙️ Setup: Chọn tỉ lệ {ratio}, model '{frontend_model}'...")
                
                settings_ok = await setup_render_settings(
                    page,
                    output_count=1,
                    aspect_ratio=ratio,
                    model=frontend_model,
                    select_ingredients=False,
                    mode="video",
                )
                
                if not settings_ok:
                    raise ValueError("Setup render settings thất bại")
                
                print(f"[Veo3 Video Batch] ✅ Đã setup")
                
                # Upload ảnh
                print(f"[Veo3 Video Batch] 📤 Upload ảnh: {image_path}")
                
                # Upload ảnh qua API giống bên tạo ảnh
                upload_payload = build_payload_upload_image(
                    image_path=image_path,
                    project_id=project_id,
                )
                
                upload_response = await request_upload_image_via_browser(
                    page,
                    upload_payload,
                    access_token,
                    timeout_ms=60_000,
                )
                
                if not upload_response.get("ok"):
                    error_msg = upload_response.get("error", "Unknown error")
                    raise ValueError(f"Upload ảnh thất bại: {error_msg}")
                
                body = str(upload_response.get("body") or "")
                reference_media_id = extract_media_id(body)
                
                if not reference_media_id:
                    raise ValueError("Upload OK nhưng không parse được mediaId")
                
                print(f"[Veo3 Video Batch] ✅ Upload thành công, mediaId: {reference_media_id}")
                
                # Bắt recaptcha token
                print(f"[Veo3 Video Batch] 🎯 Gửi prompt 'a' và bắt recaptcha token...")
                
                recaptcha_token = await fetch_recaptcha_token_via_page(
                    page,
                    prompt_for_token="a",
                    timeout=30,
                    stop_check=_scene_cancel,
                )
                
                if not recaptcha_token:
                    raise ValueError("Không thể lấy recaptcha token")
                
                print(f"[Veo3 Video Batch] ✅ Đã bắt token: {len(recaptcha_token)} ký tự")
                
                if _scene_cancel():
                    raise asyncio.CancelledError("Task đã bị hủy")

                # Tạo video
                aspect_ratio = _normalize_aspect_ratio(ratio)
                
                # Select video model key
                video_model_key = select_reference_video_model_key(
                    aspect_ratio=aspect_ratio,
                    frontend_model_label=frontend_model,
                    account_type=account_type,
                )
                
                video_payload = build_payload_generate_reference_video(
                    prompt=prompt,
                    session_id=session_id,
                    project_id=project_id,
                    recaptcha_token=recaptcha_token,
                    seed=None,
                    video_model_key=video_model_key,
                    aspect_ratio=aspect_ratio,
                    output_count=1,
                    account_type=account_type,
                    reference_media_ids=[reference_media_id],
                )
                
                print(f"[Veo3 Video Batch] 📡 Gửi request tạo video...")
                
                create_response = await request_create_reference_video_via_browser(
                    page,
                    video_payload,
                    access_token,
                )
                
                if not create_response.get("ok"):
                    error_msg = create_response.get("error", f"HTTP {create_response.get('status')}")
                    response_body = create_response.get("body", "")
                    print(f"[Veo3 Video Batch] ❌ Response body: {response_body}")
                    raise ValueError(f"Tạo video thất bại: {error_msg}")
                
                # Parse mediaId từ response (FORMAT MỚI v3.1+)
                body = create_response.get("body", "")
                
                # 🔍 LOG FULL RESPONSE để debug
                print(f"[Veo3 Video Batch] 🔍 DEBUG: Full response body for video {idx}:")
                print(body)
                
                try:
                    body_json = json.loads(body)
                    print(f"[Veo3 Video Batch] 🔍 DEBUG: Response JSON keys: {list(body_json.keys())}")
                except Exception as parse_err:
                    raise ValueError(f"Không parse được response JSON: {parse_err}")
                
                # Parse mediaId từ response format mới (media array)
                media_id = parse_media_id_from_create_response(body)
                
                if not media_id:
                    raise ValueError("API trả về thành công nhưng không parse được mediaId từ response")
                
                print(f"[Veo3 Video Batch] ✅ Đã tạo video {idx}, media_id: {media_id}")
                
                # Sử dụng workflow mới v3.1+ để poll status và download (KHÔNG TẠO THUMBNAIL)
                print(f"[Veo3 Video Batch] 🔄 Bắt đầu poll status và download video {idx} (format mới v3.1+)...")
                
                # Chạy full workflow v3.1+ (không cần ffmpeg path vì bỏ thumbnail)
                workflow_result = await full_video_workflow_v3_1(
                    page=page,
                    media_id=media_id,
                    project_id=project_id,
                    access_token=access_token,
                    output_path=out_path,
                    ffmpeg_path=None,  # Bỏ thumbnail
                    timeout_seconds=420,  # 7 phút
                    cancel_check=_scene_cancel,
                )
                
                if not workflow_result.get("success"):
                    if workflow_result.get("status") == "CANCELLED":
                        raise asyncio.CancelledError("Task đã bị hủy")
                    error_msg = workflow_result.get("error", "Unknown error")
                    raise ValueError(f"Download video thất bại: {error_msg}")
                
                print(f"[Veo3 Video Batch] ✅ Đã lưu video {idx}: {workflow_result.get('video_path')}")
                
                update_task_status(task_id, "completed", result_file=out_path)
                results.append({"ok": True, "output": out_path})
                
            except asyncio.CancelledError:
                update_task_status(task_id, "cancelled", error="Đã hủy")
                results.append({"ok": False, "error": "Đã hủy"})
                raise
            except Exception as e:
                print(f"[Veo3 Video Batch] ❌ Lỗi video {idx}: {e}")
                update_task_status(task_id, "failed", error=str(e))
                results.append({"ok": False, "error": str(e)})
        
        return results
        
    except asyncio.CancelledError:
        print("[Veo3 Video Batch] ⚠️ Batch đã bị hủy")
        raise
    except Exception as e:
        print(f"[Veo3 Video Batch] ❌ Lỗi batch: {e}")
        return results if results else [{"ok": False, "error": str(e)}]
    finally:
        if page and ws_endpoint:
            try:
                await cleanup_browser(ws_endpoint)
            except Exception as e:
                print(f"[Veo3 Video Batch] ⚠️ Lỗi cleanup: {e}")

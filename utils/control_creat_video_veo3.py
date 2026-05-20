"""
Module tạo video qua Veo3 API (Google Flow).
Tương tự control_creat_video.py nhưng dùng Veo3 thay vì Grok.
"""

import asyncio
import os
import json
import time
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
)
from utils.veo3.veo_video_api import (
    URL_GENERATE_TEXT_TO_VIDEO,
    VIDEO_ASPECT_RATIO_LANDSCAPE,
    VIDEO_ASPECT_RATIO_PORTRAIT,
    build_text_to_video_payload,
    request_create_video_via_browser,
    request_check_status_via_browser,
    parse_operations_from_create_response,
    extract_media_from_status_op,
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
)
from utils.control_script import create_video_task, update_task_status

import sys
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _normalize_aspect_ratio(ratio: Optional[str]) -> str:
    """Chuẩn hóa tỷ lệ video sang format Veo3 API."""
    r = str(ratio or "").strip().lower().replace(" ", "").replace("/", ":")
    if r in ("16:9", "169"):
        return VIDEO_ASPECT_RATIO_LANDSCAPE
    if r in ("9:16", "916"):
        return VIDEO_ASPECT_RATIO_PORTRAIT
    # Veo3 chỉ hỗ trợ 16:9 và 9:16, fallback về landscape
    return VIDEO_ASPECT_RATIO_LANDSCAPE


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
    page = None
    ws_endpoint = None
    
    try:
        # 1. Kiểm tra cancel
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        # 2. Kiểm tra file ảnh đầu vào
        if not image_path or not os.path.exists(image_path):
            raise ValueError(f"Ảnh đầu vào không tồn tại: {image_path}")
        
        # 3. Lấy profile từ config
        if profile_name:
            profile = get_veo3_profile_by_name(profile_name)
            if not profile:
                raise ValueError(f"Không tìm thấy profile: {profile_name}")
        else:
            profiles = get_active_veo3_profiles()
            if not profiles:
                raise ValueError("Không có profile Veo3 nào được cấu hình")
            profile = profiles[0]
        
        print(f"[Veo3 Video] 🎬 Sử dụng profile: {profile.get('name', 'unknown')}")
        
        # 4. Lấy thông tin auth từ profile
        session_id = profile.get("sessionId", "")
        project_id = profile.get("projectId", "")
        access_token = profile.get("access_token", "")
        project_url = profile.get("project_url", "")
        
        if not all([session_id, project_id, access_token]):
            raise ValueError("Profile thiếu thông tin auth (sessionId, projectId, access_token)")
        
        # 5. Kết nối qua CDP (dùng chính Chrome đã mở của Grok)
        print("[Veo3 Video] 🔌 Kết nối qua CDP...")
        
        # Lấy CDP port từ config
        import json
        config_path = os.path.join(BASE_DIR, 'config', 'config.json')
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
        
        # Kết nối Playwright qua CDP
        page = await connect_and_get_page(ws_endpoint)
        if not page:
            raise ValueError("Không thể kết nối Playwright qua CDP")
        
        print("[Veo3 Video] ✅ Đã kết nối Playwright")
        
        # 8. Điều hướng tới Flow và mở project
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print("[Veo3 Video] 🌐 Điều hướng tới Google Flow...")
        flow_url = project_url or "https://labs.google/fx/vi/tools/flow"
        
        def _check_cancel():
            return cancel_event and cancel_event.is_set()
        
        await goto_flow_and_open_project(
            page,
            flow_url=flow_url,
            stop_check=_check_cancel if cancel_event else None,
        )
        
        print("[Veo3 Video] ✅ Đã mở project Flow")
        
        # 9. Upload ảnh tham chiếu (bắt buộc cho video)
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print(f"[Veo3 Video] 📤 Upload ảnh tham chiếu: {image_path}")
        
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
            raise ValueError(f"Upload ảnh tham chiếu thất bại: {error_msg}")
        
        body = upload_response.get("body", "")
        reference_media_id = extract_media_id(body)
        
        if not reference_media_id:
            raise ValueError("Upload OK nhưng không parse được mediaId")
        
        print(f"[Veo3 Video] ✅ Upload thành công, mediaId: {reference_media_id}")
        
        # 10. Tạo payload generate video
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print(f"[Veo3 Video] 🎬 Tạo video với prompt: {prompt[:100]}...")
        
        aspect_ratio = _normalize_aspect_ratio(ratio)
        
        # Lấy recaptcha token từ browser bằng cách gửi prompt "a"
        print(f"[Veo3 Video] 📝 Gửi prompt 'a' để lấy recaptcha token...")
        recaptcha_token = await fetch_recaptcha_token_via_page(
            page,
            prompt_for_token="a",
            timeout=30,
            stabilize_seconds=3,
        )
        
        if not recaptcha_token:
            print("[Veo3 Video] ⚠️ Không lấy được recaptcha token, tiếp tục với token rỗng...")
            recaptcha_token = ""
        else:
            print(f"[Veo3 Video] ✅ Đã lấy recaptcha token: {recaptcha_token[:50]}...")
        
        # Map quality sang frontend_model - giữ nguyên giá trị từ frontend
        # Frontend gửi đầy đủ tên model: "Veo 3.1 - Fast", "Veo 3.1 - Lite", etc.
        frontend_model = quality if quality else "Veo 3.1 - Lite [Lower Priority]"
        
        video_payload = build_text_to_video_payload(
            prompt=prompt,
            session_id=session_id,
            project_id=project_id,
            recaptcha_token=recaptcha_token,
            frontend_model=frontend_model,
            aspect_ratio=aspect_ratio,
            output_count=1,
            account_type=account_type,
            reference_media_ids=[reference_media_id],
        )
        
        # 11. Gửi request tạo video (async)
        print(f"[Veo3 Video] 📡 Gửi request tạo video...")
        
        create_response = await request_create_video_via_browser(
            page,
            URL_GENERATE_TEXT_TO_VIDEO,
            video_payload,
            access_token,
        )
        
        if not create_response.get("ok"):
            error_msg = create_response.get("error", f"HTTP {create_response.get('status')}")
            raise ValueError(f"Tạo video thất bại: {error_msg}")
        
        # 12. Parse operations từ response
        body = create_response.get("body", "")
        operations = parse_operations_from_create_response(body)
        
        if not operations:
            raise ValueError("API trả về thành công nhưng không có operation nào")
        
        print(f"[Veo3 Video] ⏳ Đang xử lý {len(operations)} operation(s)...")
        
        # 13. Poll status cho đến khi video hoàn thành
        operation_names = []
        for op in operations:
            op_dict = op.get("operation", {}) if isinstance(op.get("operation"), dict) else {}
            op_name = op_dict.get("name", "")
            if op_name:
                operation_names.append(op_name)
        
        if not operation_names:
            raise ValueError("Không tìm thấy operation name để poll status")
        
        print(f"[Veo3 Video] 🔄 Polling status cho operation: {operation_names[0]}")
        
        # Poll status với timeout
        max_poll_time = 300  # 5 phút
        poll_interval = 5  # 5 giây
        start_time = time.time()
        video_url = None
        
        while time.time() - start_time < max_poll_time:
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Task đã bị hủy")
            
            # Tạo payload check status
            status_payload = {
                "clientContext": {
                    "sessionId": session_id,
                    "projectId": project_id,
                    "tool": "PINHOLE",
                },
                "operations": [{"name": name} for name in operation_names],
            }
            
            status_response = await request_check_status_via_browser(
                page,
                status_payload,
                access_token,
            )
            
            if not status_response.get("ok"):
                print(f"[Veo3 Video] ⚠️ Check status failed: {status_response.get('error')}")
                await asyncio.sleep(poll_interval)
                continue
            
            # Parse status response
            status_body = status_response.get("body", "")
            try:
                status_json = json.loads(status_body)
                ops = status_json.get("operations", [])
                
                if ops:
                    op = ops[0]
                    # Kiểm tra xem operation đã done chưa
                    operation_dict = op.get("operation", {}) if isinstance(op.get("operation"), dict) else {}
                    done = operation_dict.get("done", False)
                    
                    if done:
                        # Extract video URL
                        video_url, _ = extract_media_from_status_op(op)
                        if video_url:
                            print(f"[Veo3 Video] ✅ Video đã hoàn thành!")
                            break
                        else:
                            # Check for error
                            error = operation_dict.get("error", {})
                            if error:
                                error_msg = error.get("message", "Unknown error")
                                raise ValueError(f"Video generation failed: {error_msg}")
                    else:
                        # Vẫn đang xử lý
                        elapsed = int(time.time() - start_time)
                        print(f"[Veo3 Video] ⏳ Đang xử lý... ({elapsed}s)")
            except json.JSONDecodeError:
                print(f"[Veo3 Video] ⚠️ Không parse được status response")
            
            await asyncio.sleep(poll_interval)
        
        if not video_url:
            raise ValueError("Timeout: Video không hoàn thành sau 5 phút")
        
        # 14. Download video
        print(f"[Veo3 Video] 📥 Download video từ: {video_url}")
        
        # Download video qua requests
        import requests
        response = requests.get(video_url, timeout=60)
        response.raise_for_status()
        
        # Lưu video
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(response.content)
        
        print(f"[Veo3 Video] ✅ Đã lưu video: {out_path}")
        
        return {
            "ok": True,
            "output": out_path,
        }
        
    except asyncio.CancelledError:
        print("[Veo3 Video] ⚠️ Task đã bị hủy")
        raise
    
    except Exception as e:
        print(f"[Veo3 Video] ❌ Lỗi: {e}")
        return {
            "ok": False,
            "error": str(e),
        }
    
    finally:
        # Cleanup
        if page and ws_endpoint:
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
    Chạy nhiều task tạo video Veo3 song song.
    
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
        max_tabs: Số lượng task chạy song song tối đa
        cancel_event: Event để hủy tất cả tasks
    
    Returns:
        List kết quả của từng task
    """
    jobs = []
    
    try:
        max_tabs = int(max_tabs)
    except Exception:
        max_tabs = 2
    if max_tabs < 1:
        max_tabs = 1
    
    sem = asyncio.Semaphore(max_tabs)
    
    for task in tasks:
        async def _run_one(t=task):
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError()
            
            task_id = str((t or {}).get("task_id") or "").strip()
            if not task_id:
                task_name = f"Tạo video Veo3: {os.path.basename(t['out'])}"
                task_id = create_video_task(task_name, "Veo3")
            
            async with sem:
                try:
                    if cancel_event and cancel_event.is_set():
                        raise asyncio.CancelledError()
                    
                    result = await create_video_veo3(
                        context=context,
                        image_path=t["image_path"],
                        prompt=t["prompt"],
                        out_path=t["out"],
                        ratio=t.get("ratio", "16:9"),
                        duration=t.get("duration", "6s"),
                        quality=t.get("quality", "fast"),
                        task_id=task_id,
                        cancel_event=cancel_event,
                        profile_name=t.get("profile_name"),
                        account_type=t.get("account_type", "ULTRA"),
                    )
                    
                    if result.get("ok"):
                        update_task_status(task_id, "completed", result_file=t["out"])
                    else:
                        update_task_status(task_id, "failed", error=result.get("error"))
                    
                    return result
                    
                except asyncio.CancelledError:
                    update_task_status(task_id, "cancelled", error="Đã hủy")
                    raise
                except Exception as e:
                    update_task_status(task_id, "failed", error=str(e))
                    raise e
        
        jobs.append(_run_one())
    
    gathered = await asyncio.gather(*jobs, return_exceptions=True)
    
    if cancel_event and cancel_event.is_set():
        for r in gathered:
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                continue
        raise asyncio.CancelledError()
    
    return gathered

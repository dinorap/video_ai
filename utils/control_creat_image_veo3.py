"""
Module tạo ảnh qua Veo3 (Google Flow) - SỬ DỤNG API TRỰC TIẾP.
Flow: Setup batch → Upload API → Gửi prompt "a" lấy token → Gọi API tạo ảnh.
"""

import asyncio
import os
import json
import requests
from typing import Optional, List, Dict, Any
from pathlib import Path

# Import các module Veo3
from utils.veo3.flow_actions import (
    connect_and_get_page,
    cleanup_browser,
    setup_render_settings,
    select_mode,
    send_prompt_text,
    open_settings_and_select_batch,
    wait_for_project_ready,
)
from utils.veo3.veo_reference_image_api import (
    build_payload_upload_image,
    request_upload_image_via_browser,
    extract_media_id,
)
from utils.veo3.veo_image_api import (
    build_generate_image_url,
    build_generate_image_payload,
    request_generate_images_via_browser,
    parse_media_from_response,
    image_aspect_const_from_ui_ratio,
    CREATE_IMAGE_MODEL_TO_KEY,
)
from utils.veo3.veo_get_token import (
    load_veo_auth_config,
    auto_collect_veo_auth_on_project_creation,
    fetch_recaptcha_token_via_page,
)
from utils.veo3_profile import (
    get_active_veo3_profiles,
    get_veo3_profile_by_name,
)
from utils.control_script import create_image_task, update_task_status

import sys
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def create_image_veo3(
    context: Dict[str, Any],
    prompt: str,
    out_path: str,
    ratio: str = "16:9",
    reference_image: Optional[str] = None,
    reference_images: Optional[List[str]] = None,  # 🔥 NEW: Hỗ trợ nhiều ảnh
    task_id: Optional[str] = None,
    cancel_event: Optional[asyncio.Event] = None,
    profile_name: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tạo ảnh qua Veo3 - SỬ DỤNG API TRỰC TIẾP.
    
    Flow:
    1. Connect qua CDP
    2. Goto Flow + setup batch tab
    3. Chọn mode/ratio/model trong popup
    4. Upload ảnh tham chiếu qua API (nếu có) - HỖ TRỢ NHIỀU ẢNH
    5. Gửi prompt "a" qua UI để lấy recaptcha token
    6. Gọi API tạo ảnh với token
    7. Download ảnh
    """
    page = None
    ws_endpoint = None
    
    try:
        # 1. Kiểm tra cancel
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print(f"[Veo3 Image] 🎨 Bắt đầu tạo ảnh với API trực tiếp")
        
        # 2. Lấy CDP port từ config
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
        print(f"[Veo3 Image] 🔌 CDP endpoint: {ws_endpoint}")
        
        # 3. Kết nối Playwright qua CDP
        print("[Veo3 Image] 🔌 Kết nối qua CDP...")
        page = await connect_and_get_page(ws_endpoint)
        if not page:
            raise ValueError("Không thể kết nối Playwright qua CDP")
        
        print("[Veo3 Image] ✅ Đã kết nối Playwright")
        
        # 4. Kiểm tra và lấy auth
        profile_id = profile_name or "default"
        auth_data = load_veo_auth_config(profile_id)
        
        # 5. Nếu không có auth, chạy full setup flow
        if not auth_data or not all([
            auth_data.get("sessionId"),
            auth_data.get("projectId"),
            auth_data.get("access_token")
        ]):
            print("[Veo3 Image] ⚠️ Không tìm thấy auth, bắt đầu setup flow...")
            
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Task đã bị hủy")
            
            def _check_cancel():
                return cancel_event and cancel_event.is_set()
            
            auth_data = await auto_collect_veo_auth_on_project_creation(
                page,
                profile_id=profile_id,
                flow_url="https://labs.google/fx/vi/tools/flow",
                timeout_s=60,
                stop_check=_check_cancel if cancel_event else None,
            )
            
            if not auth_data:
                raise ValueError("Không thể trích xuất auth từ Flow")
            
            print("[Veo3 Image] ✅ Đã trích xuất và lưu auth")
        else:
            print("[Veo3 Image] ✅ Đã load auth từ veo_auth.json")
            
            # Điều hướng tới project
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Task đã bị hủy")
            
            project_url = auth_data.get("project_url") or "https://labs.google/fx/vi/tools/flow"
            print(f"[Veo3 Image] 🌐 Điều hướng tới project: {project_url}")
            
            # Goto project URL
            await page.goto(project_url, wait_until="domcontentloaded", timeout=30_000)
            
            # Đợi project ready
            await wait_for_project_ready(page)
            
            # Mở settings và chọn batch tab
            await open_settings_and_select_batch(page)
            
            print("[Veo3 Image] ✅ Đã mở project Flow và setup batch tab")
        
        # 6. Setup: chọn mode Image, tỉ lệ, model trong popup (copy y hệt từ nst_flow.py)
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        def _check_cancel():
            return cancel_event and cancel_event.is_set()
        
        print("[Veo3 Image] ⚙️ Setup: Chọn mode Image...")
        ok = await select_mode(page, "image", stop_check=_check_cancel if cancel_event else None)
        if not ok:
            raise ValueError("Chọn mode Image thất bại")
        
        await asyncio.sleep(0.5)
        
        # Đảm bảo model có giá trị (fallback về Banana Pro nếu rỗng)
        # KHÔNG chuẩn hóa ở đây vì setup_render_settings() sẽ tự xử lý
        final_model = str(model or "").strip() if model else "🍌 Nano Banana Pro"
        
        print(f"[Veo3 Image] ⚙️ Setup: Chọn tỉ lệ {ratio}, model '{final_model}'...")
        settings_ok = await setup_render_settings(
            page,
            output_count=1,
            aspect_ratio=ratio,
            model=final_model,
            select_ingredients=False,
            prompt="a",  # 🔥 Truyền prompt="a" để trigger nhập chữ "a" và nhấn Enter
        )
        
        if not settings_ok:
            raise ValueError("Setup render settings thất bại")
        
        print("[Veo3 Image] ✅ Đã setup đầy đủ")
        
        # 7. Upload ảnh tham chiếu qua API (nếu có) - HỖ TRỢ NHIỀU ẢNH
        media_ids = []
        
        # 🔥 Xác định danh sách ảnh cần upload
        images_to_upload = []
        if reference_images and isinstance(reference_images, list):
            # Ưu tiên dùng reference_images (list) nếu có
            images_to_upload = [img for img in reference_images if img and os.path.exists(img)]
        elif reference_image and os.path.exists(reference_image):
            # Fallback về reference_image (single) để tương thích ngược
            images_to_upload = [reference_image]
        
        if images_to_upload:
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Task đã bị hủy")
            
            print(f"[Veo3 Image] 📤 Upload {len(images_to_upload)} ảnh tham chiếu qua API...")
            
            try:
                # Lấy projectId và access_token từ auth_data
                project_id = auth_data.get("projectId")
                access_token = auth_data.get("access_token")
                
                if not project_id or not access_token:
                    raise ValueError("Thiếu projectId hoặc access_token để upload ảnh")
                
                # Upload từng ảnh tuần tự (có thể song song nhưng tuần tự an toàn hơn)
                for idx, img_path in enumerate(images_to_upload):
                    if cancel_event and cancel_event.is_set():
                        raise asyncio.CancelledError("Task đã bị hủy")
                    
                    print(f"[Veo3 Image] 📤 [{idx+1}/{len(images_to_upload)}] Upload: {os.path.basename(img_path)}")
                    
                    # Build payload
                    payload = build_payload_upload_image(
                        image_path=img_path,
                        project_id=project_id,
                    )
                    
                    # Upload qua API
                    upload_res = await request_upload_image_via_browser(
                        page,
                        payload,
                        access_token,
                        timeout_ms=60_000,
                    )
                    
                    if upload_res.get("ok"):
                        body = str(upload_res.get("body") or "")
                        media_id = extract_media_id(body)
                        
                        if media_id:
                            media_ids.append(media_id)
                            print(f"[Veo3 Image] ✅ [{idx+1}/{len(images_to_upload)}] Upload thành công: mediaId={media_id}")
                        else:
                            print(f"[Veo3 Image] ⚠️ [{idx+1}/{len(images_to_upload)}] Upload OK nhưng không parse được mediaId")
                    else:
                        error_msg = upload_res.get("error", "Unknown error")
                        print(f"[Veo3 Image] ⚠️ [{idx+1}/{len(images_to_upload)}] Upload thất bại: {error_msg}")
                
                print(f"[Veo3 Image] 📊 Tổng kết: Upload thành công {len(media_ids)}/{len(images_to_upload)} ảnh")
                    
            except Exception as e:
                print(f"[Veo3 Image] ⚠️ Upload ảnh tham chiếu thất bại: {e}")
        
        # 8. Bắt recaptcha token (prompt "a" đã được gửi trong setup_render_settings)
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print(f"[Veo3 Image] 🎯 Đợi bắt recaptcha token...")
        
        # Gọi fetch_recaptcha_token_via_page để bắt token
        # (prompt "a" đã được gửi trong setup_render_settings ở bước 6)
        recaptcha_token = await fetch_recaptcha_token_via_page(
            page,
            prompt_for_token="a",  # Không dùng nữa, chỉ giữ để tương thích
            timeout=30,
        )
        
        if not recaptcha_token:
            raise ValueError("Không thể lấy recaptcha token")
        
        print(f"[Veo3 Image] ✅ Đã bắt được recaptcha token: {len(recaptcha_token)} ký tự")
        print(f"[Veo3 Image] 📋 Token (full): {recaptcha_token}")
        
        # 9. Gọi API tạo ảnh
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Task đã bị hủy")
        
        print(f"[Veo3 Image] 🎨 Gọi API tạo ảnh với prompt: {prompt[:100]}...")
        
        # Lấy thông tin từ auth_data
        session_id = auth_data.get("sessionId")
        project_id = auth_data.get("projectId")
        access_token = auth_data.get("access_token")
        
        if not all([session_id, project_id, access_token]):
            raise ValueError("Thiếu sessionId, projectId hoặc access_token")
        
        # Build URL và payload
        api_url = build_generate_image_url(project_id)
        aspect_ratio_const = image_aspect_const_from_ui_ratio(ratio)
        
        # Map model name to model key (dùng final_model để đồng bộ với UI)
        model_key = None
        if final_model:
            model_key = CREATE_IMAGE_MODEL_TO_KEY.get(final_model)
            if not model_key:
                print(f"[Veo3 Image] ⚠️ Model '{final_model}' không tìm thấy trong mapping, sẽ dùng default")
        
        # 🔥 Build payload với NHIỀU reference images nếu có
        reference_names = media_ids if media_ids else None
        
        if reference_names:
            print(f"[Veo3 Image] 📋 Sử dụng {len(reference_names)} ảnh tham chiếu: {reference_names}")
        
        payload = build_generate_image_payload(
            prompt=prompt,
            session_id=session_id,
            project_id=project_id,
            recaptcha_token=recaptcha_token,
            model_key=model_key,
            aspect_ratio=aspect_ratio_const,
            output_count=1,
            reference_input_names=reference_names,
        )
        
        # Gọi API
        api_response = await request_generate_images_via_browser(
            page,
            api_url,
            payload,
            access_token,
            timeout_ms=60_000,
        )
        
        if not api_response.get("ok"):
            error_msg = api_response.get("error", "Unknown error")
            status = api_response.get("status", 0)
            if status == 403:
                raise ValueError(f"Lỗi captcha (HTTP 403). Vui lòng thử lại sau.")
            elif status == 400:
                raise ValueError(f"Lỗi nội dung (HTTP 400). Prompt vi phạm chính sách nội dung.")
            else:
                raise ValueError(f"API tạo ảnh thất bại: {error_msg}")
        
        # Parse response để lấy URL download
        body = api_response.get("body", "")
        media_list = parse_media_from_response(body)
        
        if not media_list:
            raise ValueError("Không tìm thấy media trong response")
        
        # Lấy URL download của ảnh đầu tiên
        download_url = media_list[0].get("downloadUrl")
        if not download_url:
            raise ValueError("Không tìm thấy downloadUrl trong response")
        
        print(f"[Veo3 Image] 📥 Downloading ảnh từ {download_url[:80]}...")
        
        # 10. Download ảnh
        try:
            response = requests.get(download_url, timeout=30)
            if response.status_code == 200:
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, 'wb') as f:
                    f.write(response.content)
                print(f"[Veo3 Image] ✅ Đã download và lưu ảnh: {out_path}")
            else:
                raise ValueError(f"Download thất bại: HTTP {response.status_code}")
        except Exception as e:
            raise ValueError(f"Download ảnh thất bại: {e}")
        
        print(f"[Veo3 Image] ✅ Tạo ảnh thành công: {out_path}")
        return {
            "ok": True,
            "output": out_path,
        }
    
    except asyncio.CancelledError:
        print("[Veo3 Image] ⚠️ Task đã bị hủy")
        raise
    
    except Exception as e:
        print(f"[Veo3 Image] ❌ Lỗi: {e}")
        return {
            "ok": False,
            "error": str(e),
        }
    
    finally:
        # Cleanup browser (không đóng page, chỉ detach)
        if page and ws_endpoint:
            try:
                await cleanup_browser(ws_endpoint)
            except Exception as e:
                print(f"[Veo3 Image] ⚠️ Lỗi cleanup: {e}")


async def run_tasks_veo3(
    context: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    max_tabs: int = 3,
    cancel_event: Optional[asyncio.Event] = None,
) -> List[Any]:
    """
    Chạy nhiều task tạo ảnh Veo3 song song.
    """
    jobs = []
    
    try:
        max_tabs = int(max_tabs)
    except Exception:
        max_tabs = 3
    if max_tabs < 1:
        max_tabs = 1
    
    sem = asyncio.Semaphore(max_tabs)
    
    for task in tasks:
        async def _run_one(t=task):
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError()
            
            task_id = str((t or {}).get("task_id") or "").strip()
            if not task_id:
                task_name = f"Tạo ảnh Veo3: {os.path.basename(t['out'])}"
                task_id = create_image_task(task_name, "Veo3")
            
            async with sem:
                try:
                    if cancel_event and cancel_event.is_set():
                        raise asyncio.CancelledError()
                    
                    result = await create_image_veo3(
                        context=context,
                        prompt=t["prompt"],
                        out_path=t["out"],
                        ratio=t.get("ratio", "16:9"),
                        reference_image=t.get("reference_image"),  # Backward compatibility
                        reference_images=t.get("reference_images"),  # 🔥 NEW: Support multiple images
                        task_id=task_id,
                        cancel_event=cancel_event,
                        profile_name=t.get("profile_name"),
                        model=t.get("model"),
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

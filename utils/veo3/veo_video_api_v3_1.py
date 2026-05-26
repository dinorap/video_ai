"""
VEO API v3.1+ - Module tải video từ encodedVideo và tạo thumbnail

Dùng cho dự án migrate từ operation cũ (fifeUrl) sang format mới (media array + encodedVideo base64).
"""

import asyncio
import json
import base64
import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from playwright.async_api import Page  # type: ignore


# ============================================================================
# PHẦN 1: POLL STATUS VỚI FORMAT MỚI (media array)
# ============================================================================

async def poll_video_status_v3_1(
    page: Page,
    media_id: str,
    project_id: str,
    access_token: str,
    timeout_seconds: int = 420,
    poll_interval: int = 6,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """
    Poll status video với API v3.1+ format mới.
    
    Args:
        page: Playwright page object
        media_id: Media ID từ CREATE response (field "mediaId")
        project_id: Project ID
        access_token: Bearer token
        timeout_seconds: Timeout tổng
        poll_interval: Khoảng thời gian giữa các lần poll
    
    Returns:
        {
            "success": True/False,
            "status": "SUCCESSFUL"/"FAILED"/"TIMEOUT",
            "media_id": str,
            "error": str (nếu có)
        }
    """
    import time
    
    start_time = time.time()
    last_status = "PENDING"
    
    # URL check status - ĐÚNG ENDPOINT
    status_url = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"
    
    while True:
        if cancel_check is not None:
            try:
                if cancel_check():
                    print("ℹ️ Poll status: đã hủy theo yêu cầu user")
                    return {
                        "success": False,
                        "status": "CANCELLED",
                        "media_id": media_id,
                        "error": "Đã hủy",
                    }
            except Exception:
                pass

        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            return {
                "success": False,
                "status": "TIMEOUT",
                "media_id": media_id,
                "error": f"Timeout after {timeout_seconds}s"
            }
        
        # Payload format mới: wrap trong object với key "media"
        status_payload = {
            "media": [
                {
                    "name": media_id,
                    "projectId": project_id
                }
            ]
        }
        
        try:
            # Gọi API check status
            resp = await page.request.post(
                status_url,
                data=json.dumps(status_payload, ensure_ascii=False),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}"
                },
                timeout=30_000
            )
            
            if not resp.ok:
                print(f"⚠️ Check status HTTP {resp.status}: {await resp.text()}")
                await asyncio.sleep(poll_interval)
                continue
            
            body = await resp.json()
            
            # Parse response format mới
            media = body.get("media") or []
            if not isinstance(media, list) or not media:
                await asyncio.sleep(poll_interval)
                continue
            
            matched_item = media[0]  # Lấy item đầu tiên
            
            # Lấy status từ mediaMetadata.mediaStatus.mediaGenerationStatus
            metadata = matched_item.get("mediaMetadata", {})
            media_status = metadata.get("mediaStatus", {})
            status_str = str(media_status.get("mediaGenerationStatus") or "").upper()
            
            # Chuẩn hóa status
            if status_str.startswith("MEDIA_GENERATION_STATUS_"):
                short_status = status_str.replace("MEDIA_GENERATION_STATUS_", "")
            else:
                short_status = status_str or "PENDING"
            
            if short_status != last_status:
                print(f"ℹ️ Status: {short_status}")
                last_status = short_status
            
            # Check error object on media item
            error = matched_item.get("error")
            if isinstance(error, dict):
                msg = error.get("message") or error.get("status") or str(error)
                return {
                    "success": False,
                    "status": "FAILED",
                    "media_id": media_id,
                    "error": f"Code {error.get('code')}: {msg}"
                }

            failure_reasons = media_status.get("failureReasons") or []
            if not isinstance(failure_reasons, list):
                failure_reasons = [failure_reasons] if failure_reasons else []

            def _format_failure_detail() -> str:
                parts = []
                for r in failure_reasons[:5]:
                    if isinstance(r, dict):
                        parts.append(
                            r.get("message")
                            or r.get("reason")
                            or r.get("code")
                            or str(r)
                        )
                    elif r:
                        parts.append(str(r))
                detail = "; ".join(p for p in parts if p)
                if detail:
                    return detail
                gen_err = metadata.get("generationError") or metadata.get("errorMessage")
                if gen_err:
                    return str(gen_err)
                return ""

            # Nếu SUCCESSFUL -> return
            if short_status == "SUCCESSFUL":
                return {
                    "success": True,
                    "status": "SUCCESSFUL",
                    "media_id": media_id
                }

            # FAILED / cancelled / other terminal states
            if short_status not in {"PENDING", "ACTIVE"}:
                detail = _format_failure_detail()
                err_msg = f"Google render {short_status}"
                if detail:
                    err_msg = f"{err_msg}: {detail}"
                if short_status == "FAILED":
                    print(f"❌ Chi tiết FAILED: {detail or '(không có failureReasons)'}")
                    try:
                        snippet = json.dumps(matched_item, ensure_ascii=False)[:1200]
                        print(f"❌ Response media item (rút gọn): {snippet}")
                    except Exception:
                        pass
                return {
                    "success": False,
                    "status": short_status,
                    "media_id": media_id,
                    "error": err_msg
                }
            
        except Exception as e:
            print(f"⚠️ Exception khi poll status: {e}")
        
        await asyncio.sleep(poll_interval)


# ============================================================================
# PHẦN 2: GET MEDIA VÀ DOWNLOAD VIDEO TỪ ENCODEDVIDEO
# ============================================================================

async def download_video_from_encoded_v3_1(
    page: Page,
    media_id: str,
    access_token: str,
    output_path: str,
    ffmpeg_path: str = "ffmpeg"
) -> Dict[str, Any]:
    """
    GET media và download video từ encodedVideo (base64).
    Tự động tạo thumbnail từ frame đầu tiên bằng ffmpeg.
    
    Args:
        page: Playwright page object
        media_id: Media ID
        access_token: Bearer token
        output_path: Đường dẫn lưu video (VD: "output/video.mp4")
        ffmpeg_path: Path đến ffmpeg binary (mặc định "ffmpeg" trong PATH)
    
    Returns:
        {
            "success": True/False,
            "video_path": str,
            "thumbnail_path": str (nếu có),
            "error": str (nếu có)
        }
    """
    # GET /v1/media/{mediaId}
    media_url = f"https://aisandbox-pa.googleapis.com/v1/media/{media_id}?clientContext.tool=PINHOLE"
    
    try:
        print(f"📥 GET media: {media_id}")
        
        resp = await page.request.get(
            media_url,
            headers={
                "accept": "*/*",
                "authorization": f"Bearer {access_token}"
            },
            timeout=60_000
        )
        
        if not resp.ok:
            error_text = await resp.text()
            return {
                "success": False,
                "error": f"GET media HTTP {resp.status}: {error_text[:200]}"
            }
        
        media_data = await resp.json()
        
        # Lấy encodedVideo từ response
        encoded_video = media_data.get("video", {}).get("encodedVideo")
        
        if not encoded_video:
            return {
                "success": False,
                "error": "Không có encodedVideo trong response",
                "response_snippet": json.dumps(media_data, ensure_ascii=False)[:500]
            }
        
        # Decode base64 và lưu file
        video_bytes = base64.b64decode(encoded_video)

        raw_out = str(output_path or "").strip()
        if not raw_out:
            return {"success": False, "error": "Missing output_path"}
        if os.path.isdir(raw_out):
            os.makedirs(raw_out, exist_ok=True)
            raw_out = os.path.join(raw_out, f"clip_{media_id[:8]}.mp4")

        out_path = Path(raw_out)
        if not out_path.suffix:
            out_path = out_path.with_suffix(".mp4")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(video_bytes)
        
        print(f"✅ Đã lưu video: {out_path} ({len(video_bytes) / 1024 / 1024:.2f} MB)")
        
        # Tạo thumbnail từ frame đầu tiên bằng ffmpeg
        thumb_path = out_path.with_suffix(".jpg")
        thumbnail_created = False
        
        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    str(out_path),
                    "-frames:v",
                    "1",
                    str(thumb_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            thumbnail_created = True
            print(f"🖼️ Đã tạo thumbnail: {thumb_path}")
        except Exception as e:
            print(f"⚠️ Không tạo được thumbnail: {e}")
        
        return {
            "success": True,
            "video_path": str(out_path),
            "thumbnail_path": str(thumb_path) if thumbnail_created else None
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Exception: {e}",
            "traceback": traceback.format_exc()
        }


# ============================================================================
# PHẦN 3: FULL WORKFLOW - TỪ CREATE ĐẾN DOWNLOAD
# ============================================================================

async def full_video_workflow_v3_1(
    page: Page,
    media_id: str,
    project_id: str,
    access_token: str,
    output_path: str,
    ffmpeg_path: str = "ffmpeg",
    timeout_seconds: int = 420,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """
    Workflow đầy đủ: Poll status -> GET media -> Download video + thumbnail
    
    Args:
        page: Playwright page object
        media_id: Media ID từ CREATE response
        project_id: Project ID
        access_token: Bearer token
        output_path: Đường dẫn lưu video
        ffmpeg_path: Path đến ffmpeg
        timeout_seconds: Timeout poll status
    
    Returns:
        {
            "success": True/False,
            "video_path": str,
            "thumbnail_path": str,
            "status": str,
            "error": str (nếu có)
        }
    """
    # Bước 1: Poll status
    print(f"🔄 Bắt đầu poll status cho media_id: {media_id}")
    status_result = await poll_video_status_v3_1(
        page,
        media_id,
        project_id,
        access_token,
        timeout_seconds=timeout_seconds,
        cancel_check=cancel_check,
    )
    
    if not status_result.get("success"):
        return {
            "success": False,
            "status": status_result.get("status"),
            "error": status_result.get("error")
        }
    
    # Bước 2: Download video từ encodedVideo
    print(f"📥 Bắt đầu download video...")
    download_result = await download_video_from_encoded_v3_1(
        page,
        media_id,
        access_token,
        output_path,
        ffmpeg_path=ffmpeg_path
    )
    
    if not download_result.get("success"):
        return {
            "success": False,
            "status": "DOWNLOAD_FAILED",
            "error": download_result.get("error")
        }
    
    return {
        "success": True,
        "video_path": download_result.get("video_path"),
        "thumbnail_path": download_result.get("thumbnail_path"),
        "status": "COMPLETED"
    }


# ============================================================================
# PHẦN 4: HELPER - PARSE MEDIA_ID TỪ CREATE RESPONSE
# ============================================================================

def parse_media_id_from_create_response(create_response_body: str) -> Optional[str]:
    """
    Parse mediaId từ CREATE response (API v3.1+).
    
    Response format mới:
    {
        "media": [
            {
                "name": "85524ffd-e12d-40a0-ab24-2960999015a4",
                "projectId": "...",
                "video": {...}
            }
        ]
    }
    
    Args:
        create_response_body: JSON string từ CREATE response
    
    Returns:
        media_id (name field) hoặc None
    """
    try:
        data = json.loads(create_response_body)
        media = data.get("media", [])
        
        if isinstance(media, list) and media:
            first_item = media[0]
            if isinstance(first_item, dict):
                # Lấy field "name" - đây là media_id thực tế
                media_id = first_item.get("name")
                if media_id:
                    return str(media_id)
        
        return None
    except Exception as e:
        print(f"⚠️ Parse mediaId lỗi: {e}")
        return None


# ============================================================================
# PHẦN 5: MIGRATION GUIDE - THAY THẾ CODE CŨ
# ============================================================================

"""
MIGRATION GUIDE - Thay thế code cũ sang v3.1+:

1. CODE CŨ (operations format):
   --------------------------------
   # Poll status
   status_payload = {
       "operations": [
           {
               "sceneId": "...",
               "status": "MEDIA_GENERATION_STATUS_ACTIVE",
               "operation": {"name": "operations/xxx"}
           }
       ]
   }
   
   # Parse status
   ops = response.get("operations", [])
   status = ops[0].get("status")
   
   # Download video
   video_url = ops[0].get("video", {}).get("fifeUrl")
   # Tải từ URL...


2. CODE MỚI (media format):
   --------------------------------
   # Poll status
   status_payload = {
       "media": [
           {
               "name": "media/xxx",
               "projectId": "project-id"
           }
       ]
   }
   
   # Parse status
   media = response.get("media", [])
   metadata = media[0].get("mediaMetadata", {})
   status = metadata.get("mediaStatus", {}).get("mediaGenerationStatus")
   
   # Download video
   # GET /v1/media/{mediaId}
   encoded_video = response.get("video", {}).get("encodedVideo")
   video_bytes = base64.b64decode(encoded_video)
   # Lưu file...


3. ĐIỂM KHÁC BIỆT CHÍNH:
   --------------------------------
   - CREATE response: "operations" -> "media" array
   - Media identifier: "operation.name" -> "mediaId"
   - Status payload: operations array -> media array với name + projectId
   - Status field: "status" -> "mediaMetadata.mediaStatus.mediaGenerationStatus"
   - Video download: fifeUrl (HTTP) -> encodedVideo (base64)
   - Thumbnail: có URL riêng -> KHÔNG CÓ, phải dùng ffmpeg extract


4. CÁCH DÙNG MODULE NÀY:
   --------------------------------
   # Import các hàm chính:
   from utils.veo3.veo_video_api_v3_1 import (
       poll_video_status_v3_1,
       download_video_from_encoded_v3_1,
       full_video_workflow_v3_1,
       parse_media_id_from_create_response,
   )
   
   # Sau khi CREATE video thành công:
   media_id = parse_media_id_from_create_response(create_body)
   
   # Thay vì poll + download theo cách cũ:
   result = await full_video_workflow_v3_1(
       page, media_id, project_id, access_token, output_path
   )
   
   if result["success"]:
       video_path = result["video_path"]
       thumbnail_path = result["thumbnail_path"]
"""

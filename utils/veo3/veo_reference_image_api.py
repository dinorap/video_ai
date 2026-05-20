import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional


URL_UPLOAD_IMAGE = "https://aisandbox-pa.googleapis.com/v1/flow/uploadImage"


def _read_file_base64(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("utf-8")


def build_payload_upload_image(
    *,
    image_path: str,
    project_id: str,
    file_name: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> dict:
    p = Path(image_path)
    name = str(file_name or p.name or "reference.jpg")
    guessed_mime = mime_type or mimetypes.guess_type(name)[0] or "image/jpeg"
    base64_image = _read_file_base64(str(p))
    return {
        "clientContext": {
            "projectId": project_id,
            "tool": "PINHOLE",
        },
        "imageBytes": base64_image,
        "isUserUploaded": True,
        "isHidden": False,
        "mimeType": str(guessed_mime),
        "fileName": name,
    }


async def request_upload_image_via_browser(
    page: Any,
    payload: dict,
    access_token: str,
    timeout_ms: int = 60_000,
) -> Dict[str, Any]:
    """Upload ảnh tham chiếu qua Playwright page.request với Bearer token."""
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        data = json.dumps(payload)
        
        # 🔍 LOG REQUEST: Log thông tin request (không log imageBytes vì quá dài)
        payload_debug = {k: v for k, v in payload.items() if k != "imageBytes"}
        payload_debug["imageBytes"] = f"<base64 data, length={len(payload.get('imageBytes', ''))}>"
        print(f"[VEO Upload API] 📤 REQUEST:")
        print(f"  - URL: {URL_UPLOAD_IMAGE}")
        print(f"  - fileName: {payload.get('fileName')}")
        print(f"  - mimeType: {payload.get('mimeType')}")
        print(f"  - projectId: {payload.get('clientContext', {}).get('projectId')}")
        print(f"  - Payload (sanitized): {json.dumps(payload_debug, indent=2, ensure_ascii=False)}")
        
        response = await page.request.post(
            URL_UPLOAD_IMAGE,
            data=data,
            headers=headers,
            timeout=int(timeout_ms or 15_000),
        )
        body = await response.text()
        
        # 🔍 LOG RESPONSE: Log toàn bộ response để phân tích
        print(f"[VEO Upload API] 📥 RESPONSE:")
        print(f"  - Status: {response.status} {response.status_text}")
        print(f"  - OK: {response.ok}")
        print(f"  - Headers: {dict(response.headers)}")
        print(f"  - Body (full): {body}")
        
        # Parse và log các field quan trọng
        try:
            body_json = json.loads(body)
            print(f"[VEO Upload API] 🔍 PARSED RESPONSE:")
            print(f"  - Full JSON: {json.dumps(body_json, indent=2, ensure_ascii=False)}")
            
            # Liệt kê tất cả keys ở root level
            if isinstance(body_json, dict):
                print(f"  - Root keys: {list(body_json.keys())}")
                
                # Log chi tiết các field có thể chứa mapping
                for key in ["mediaGenerationId", "media", "workflow", "mediaId", "id", "name", "fileName"]:
                    if key in body_json:
                        print(f"  - {key}: {body_json[key]}")
        except Exception as parse_err:
            print(f"[VEO Upload API] ⚠️ Không parse được JSON: {parse_err}")
        
        return {
            "ok": response.ok,
            "url": URL_UPLOAD_IMAGE,
            "status": response.status,
            "reason": response.status_text,
            "headers": dict(response.headers),
            "body": body,
        }
    except Exception as exc:
        print(f"[VEO Upload API] ❌ Exception: {exc}")
        return {"ok": False, "url": URL_UPLOAD_IMAGE, "error": str(exc)}


def extract_media_id(response_body: str) -> str:
    """Trích name/mediaId trả về từ uploadImage để đưa vào imageInputs[].name."""
    try:
        body_json = json.loads(response_body)
    except Exception:
        return ""
    if not isinstance(body_json, dict):
        return ""

    def _pick(value: Any) -> str:
        return str(value or "").strip()

    def _normalize_media_name(value: Any) -> str:
        text = _pick(value)
        if not text:
            return ""
        if "/" in text:
            last = text.rsplit("/", 1)[-1].strip()
            if last:
                return last
        return text

    mg = body_json.get("mediaGenerationId")
    if isinstance(mg, dict):
        mid = _normalize_media_name(mg.get("mediaGenerationId") or mg.get("name"))
        if mid:
            return mid
    if mg and not isinstance(mg, dict):
        mid = _normalize_media_name(mg)
        if mid:
            return mid

    media = body_json.get("media")
    if isinstance(media, dict):
        mid = _normalize_media_name(media.get("mediaId") or media.get("id") or media.get("name"))
        if mid:
            return mid

    workflow = body_json.get("workflow")
    if isinstance(workflow, dict):
        metadata = workflow.get("metadata")
        if isinstance(metadata, dict):
            mid = _normalize_media_name(metadata.get("primaryMediaId"))
            if mid:
                return mid

    return _normalize_media_name(body_json.get("mediaId") or body_json.get("id") or body_json.get("name"))


def extract_media_info(response_body: str) -> Dict[str, str]:
    """
    Trích cả mediaId VÀ original filename từ response upload.
    
    Returns:
        {
            "media_id": "4df4a34c-4d7d-419c-a1bd-958af51751f5",
            "original_filename": "video_0.png"
        }
    """
    try:
        body_json = json.loads(response_body)
    except Exception:
        return {}
    
    if not isinstance(body_json, dict):
        return {}
    
    result = {}
    
    # 1. Lấy mediaId (UUID)
    media_id = extract_media_id(response_body)
    if media_id:
        result["media_id"] = media_id
    
    # 2. Lấy original filename từ workflow.metadata.displayName
    workflow = body_json.get("workflow")
    if isinstance(workflow, dict):
        metadata = workflow.get("metadata")
        if isinstance(metadata, dict):
            display_name = str(metadata.get("displayName") or "").strip()
            if display_name:
                result["original_filename"] = display_name
    
    return result


async def batch_upload_images_parallel(
    page: Any,
    image_paths: list,
    project_id: str,
    access_token: str,
    timeout_ms: int = 60_000,
) -> Dict[str, str]:
    """
    Upload nhiều ảnh SONG SONG (parallel) và trả về mapping {mediaId: original_filename}.
    Dùng cho test script và tab NEW (upload song song toàn bộ ảnh nhân vật / profile).
    """
    import asyncio

    if not image_paths:
        return {}

    print(f"[VEO Upload API] 📤 Bắt đầu upload {len(image_paths)} ảnh SONG SONG...")

    async def _upload_single(image_path: str, index: int) -> tuple:
        try:
            if not Path(image_path).exists():
                print(f"[VEO Upload API] ⚠️ [{index+1}] File không tồn tại: {image_path}")
                return (None, None)

            original_name = Path(image_path).name
            print(f"[VEO Upload API] 📤 [{index+1}/{len(image_paths)}] Uploading: {original_name}")

            payload = build_payload_upload_image(
                image_path=image_path,
                project_id=project_id,
            )

            upload_res = await request_upload_image_via_browser(
                page,
                payload,
                access_token,
                timeout_ms=timeout_ms,
            )

            if upload_res.get("ok"):
                body = str(upload_res.get("body") or "")
                info = extract_media_info(body)
                media_id = info.get("media_id") or extract_media_id(body)
                filename = info.get("original_filename") or original_name

                if media_id:
                    print(f"[VEO Upload API] ✅ [{index+1}] Upload OK: {filename} -> {media_id}")
                    return (media_id, filename)
                print(f"[VEO Upload API] ⚠️ [{index+1}] Upload OK nhưng không parse được info")
                return (None, None)
            print(f"[VEO Upload API] ❌ [{index+1}] Upload thất bại: {upload_res.get('error')}")
            return (None, None)

        except Exception as e:
            print(f"[VEO Upload API] ❌ [{index+1}] Exception: {e}")
            return (None, None)

    tasks = [_upload_single(path, idx) for idx, path in enumerate(image_paths)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    mapping = {}
    for result in results:
        if isinstance(result, tuple) and len(result) == 2:
            media_id, filename = result
            if media_id and filename:
                mapping[media_id] = filename

    print(f"[VEO Upload API] 🎉 Hoàn thành upload {len(mapping)}/{len(image_paths)} ảnh thành công")
    return mapping


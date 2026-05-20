import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Page  # type: ignore

URL_GENERATE_REFERENCE_VIDEO = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoReferenceImages"
URL_STATUS_REFERENCE_VIDEO = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"
URL_UPLOAD_USER_IMAGE = "https://aisandbox-pa.googleapis.com/v1:uploadUserImage"


IMAGE_ASPECT_RATIO_LANDSCAPE = "IMAGE_ASPECT_RATIO_LANDSCAPE"
IMAGE_ASPECT_RATIO_PORTRAIT = "IMAGE_ASPECT_RATIO_PORTRAIT"

VIDEO_ASPECT_RATIO_LANDSCAPE = "VIDEO_ASPECT_RATIO_LANDSCAPE"
VIDEO_ASPECT_RATIO_PORTRAIT = "VIDEO_ASPECT_RATIO_PORTRAIT"

DEFAULT_SEED = 9797

# Model keys r2v (tham khảo theo veo_video_api: t2v -> r2v)
MODEL_KEY_ULTRA_LANDSCAPE = "veo_3_1_r2v_fast_landscape_ultra"
MODEL_KEY_PORTRAIT_ULTRA = "veo_3_1_r2v_fast_portrait_ultra"

MODEL_KEY_ULTRA_LANDSCAPE_RELAXED = "veo_3_1_r2v_fast_landscape_ultra_relaxed"
MODEL_KEY_PORTRAIT_ULTRA_RELAXED = "veo_3_1_r2v_fast_portrait_ultra_relaxed"

MODEL_KEY_LANDSCAPE_NORMAL_PRO = "veo_3_1_r2v_fast_landscape"
MODEL_KEY_PORTRAIT_NORMAL_PRO = "veo_3_1_r2v_fast_portrait"

# Quality model (không fast) — theo veo_video_api: thay t2v -> r2v
MODEL_KEY_LANDSCAPE_QUALITY = "veo_3_1_r2v"
MODEL_KEY_PORTRAIT_QUALITY = "veo_3_1_r2v_portrait"


def _normalize_account_type(value: Optional[str]) -> str:
    v = str(value or "").strip().upper()
    return v if v in {"NORMAL", "PRO", "ULTRA"} else "ULTRA"


def _user_paygate_tier(account_type: Optional[str]) -> str:
    """
    Map NORMAL/PRO/ULTRA sang PAYGATE_TIER_* giống veo_video_api.
    """
    t = _normalize_account_type(account_type)
    if t == "NORMAL":
        return "PAYGATE_TIER_NOT_PAID"
    if t == "PRO":
        return "PAYGATE_TIER_ONE"
    return "PAYGATE_TIER_TWO"


def _normalize_model_label(model: Optional[str]) -> str:
    """
    Chuẩn hoá nhãn model từ frontend (veo 3.1 - fast / quality / fast [low priority]...).
    """
    if not isinstance(model, str):
        return ""
    return " ".join(model.strip().lower().split())


def _is_fast_2_mode(veo_model: Optional[str]) -> bool:
    return "fast 2.0" in str(veo_model or "").strip().lower()


def select_reference_video_model_key(
    *,
    aspect_ratio: str,
    frontend_model_label: Optional[str],
    account_type: Optional[str],
) -> str:
    """
    Chọn model r2v cho Reference Video theo logic tương tự veo_video_api:
    - "veo 3.1 - lite"                        -> fast NORMAL/PRO
    - "veo 3.1 - lite [lower/low priority]"  -> relaxed ULTRA (cùng nhánh ưu tiên thấp như fast)
    - "veo 3.1 - fast"                        -> fast (ULTRA hoặc NORMAL/PRO)
    - legacy fast priority label              -> fast_ultra_relaxed cho ULTRA
    - "veo 3.1 - quality"             -> dùng model fast portrait (hiện chưa có r2v quality riêng)
    Nếu không khớp, fallback theo loại tài khoản (ULTRA vs NORMAL/PRO).
    """
    label = _normalize_model_label(frontend_model_label)
    acc = _normalize_account_type(account_type)

    is_portrait = aspect_ratio == VIDEO_ASPECT_RATIO_PORTRAIT

    # Default UI mới: "Veo 3.1 - Lite [Lower Priority]".
    if not label:
        if acc == "ULTRA":
            return (
                MODEL_KEY_PORTRAIT_ULTRA_RELAXED
                if is_portrait
                else MODEL_KEY_ULTRA_LANDSCAPE_RELAXED
            )
        return MODEL_KEY_PORTRAIT_NORMAL_PRO if is_portrait else MODEL_KEY_LANDSCAPE_NORMAL_PRO

    # "Veo 3.1 - Lite [Lower Priority]" / tương đương
    if "veo 3.1 - lite" in label and "priority" in label:
        if acc == "ULTRA":
            return (
                MODEL_KEY_PORTRAIT_ULTRA_RELAXED
                if is_portrait
                else MODEL_KEY_ULTRA_LANDSCAPE_RELAXED
            )
        return MODEL_KEY_PORTRAIT_NORMAL_PRO if is_portrait else MODEL_KEY_LANDSCAPE_NORMAL_PRO

    # "Veo 3.1 - Lite"
    if label == "veo 3.1 - lite":
        return MODEL_KEY_PORTRAIT_NORMAL_PRO if is_portrait else MODEL_KEY_LANDSCAPE_NORMAL_PRO

    # "Veo 3.1 - Fast"
    if label == "veo 3.1 - fast":
        if acc == "ULTRA":
            return MODEL_KEY_PORTRAIT_ULTRA if is_portrait else MODEL_KEY_ULTRA_LANDSCAPE
        return MODEL_KEY_PORTRAIT_NORMAL_PRO if is_portrait else MODEL_KEY_LANDSCAPE_NORMAL_PRO

    # Legacy fast priority labels (normalize)
    if "veo 3.1 - fast" in label and "priority" in label:
        if acc == "ULTRA":
            return (
                MODEL_KEY_PORTRAIT_ULTRA_RELAXED
                if is_portrait
                else MODEL_KEY_ULTRA_LANDSCAPE_RELAXED
            )
        return MODEL_KEY_PORTRAIT_NORMAL_PRO if is_portrait else MODEL_KEY_LANDSCAPE_NORMAL_PRO

    # "Veo 3.1 - Quality" → tạm thời map về fast portrait tương ứng
    if label == "veo 3.1 - quality":
        return MODEL_KEY_PORTRAIT_QUALITY if is_portrait else MODEL_KEY_LANDSCAPE_QUALITY

    # Fallback theo loại tài khoản
    if acc == "ULTRA":
        # Nếu frontend chọn mode "fast 2.0" thì dùng relaxed ULTRA (giống API_sync_chactacter)
        if _is_fast_2_mode(frontend_model_label):
            return (
                MODEL_KEY_PORTRAIT_ULTRA_RELAXED
                if is_portrait
                else MODEL_KEY_ULTRA_LANDSCAPE_RELAXED
            )
        return MODEL_KEY_PORTRAIT_ULTRA if is_portrait else MODEL_KEY_ULTRA_LANDSCAPE
    return MODEL_KEY_PORTRAIT_NORMAL_PRO if is_portrait else MODEL_KEY_LANDSCAPE_NORMAL_PRO


def build_payload_upload_user_image(
    *,
    base64_image: str,
    mime_type: str,
    session_id: str,
    aspect_ratio: str = IMAGE_ASPECT_RATIO_PORTRAIT,
) -> Dict[str, Any]:
    return {
        "imageInput": {
            "rawImageBytes": base64_image,
            "mimeType": mime_type,
            "isUserUploaded": True,
            "aspectRatio": aspect_ratio,
        },
        "clientContext": {
            "sessionId": session_id,
            "tool": "ASSET_MANAGER",
        },
    }


def build_payload_generate_reference_video(
    *,
    recaptcha_token: str,
    session_id: str,
    project_id: str,
    prompt: str,
    seed: Optional[int],
    video_model_key: str,
    reference_media_ids: List[str],
    scene_id: Optional[str] = None,
    aspect_ratio: str = VIDEO_ASPECT_RATIO_PORTRAIT,
    output_count: int = 1,
    account_type: Optional[str] = None,
    batch_id: Optional[str] = None,
    reference_audio_media_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây payload cho batchAsyncGenerateVideoReferenceImages (Reference Video).
    reference_audio_media_id: mediaId giọng (chữ thường), giống build_text_to_video_payload.
    """
    refs: List[Dict[str, Any]] = []
    for media_id in list(reference_media_ids or [])[:3]:
        mid = str(media_id or "").strip()
        if not mid:
            continue
        refs.append(
            {
                "mediaId": mid,
                "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
            }
        )

    if not refs:
        raise ValueError("reference_media_ids is required")

    user_paygate_tier = _user_paygate_tier(account_type)

    request_item: Dict[str, Any] = {
        "aspectRatio": aspect_ratio,
        "seed": int(seed or DEFAULT_SEED),
        "textInput": {
            "structuredPrompt": {
                "parts": [
                    {
                        "text": str(prompt or ""),
                    }
                ]
            }
        },
        "videoModelKey": str(video_model_key or "").strip(),
        "metadata": {},
        "referenceImages": refs,
    }

    if reference_audio_media_id:
        mid = str(reference_audio_media_id or "").strip().lower()
        if mid:
            request_item["referenceAudio"] = [{"mediaId": mid}]

    if scene_id:
        request_item["metadata"]["sceneId"] = str(scene_id)

    count = int(output_count or 1)
    if count < 1:
        count = 1

    requests = [json.loads(json.dumps(request_item)) for _ in range(count)]

    payload: Dict[str, Any] = {
        "clientContext": {
            "projectId": str(project_id or ""),
            "tool": "PINHOLE",
            "userPaygateTier": user_paygate_tier,
            "sessionId": str(session_id or ""),
            "recaptchaContext": {
                "token": str(recaptcha_token or ""),
                "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            },
        },
        "mediaGenerationContext": {
            "batchId": str(batch_id or uuid.uuid4()),
        },
        "requests": requests,
    }

    return payload


async def _send_request_via_browser(
    page: Page,
    url: str,
    payload: Dict[str, Any],
    access_token: str,
) -> Dict[str, Any]:
    data = json.dumps(payload)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    try:
        response = await page.request.post(
            url,
            data=data,
            headers=headers,
        )
        body = await response.text()
        return {
            "ok": response.ok,
            "url": url,
            "status": response.status,
            "reason": response.status_text,
            "headers": dict(response.headers),
            "body": body,
        }
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "error": str(exc),
        }


async def request_upload_user_image_via_browser(
    page: Page,
    payload: Dict[str, Any],
    access_token: str,
) -> Dict[str, Any]:
    """
    Upload ảnh tham chiếu qua endpoint v1:uploadUserImage (Reference Video).
    """
    return await _send_request_via_browser(
        page,
        URL_UPLOAD_USER_IMAGE,
        payload,
        access_token,
    )


async def request_create_reference_video_via_browser(
    page: Page,
    payload: Dict[str, Any],
    access_token: str,
) -> Dict[str, Any]:
    """
    Gửi request tạo video reference qua batchAsyncGenerateVideoReferenceImages.
    """
    return await _send_request_via_browser(
        page,
        URL_GENERATE_REFERENCE_VIDEO,
        payload,
        access_token,
    )


async def request_check_reference_status_via_browser(
    page: Page,
    payload: Dict[str, Any],
    access_token: str,
) -> Dict[str, Any]:
    """
    Poll status cho video reference qua batchCheckAsyncVideoGenerationStatus.
    """
    return await _send_request_via_browser(
        page,
        URL_STATUS_REFERENCE_VIDEO,
        payload,
        access_token,
    )


def parse_operations_from_reference_response(response_body: str) -> List[Dict[str, Any]]:
    try:
        body_json = json.loads(response_body or "")
    except Exception:
        return []
    ops = body_json.get("operations", [])
    return ops if isinstance(ops, list) else []


def extract_media_from_reference_status_op(op: Dict[str, Any]) -> Tuple[str, str]:
    """
    Trích video/image URL từ 1 operation trong response check status reference.
    Trả về (video_url, image_url/serving_base_uri).
    """
    operation = op.get("operation", {}) if isinstance(op.get("operation"), dict) else {}
    metadata = operation.get("metadata", {}) if isinstance(operation.get("metadata"), dict) else {}
    video = metadata.get("video", {}) if isinstance(metadata.get("video"), dict) else {}
    fife_url = str(video.get("fifeUrl") or "") or ""
    serving_base_uri = str(video.get("servingBaseUri") or "") or ""
    image = metadata.get("image", {}) if isinstance(metadata.get("image"), dict) else {}
    image_url = str(image.get("fifeUrl") or "" or image.get("uri") or "")
    return fife_url, (image_url or serving_base_uri)


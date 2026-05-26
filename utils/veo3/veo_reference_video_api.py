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


def normalize_ui_ratio_to_video_aspect(ratio: Optional[str]) -> str:
    """
    Map tỷ lệ UI → aspectRatio trong payload generate video.

    - 16:9 → VIDEO_ASPECT_RATIO_LANDSCAPE
    - 9:16 → VIDEO_ASPECT_RATIO_PORTRAIT

    Luôn truyền field ``aspectRatio`` trên mỗi request (mọi tier: lite / fast / quality),
    kể cả khi videoModelKey đã có landscape/portrait trong tên.
    """
    r = str(ratio or "").strip().lower().replace(" ", "").replace("/", ":")
    if r in ("16:9", "169"):
        return VIDEO_ASPECT_RATIO_LANDSCAPE
    if r in ("9:16", "916"):
        return VIDEO_ASPECT_RATIO_PORTRAIT
    return VIDEO_ASPECT_RATIO_LANDSCAPE

# Veo 3.1 r2v — không dùng biến thể *_4s / *_6s (chỉ UI 4 tier + aspectRatio)
VEO_MODELS: Dict[str, str] = {
    # FAST (Normal / Pro)
    "fast_landscape": "veo_3_1_r2v_fast_landscape",
    "fast_portrait": "veo_3_1_r2v_fast_portrait",
    # FAST ULTRA
    "fast_ultra_landscape": "veo_3_1_r2v_fast_landscape_ultra",
    "fast_ultra_portrait": "veo_3_1_r2v_fast_portrait_ultra",
    # FAST ULTRA RELAXED (không map UI mặc định; dùng khi gọi API trực tiếp)
    "fast_ultra_landscape_relaxed": "veo_3_1_r2v_fast_landscape_ultra_relaxed",
    "fast_ultra_portrait_relaxed": "veo_3_1_r2v_fast_portrait_ultra_relaxed",
    # QUALITY
    "quality_landscape": "veo_3_1_r2v",
    "quality_portrait": "veo_3_1_r2v_portrait",
    # LITE — tỷ lệ qua aspectRatio trong payload
    "lite": "veo_3_1_r2v_lite",
    # LOW PRIORITY (UI: Lite [Lower Priority])
    "lite_low": "veo_3_1_r2v_lite_low_priority",
}

# Alias tương thích import cũ
MODEL_KEY_LITE = VEO_MODELS["lite"]
MODEL_KEY_LITE_LOW_PRIORITY = VEO_MODELS["lite_low"]
MODEL_KEY_QUALITY_LANDSCAPE = VEO_MODELS["quality_landscape"]
MODEL_KEY_QUALITY_PORTRAIT = VEO_MODELS["quality_portrait"]
MODEL_KEY_FAST_ULTRA_LANDSCAPE = VEO_MODELS["fast_ultra_landscape"]
MODEL_KEY_FAST_ULTRA_PORTRAIT = VEO_MODELS["fast_ultra_portrait"]
MODEL_KEY_FAST_LANDSCAPE = VEO_MODELS["fast_landscape"]
MODEL_KEY_FAST_PORTRAIT = VEO_MODELS["fast_portrait"]
MODEL_KEY_ULTRA_LANDSCAPE = VEO_MODELS["fast_ultra_landscape"]
MODEL_KEY_PORTRAIT_ULTRA = VEO_MODELS["fast_ultra_portrait"]
MODEL_KEY_LANDSCAPE_NORMAL_PRO = VEO_MODELS["fast_landscape"]
MODEL_KEY_PORTRAIT_NORMAL_PRO = VEO_MODELS["fast_portrait"]
MODEL_KEY_LANDSCAPE_QUALITY = VEO_MODELS["quality_landscape"]
MODEL_KEY_PORTRAIT_QUALITY = VEO_MODELS["quality_portrait"]
MODEL_KEY_ULTRA_LANDSCAPE_RELAXED = VEO_MODELS["fast_ultra_landscape_relaxed"]
MODEL_KEY_PORTRAIT_ULTRA_RELAXED = VEO_MODELS["fast_ultra_portrait_relaxed"]

R2V_MODEL_KEYS_USE_ASPECT_RATIO_PARAM = frozenset(
    {VEO_MODELS["lite"], VEO_MODELS["lite_low"]}
)


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


def _parse_frontend_r2v_tier(label: str) -> str:
    """
    Map nhãn UI → một trong: lite_priority | lite | fast | quality.
    """
    if not label:
        return "lite_priority"
    if "quality" in label:
        return "quality"
    if "fast" in label and "lite" not in label:
        return "fast"
    if "lite" in label and "priority" in label:
        return "lite_priority"
    if label == "veo 3.1 - lite" or ("lite" in label and "priority" not in label):
        return "lite"
    return "lite_priority"


def _r2v_model_from_veo_models(
    *,
    tier: str,
    is_portrait: bool,
    account_type: str,
) -> str:
    """Chọn key trong VEO_MODELS theo tier UI + 9:16/16:9 + loại tài khoản."""
    if tier == "lite_priority":
        return VEO_MODELS["lite_low"]
    if tier == "lite":
        return VEO_MODELS["lite"]
    if tier == "quality":
        return VEO_MODELS["quality_portrait"] if is_portrait else VEO_MODELS["quality_landscape"]
    # fast
    if account_type == "ULTRA":
        return (
            VEO_MODELS["fast_ultra_portrait"]
            if is_portrait
            else VEO_MODELS["fast_ultra_landscape"]
        )
    return VEO_MODELS["fast_portrait"] if is_portrait else VEO_MODELS["fast_landscape"]


def select_reference_video_model_key(
    *,
    aspect_ratio: str,
    frontend_model_label: Optional[str],
    account_type: Optional[str],
) -> str:
    """
    Chọn videoModelKey r2v (VEO_MODELS) theo 4 tier UI × 16:9 / 9:16.

    | UI | VEO_MODELS key | Ghi chú |
    |----|----------------|---------|
    | Lite [Lower Priority] | lite_low | + aspectRatio |
    | Lite | lite | + aspectRatio |
    | Fast + ULTRA | fast_ultra_landscape / fast_ultra_portrait | trong id model |
    | Fast + Normal/Pro | fast_landscape / fast_portrait | trong id model |
    | Quality | quality_landscape / quality_portrait | portrait có _portrait |
    """
    label = _normalize_model_label(frontend_model_label)
    tier = _parse_frontend_r2v_tier(label)
    acc = _normalize_account_type(account_type)
    is_portrait = aspect_ratio == VIDEO_ASPECT_RATIO_PORTRAIT
    return _r2v_model_from_veo_models(tier=tier, is_portrait=is_portrait, account_type=acc)


def r2v_model_uses_aspect_ratio_param(video_model_key: str) -> bool:
    """
    True nếu tỷ lệ KHÔNG nằm trong videoModelKey (lite / lite_low).
    Fast & Quality vẫn bắt buộc truyền aspectRatio trong payload — chỉ khác là
    model id cũng có landscape/portrait.
    """
    return str(video_model_key or "").strip() in R2V_MODEL_KEYS_USE_ASPECT_RATIO_PARAM


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
    aspect_ratio: str = VIDEO_ASPECT_RATIO_LANDSCAPE,
    output_count: int = 1,
    account_type: Optional[str] = None,
    batch_id: Optional[str] = None,
    reference_audio_media_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây payload cho batchAsyncGenerateVideoReferenceImages (Reference Video).

    Mỗi phần tử requests[] luôn có aspectRatio:
    VIDEO_ASPECT_RATIO_LANDSCAPE (16:9) hoặc VIDEO_ASPECT_RATIO_PORTRAIT (9:16).

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


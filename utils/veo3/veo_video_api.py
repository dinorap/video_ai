import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Page  # type: ignore

URL_GENERATE_TEXT_TO_VIDEO = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoText"
URL_STATUS_TEXT_TO_VIDEO = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"

VIDEO_ASPECT_RATIO_LANDSCAPE = "VIDEO_ASPECT_RATIO_LANDSCAPE"
VIDEO_ASPECT_RATIO_PORTRAIT = "VIDEO_ASPECT_RATIO_PORTRAIT"

# Model keys giống API_text_to_video
DEFAULT_VIDEO_MODEL_KEY_ULTRA = "veo_3_1_t2v_fast_ultra"
DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_ULTRA = "veo_3_1_t2v_fast_portrait_ultra"
DEFAULT_VIDEO_MODEL_KEY_ULTRA_RELAXED = "veo_3_1_t2v_fast_ultra_relaxed"
DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_ULTRA_RELAXED = "veo_3_1_t2v_fast_portrait_ultra_relaxed"
DEFAULT_VIDEO_MODEL_KEY_NORMAL = "veo_3_1_t2v_fast"
DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_NORMAL = "veo_3_1_t2v_fast_portrait"

# Quality model (không fast)
DEFAULT_VIDEO_MODEL_KEY_QUALITY = "veo_3_1_t2v"
DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_QUALITY = "veo_3_1_t2v_portrait"


def _normalize_account_type(value: Optional[str]) -> str:
    v = str(value or "").strip().upper()
    return v if v in {"NORMAL", "PRO", "ULTRA"} else "ULTRA"


def _user_paygate_tier(account_type: Optional[str]) -> str:
    t = _normalize_account_type(account_type)
    if t == "NORMAL":
        return "PAYGATE_TIER_NOT_PAID"
    if t == "PRO":
        return "PAYGATE_TIER_ONE"
    return "PAYGATE_TIER_TWO"


def _normalize_model_label(model: Optional[str]) -> str:
    if not isinstance(model, str):
        return ""
    return " ".join(model.strip().lower().split())


def _resolve_video_model_key_from_frontend(
    model: Optional[str],
    aspect_ratio: str,
    account_type: Optional[str],
) -> str:
    """
    Map label model từ frontend sang videoModelKey:
    - "veo 3.1 - lite"                        -> fast NORMAL (portrait/landscape)
    - "veo 3.1 - lite [lower/low priority]" -> giống fast low priority: relaxed ULTRA, NORMAL/PRO giữ lite
    - "veo 3.1 - fast"                        -> fast (ULTRA)
    - legacy fast priority label             -> fast_ultra_relaxed
    - "veo 3.1 - quality"                     -> quality keys
    Nếu không khớp, fallback về ULTRA theo aspect_ratio.
    """
    label = _normalize_model_label(model)
    is_portrait = aspect_ratio == VIDEO_ASPECT_RATIO_PORTRAIT
    acc = _normalize_account_type(account_type)

    # Default UI mới: "Veo 3.1 - Lite [Lower Priority]".
    if not label:
        if acc == "ULTRA":
            return (
                DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_ULTRA_RELAXED
                if is_portrait
                else DEFAULT_VIDEO_MODEL_KEY_ULTRA_RELAXED
            )
        return DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_NORMAL if is_portrait else DEFAULT_VIDEO_MODEL_KEY_NORMAL

    # "Veo 3.1 - Lite [Lower Priority]" / "[Low Priority]" (UI Flow dùng Lower)
    if "veo 3.1 - lite" in label and "priority" in label:
        if acc == "ULTRA":
            return (
                DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_ULTRA_RELAXED
                if is_portrait
                else DEFAULT_VIDEO_MODEL_KEY_ULTRA_RELAXED
            )
        return DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_NORMAL if is_portrait else DEFAULT_VIDEO_MODEL_KEY_NORMAL

    # "Veo 3.1 - Lite"
    if label == "veo 3.1 - lite":
        return DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_NORMAL if is_portrait else DEFAULT_VIDEO_MODEL_KEY_NORMAL

    # "Veo 3.1 - Fast"
    if label == "veo 3.1 - fast":
        # NORMAL/PRO dùng fast thường, ULTRA dùng fast_ultra
        if acc == "ULTRA":
            return DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_ULTRA if is_portrait else DEFAULT_VIDEO_MODEL_KEY_ULTRA
        return DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_NORMAL if is_portrait else DEFAULT_VIDEO_MODEL_KEY_NORMAL

    # Legacy fast priority labels (normalize)
    if "veo 3.1 - fast" in label and "priority" in label:
        # Chỉ ULTRA mới có relaxed; tài khoản khác fallback về fast thường
        if acc == "ULTRA":
            return (
                DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_ULTRA_RELAXED
                if is_portrait
                else DEFAULT_VIDEO_MODEL_KEY_ULTRA_RELAXED
            )
        return DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_NORMAL if is_portrait else DEFAULT_VIDEO_MODEL_KEY_NORMAL
    if label == "veo 3.1 - quality":
        return (
            DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_QUALITY
            if is_portrait
            else DEFAULT_VIDEO_MODEL_KEY_QUALITY
        )

    # Fallback: ULTRA theo aspect ratio
    return DEFAULT_VIDEO_MODEL_KEY_PORTRAIT_ULTRA if is_portrait else DEFAULT_VIDEO_MODEL_KEY_ULTRA


def build_text_to_video_payload(
    prompt: str,
    session_id: str,
    project_id: str,
    recaptcha_token: str,
    *,
    scene_id: Optional[str] = None,
    frontend_model: Optional[str] = None,
    aspect_ratio: str = VIDEO_ASPECT_RATIO_LANDSCAPE,
    output_count: int = 1,
    account_type: Optional[str] = None,
    reference_media_ids: Optional[List[str]] = None,
    reference_audio_media_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Xây payload batchAsyncGenerateVideoText giống API_text_to_video:
    - Có clientContext.userPaygateTier
    - Chọn videoModelKey dựa vào nhãn model từ frontend + aspect_ratio.
    """
    model_key = _resolve_video_model_key_from_frontend(frontend_model, aspect_ratio, account_type)
    user_paygate_tier = _user_paygate_tier(account_type)

    # Log debug: loại tài khoản, model key, tier đang dùng
    try:
        print(
            "[VEO Video API] account_type="
            f"{_normalize_account_type(account_type)} | "
            f"model_label={_normalize_model_label(frontend_model)} | "
            f"videoModelKey={model_key} | "
            f"userPaygateTier={user_paygate_tier}"
        )
    except Exception:
        pass

    base: Dict[str, Any] = {
        "clientContext": {
            "recaptchaContext": {
                "token": recaptcha_token,
                "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            },
            "sessionId": session_id,
            "projectId": project_id,
            "tool": "PINHOLE",
            "userPaygateTier": user_paygate_tier,
        },
        "requests": [
            {
                "aspectRatio": aspect_ratio,
                "seed": 9797,
                "textInput": {
                    "prompt": prompt,
                },
                "videoModelKey": model_key,
                "metadata": {
                    # sceneId sẽ được set ở dưới
                },
            }
        ],
    }

    req = base["requests"][0]
    if scene_id:
        req["metadata"]["sceneId"] = str(scene_id)
    else:
        req["metadata"]["sceneId"] = str(uuid.uuid4())

    # Thêm referenceImages nếu có media_id (ảnh tham chiếu upload qua API_uploadImage)
    refs: List[Dict[str, Any]] = []
    for mid in (reference_media_ids or [])[:3]:
        m = str(mid or "").strip()
        if not m:
            continue
        refs.append(
            {
                "mediaId": m,
                "imageUsageType": "IMAGE_USAGE_TYPE_ASSET",
            }
        )
    if refs:
        req["referenceImages"] = refs

    # Thêm referenceAudio nếu có mediaId giọng (đồng nhất giọng nhân vật).
    if reference_audio_media_id:
        mid = str(reference_audio_media_id or "").strip().lower()
        if mid:
            req["referenceAudio"] = [{"mediaId": mid}]

    count = output_count if isinstance(output_count, int) and output_count > 0 else 1
    base["requests"] = [json.loads(json.dumps(req)) for _ in range(count)]
    return base


async def request_create_video_via_browser(
    page: Page,
    url: str,
    payload: Dict[str, Any],
    access_token: str,
) -> Dict[str, Any]:
    """Gửi request tạo video qua Playwright page.request.post (giống API_text_to_video)."""
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
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "ok": False,
            "url": url,
            "error": str(exc),
        }


async def request_check_status_via_browser(
    page: Page,
    payload: Dict[str, Any],
    access_token: str,
) -> Dict[str, Any]:
    """Gửi request check status qua browser, dùng cùng access_token."""
    data = json.dumps(payload)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    try:
        response = await page.request.post(
            URL_STATUS_TEXT_TO_VIDEO,
            data=data,
            headers=headers,
        )
        body = await response.text()
        return {
            "ok": response.ok,
            "url": URL_STATUS_TEXT_TO_VIDEO,
            "status": response.status,
            "reason": response.status_text,
            "headers": dict(response.headers),
            "body": body,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "ok": False,
            "url": URL_STATUS_TEXT_TO_VIDEO,
            "error": str(exc),
        }


def parse_operations_from_create_response(response_body: str) -> List[Dict[str, Any]]:
    try:
        body_json = json.loads(response_body or "")
    except Exception:
        return []
    ops = body_json.get("operations", [])
    return ops if isinstance(ops, list) else []


def extract_media_from_status_op(op: Dict[str, Any]) -> Tuple[str, str]:
    """
    Trích video/image URL từ 1 operation trong response check status.
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


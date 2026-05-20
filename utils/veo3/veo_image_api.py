import json
import random
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

# =========================
# VEO Image API (no RUN_VEO dependency)
# =========================

# Endpoint template: projectId must be injected per request
URL_GENERATE_IMAGES_TEMPLATE = (
    "https://aisandbox-pa.googleapis.com/v1/projects/{project_id}/flowMedia:batchGenerateImages"
)

IMAGE_ASPECT_RATIO_LANDSCAPE = "IMAGE_ASPECT_RATIO_LANDSCAPE"
IMAGE_ASPECT_RATIO_PORTRAIT = "IMAGE_ASPECT_RATIO_PORTRAIT"
IMAGE_ASPECT_RATIO_SQUARE = "IMAGE_ASPECT_RATIO_SQUARE"
# Khớp Flow UI (LANDSCAPE_4_3 / PORTRAIT_3_4) — batchGenerateImages enum
IMAGE_ASPECT_RATIO_LANDSCAPE_4_3 = "IMAGE_ASPECT_RATIO_LANDSCAPE_4_3"
IMAGE_ASPECT_RATIO_PORTRAIT_3_4 = "IMAGE_ASPECT_RATIO_PORTRAIT_3_4"


def image_aspect_const_from_ui_ratio(ratio: Optional[str]) -> str:
    """Map tỉ lệ sidebar (16:9, 4:3, …) sang imageAspectRatio API."""
    if not ratio:
        return IMAGE_ASPECT_RATIO_LANDSCAPE
    r = str(ratio).strip().lower().replace(" ", "").replace("/", ":")
    table = {
        "16:9": IMAGE_ASPECT_RATIO_LANDSCAPE,
        "169": IMAGE_ASPECT_RATIO_LANDSCAPE,
        "9:16": IMAGE_ASPECT_RATIO_PORTRAIT,
        "916": IMAGE_ASPECT_RATIO_PORTRAIT,
        "4:3": IMAGE_ASPECT_RATIO_LANDSCAPE_4_3,
        "43": IMAGE_ASPECT_RATIO_LANDSCAPE_4_3,
        "1:1": IMAGE_ASPECT_RATIO_SQUARE,
        "11": IMAGE_ASPECT_RATIO_SQUARE,
        "3:4": IMAGE_ASPECT_RATIO_PORTRAIT_3_4,
        "34": IMAGE_ASPECT_RATIO_PORTRAIT_3_4,
    }
    return table.get(r, IMAGE_ASPECT_RATIO_LANDSCAPE)

# Mapping từ UI/label -> model key mà API nhận
# Hỗ trợ cả variant có emoji và không có emoji
CREATE_IMAGE_MODEL_TO_KEY = {
    "Nano Banana pro": "GEM_PIX_2",
    "🍌 Nano Banana Pro": "GEM_PIX_2",  # UI hiển thị với emoji và chữ P hoa
    "Nano Banana 2": "NARWHAL",
    "🍌 Nano Banana 2": "NARWHAL",
    "Imagen 4": "IMAGEN_3_5",
}


def build_generate_image_url(project_id: str) -> str:
    encoded_project = quote(str(project_id or ""), safe="")
    return URL_GENERATE_IMAGES_TEMPLATE.format(project_id=encoded_project)


def _clone_payload_template() -> dict:
    # Template tối thiểu đủ dùng cho flowMedia:batchGenerateImages
    return {
        "clientContext": {
            "recaptchaContext": {
                "token": "",
                "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            },
            "sessionId": "",
            "projectId": "",
            "tool": "PINHOLE",
        },
        "mediaGenerationContext": {
            "batchId": "",
        },
        "useNewMedia": True,
        "requests": [
            {
                "clientContext": {
                    "recaptchaContext": {
                        "token": "",
                        "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
                    },
                    "sessionId": "",
                    "projectId": "",
                    "tool": "PINHOLE",
                },
                "imageAspectRatio": IMAGE_ASPECT_RATIO_LANDSCAPE,
                "seed": 0,
                "imageModelName": "",
                "prompt": "",
                "imageInputs": [],
            }
        ],
    }


def build_generate_image_payload(
    prompt: str,
    session_id: str,
    project_id: str,
    recaptcha_token: str,
    *,
    seed: Optional[int] = None,
    model_key: Optional[str] = None,
    aspect_ratio: str = IMAGE_ASPECT_RATIO_LANDSCAPE,
    output_count: int = 1,
    reference_input_names: Optional[List[str]] = None,
) -> dict:
    payload = _clone_payload_template()
    payload["clientContext"]["recaptchaContext"]["token"] = recaptcha_token
    payload["clientContext"]["sessionId"] = session_id
    payload["clientContext"]["projectId"] = project_id
    payload["mediaGenerationContext"] = {"batchId": str(uuid.uuid4())}
    payload["useNewMedia"] = True

    request_item = payload["requests"][0]
    request_item["clientContext"] = json.loads(json.dumps(payload["clientContext"]))
    request_item["clientContext"]["recaptchaContext"]["token"] = recaptcha_token
    if aspect_ratio:
        request_item["imageAspectRatio"] = aspect_ratio

    effective_seed = int(seed) if seed is not None else random.randint(0, 294967295)
    request_item["seed"] = effective_seed

    if model_key:
        request_item["imageModelName"] = str(model_key)

    ref_names = [
        str(x or "").strip()
        for x in list(reference_input_names or [])
        if str(x or "").strip()
    ]
    if ref_names:
        request_item["structuredPrompt"] = {"parts": [{"text": str(prompt or "")}]}
        request_item.pop("prompt", None)
        request_item["imageInputs"] = [
            {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": ref_name}
            for ref_name in ref_names
        ]
    else:
        request_item["prompt"] = prompt
        request_item.pop("structuredPrompt", None)
        if "imageInputs" not in request_item or request_item["imageInputs"] is None:
            request_item["imageInputs"] = []

    count = output_count if isinstance(output_count, int) and output_count > 0 else 1
    requests_list = []
    for i in range(count):
        copied = json.loads(json.dumps(request_item))
        if i > 0:
            copied["seed"] = (effective_seed + i) % 294967296
        requests_list.append(copied)
    payload["requests"] = requests_list
    return payload


async def request_generate_images_via_browser(
    page: Any,
    url: str,
    payload: dict,
    access_token: str,
    timeout_ms: int = 30_000,
) -> Dict[str, Any]:
    """Gửi request tạo ảnh qua browser (Playwright page.request API) với Bearer token."""
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        data = json.dumps(payload)

        response = await page.request.post(
            url,
            data=data,
            headers=headers,
            timeout=int(timeout_ms or 30_000),
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


def parse_media_from_response(response_body: str) -> List[dict]:
    try:
        body_json = json.loads(response_body)
    except Exception:
        return []

    medias: List[dict] = []

    def _collect(obj: Any) -> None:
        if isinstance(obj, dict):
            url = obj.get("downloadUrl") or obj.get("uri") or obj.get("fifeUrl")
            if url:
                medias.append(
                    {
                        "mediaId": obj.get("mediaId")
                        or obj.get("mediaGenerationId")
                        or obj.get("name"),
                        "downloadUrl": url,
                        "mimeType": obj.get("mimeType"),
                    }
                )
            for value in obj.values():
                _collect(value)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item)

    _collect(body_json)
    return medias


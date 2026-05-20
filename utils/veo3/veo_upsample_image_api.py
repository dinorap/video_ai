import json
from typing import Any, Dict, Optional

from playwright.async_api import Page  # type: ignore


URL_UPSAMPLE_IMAGE = "https://aisandbox-pa.googleapis.com/v1/flow/upsampleImage"


async def request_upsample_image_via_browser(
    page: Page,
    *,
    media_id: str,
    recaptcha_token: str,
    session_id: str,
    project_id: str,
    access_token: str,
    user_paygate_tier: str = "PAYGATE_TIER_TWO",
    tool: str = "PINHOLE",
    target_resolution: str = "UPSAMPLE_IMAGE_RESOLUTION_2K",
    timeout_ms: int = 60_000,
) -> Dict[str, Any]:
    """
    Call Flow upscale image endpoint.

    Returns:
      { ok, status, body, json } or { ok: False, error }
    """
    payload = {
        "mediaId": str(media_id),
        "targetResolution": str(target_resolution),
        "clientContext": {
            "recaptchaContext": {
                "token": str(recaptcha_token),
                "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            },
            "projectId": str(project_id),
            "tool": str(tool),
            "userPaygateTier": str(user_paygate_tier),
            "sessionId": str(session_id),
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    try:
        # Use data= to be compatible with Playwright versions
        data = json.dumps(payload, ensure_ascii=False)
        resp = await page.request.post(
            URL_UPSAMPLE_IMAGE,
            data=data,
            headers=headers,
            timeout=int(timeout_ms),
        )
        body_text = await resp.text()
        body_json: Optional[dict] = None
        try:
            body_json = await resp.json()
        except Exception:
            body_json = None
        return {
            "ok": bool(resp.ok),
            "status": int(resp.status),
            "body": body_text,
            "json": body_json,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


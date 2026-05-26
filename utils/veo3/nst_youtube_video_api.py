import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Page  # type: ignore

from services_api.veo_get_token import (  # type: ignore
    load_veo_auth_config,
    auto_collect_veo_auth_from_flow,
    fetch_recaptcha_token_via_page,
)
from services_api.veo_video_api import (  # type: ignore
    VIDEO_ASPECT_RATIO_LANDSCAPE,
    VIDEO_ASPECT_RATIO_PORTRAIT,
    URL_GENERATE_TEXT_TO_VIDEO,
    build_text_to_video_payload,
    request_create_video_via_browser,
    request_check_status_via_browser,
    parse_operations_from_create_response,
    extract_media_from_status_op,
)
from services_api.veo_reference_image_api import (  # type: ignore
    build_payload_upload_image,
    request_upload_image_via_browser,
    extract_media_id,
)
from services_api.character_reference_media import (  # type: ignore
    CAST_REFERENCE_MEDIA_META_KEY,
    build_profiles_with_media_ids,
    enrich_scene_tasks_with_cast_references,
    load_cast_profiles_from_script,
    resolve_cast_reference_media_for_profile,
)
from services_api.veo_reference_video_api import (  # type: ignore
    URL_GENERATE_REFERENCE_VIDEO,
    build_payload_generate_reference_video,
    parse_operations_from_reference_response,
    extract_media_from_reference_status_op,
    request_create_reference_video_via_browser,
    request_check_reference_status_via_browser,
    select_reference_video_model_key,
)
from services.nst_browser import NSTBrowserManager  # type: ignore
from services.config_loader import get_settings  # type: ignore
from services.browser_engine import get_ws_endpoint_for_profile, profile_pool_for_run, is_chrome_local  # type: ignore
from services.nst_flow import (  # type: ignore
    _build_profile_api_key_map,
    _stop_profiles_by_key,
    _filter_scenes_by_range,
    _STOP_SIGNAL,
    _RUNNING_LOOPS,
    _RUNNING_LOOPS_LOCK,
    _resolve_script_path,
    update_scene_status,
    set_script_running_state,
    set_script_run_finished,
    _wait_for_profiles_ready,
    _goto_flow_with_profile_cache,
    _ensure_profiles_started,
)
from services.flow_actions import (  # type: ignore
    connect_and_get_page,
    cleanup_browser,
    detach_browser_session,
    select_mode,
    setup_render_settings,
    clamp_aspect_ratio_for_flow_video,
)


TIMEOUT_VIDEO_STATUS = 420  # tổng thời gian tối đa chờ 1 scene hoàn tất (giây)
STATUS_POLL_INTERVAL = 6
WAIT_BETWEEN_TOKEN_SECONDS = 30.0  # Video: ép mỗi 30s mới bắn prompt 'a' để lấy token 1 lần
DEFAULT_VEO_MODEL_LABEL = "Veo 3.1 - Lite [Lower Priority]"


def _video_aspect_ratio_from_str(ratio: Optional[str]) -> str:
    r = (ratio or "").strip().lower().replace(" ", "").replace("/", ":")
    if r in ("9:16", "916", "portrait", "doc", "dọc", "3:4", "34"):
        return VIDEO_ASPECT_RATIO_PORTRAIT
    return VIDEO_ASPECT_RATIO_LANDSCAPE


def _normalize_requested_veo_model(model: Optional[str]) -> str:
    requested = str(model or "").strip()
    requested_lower = requested.lower()
    if (
        not requested
        or ("veo 3.1 - fast" in requested_lower and "priority" in requested_lower)
    ):
        return DEFAULT_VEO_MODEL_LABEL
    return requested


async def _detect_account_type_from_page(page: Page) -> str:
    """
    Detect loại tài khoản (NORMAL/PRO/ULTRA) trực tiếp từ UI Flow cho MỖI profile,
    giống login.py nhưng không lưu vào config, chỉ trả về string.
    """
    account_type = "ULTRA"
    try:
        btn = page.locator(
            "//button[.//img[contains(@alt, 'Hình ảnh hồ sơ người dùng')]]"
        )
        btn_count = 0
        for _ in range(5):
            try:
                btn_count = await btn.count()
            except Exception:
                btn_count = 0
            if btn_count > 0:
                break
            await asyncio.sleep(1)

        if btn_count > 0:
            ultra_div = btn.locator("xpath=.//div[normalize-space()='ULTRA']")
            pro_div = btn.locator("xpath=.//div[normalize-space()='PRO']")
            ultra_count = 0
            pro_count = 0
            try:
                ultra_count = await ultra_div.count()
            except Exception:
                ultra_count = 0
            try:
                pro_count = await pro_div.count()
            except Exception:
                pro_count = 0

            if pro_count > 0:
                account_type = "PRO"
            elif ultra_count > 0:
                account_type = "ULTRA"
            else:
                account_type = "NORMAL"
        else:
            account_type = "ULTRA"
    except Exception:
        account_type = "ULTRA"

    print(f"[VEO Video API] 🔎 Detect account_type từ UI: {account_type}")
    return account_type


def _load_auth_config(profile_id: str) -> Optional[dict]:
    return load_veo_auth_config(profile_id)


def _build_status_payload_from_create_response(create_body: str) -> List[Dict[str, Any]]:
    """
    Trích operation names từ response create/upscale, build payload cho batchCheckAsyncVideoGenerationStatus.
    Payload shape:
      {"operations":[{"sceneId":..., "status":"MEDIA_GENERATION_STATUS_ACTIVE", "operation":{"name":...}}]}
    """
    try:
        obj = json.loads(create_body or "")
    except Exception:
        return []

    ops = obj.get("operations", [])
    if not isinstance(ops, list):
        return []

    results: List[Dict[str, Any]] = []
    for item in ops:
        if not isinstance(item, dict):
            continue
        op = item.get("operation") if isinstance(item.get("operation"), dict) else {}
        name = (op or {}).get("name")
        scene_id = item.get("sceneId") or item.get("workflowId") or item.get("batchId")
        if name:
            results.append(
                {
                    "sceneId": str(scene_id or uuid.uuid4()),
                    "status": "MEDIA_GENERATION_STATUS_ACTIVE",
                    "operation": {"name": str(name)},
                }
            )
    return results


def _parse_video_urls_from_status_body(status_body: str) -> List[Tuple[str, str]]:
    """
    Return list of (video_url, image_url_or_serving_base_uri) from batchCheckAsyncVideoGenerationStatus.
    """
    try:
        obj = json.loads(status_body or "")
    except Exception:
        return []

    ops = obj.get("operations", [])
    if not isinstance(ops, list):
        return []

    out: List[Tuple[str, str]] = []
    for item in ops:
        if not isinstance(item, dict):
            continue
        v, img = extract_media_from_status_op(item)
        if v or img:
            out.append((v, img))
    return out


async def _wait_with_stop(total: float, *, step: float = 0.5) -> bool:
    end_ts = time.time() + max(0.0, total)
    while time.time() < end_ts:
        if _STOP_SIGNAL.is_set():
            return False
        await asyncio.sleep(min(step, max(0.05, end_ts - time.time())))
    return True


async def _restart_nst_profile_and_reconnect(
    nst: NSTBrowserManager,
    api_key_map: Dict[str, str],
    profile_id: str,
) -> Optional[Page]:
    if _STOP_SIGNAL.is_set():
        return None

    api_key = api_key_map.get(profile_id, "")
    settings_snap = get_settings() or {}

    try:
        print(f"[VEO Video API] 🔁 Restart NST profile {profile_id[-4:]}: stop_profiles...")
        _stop_profiles_by_key(nst, [profile_id], api_key_map)
    except Exception as e:
        print(f"[VEO Video API] ⚠️ stop_profiles {profile_id[-4:]} lỗi: {e}")

    if _STOP_SIGNAL.is_set():
        return None

    try:
        print(f"[VEO Video API] 🔁 Restart NST profile {profile_id[-4:]}: start_profiles...")
        _ensure_profiles_started(nst, [profile_id], api_key_map)
        await _wait_for_profiles_ready(nst, [profile_id], api_key_map)
    except Exception as e:
        print(f"[VEO Video API] ❌ start_profiles {profile_id[-4:]} lỗi: {e}")
        return None

    if _STOP_SIGNAL.is_set():
        return None

    ws = get_ws_endpoint_for_profile(nst, profile_id, api_key, settings=settings_snap)
    if not ws:
        print(f"[VEO Video API] ❌ Sau restart không lấy được WS cho {profile_id[-4:]}.")
        return None

    page = await connect_and_get_page(ws)
    if not page:
        print(f"[VEO Video API] ❌ Sau restart không connect được Playwright cho {profile_id[-4:]}")
        return None

    try:
        await _goto_flow_with_profile_cache(
            page,
            profile_id,
            stop_check=lambda: _STOP_SIGNAL.is_set(),
        )
    except Exception as e:
        print(f"[VEO Video API] ❌ goto_flow_with_profile_cache sau restart lỗi: {e}")
        return None

    return page


async def generate_youtube_videos_via_api_for_page(
    page: Page,
    scene_tasks: List[Dict[str, Any]],
    script_path: str,
    *,
    profile_id: str,
    ratio: str = "16:9",
    model: Optional[str] = None,
    timeout_status: int = TIMEOUT_VIDEO_STATUS,
    reference_image_path: Optional[str] = None,
    reference_audio_media_id: Optional[str] = None,
    use_cast_profile_references: bool = False,
    cast_reference_media_by_name: Optional[Dict[str, str]] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Tạo video YouTube bằng Text-to-Video API trên MỘT Flow Page (không ảnh tham chiếu).
    Mỗi scene -> 1 request + vòng poll status riêng, lưu video vào storage/projects/<project>/videos.
    """
    if not scene_tasks:
        return {}

    auth = _load_auth_config(profile_id)
    if not auth:
        await auto_collect_veo_auth_from_flow(page, profile_id=profile_id)
        auth = _load_auth_config(profile_id)
    if not auth:
        print("[VEO Video API] ❌ Thiếu sessionId/projectId/access_token.")
        return {i + 1: {"ok": False, "error": "missing_auth_config"} for i in range(len(scene_tasks))}

    session_id = auth["sessionId"]
    project_id = auth["projectId"]
    access_token = auth["access_token"]

    video_aspect_ratio = _video_aspect_ratio_from_str(ratio)
    effective_model = _normalize_requested_veo_model(model)

    # Tab NEW: upload batch; mỗi profile nhớ media_id riêng (RAM).
    cast_media_by_name: Dict[str, str] = dict(cast_reference_media_by_name or {})
    if use_cast_profile_references:
        cast_media_by_name, upload_err = await resolve_cast_reference_media_for_profile(
            page,
            script_path,
            profile_id=profile_id,
            project_id=str(project_id),
            access_token=access_token,
            cache=cast_media_by_name,
            log_prefix="VEO Video API",
        )
        if upload_err:
            print(
                f"[VEO Video API] [{profile_id[-4:]}] ❌ Cast reference upload: {upload_err}"
            )
            return {
                i + 1: {"ok": False, "error": upload_err} for i in range(len(scene_tasks))
            }
        raw_profiles, _ = load_cast_profiles_from_script(script_path)
        profiles_with_media = build_profiles_with_media_ids(raw_profiles, cast_media_by_name)
        enrich_scene_tasks_with_cast_references(scene_tasks, profiles_with_media)
        print(
            f"[VEO Video API] [{profile_id[-4:]}] 🖼️ Cast refs ready "
            f"({len(cast_media_by_name)} media_id cho profile này)"
        )

    # Cũ: upload master_image_url 1 lần để lấy media_id
    reference_media_id: Optional[str] = None
    if reference_image_path and not use_cast_profile_references:
        try:
            payload_image = build_payload_upload_image(
                image_path=reference_image_path,
                project_id=project_id,
            )
            print(f"[VEO Video API] 📤 Upload reference image via API: {reference_image_path}")
            upload_res = await request_upload_image_via_browser(page, payload_image, access_token, timeout_ms=60_000)
            if upload_res.get("ok"):
                body = str(upload_res.get("body") or "")
                mid = extract_media_id(body)
                if mid:
                    reference_media_id = mid
                    print(f"[VEO Video API] ✅ Reference image uploaded, media_id={reference_media_id}")
                else:
                    print("[VEO Video API] ⚠️ Upload image OK nhưng không trích được media_id.")
            else:
                print(
                    f"[VEO Video API] ❌ Upload reference image failed: "
                    f"status={upload_res.get('status')} body={str(upload_res.get('body') or '')[:160]}"
                )
        except Exception as e:
            print(f"[VEO Video API] ❌ Exception while uploading reference image: {e}")

    # Detect loại tài khoản riêng cho từng profile (không lưu config)
    account_type = await _detect_account_type_from_page(page)

    # Batch id cho reference video (đúng payload thực tế: mediaGenerationContext.batchId)
    batch_id_for_reference = str(uuid.uuid4())

    abs_script_path = _resolve_script_path(script_path)
    if not abs_script_path or not os.path.exists(abs_script_path):
        return {"error": f"File không tồn tại: {script_path} (resolved: {abs_script_path})"}

    script_name = Path(abs_script_path).stem
    project_dir = Path(abs_script_path).resolve().parents[1]
    # Lưu video theo từng "sản phẩm" (script) riêng: videos/<script_name>/scene.mp4
    videos_output_dir = project_dir / "videos" / script_name
    videos_output_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[int, Dict[str, Any]] = {}

    # Giới hạn số scene video đang xử lý song song trên MỘT Flow page (tương tự max_in_flight của image)
    max_in_flight = 3
    semaphore = asyncio.Semaphore(max_in_flight)
    pending_tasks: List[asyncio.Task] = []
    # Chia sẻ mốc thời gian lần cuối gửi prompt "a" để lấy recaptcha token (toàn page/profile)
    token_lock = asyncio.Lock()
    last_token_sent_ts: List[float] = []  # dùng list để pass-by-ref

    async def _rate_limited_fetch_token(*, ptag: str, label: str, timeout_s: int) -> Optional[str]:
        """
        Video: ép mỗi WAIT_BETWEEN_TOKEN_SECONDS mới bắn prompt 'a' (kể cả upscale).
        """
        async with token_lock:
            if last_token_sent_ts:
                while True:
                    if _STOP_SIGNAL.is_set():
                        return None
                    elapsed = time.time() - last_token_sent_ts[0]
                    if elapsed >= WAIT_BETWEEN_TOKEN_SECONDS:
                        break
                    await asyncio.sleep(min(1.0, max(0.05, WAIT_BETWEEN_TOKEN_SECONDS - elapsed)))
            if _STOP_SIGNAL.is_set():
                return None
            # cập nhật timestamp NGAY TRƯỚC khi fetch (vì fetch sẽ bắn prompt 'a' bên trong)
            if last_token_sent_ts:
                last_token_sent_ts[0] = time.time()
            else:
                last_token_sent_ts.append(time.time())

        try:
            return await fetch_recaptcha_token_via_page(
                page,
                prompt_for_token="a",
                timeout=timeout_s,
            )
        except Exception as e:
            print(f"[VEO Video API] [{ptag}] ⚠️ {label} lấy token lỗi: {e}")
            return None

    async def _upscale_video_1080_for_scene(
        *,
        scene_id: int,
        base_video_url: str,
        base_thumb_url: Optional[str],
        ptag: str,
    ) -> None:
        """
        Upscale video 720 -> 1080p cho 1 scene:
        - Lấy mediaId từ base_video_url.
        - Lấy token 'a' mới.
        - Gọi batchAsyncGenerateVideoUpsampleVideo.
        - Nếu có rawBytes: lưu MP4 1080p trực tiếp.
        - Nếu fail: fallback tải video gốc 720 như cũ.
        """
        # 1) Parse mediaId từ URL video gốc
        import re

        m = re.search(r"/video/([0-9a-fA-F-]+)", base_video_url)
        if not m:
            print(
                f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} không parse được mediaId từ URL, "
                "dùng video gốc 720."
            )
            return
        media_id = m.group(1)

        # 2) Lấy token riêng cho upscale (vẫn rate-limit 25s)
        recaptcha_up = await _rate_limited_fetch_token(
            ptag=ptag,
            label=f"scene={scene_id} (upscale 1080p)",
            timeout_s=60,
        )

        if not recaptcha_up:
            print(
                f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} không lấy được token upscale, dùng video gốc 720."
            )
            return

        # 3) Gọi API upscale video
        up_url = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoUpsampleVideo"
        import uuid

        batch_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())

        up_payload: Dict[str, Any] = {
            "mediaGenerationContext": {"batchId": batch_id},
            "clientContext": {
                "projectId": project_id,
                "tool": "PINHOLE",
                "userPaygateTier": "PAYGATE_TIER_TWO",
                "sessionId": session_id,
                "recaptchaContext": {
                    "token": recaptcha_up,
                    "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
                },
            },
            "requests": [
                {
                    "resolution": "VIDEO_RESOLUTION_1080P",
                    "aspectRatio": video_aspect_ratio,
                    "seed": 13126,
                    "videoModelKey": "veo_3_1_upsampler_1080p",
                    "metadata": {"workflowId": workflow_id},
                    "videoInput": {"mediaId": media_id},
                }
            ],
            "useV2ModelConfig": True,
        }

        data = json.dumps(up_payload, ensure_ascii=False)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        try:
            # Không refresh auth ở đây (theo yêu cầu). Nếu có cookie trong veo_auth.json thì đính kèm để giống nst_upscale_video.py.
            try:
                current_auth = _load_auth_config(profile_id) or {}
                current_cookie = str(current_auth.get("cookie") or "")
                if current_cookie:
                    headers["Cookie"] = current_cookie
            except Exception:
                pass

            resp = await page.request.post(
                up_url,
                data=data,
                headers=headers,
                timeout=180_000,
            )
            body = await resp.text()
            if not resp.ok:
                print(
                    f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} upscale HTTP {resp.status} {resp.status_text}. "
                    f"body_snip={(body or '')[:220]!r}"
                )
                return
        except Exception as e:
            print(
                f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} lỗi gọi upscale video: {e}, dùng video gốc 720."
            )
            return

        # 4) Nếu có rawBytes trong operations -> ghi trực tiếp MP4
        upscale_ok = False
        try:
            obj = json.loads(body or "")
            ops = obj.get("operations") or []
            if isinstance(ops, list) and ops:
                first_op = ops[0] if isinstance(ops[0], dict) else {}
                raw_b64 = first_op.get("rawBytes")
                if isinstance(raw_b64, str) and raw_b64.strip():
                    import base64

                    rel_path = f"videos/{script_name}/{scene_id:03d}.mp4"
                    out_path = videos_output_dir / f"{scene_id:03d}.mp4"
                    out_path.write_bytes(base64.b64decode(raw_b64))
                    upscale_ok = True
                    print(
                        f"[VEO Video API] [{ptag}] 🎉 scene={scene_id} upscale 1080p OK → {out_path}"
                    )
                    thumb_rel_path: Optional[str] = None
                    if base_thumb_url:
                        thumb_output_dir = project_dir / "videos" / script_name
                        thumb_output_dir.mkdir(parents=True, exist_ok=True)
                        thumb_rel_path = f"videos/{script_name}/{scene_id:03d}.jpg"
                        thumb_out_path = thumb_output_dir / f"{scene_id:03d}.jpg"
                        try:
                            import requests as _req

                            print(
                                f"[VEO Video API] [{ptag}] 📥 Tải thumbnail 1080p cho scene={scene_id} -> {thumb_out_path}"
                            )
                            with _req.get(base_thumb_url, stream=True, timeout=(5, 10)) as r:
                                r.raise_for_status()
                                with open(thumb_out_path, "wb") as f:
                                    for chunk in r.iter_content(chunk_size=256 * 1024):
                                        if not chunk:
                                            continue
                                        f.write(chunk)
                        except Exception as e:
                            print(
                                f"[VEO Video API] [{ptag}] ⚠️ Không tải được thumbnail 1080p scene={scene_id}: {e}"
                            )
                            thumb_rel_path = None

                    await update_scene_status(script_path, scene_id, "done", rel_path)
                    if thumb_rel_path:
                        await update_scene_status(script_path, scene_id, "done", thumb_rel_path)
                    results[scene_id] = {
                        "ok": True,
                        "scene_id": scene_id,
                        "video_path": rel_path,
                        "thumbnail_path": thumb_rel_path,
                        "download_url": base_video_url,
                    }
        except Exception as e:
            print(
                f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} lỗi parse response upscale: {e}, dùng video gốc 720."
            )
            upscale_ok = False

        if upscale_ok:
            return

        # 5) Nếu không có rawBytes thì nhiều khả năng upscale chạy ASYNC: poll status để lấy URL 1080p.
        ops_payload = _build_status_payload_from_create_response(body)
        if not ops_payload:
            print(
                f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} upscale không có rawBytes và cũng không parse được operations; "
                "giữ video 720."
            )
            return

        print(f"[VEO Video API] [{ptag}] 🔎 scene={scene_id} poll status upscale 1080p...")
        deadline = time.time() + 15 * 60
        while time.time() < deadline:
            if _STOP_SIGNAL.is_set():
                return

            try:
                # Refresh auth nếu cần
                if not _load_auth_config(profile_id):
                    await auto_collect_veo_auth_from_flow(page, profile_id=profile_id)
                current_auth = _load_auth_config(profile_id) or {}
                current_access_token = str(current_auth.get("access_token") or access_token)
                st = await request_check_status_via_browser(page, {"operations": ops_payload}, current_access_token)
            except Exception as e:
                print(f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} check status upscale exception: {e}")
                await _wait_with_stop(3)
                continue

            if not st.get("ok"):
                print(
                    f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} check status upscale lỗi: "
                    f"status={st.get('status')} error={st.get('error')} body_snip={str(st.get('body') or '')[:160]!r}"
                )
                await _wait_with_stop(3)
                continue

            urls = _parse_video_urls_from_status_body(str(st.get("body") or ""))
            video_urls = [u for u, _img in urls if u]
            if not video_urls:
                await _wait_with_stop(3)
                continue

            first_video, first_image = urls[0]
            # tải video 1080p về đúng path của scene
            try:
                import requests as _req

                rel_path = f"videos/{script_name}/{scene_id:03d}.mp4"
                out_path = videos_output_dir / f"{scene_id:03d}.mp4"
                print(f"[VEO Video API] [{ptag}] 📥 Tải video 1080p scene={scene_id} -> {out_path}")
                with _req.get(first_video, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)

                thumb_rel_path: Optional[str] = None
                if first_image:
                    thumb_rel_path = f"videos/{script_name}/{scene_id:03d}.jpg"
                    thumb_out_path = (project_dir / "videos" / script_name) / f"{scene_id:03d}.jpg"
                    try:
                        with _req.get(first_image, stream=True, timeout=120) as r:
                            r.raise_for_status()
                            with open(thumb_out_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=256 * 1024):
                                    if chunk:
                                        f.write(chunk)
                    except Exception:
                        thumb_rel_path = None

                await update_scene_status(script_path, scene_id, "done", rel_path)
                if thumb_rel_path:
                    await update_scene_status(script_path, scene_id, "done", thumb_rel_path)
                results[scene_id] = {
                    "ok": True,
                    "scene_id": scene_id,
                    "video_path": rel_path,
                    "thumbnail_path": thumb_rel_path,
                    "download_url": first_video,
                }
                print(f"[VEO Video API] [{ptag}] 🎉 scene={scene_id} upscale 1080p OK → {out_path}")
                return
            except Exception as e:
                print(
                    f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} tải video upscale 1080p thất bại: {e}, giữ 720."
                )
                return

        print(
            f"[VEO Video API] [{ptag}] ⚠️ scene={scene_id} poll upscale 1080p timeout, giữ video 720."
        )


    async def _video_job(job_id: int, task: Dict[str, Any]) -> None:
        if _STOP_SIGNAL.is_set():
            return
        async with semaphore:
            if _STOP_SIGNAL.is_set():
                return

            scene_id = int(task.get("scene_id") or 0)
            prompt_text = str(task.get("video_prompt") or task.get("prompt") or "").strip()
            video_res = str(task.get("video_resolution") or task.get("yt_video_res") or "").strip().lower()
            use_upscale_1080 = video_res in ("1080", "1080p")
            if not prompt_text or not scene_id:
                results[job_id] = {"ok": False, "error": "empty_prompt_or_scene", "scene_id": scene_id}
                return

            ptag = profile_id[-4:]
            print(f"[VEO Video API] [{ptag}] 🎬 job={job_id} scene={scene_id} chuẩn bị lấy token...")

            # Lấy recaptcha token (tối đa 3 lần), và đảm bảo mỗi 25s mới gửi 1 prompt "a" trên toàn page
            recaptcha_token: Optional[str] = None
            for attempt in range(3):
                if _STOP_SIGNAL.is_set():
                    return
                recaptcha_token = await _rate_limited_fetch_token(
                    ptag=ptag,
                    label=f"scene={scene_id}",
                    timeout_s=25,
                )
                if recaptcha_token:
                    break
                print(
                    f"[VEO Video API] [{ptag}] ⏱️ scene={scene_id} token timeout lần {attempt + 1}/3, "
                    "sẽ thử lại sau 5s..."
                )
                await asyncio.sleep(5)

            if not recaptcha_token:
                print(
                    f"[VEO Video API] [{ptag}] ⛔ scene={scene_id} không lấy được recaptcha token sau nhiều lần "
                    "(có thể đã hết quota, Flow không nhận prompt 'a')."
                )
                results[job_id] = {
                    "ok": False,
                    "error": "recaptcha_token_failed",
                    "scene_id": scene_id,
                }
                await update_scene_status(script_path, scene_id, "quota_exceeded")
                return

            # Nếu có ảnh tham chiếu: dùng Reference Video API (batchAsyncGenerateVideoReferenceImages)
            # Nếu không: dùng Text-to-Video API (batchAsyncGenerateVideoText) như cũ.
            scene_ref_ids = [
                str(x).strip()
                for x in (task.get("reference_media_ids") or [])
                if str(x or "").strip()
            ]
            if not scene_ref_ids and reference_media_id:
                scene_ref_ids = [reference_media_id]
            use_reference = bool(scene_ref_ids)
            if use_reference:
                r2v_model_key = select_reference_video_model_key(
                    aspect_ratio=video_aspect_ratio,
                    frontend_model_label=effective_model,
                    account_type=account_type,
                )
                try:
                    payload = build_payload_generate_reference_video(
                        recaptcha_token=recaptcha_token,
                        session_id=session_id,
                        project_id=project_id,
                        prompt=prompt_text,
                        seed=9797,
                        video_model_key=r2v_model_key,
                        reference_media_ids=scene_ref_ids[:3],
                        scene_id=str(scene_id),
                        aspect_ratio=video_aspect_ratio,
                        output_count=1,
                        account_type=account_type,
                        batch_id=batch_id_for_reference,
                        reference_audio_media_id=reference_audio_media_id,
                    )
                except Exception as e:
                    print(f"[VEO Video API] [{ptag}] ❌ Lỗi build payload Reference Video scene={scene_id}: {e}")
                    results[job_id] = {
                        "ok": False,
                        "error": f"build_reference_payload_failed: {e}",
                        "scene_id": scene_id,
                    }
                    await update_scene_status(script_path, scene_id, "FAILED")
                    return
                print(
                    f"[VEO Video API] [{ptag}] 🚀 Gửi request tạo REFERENCE video cho scene={scene_id}..."
                )
            else:
                payload = build_text_to_video_payload(
                    prompt_text,
                    session_id,
                    project_id,
                    recaptcha_token,
                    scene_id=str(scene_id),
                    frontend_model=effective_model,
                    aspect_ratio=video_aspect_ratio,
                    output_count=1,
                    account_type=account_type,
                )
                print(f"[VEO Video API] [{ptag}] 🚀 Gửi request tạo video cho scene={scene_id}...")
            max_create_retries = 3  # Tăng retry lên 3 lần cho các lỗi 500, 403, 429
            create_res: Optional[Dict[str, Any]] = None

            for attempt in range(max_create_retries + 1):
                try:
                    # Force reload auth để lấy token/cookie mới nhất
                    if not _load_auth_config(profile_id):
                        await auto_collect_veo_auth_from_flow(page, profile_id=profile_id)
                    current_auth = _load_auth_config(profile_id, force_reload=True) or {}
                    current_access_token = str(current_auth.get("access_token") or access_token)
                    if use_reference:
                        create_res = await request_create_reference_video_via_browser(
                            page,
                            payload,
                            current_access_token,
                        )
                    else:
                        create_res = await request_create_video_via_browser(
                            page,
                            URL_GENERATE_TEXT_TO_VIDEO,
                            payload,
                            current_access_token,
                        )
                except Exception as e:  # pragma: no cover - defensive
                    print(f"[VEO Video API] [{ptag}] ❌ Ngoại lệ khi gửi create video: {e}")
                    results[job_id] = {"ok": False, "error": f"create_exception: {e}", "scene_id": scene_id}
                    await update_scene_status(script_path, scene_id, "FAILED")
                    create_res = None
                    break

                if create_res.get("ok"):
                    break

                # Parse status code
                try:
                    status_code = int(create_res.get("status") or 0)
                except Exception:
                    status_code = 0

                # 401: access_token sai / hết hạn → refresh auth rồi retry
                if status_code == 401 and attempt < max_create_retries:
                    print(
                        f"[VEO Video API] [{ptag}] 🔑 scene={scene_id} HTTP 401 khi create video, "
                        "refresh auth rồi retry..."
                    )
                    await auto_collect_veo_auth_from_flow(page, profile_id=profile_id)
                    await asyncio.sleep(2)
                    continue

                # 500: Internal Server Error → retry với delay tăng dần
                if status_code == 500 and attempt < max_create_retries:
                    wait_time = (attempt + 1) * 3  # 3, 6, 9 giây
                    print(
                        f"[VEO Video API] [{ptag}] 🔄 scene={scene_id} HTTP 500 (Internal Error), "
                        f"retry lần {attempt + 2} sau {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # 403: Forbidden → retry với delay (có thể do rate limit hoặc captcha)
                if status_code == 403 and attempt < max_create_retries:
                    wait_time = (attempt + 1) * 4  # 4, 8, 12 giây
                    print(
                        f"[VEO Video API] [{ptag}] 🔄 scene={scene_id} HTTP 403 (Forbidden), "
                        f"retry lần {attempt + 2} sau {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # 429: Too Many Requests → retry với delay dài hơn
                if status_code == 429 and attempt < max_create_retries:
                    wait_time = (attempt + 1) * 5  # 5, 10, 15 giây
                    print(
                        f"[VEO Video API] [{ptag}] 🔄 scene={scene_id} HTTP 429 (Rate Limit), "
                        f"retry lần {attempt + 2} sau {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                # Các lỗi khác: không retry thêm trong vòng lặp này
                break

            if not create_res or not create_res.get("ok"):
                body_snip = (create_res.get("body") or "")[:400] if create_res else ""
                status_code = int(create_res.get("status") or 0) if create_res else 0
                
                # Tạo thông báo lỗi chi tiết hơn cho các HTTP code cụ thể
                error_msg = "create_failed"
                if status_code == 500:
                    error_msg = f"HTTP 500 Internal Server Error - Veo3 server đang bận. Vui lòng thử lại sau."
                elif status_code == 403:
                    error_msg = f"HTTP 403 Forbidden - Có thể bị rate limit hoặc tài khoản hết quyền truy cập."
                elif status_code == 429:
                    error_msg = f"HTTP 429 Too Many Requests - Đã gửi quá nhiều yêu cầu. Vui lòng chờ và thử lại."
                elif status_code == 401:
                    error_msg = f"HTTP 401 Unauthorized - Token hết hạn. Đã thử refresh nhưng không thành công."
                
                print(
                    f"[VEO Video API] [{ptag}] ❌ Create video lỗi: "
                    f"status={create_res.get('status') if create_res else 'N/A'} "
                    f"body={(body_snip or '')[:160]}"
                )
                results[job_id] = {
                    "ok": False,
                    "error": error_msg,
                    "status": create_res.get("status") if create_res else None,
                    "body": body_snip,
                    "scene_id": scene_id,
                }
                await update_scene_status(script_path, scene_id, "FAILED")
                return

            if use_reference:
                operations = parse_operations_from_reference_response(str(create_res.get("body") or ""))
            else:
                operations = parse_operations_from_create_response(str(create_res.get("body") or ""))
            op_for_scene = next((op for op in operations if str(op.get("sceneId")) == str(scene_id)), None)
            if not op_for_scene and operations:
                op_for_scene = operations[0]

            op_name = ""
            if isinstance(op_for_scene, dict):
                op_name = str((op_for_scene.get("operation") or {}).get("name") or "")

            if not op_name:
                body_debug = str(create_res.get("body") or "")[:500]
                print(f"[VEO Video API] [{ptag}] ❌ Không lấy được operation name cho scene={scene_id}.")
                print(f"[VEO Video API] [{ptag}] 🔍 Response body (500 ký tự đầu): {body_debug}")
                print(f"[VEO Video API] [{ptag}] 🔍 Parsed operations count: {len(operations)}")
                if operations:
                    print(f"[VEO Video API] [{ptag}] 🔍 First operation: {operations[0]}")
                results[job_id] = {
                    "ok": False,
                    "error": "missing_operation_name",
                    "scene_id": scene_id,
                    "body_snippet": body_debug,
                }
                await update_scene_status(script_path, scene_id, "FAILED")
                return

            # Đã gửi request tạo video, chuyển cảnh sang trạng thái processing
            await update_scene_status(script_path, scene_id, "processing")

            # Poll status: lấy operation SUCCESSFUL + video_url, image_url (thumbnail)
            start_ts = time.time()
            final_video_url: Optional[str] = None
            final_image_url: Optional[str] = None
            last_status: str = "PENDING"
            auth_refreshed_for_status = False

            while True:
                if _STOP_SIGNAL.is_set():
                    print(f"[VEO Video API] [{ptag}] 🛑 Dừng theo lệnh Stop khi đang chờ status scene={scene_id}.")
                    break

                elapsed = time.time() - start_ts
                if elapsed > timeout_status:
                    print(f"[VEO Video API] [{ptag}] ⏱️ Timeout chờ video cho scene={scene_id}.")
                    break

                status_payload = {
                    "operations": [
                        {
                            "operation": {"name": op_name},
                            "sceneId": str(scene_id),
                        }
                    ]
                }

                try:
                    if not _load_auth_config(profile_id):
                        await auto_collect_veo_auth_from_flow(page, profile_id=profile_id)
                    current_auth = _load_auth_config(profile_id) or {}
                    current_access_token = str(current_auth.get("access_token") or access_token)
                    if use_reference:
                        status_res = await request_check_reference_status_via_browser(
                            page, status_payload, current_access_token
                        )
                    else:
                        status_res = await request_check_status_via_browser(
                            page, status_payload, current_access_token
                        )
                except Exception as e:  # pragma: no cover - defensive
                    print(f"[VEO Video API] [{ptag}] ⚠️ Ngoại lệ khi check status scene={scene_id}: {e}")
                    await _wait_with_stop(STATUS_POLL_INTERVAL)
                    continue

                if not status_res.get("ok"):
                    try:
                        status_code = int(status_res.get("status") or 0)
                    except Exception:
                        status_code = 0

                    # 401 khi check status: refresh auth một lần rồi retry vòng while
                    # (KHÔNG auto-collect khi 403 theo yêu cầu)
                    if status_code == 401 and not auth_refreshed_for_status:
                        print(
                            f"[VEO Video API] [{ptag}] 🔑 scene={scene_id} HTTP {status_code} khi check status, "
                            "refresh auth rồi retry poll..."
                        )
                        auth_refreshed_for_status = True
                        await auto_collect_veo_auth_from_flow(page, profile_id=profile_id)
                        await _wait_with_stop(STATUS_POLL_INTERVAL)
                        continue

                    print(
                        f"[VEO Video API] [{ptag}] ⚠️ Check status lỗi scene={scene_id}, status={status_res.get('status')}"
                    )
                    await _wait_with_stop(STATUS_POLL_INTERVAL)
                    continue

                try:
                    body_json = json.loads(status_res.get("body") or "{}")
                    ops = body_json.get("operations") or []
                except Exception:
                    ops = []

                matched_op = None
                for op in ops:
                    if str(op.get("sceneId")) == str(scene_id):
                        matched_op = op
                        break
                if not matched_op and ops:
                    matched_op = ops[0]

                if not isinstance(matched_op, dict):
                    await _wait_with_stop(STATUS_POLL_INTERVAL)
                    continue

                status_str = str(matched_op.get("status") or "").upper()
                if status_str.startswith("MEDIA_GENERATION_STATUS_"):
                    short_status = status_str.replace("MEDIA_GENERATION_STATUS_", "")
                else:
                    short_status = status_str or "PENDING"

                if short_status != last_status:
                    print(f"[VEO Video API] [{ptag}] ℹ️ scene={scene_id} status={short_status}")
                    last_status = short_status

                error = matched_op.get("error") or (matched_op.get("operation") or {}).get("error")
                if isinstance(error, dict):
                    code = error.get("code")
                    message = error.get("message")
                    print(
                        f"[VEO Video API] [{ptag}] ❌ scene={scene_id} lỗi từ status: code={code} message={message}"
                    )
                    last_status = "FAILED"
                    break

                if short_status == "SUCCESSFUL":
                    if use_reference:
                        video_url, image_url = extract_media_from_reference_status_op(matched_op)
                    else:
                        video_url, image_url = extract_media_from_status_op(matched_op)
                    final_video_url = video_url or None
                    final_image_url = image_url or None
                    break

                if short_status not in {"PENDING", "ACTIVE"}:
                    break

                await _wait_with_stop(STATUS_POLL_INTERVAL)

            if not final_video_url:
                print(f"[VEO Video API] [{ptag}] ❌ Không lấy được video_url cho scene={scene_id}.")
                await update_scene_status(script_path, scene_id, "FAILED")
                results[job_id] = {
                    "ok": False,
                    "error": "no_video_url",
                    "scene_id": scene_id,
                    "status": last_status,
                }
                return

            rel_path = f"videos/{script_name}/{scene_id:03d}.mp4"
            out_path = videos_output_dir / f"{scene_id:03d}.mp4"

            import requests

            # Nếu không bật 1080p, tải video gốc như cũ
            if not use_upscale_1080:
                print(f"[VEO Video API] [{ptag}] 📥 Tải video cho scene={scene_id} -> {out_path}")
                ok_download = False
                for attempt in range(3):
                    try:
                        with requests.get(final_video_url, stream=True, timeout=(8, 30)) as resp:
                            resp.raise_for_status()
                            with open(out_path, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                                    if not chunk:
                                        continue
                                    f.write(chunk)
                        ok_download = True
                        break
                    except Exception as e:
                        print(
                            f"[VEO Video API] [{ptag}] ⚠️ Lỗi tải video (attempt {attempt+1}/3) scene={scene_id}: {e}"
                        )
                        if attempt < 2:
                            await _wait_with_stop(3)

                if not ok_download:
                    await update_scene_status(script_path, scene_id, "FAILED")
                    results[job_id] = {
                        "ok": False,
                        "error": "download_failed",
                        "scene_id": scene_id,
                        "download_url": final_video_url,
                    }
                    return

            # Nếu bật 1080p: gọi helper upscale; nếu fail, fallback giữ nguyên 720 như trên
            if use_upscale_1080:
                await _upscale_video_1080_for_scene(
                    scene_id=scene_id,
                    base_video_url=final_video_url,
                    base_thumb_url=final_image_url,
                    ptag=ptag,
                )
                # Nếu helper không tự set kết quả (upscale fail), tải 720 như cũ:
                if scene_id not in results:
                    print(
                        f"[VEO Video API] [{ptag}] 📥 Fallback tải video 720 cho scene={scene_id} -> {out_path}"
                    )
                    ok_download = False
                    for attempt in range(3):
                        try:
                            with requests.get(final_video_url, stream=True, timeout=(8, 30)) as resp:
                                resp.raise_for_status()
                                with open(out_path, "wb") as f:
                                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                                        if not chunk:
                                            continue
                                        f.write(chunk)
                            ok_download = True
                            break
                        except Exception as e:
                            print(
                                f"[VEO Video API] [{ptag}] ⚠️ Lỗi tải video (attempt {attempt+1}/3) scene={scene_id}: {e}"
                            )
                            if attempt < 2:
                                await _wait_with_stop(3)

                    if not ok_download:
                        await update_scene_status(script_path, scene_id, "FAILED")
                        results[job_id] = {
                            "ok": False,
                            "error": "download_failed",
                            "scene_id": scene_id,
                            "download_url": final_video_url,
                        }
                        return


            # Tải thêm thumbnail (ảnh) cho scene này nếu server trả về image_url (cùng folder videos)
            thumb_rel_path: Optional[str] = None
            if final_image_url:
                thumb_output_dir = project_dir / "videos" / script_name
                thumb_output_dir.mkdir(parents=True, exist_ok=True)
                thumb_rel_path = f"videos/{script_name}/{scene_id:03d}.jpg"
                thumb_out_path = thumb_output_dir / f"{scene_id:03d}.jpg"
                try:
                    print(f"[VEO Video API] [{ptag}] 📥 Tải thumbnail cho scene={scene_id} -> {thumb_out_path}")
                    with requests.get(final_image_url, stream=True, timeout=(5, 10)) as resp:
                        resp.raise_for_status()
                        with open(thumb_out_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=256 * 1024):
                                if not chunk:
                                    continue
                                f.write(chunk)
                except Exception as e:
                    print(f"[VEO Video API] [{ptag}] ⚠️ Không tải được thumbnail scene={scene_id}: {e}")
                    thumb_rel_path = None

            # Nếu helper upscale đã set kết quả, không override nữa
            if scene_id in results:
                return

            # Cập nhật trạng thái: video_url (và image_url nếu có thumbnail) cho video gốc 720
            await update_scene_status(script_path, scene_id, "done", rel_path)
            if thumb_rel_path:
                await update_scene_status(script_path, scene_id, "done", thumb_rel_path)

            print(f"[VEO Video API] [{ptag}] ✅ scene={scene_id} OK → {rel_path}")
            results[job_id] = {
                "ok": True,
                "scene_id": scene_id,
                "video_path": rel_path,
                "thumbnail_path": thumb_rel_path,
                "download_url": final_video_url,
            }

    for job_id, task in enumerate(scene_tasks, start=1):
        if _STOP_SIGNAL.is_set():
            print("[VEO Video API] 🛑 Dừng theo lệnh Stop trước khi gửi video request.")
            break
        pending_tasks.append(asyncio.create_task(_video_job(job_id, task)))

    if pending_tasks:
        try:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        except Exception:
            pass

    if cast_media_by_name and use_cast_profile_references:
        results[CAST_REFERENCE_MEDIA_META_KEY] = cast_media_by_name

    return results


async def _execute_youtube_video_generation_api_async(
    count: int,
    script_path: str,
    *,
    max_scenes: Optional[int] = None,
    start_scene: Optional[int] = None,
    end_scene: Optional[int] = None,
    ratio: Optional[str] = None,
    model: Optional[str] = None,
    ai_video_resolution: Optional[str] = None,
    grok_video_resolution: Optional[str] = None,
    use_reference_image: bool = False,
    use_cast_profile_references: bool = False,
    ai_character_voice_consistency: bool = False,
    ai_character_voice_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Orchestrator YouTube Video cho chế độ API (không ảnh tham chiếu).
    """
    from typing import Tuple  # local import tránh circular

    _STOP_SIGNAL.clear()

    abs_script_path = _resolve_script_path(script_path)
    if not abs_script_path or not os.path.exists(abs_script_path):
        return {"error": f"File không tồn tại: {script_path} (resolved: {abs_script_path})"}

    try:
        with open(abs_script_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            scenes = data.get("scenes", [])
            master_image_url = data.get("master_image_url")
    except Exception as e:
        return {"error": f"Lỗi đọc file kịch bản: {e}"}

    effective_ratio = ratio or "16:9"
    effective_model = _normalize_requested_veo_model(model)
    # Chọn chất lượng video theo input frontend (ưu tiên ai_video_resolution; fallback grok_video_resolution)
    # Mapping: frontend gửi "1080p"/"720p" hoặc grok "480p"/"720p".
    effective_video_resolution = (ai_video_resolution or grok_video_resolution or "").strip().lower()

    # Với AI tab (script_path nằm trong ai_custom) và bật cờ reference → tìm full path ảnh master để upload qua API
    reference_image_path: Optional[str] = None
    if use_reference_image and master_image_url and not use_cast_profile_references:
        try:
            script_dir = Path(abs_script_path).resolve().parent
            mode_dir = script_dir.parent
            candidate = (mode_dir / str(master_image_url)).resolve()
            if candidate.exists():
                reference_image_path = str(candidate)
                print(f"[VEO Video API] ✅ Found master reference image for API mode: {reference_image_path}")
            else:
                print(f"[VEO Video API] ⚠️ master_image_url not found on disk: {candidate}")
        except Exception as e:
            print(f"[VEO Video API] ⚠️ Error resolving master_image_url: {e}")

    # Đồng nhất giọng (API): chỉ khi có ảnh tham chiếu + bật cờ + có tên giọng → mediaId chữ thường.
    reference_audio_media_id: Optional[str] = None
    if reference_image_path and bool(ai_character_voice_consistency):
        vn = (ai_character_voice_name or "").strip()
        if vn:
            reference_audio_media_id = vn.lower()

    nst = NSTBrowserManager()
    api_key_map = _build_profile_api_key_map()
    active_ids = profile_pool_for_run(count, get_settings() or {})

    scenes_to_consider = _filter_scenes_by_range(
        scenes,
        start_scene,
        end_scene,
        max_scenes,
    )
    tasks_to_run: List[Dict[str, Any]] = []
    for s in scenes_to_consider:
        status = s.get("status")
        if status != "done":
            tasks_to_run.append(
                {
                    "scene_id": s["scene_id"],
                    "video_prompt": s.get("video_prompt") or s.get("image_prompt") or "",
                    # để worker bật upscale 1080p nếu cần
                    "video_resolution": effective_video_resolution,
                }
            )

    if not tasks_to_run:
        return {"success": True, "message": "Tất cả video đã hoàn thành (API).", "profiles": {}}

    if not active_ids:
        return {"error": "Thiếu danh sách profiles khả dụng cho API video mode."}

    assignments: Dict[str, List[Dict[str, Any]]] = {}
    for pid in active_ids:
        assignments[pid] = []
    for i, task in enumerate(tasks_to_run):
        pid = active_ids[i % len(active_ids)]
        assignments[pid].append(task)

    settings_vid_api = get_settings() or {}
    is_local_engine = is_chrome_local(settings_vid_api)

    # Đảm bảo NST profiles đã được start (tự bật browser giống luồng không API)
    try:
        print(
            f"[Youtube Video API] 🔄 Đảm bảo profiles đã start cho API mode: "
            f"{[pid[-4:] for pid in active_ids]}"
        )
        await asyncio.to_thread(_ensure_profiles_started, nst, active_ids, api_key_map)
        await _wait_for_profiles_ready(nst, active_ids, api_key_map)
    except Exception as e:
        print(f"[Youtube Video API] ⚠️ Không đảm bảo start profiles được cho API video mode: {e}")

    async def _worker_api(pid: str, tasks: List[Dict[str, Any]]) -> Tuple[str, Dict[int, Dict[str, Any]]]:
        if not tasks or _STOP_SIGNAL.is_set():
            return pid, {}

        api_key = api_key_map.get(pid)
        ws = get_ws_endpoint_for_profile(nst, pid, api_key, settings=settings_vid_api)
        if not ws:
            print(f"[Youtube Video API] ⚠️ Profile {pid[-4:]} không lấy được WS endpoint.")
            return pid, {}

        page = await connect_and_get_page(ws)
        if not page:
            print(f"[Youtube Video API] ⚠️ Profile {pid[-4:]} không connect được Playwright.")
            return pid, {}

        # Đảm bảo đã vào đúng Flow project (giống luồng Playwright thường)
        try:
            await _goto_flow_with_profile_cache(
                page,
                pid,
                stop_check=lambda: _STOP_SIGNAL.is_set(),
            )
            # API mode cũng phải setup mode/model/ratio như Playwright mode.
            ok_mode = await select_mode(page, "video", stop_check=lambda: _STOP_SIGNAL.is_set())
            if not ok_mode:
                print(
                    f"[Youtube Video API] ⚠️ Profile {pid[-4:]} không chọn được mode video sau goto cached."
                )
                return pid, {}
            await setup_render_settings(
                page,
                output_count=1,
                aspect_ratio=clamp_aspect_ratio_for_flow_video(effective_ratio),
                model=effective_model,
                select_ingredients=True,
            )
            print(
                f"[Youtube Video API] ✅ Profile {pid[-4:]} setup xong (mode/model/ratio) trong API mode."
            )
        except Exception as e:
            print(
                f"[Youtube Video API] ⚠️ Không goto/setup Flow được cho profile {pid[-4:]} trong API mode: {e}"
            )
            return pid, {}

        restart_attempts = 0
        MAX_RESTARTS = 2
        results_agg: Dict[int, Dict[str, Any]] = {}
        cast_reference_media_by_name: Optional[Dict[str, str]] = None

        try:
            while tasks and not _STOP_SIGNAL.is_set():
                print(f"[Youtube Video API] 🚀 Profile {pid[-4:]} chạy {len(tasks)} scene video bằng API...")
                results_for_profile = await generate_youtube_videos_via_api_for_page(
                    page,
                    tasks,
                    script_path=script_path,
                    profile_id=pid,
                    ratio=effective_ratio,
                    model=effective_model,
                    reference_image_path=reference_image_path,
                    reference_audio_media_id=reference_audio_media_id,
                    use_cast_profile_references=use_cast_profile_references,
                    cast_reference_media_by_name=cast_reference_media_by_name,
                )

                if CAST_REFERENCE_MEDIA_META_KEY in results_for_profile:
                    raw_cast = results_for_profile.get(CAST_REFERENCE_MEDIA_META_KEY)
                    if isinstance(raw_cast, dict):
                        cast_reference_media_by_name = raw_cast
                    results_for_profile.pop(CAST_REFERENCE_MEDIA_META_KEY, None)

                results_agg.update(results_for_profile)

                # Lọc lại những scene chưa ok để retry sau restart
                pending_scene_ids = {
                    int(info.get("scene_id") or 0)
                    for _, info in results_for_profile.items()
                    if isinstance(info, dict) and not info.get("ok")
                }

                if not pending_scene_ids:
                    break

                if restart_attempts >= MAX_RESTARTS:
                    print(
                        f"[VEO Video API] ⛔ Profile {pid[-4:]} đã restart đủ {MAX_RESTARTS} lần, dừng hẳn profile này."
                    )
                    try:
                        _stop_profiles_by_key(nst, [pid], api_key_map)
                    except Exception as e:
                        print(f"[VEO Video API] ⚠️ stop_profiles khi dừng hẳn profile {pid[-4:]} lỗi: {e}")
                    break

                restart_attempts += 1
                print(
                    f"[VEO Video API] 🔁 Restart profile {pid[-4:]} lần {restart_attempts}/{MAX_RESTARTS} cho {len(pending_scene_ids)} scene lỗi..."
                )

                new_page = await _restart_nst_profile_and_reconnect(nst, api_key_map, pid)
                if not new_page:
                    print(f"[VEO Video API] ❌ Restart profile {pid[-4:]} thất bại, dừng.")
                    break

                page = new_page
                tasks = [t for t in tasks if int(t.get("scene_id") or 0) in pending_scene_ids]
        finally:
            try:
                if is_local_engine:
                    await detach_browser_session(ws)
                else:
                    await cleanup_browser(ws)
            except Exception:
                pass

        return pid, results_agg

    worker_tasks = []
    for pid, assigned_tasks in assignments.items():
        if not assigned_tasks:
            continue
        worker_tasks.append(_worker_api(pid, assigned_tasks))

    if not worker_tasks:
        return {"error": "Không có scene nào được gán cho profiles trong API video mode."}

    await set_script_running_state(script_path, True)

    try:
        worker_results = await asyncio.gather(*worker_tasks, return_exceptions=False)
    finally:
        await set_script_run_finished(script_path)

    summary: Dict[str, Any] = {
        "success": True,
        "profiles": {},
    }
    for pid, res in worker_results:
        summary["profiles"][pid] = res
    return summary


def execute_youtube_video_generation_api(
    count: int,
    script_path: str,
    *,
    max_scenes: Optional[int] = None,
    start_scene: Optional[int] = None,
    end_scene: Optional[int] = None,
    ratio: Optional[str] = None,
    model: Optional[str] = None,
    ai_video_resolution: Optional[str] = None,
    grok_video_resolution: Optional[str] = None,
    use_reference_image: bool = False,
    use_cast_profile_references: bool = False,
    ai_character_voice_consistency: bool = False,
    ai_character_voice_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Wrapper sync để gọi từ FastAPI router cho YouTube Video API.
    """
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with _RUNNING_LOOPS_LOCK:
        _RUNNING_LOOPS.add(loop)
    try:
        return loop.run_until_complete(
            _execute_youtube_video_generation_api_async(
                count,
                script_path,
                max_scenes=max_scenes,
                start_scene=start_scene,
                end_scene=end_scene,
                ratio=ratio,
                model=model,
                ai_video_resolution=ai_video_resolution,
                grok_video_resolution=grok_video_resolution,
                use_reference_image=use_reference_image,
                use_cast_profile_references=use_cast_profile_references,
                ai_character_voice_consistency=ai_character_voice_consistency,
                ai_character_voice_name=ai_character_voice_name,
            )
        )
    finally:
        with _RUNNING_LOOPS_LOCK:
            _RUNNING_LOOPS.discard(loop)
        loop.close()


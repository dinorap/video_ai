import asyncio
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

from playwright.async_api import Page, TimeoutError  # type: ignore

from utils.veo3.flow_actions import send_prompt_text, goto_flow_and_open_project


FLOW_URL = "https://labs.google/fx/vi/tools/flow"
RECAPTCHA_SITE_KEY = "k=6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"

BLOCK_KEYWORDS = [
    "flowMedia:batchGenerateImages",
    "batchGenerateImages",
    "batchAsyncGenerateVideoText",
    "batchAsyncGenerateVideoStartImage",
]


def _veo_auth_path() -> Path:
    from utils.path_helper import VEO_AUTH_FILE
    return VEO_AUTH_FILE


def _read_auth_file() -> Dict[str, Any]:
    path = _veo_auth_path()
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8") or "{}")
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write_auth_file(obj: Dict[str, Any]) -> None:
    path = _veo_auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj or {}, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_filled(obj: Dict[str, Any]) -> bool:
    return bool(obj.get("sessionId") and obj.get("projectId") and obj.get("access_token"))


# Cache auth trong RAM với thời gian sống (để tránh đọc file liên tục trong cùng 1 phiên)
_AUTH_CACHE: Dict[str, Dict[str, Any]] = {}
_AUTH_CACHE_TTL = 300  # Cache 5 phút, sau đó reload để lấy token/cookie mới


def save_veo_auth_config(profile_id: str, auth: dict) -> None:
    """
    Lưu auth theo từng NST profile_id vào `backend/config/veo_auth.json`.

    Format:
    {
      "profiles": {
        "<profile_id>": { sessionId, projectId, access_token, cookie, updated_at }
      }
    }
    """
    pid = str(profile_id or "").strip()
    if not pid:
        return
    root = _read_auth_file()
    profiles = root.get("profiles") if isinstance(root.get("profiles"), dict) else {}
    if not isinstance(profiles, dict):
        profiles = {}
    entry = dict(auth or {})
    try:
        import time as _time
        entry["updated_at"] = _time.time()
    except Exception:
        entry["updated_at"] = None
    profiles[pid] = entry
    root["profiles"] = profiles
    _write_auth_file(root)


def load_veo_auth_config(profile_id: str, *, force_reload: bool = False) -> Optional[dict]:
    """
    Đọc auth theo profile_id từ backend/config/veo_auth.json.
    
    Cache trong RAM với TTL 5 phút:
    - Lần đầu gọi (hoặc force_reload=True): đọc file mới
    - Trong cùng phiên (< 5 phút): dùng cache
    - Sau 5 phút: tự động reload để lấy token/cookie mới
    """
    pid = str(profile_id or "").strip()
    if not pid:
        return None
    
    # Kiểm tra cache nếu không force reload
    if not force_reload and pid in _AUTH_CACHE:
        cached = _AUTH_CACHE[pid]
        cache_time = cached.get("_cache_time", 0)
        try:
            import time as _time
            if _time.time() - cache_time < _AUTH_CACHE_TTL:
                # Cache còn sống, trả về luôn
                result = dict(cached)
                result.pop("_cache_time", None)
                return result
        except Exception:
            pass
    
    # Đọc lại file (cache hết hạn hoặc chưa có cache)
    root = _read_auth_file()

    # Backward compat: file cũ dạng phẳng -> tự chuyển sang profiles[pid]
    if _is_filled(root) and not isinstance(root.get("profiles"), dict):
        migrated = {
            "sessionId": root.get("sessionId"),
            "projectId": root.get("projectId"),
            "access_token": root.get("access_token"),
            "cookie": root.get("cookie") or "",
        }
        _write_auth_file({"profiles": {pid: migrated}})
        # Lưu vào cache
        try:
            import time as _time
            cached_entry = dict(migrated)
            cached_entry["_cache_time"] = _time.time()
            _AUTH_CACHE[pid] = cached_entry
        except Exception:
            pass
        return migrated

    profiles = root.get("profiles") if isinstance(root.get("profiles"), dict) else {}
    if not isinstance(profiles, dict):
        return None
    entry = profiles.get(pid)
    if isinstance(entry, dict) and _is_filled(entry):
        result = {
            "sessionId": entry.get("sessionId"),
            "projectId": entry.get("projectId"),
            "access_token": entry.get("access_token"),
            "cookie": entry.get("cookie") or "",
            "project_url": entry.get("project_url") or "",
        }
        # Lưu vào cache với timestamp
        try:
            import time as _time
            cached_entry = dict(result)
            cached_entry["_cache_time"] = _time.time()
            _AUTH_CACHE[pid] = cached_entry
        except Exception:
            pass
        return result
    return None


def _cookies_to_header(cookies: List[Dict[str, Any]]) -> str:
    parts = []
    for c in cookies:
        # Chỉ lấy cookie thuộc Google/Flow, bỏ cookie của hệ thống khác (NST token/x-api-key/profileId...)
        domain = str(c.get("domain") or "").lstrip(".").lower()
        if not (domain.endswith("google.com") or domain.endswith("labs.google")):
            continue
        name = c.get("name")
        value = c.get("value")
        if name and value is not None:
            # bỏ các cookie không liên quan / nhạy cảm nội bộ
            if str(name).lower() in {"token", "x-api-key", "profileid", "profilename"}:
                continue
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _is_recaptcha_reload(url: str) -> bool:
    url = url or ""
    return "/recaptcha/enterprise/reload" in url


def _extract_recaptcha_token(text: str) -> Optional[str]:
    marker = '["rresp","'
    start = text.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = text.find('"', start)
    if end == -1:
        return None
    return text[start:end]


def _extract_token_from_generate_post_data(raw: str) -> Optional[str]:
    """
    Fallback: đôi khi Flow không gọi `/recaptcha/enterprise/reload` (hoặc bị cache),
    nhưng request generate vẫn chứa `recaptchaContext.token` trong payload JSON.
    """
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None

    def _pick_token(o: Any) -> Optional[str]:
        if not isinstance(o, dict):
            return None
        cc = o.get("clientContext") or {}
        if isinstance(cc, dict):
            rc = cc.get("recaptchaContext") or {}
            if isinstance(rc, dict):
                tok = rc.get("token")
                if isinstance(tok, str) and tok.strip():
                    return tok.strip()
        return None

    # Case 1: payload root có clientContext
    tok = _pick_token(obj)
    if tok:
        return tok

    # Case 2: payload dạng { requests: [ { clientContext: { recaptchaContext: { token }}}]}
    reqs = obj.get("requests")
    if isinstance(reqs, list) and reqs:
        tok = _pick_token(reqs[0])
        if tok:
            return tok

    return None


async def apply_request_blocking_for_token(page: Page):
    """
    Block các request generate nội bộ bằng CDP để chỉ bắt token.
    Trả về cdp_session để có thể cleanup sau.
    
    🔥 Chỉ dùng CDP blocking, KHÔNG dùng route handler để tránh conflict.
    """
    cdp = None
    
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable")
        urls_to_block = [
            "*aisandbox-pa.googleapis.com/v1/flowMedia:batchGenerateImages*",
            "*aisandbox-pa.googleapis.com/v1/projects/*/flowMedia:batchGenerateImages*",
            "*aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoText*",
            "*aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoStartImage*",
        ]
        await cdp.send("Network.setBlockedURLs", {"urls": urls_to_block})
    except Exception:
        pass
    
    return cdp


async def fetch_recaptcha_token_via_page(
    page: Page,
    *,
    prompt_for_token: str = "a",
    timeout: int = 60,
    stabilize_seconds: int = 0,
    stop_check=None,
) -> Optional[str]:
    """
    🔥 Setup listeners, GỬI PROMPT "a", và bắt recaptcha token.
    
    - Bật chặn + gắn listener trước
    - Gửi prompt vào input và nhấn Enter
    - Đợi bắt /recaptcha/enterprise/reload để lấy rresp
    - Cleanup đúng cách để tránh listener/route handler tồn đọng
    """
    loop = asyncio.get_running_loop()
    fut: "asyncio.Future[Optional[str]]" = loop.create_future()
    
    cdp_session = None
    
    print(f"[Veo Get Token] 🎯 Setup listeners để bắt recaptcha token...")

    async def _on_response(response):
        if not _is_recaptcha_reload(response.url):
            return
        try:
            text = await response.text()
        except Exception:
            return
        token_value = _extract_recaptcha_token(text or "")
        if token_value and not fut.done():
            print(f"[Veo Get Token] ✅ Bắt được token từ /recaptcha/enterprise/reload")
            fut.set_result(token_value)

    def _on_request(req):
        # Fallback bắt token từ request generate (payload) nếu không có reload
        try:
            url = (req.url or "").strip()
            if (
                "flowMedia:batchGenerateImages" not in url
                and "batchGenerateImages" not in url
                and "batchAsyncGenerateVideoText" not in url
                and "batchAsyncGenerateVideoStartImage" not in url
            ):
                return
            raw = req.post_data or ""
            token_value = _extract_token_from_generate_post_data(raw)
            if token_value and not fut.done():
                print(f"[Veo Get Token] ✅ Bắt được token từ request payload (fallback)")
                fut.set_result(token_value)
        except Exception:
            return

    try:
        # Setup blocking + listeners TRƯỚC
        cdp_session = await apply_request_blocking_for_token(page)
        page.on("response", _on_response)
        page.on("request", _on_request)
        
        # 🔥 GỬI PROMPT để trigger recaptcha token
        if prompt_for_token:
            print(f"[Veo Get Token] 📝 Gửi prompt '{prompt_for_token}' để trigger token...")
            prompt_sent = await send_prompt_text(page, prompt_for_token, wait_ms=5000)
            if not prompt_sent:
                print(f"[Veo Get Token] ⚠️ Không gửi được prompt '{prompt_for_token}'")
            else:
                print(f"[Veo Get Token] ✅ Đã gửi prompt '{prompt_for_token}'")
        
        print(f"[Veo Get Token] ⏳ Đợi bắt recaptcha token (timeout: {timeout}s)...")

        import time as _time

        deadline = _time.monotonic() + max(1, int(timeout))
        while _time.monotonic() < deadline:
            if stop_check is not None:
                try:
                    if stop_check():
                        print("[Veo Get Token] ⚠️ Đã hủy khi đợi recaptcha token")
                        return None
                except Exception:
                    pass
            wait_s = min(1.0, deadline - _time.monotonic())
            if wait_s <= 0:
                break
            try:
                token = await asyncio.wait_for(asyncio.shield(fut), timeout=wait_s)
                if token:
                    print(f"[Veo Get Token] ✅ Đã bắt được token: {len(token)} ký tự")
                return token
            except asyncio.TimeoutError:
                continue

        print(f"[Veo Get Token] ⚠️ Timeout {timeout}s - không bắt được token")
        return None
    finally:
        # 🔥 CLEANUP: Gỡ bỏ tất cả listeners và CDP session
        try:
            page.off("response", _on_response)
        except Exception:
            pass
        try:
            page.off("request", _on_request)
        except Exception:
            pass
        
        # Tắt CDP blocking và đóng session
        if cdp_session:
            try:
                await cdp_session.send("Network.setBlockedURLs", {"urls": []})
                await cdp_session.detach()
            except Exception:
                pass


async def auto_collect_veo_auth_from_flow(page: Page, *, profile_id: str, timeout_s: int = 45) -> Optional[dict]:
    """
    Tự lấy sessionId/projectId/access_token bằng cách bắt request thật của Flow UI.
    Sau khi lấy được sẽ ghi vào backend/config/veo_auth.json.
    """
    loop = asyncio.get_running_loop()
    fut: "asyncio.Future[Optional[dict]]" = loop.create_future()

    def _try_extract_from_request(req) -> Optional[dict]:
        try:
            url = (req.url or "").strip()
            if "flowMedia:batchGenerateImages" not in url:
                return None
            m = re.search(r"/v1/projects/([^/]+)/flowMedia:batchGenerateImages", url)
            project_id = m.group(1) if m else None

            headers = req.headers or {}
            auth = headers.get("authorization") or headers.get("Authorization") or ""
            if "bearer " in auth.lower():
                access_token = auth.split(" ", 1)[1].strip()
            else:
                access_token = ""

            session_id = ""
            try:
                raw = req.post_data or ""
                obj = json.loads(raw) if raw else {}
                session_id = (
                    (obj.get("clientContext") or {}).get("sessionId")
                    or (((obj.get("requests") or [{}])[0].get("clientContext") or {}).get("sessionId"))
                    or ""
                )
            except Exception:
                session_id = ""

            if project_id and access_token and session_id:
                return {
                    "sessionId": session_id,
                    "projectId": project_id,
                    "access_token": access_token,
                    "cookie": "",
                }
        except Exception:
            return None
        return None

    async def _on_request(req):
        if fut.done():
            return
        extracted = _try_extract_from_request(req)
        if extracted:
            fut.set_result(extracted)

    page.on("request", _on_request)
    try:
        ok = await send_prompt_text(page, "a")
        if ok:
            try:
                btn = (
                    page.locator("button:has-text('Tạo')")
                    .filter(has_not_text="Trình tạo cảnh")
                    .filter(has_not_text="Không tạo được")
                    .last
                )
                await btn.wait_for(state="visible", timeout=10_000)
                await btn.click()
            except Exception:
                try:
                    btn = page.locator("button:has-text('Create')").last
                    await btn.wait_for(state="visible", timeout=10_000)
                    await btn.click()
                except Exception:
                    pass

        try:
            auth = await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            return None

        if auth:
            # Luôn cố lấy cookie từ context (ổn định hơn header request) để dùng cho các endpoint nhạy (upscale).
            try:
                cookies = await page.context.cookies()
                cookie_header = _cookies_to_header(cookies)
                if cookie_header:
                    auth["cookie"] = cookie_header
            except Exception:
                pass
            auth["cookie"] = auth.get("cookie") or ""
            save_veo_auth_config(profile_id, auth)
        return auth
    finally:
        try:
            page.off("request", _on_request)
        except Exception:
            pass


def _extract_session_id_from_submit_batch(payload: Dict[str, Any]) -> Optional[str]:
    """
    Rút sessionId từ general.submitBatchLog giống login.py:
    payload.json.appEvents[].event == 'PINHOLE_CREATE_NEW_PROJECT'
    """
    try:
        app_events = (payload.get("json") or {}).get("appEvents") or []
        for event in app_events:
            if not isinstance(event, dict):
                continue
            if event.get("event") == "PINHOLE_CREATE_NEW_PROJECT":
                metadata = event.get("eventMetadata") or {}
                session_id = metadata.get("sessionId")
                if session_id:
                    return str(session_id)
    except Exception:
        return None
    return None


def _extract_project_id_from_trpc(payload: Dict[str, Any]) -> Optional[str]:
    """
    Rút projectId từ payload/response của project.createProject (TRPC).
    Format giống login.py:
    result.data.json.result.projectId
    """
    try:
        return (
            (payload.get("result") or {})
            .get("data", {})
            .get("json", {})
            .get("result", {})
            .get("projectId")
        )
    except Exception:
        return None


def _extract_access_token_from_next_data(payload: Dict[str, Any]) -> Optional[str]:
    """
    Rút access_token từ response /_next/data giống login.py:
    pageProps.session.access_token
    """
    try:
        return (
            (payload.get("pageProps") or {})
            .get("session", {})
            .get("access_token")
        )
    except Exception:
        return None


async def auto_collect_veo_auth_on_project_creation(
    page: Page,
    *,
    profile_id: str,
    flow_url: str = FLOW_URL,
    timeout_s: int = 60,
    stop_check=None,
) -> Optional[dict]:
    """
    Flow mới: vào Flow + bấm 'Tạo dự án' rồi bắt chính request tạo project để lấy:
    - sessionId  (general.submitBatchLog)
    - projectId  (project.createProject)
    - access_token + cookie (_next/data)

    Sau khi đủ trường sẽ lưu vào backend/config/veo_auth.json theo profile_id.
    """
    loop = asyncio.get_running_loop()
    fut: "asyncio.Future[Optional[dict]]" = loop.create_future()

    capture: Dict[str, Any] = {
        "sessionId": None,
        "projectId": None,
        "access_token": None,
        "cookie": None,
    }

    def _maybe_finish() -> None:
        if (
            capture.get("sessionId")
            and capture.get("projectId")
            and capture.get("access_token")
            and not fut.done()
        ):
            project_id = str(capture.get("projectId"))
            # URL chuẩn theo projectId (không còn lưu vào settings.json)
            project_url = f"{FLOW_URL.rstrip('/')}/project/{project_id}"
            auth = {
                "sessionId": capture.get("sessionId"),
                "projectId": capture.get("projectId"),
                "access_token": capture.get("access_token"),
                "cookie": capture.get("cookie") or "",
                "project_url": project_url,
            }
            save_veo_auth_config(profile_id, auth)
            fut.set_result(auth)

    async def _on_request(req) -> None:
        if fut.done():
            return
        try:
            url = (req.url or "").strip()
        except Exception:
            url = ""

        # general.submitBatchLog -> sessionId
        if "general.submitBatchLog" in url and not capture.get("sessionId"):
            try:
                raw = req.post_data or ""
            except Exception:
                raw = ""
            try:
                obj = json.loads(raw) if raw else {}
            except Exception:
                obj = {}
            session_id = _extract_session_id_from_submit_batch(obj)
            if session_id:
                capture["sessionId"] = session_id
                _maybe_finish()

        # project.createProject -> projectId (từ request)
        if "project.createProject" in url and not capture.get("projectId"):
            try:
                raw = req.post_data or ""
            except Exception:
                raw = ""
            try:
                obj = json.loads(raw) if raw else {}
            except Exception:
                obj = {}
            project_id = _extract_project_id_from_trpc(obj)
            if project_id:
                capture["projectId"] = project_id
                _maybe_finish()

        # /_next/data -> cookie (nếu có)
        if "labs.google/fx/_next/data" in url and not capture.get("cookie"):
            try:
                cookie_header = req.headers.get("cookie")
            except Exception:
                cookie_header = None
            if cookie_header:
                capture["cookie"] = cookie_header
                _maybe_finish()

    async def _on_response(response) -> None:
        if fut.done():
            return
        try:
            url = (response.url or "").strip()
        except Exception:
            url = ""

        # project.createProject -> projectId (từ response)
        if "project.createProject" in url and not capture.get("projectId"):
            try:
                payload = await response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                project_id = _extract_project_id_from_trpc(payload)
                if project_id:
                    capture["projectId"] = project_id
                    _maybe_finish()

        # /_next/data -> access_token (+ cookie fallback)
        if "labs.google/fx/_next/data" in url and not capture.get("access_token"):
            try:
                payload = await response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                token = _extract_access_token_from_next_data(payload)
                if token:
                    capture["access_token"] = token
                    _maybe_finish()

            if not capture.get("cookie"):
                try:
                    req = response.request
                    cookie_header = req.headers.get("cookie") if req else None
                except Exception:
                    cookie_header = None
                if cookie_header:
                    capture["cookie"] = cookie_header
                    _maybe_finish()

    page.on("request", _on_request)
    page.on("response", _on_response)

    try:
        # Điều hướng + bấm "Tạo dự án" (Flow mới)
        await goto_flow_and_open_project(
            page,
            flow_url,
            stop_check=stop_check,
        )

        try:
            auth = await asyncio.wait_for(fut, timeout=max(1, int(timeout_s)))
        except asyncio.TimeoutError:
            auth = None

        # Best-effort: bổ sung cookie từ context (đôi khi request header không có/không đủ).
        if auth and isinstance(auth, dict):
            try:
                cookies = await page.context.cookies()
                cookie_header = _cookies_to_header(cookies)
                if cookie_header:
                    auth["cookie"] = cookie_header
                    save_veo_auth_config(profile_id, auth)
            except Exception:
                pass

        return auth
    finally:
        try:
            page.off("request", _on_request)
        except Exception:
            pass
        try:
            page.off("response", _on_response)
        except Exception:
            pass


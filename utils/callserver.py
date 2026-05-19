import aiohttp
import asyncio
import json
import os
import sys
import uuid
from typing import Dict, Any, Optional

# ========= CONFIG =========
API_BASE_URL = "https://server.autovideo9999.store"
TOKEN = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# BYPASS KEYS
BYPASS_KEYS = {
    "hiep2003",
    "tuan2003",
    "hiep2002",
    'phuong2003',}

_api_gate = asyncio.Semaphore(4)


# =========================================================
# RESULT TYPES
# =========================================================
class GenericApiResult:
    def __init__(self, success=False, message="", data=None):
        self.success = success
        self.message = message
        self.data: Dict[str, Any] = data or {}


class CheckAccountResult(GenericApiResult):
    def __init__(self, success=False, message="", redirect_to_payment=False, data=None):
        super().__init__(success, message, data)
        self.redirect_to_payment = redirect_to_payment


# =========================================================
# HELPERS
# =========================================================
def is_bypass_key(user_id: str) -> bool:
    return user_id and user_id.strip().lower() in BYPASS_KEYS


def _read_account_id_from_config() -> str:
    try:
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_path = os.path.join(base_dir, 'config', 'config.json')
        if not os.path.exists(cfg_path):
            return ''
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f) or {}
        if isinstance(cfg, dict):
            return str(cfg.get('ACCOUNT_ID') or cfg.get('account_id') or '').strip()
    except Exception:
        pass
    return ''


def bypass_check_result(user_id: str) -> CheckAccountResult:
    return CheckAccountResult(
        success=True,
        message="Thành công",
        redirect_to_payment=False,
        data={
            "id": user_id,
            "count": 0,
            "limit": 999999,
            "active": True,
            "bypass": True
        }
    )


def bypass_add_count_result(user_id: str) -> GenericApiResult:
    return GenericApiResult(
        success=True,
        message="Thành công",
        data={
            "id": user_id,
            "request_id": "bypass_" + uuid.uuid4().hex[:12],
            "bypass": True
        }
    )


def bypass_generic_result(user_id: str) -> GenericApiResult:
    return GenericApiResult(
        success=True,
        message="Thành công",
        data={"id": user_id, "bypass": True}
    )


def snip(text: str, max_len=600):
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return text[:max_len]


def looks_like_already_verified(msg: str) -> bool:
    if not msg:
        return False
    m = str(msg).strip().lower()
    return (
        ("already" in m)
        or ("đã xác nhận" in m)
        or ("da xac nhan" in m)
        or ("đã xử lý" in m)
        or ("da xu ly" in m)
    )


def get_headers():
    headers = {
        "Content-Type": "application/json",
        # Force no compression to avoid brotli (br) decode errors when brotli support isn't installed
        "Accept-Encoding": "identity",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


async def _read_resp_text(resp: aiohttp.ClientResponse) -> str:
    try:
        raw = await resp.read()
    except Exception:
        raw = b""

    enc = ""
    try:
        enc = str(resp.headers.get("Content-Encoding") or "").lower().strip()
    except Exception:
        enc = ""

    if enc == "br":
        try:
            import brotli  # type: ignore
            raw = brotli.decompress(raw)
        except Exception:
            return "BROTLi_ENCODED_RESPONSE"

    # decode bytes to text
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        try:
            return str(raw)
        except Exception:
            return ""


# =========================================================
# CHECK
# =========================================================
async def check_async(user_id: str) -> CheckAccountResult:
    if is_bypass_key(user_id):
        return bypass_check_result(user_id)

    if not API_BASE_URL:
        return fail_check("API URL chưa được cấu hình", "CONFIG_ERROR", user_id)

    url = f"{API_BASE_URL}/check"
    payload = {"id": user_id}

    async with _api_gate:
        try:
            async with aiohttp.ClientSession(auto_decompress=False) as session:
                async with session.post(url, json=payload, headers=get_headers(), timeout=30) as resp:
                    status = resp.status
                    text = await _read_resp_text(resp)

                    if text == "BROTLi_ENCODED_RESPONSE":
                        return fail_check(
                            "Server returned brotli (br) but brotli is not installed. Please install brotli or disable br on server.",
                            "BROTLI",
                            user_id,
                        )

                    parsed = parse_check(text, user_id)
                    parsed.data["http_status"] = status
                    parsed.data["raw_snippet"] = snip(text)

                    if status >= 300:
                        parsed.success = False
                        parsed.redirect_to_payment = True

                    return parsed

        except asyncio.TimeoutError:
            return fail_check("Timeout", "TIMEOUT", user_id)
        except Exception as e:
            return fail_check(str(e), "ERROR", user_id)


def parse_check(text: str, fallback_id: str) -> CheckAccountResult:
    try:
        data = json.loads(text)
    except:
        return fail_check("JSON error", "JSON_ERROR", fallback_id)

    if not isinstance(data, dict):
        return fail_check("Invalid format", "INVALID_RESPONSE", fallback_id)

    if "id" in data and "count" in data:
        return CheckAccountResult(
            success=True,
            message=data.get("message", "Thành công"),
            redirect_to_payment=False,
            data={
                "id": data.get("id"),
                "count": int(data.get("count", 0)),
                "limit": int(data.get("limit", 0)),
                "active": data.get("active", True)
            }
        )

    return fail_check("Invalid structure", "INVALID_RESPONSE", fallback_id)


# =========================================================
# ADD COUNT
# =========================================================
async def add_count_async(user_id: str) -> GenericApiResult:
    if not user_id:
        user_id = _read_account_id_from_config()
    if is_bypass_key(user_id):
        return bypass_add_count_result(user_id)

    if not API_BASE_URL:
        return GenericApiResult(False, "API URL chưa được cấu hình")
    if not user_id:
        return GenericApiResult(False, "ACCOUNT_ID rỗng")

    url = f"{API_BASE_URL}/add_count"

    async with _api_gate:
        try:
            async with aiohttp.ClientSession(auto_decompress=False) as session:
                async with session.post(url, json={"id": user_id}, headers=get_headers(), timeout=30) as resp:
                    text = await _read_resp_text(resp)

                    if text == "BROTLi_ENCODED_RESPONSE":
                        return GenericApiResult(False, "Server returned brotli (br) but brotli is not installed")

                    parsed: Dict[str, Any] = {}
                    try:
                        parsed = json.loads(text) if text else {}
                    except Exception:
                        parsed = {}

                    if resp.status >= 300:
                        msg = ""
                        try:
                            if isinstance(parsed, dict):
                                msg = str(parsed.get("message") or parsed.get("error") or "")
                        except Exception:
                            msg = ""
                        msg = msg.strip() if msg else ""
                        if not msg:
                            msg = snip(text)
                        return GenericApiResult(False, f"HTTP {resp.status}: {msg}", data={"http_status": resp.status, "raw_snippet": snip(text)})

                    if not isinstance(parsed, dict):
                        parsed = {}

                    data_obj = parsed.get("data", {}) if isinstance(parsed, dict) else {}
                    if not isinstance(data_obj, dict):
                        data_obj = {}
                    data_obj["http_status"] = resp.status
                    data_obj["raw_snippet"] = snip(text)

                    return GenericApiResult(
                        success=bool(parsed.get("success", False)),
                        message=str(parsed.get("message", "")),
                        data=data_obj,
                    )

        except Exception as e:
            return GenericApiResult(False, str(e))


# =========================================================
# VERIFY
# =========================================================
async def verify_count_async(request_id: str, approved: bool) -> GenericApiResult:
    if request_id.startswith("bypass_"):
        return bypass_generic_result("bypass")

    account_id = _read_account_id_from_config()
    if is_bypass_key(account_id):
        return bypass_generic_result(account_id)

    if not API_BASE_URL:
        return GenericApiResult(False, "API URL chưa được cấu hình")
    if not request_id:
        return GenericApiResult(False, "requestId rỗng")

    return await verify_with_retry(request_id, approved)


async def verify_with_retry(request_id, approved, retries=3):
    last = None
    for i in range(retries):
        last = await verify_once(request_id, approved)
        if last.success:
            return last

        try:
            msg = str(getattr(last, 'message', '') or '')
            if looks_like_already_verified(msg):
                last.success = True
                return last
        except Exception:
            pass

        if i < retries - 1:
            await asyncio.sleep(0.7 + (0.7 * i))
    return last


async def verify_once(request_id, approved):
    url = f"{API_BASE_URL}/verify_count"

    async with _api_gate:
        try:
            async with aiohttp.ClientSession(auto_decompress=False) as session:
                async with session.post(
                    url,
                    json={"request_id": request_id, "approved": approved},
                    headers=get_headers(),
                    timeout=30
                ) as resp:

                    text = await _read_resp_text(resp)

                    if text == "BROTLi_ENCODED_RESPONSE":
                        return GenericApiResult(False, "Server returned brotli (br) but brotli is not installed")

                    parsed: Dict[str, Any] = {}
                    try:
                        parsed = json.loads(text) if text else {}
                    except Exception:
                        parsed = {}

                    if resp.status >= 300:
                        msg = ""
                        try:
                            if isinstance(parsed, dict):
                                msg = str(parsed.get("message") or parsed.get("error") or "")
                        except Exception:
                            msg = ""
                        msg = msg.strip() if msg else ""
                        if not msg:
                            msg = snip(text)
                        return GenericApiResult(
                            False,
                            f"HTTP {resp.status}: {msg}",
                            data={"http_status": resp.status, "raw_snippet": snip(text)},
                        )

                    if not isinstance(parsed, dict):
                        parsed = {}

                    data_obj = parsed.get("data", {}) if isinstance(parsed, dict) else {}
                    if not isinstance(data_obj, dict):
                        data_obj = {}
                    data_obj["http_status"] = resp.status
                    data_obj["raw_snippet"] = snip(text)

                    return GenericApiResult(
                        success=bool(parsed.get("success", False)),
                        message=str(parsed.get("message", "")),
                        data=data_obj,
                    )

        except Exception as e:
            return GenericApiResult(False, str(e))


# =========================================================
# FAIL HELPERS
# =========================================================
def fail_check(message, code, user_id):
    return CheckAccountResult(
        success=False,
        message=message,
        redirect_to_payment=False,
        data={
            "error_code": code,
            "id": user_id,
            "count": 0,
            "limit": 0
        }
    )
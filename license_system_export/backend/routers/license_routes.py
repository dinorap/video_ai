from fastapi import APIRouter
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

router = APIRouter()

# --- MODELS ---
class LicenseActivateReq(BaseModel):
    license_key: str

# --- HELPER FUNCTIONS ---
def _get_license_server_data() -> dict:
    """
    Đọc `server_data` từ cache license (storage/config/{product_id}.lic).
    server_data là response gần nhất từ license-server (verify/activate).
    """
    try:
        from license_core.storage import LicenseStorage  # type: ignore
        
        # Thay đổi STORAGE_DIR và product_id theo project của bạn
        STORAGE_DIR = Path("storage")  # Hoặc đường dẫn khác
        product_id = "yt_tool"  # Thay đổi theo product của bạn
        
        lic_path = STORAGE_DIR / "config" / f"{product_id}.lic"
        storage = LicenseStorage(str(lic_path))
        data = storage.load_full_data() or {}
        if not isinstance(data, dict):
            return {}
        server_data = data.get("server_data") or {}
        return server_data if isinstance(server_data, dict) else {}
    except Exception:
        return {}


def _get_license_ui_mode() -> int:
    """
    Đọc ui_mode từ cache license (storage/config/{product_id}.lic).
    ui_mode do license-server trả về và được lưu trong `server_data`.

    Quy ước:
    - 1: All (url/custom/comic/story)
    - 2: Chỉ url + custom
    - 3: Chỉ comic + story
    """
    try:
        server_data = _get_license_server_data()
        ui_mode = server_data.get("ui_mode", 1)
        ui_mode_int = int(ui_mode)
        if ui_mode_int in (1, 2, 3):
            return ui_mode_int
        return 1
    except Exception:
        return 1


def _get_license_yt_plan() -> str:
    """
    Đọc yt_plan từ cache license (server_data["yt_plan"]).
    Quy ước:
    - "standard": Plan cơ bản
    - "pro": Plan Pro
    - "pro_plus": Plan Pro+
    """
    try:
        server_data = _get_license_server_data()
        plan = str(server_data.get("yt_plan") or "").strip().lower()
        if plan in ("pro_plus", "pro+"):
            return "pro_plus"
        if plan == "pro":
            return "pro"
        return "standard"
    except Exception:
        return "standard"


# --- API ENDPOINTS ---

@router.get("/api/license/ui-mode")
def api_get_license_ui_mode():
    """
    Trả về ui_mode để frontend ẩn/hiện subtab theo license key.
    """
    return {"ui_mode": _get_license_ui_mode()}


@router.get("/api/license/info")
def api_get_license_info():
    """
    Trả về thông tin license cần cho UI gating (ui_mode/yt_plan).
    """
    return {"ui_mode": _get_license_ui_mode(), "yt_plan": _get_license_yt_plan()}


@router.get("/api/license/status")
def api_get_license_status():
    """
    Trả về thông tin license hiện tại để hiển thị trên UI:
    - license_key: key đang lưu (nguyên bản)
    - ui_mode, yt_plan: như /api/license/info
    - expire_at, ok: lấy từ server_data cache (nếu có)
    """
    try:
        from license_core.storage import LicenseStorage  # type: ignore
        
        # Thay đổi STORAGE_DIR và product_id theo project của bạn
        STORAGE_DIR = Path("storage")
        product_id = "yt_tool"
        
        lic_path = STORAGE_DIR / "config" / f"{product_id}.lic"
        storage = LicenseStorage(str(lic_path))
        data = storage.load_full_data() or {}
        if not isinstance(data, dict):
            data = {}
        license_key = str(data.get("license_key") or "").strip()
        server_data = data.get("server_data") or {}
        
        ok = bool(server_data.get("ok"))
        expire_at = server_data.get("expire_at")
        
        return {
            "license_key": license_key,
            "ok": ok,
            "expire_at": expire_at,
            "ui_mode": _get_license_ui_mode(),
            "yt_plan": _get_license_yt_plan(),
        }
    except Exception:
        return {
            "license_key": "",
            "ok": False,
            "expire_at": None,
            "ui_mode": _get_license_ui_mode(),
            "yt_plan": _get_license_yt_plan(),
        }


@router.post("/api/license/activate")
def api_activate_license(req: LicenseActivateReq):
    """
    Kích hoạt license key mới từ frontend:
    - Gọi LicenseGuard.activate
    - Trả về kết quả kèm ui_mode/yt_plan
    """
    key = (req.license_key or "").strip().upper()
    if not key:
        return {"ok": False, "message": "Vui lòng nhập license key"}
    
    try:
        from license_core.api import LicenseGuard  # type: ignore
        
        # Lấy server_url (thay đổi theo logic của bạn)
        default_url = "https://license.nanoproai.shop"
        server_url = default_url
        
        # Thay đổi product_id theo project của bạn
        product_id = "yt_tool"
        
        try:
            from license_core.storage import LicenseStorage  # type: ignore
            STORAGE_DIR = Path("storage")
            lic_path = STORAGE_DIR / "config" / f"{product_id}.lic"
            storage = LicenseStorage(str(lic_path))
            stored_url = storage.load_server_url()
            if stored_url:
                server_url = stored_url
        except Exception:
            pass
        
        guard = LicenseGuard(server_url=server_url, product_id=product_id, allow_offline=False)
        ok, msg = guard.activate(key)
        
        if not ok:
            return {"ok": False, "message": msg}
        
        # Sau khi activate, chạy check_license để cập nhật server_data/ui_mode vào cache
        result = guard.check_license()
        if not result.get("ok"):
            return {"ok": False, "message": result.get("message", "Kích hoạt thất bại")}
        
        return {
            "ok": True,
            "message": msg,
            "ui_mode": _get_license_ui_mode(),
            "yt_plan": _get_license_yt_plan(),
        }
    except Exception as e:
        return {"ok": False, "message": f"Lỗi hệ thống: {str(e)}"}

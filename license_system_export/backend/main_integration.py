# backend/main_integration.py
# Code mẫu để tích hợp license system vào FastAPI app

import os
import sys
from pathlib import Path
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

# --- CẤU HÌNH ---
PRODUCT_ID = "yt_tool"  # Thay đổi theo product của bạn
STORAGE_DIR = Path("storage")  # Thay đổi theo cấu trúc project

# --- GLOBAL STATE ---
LICENSE_OK = False
LICENSE_REASON = None
LICENSE_GUARD = None


def _license_config_dir() -> Path:
    """Thư mục lưu file license"""
    return STORAGE_DIR / "config"


def _get_license_server_url() -> str:
    """
    Load license server url từ storage/config/{product_id}.lic (có signature bảo vệ).
    Nếu không có trong .lic, dùng default: https://license.nanoproai.shop
    """
    default_url = "https://license.nanoproai.shop"
    
    try:
        from license_core.storage import LicenseStorage
        cfg_dir = _license_config_dir()
        license_file = cfg_dir / f"{PRODUCT_ID}.lic"
        
        if license_file.exists():
            storage = LicenseStorage(str(license_file))
            stored_url = storage.load_server_url()
            if stored_url and isinstance(stored_url, str):
                url = stored_url.strip()
                if url:
                    return url.rstrip("/")
    except Exception:
        pass
    
    return default_url.rstrip("/")


def _save_license_server_url_to_settings(server_url: str) -> None:
    """
    Persist license server url to storage/config/{product_id}.lic (có signature bảo vệ).
    """
    server_url = (server_url or "").strip().rstrip("/")
    if not server_url:
        return
    
    try:
        from license_core.storage import LicenseStorage
        cfg_dir = _license_config_dir()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        license_file = cfg_dir / f"{PRODUCT_ID}.lic"
        
        storage = LicenseStorage(str(license_file))
        storage.save_server_url(server_url)
        print(f"🔐 [LICENSE] Đã lưu server URL vào file license")
    except Exception as e:
        print(f"⚠️ [LICENSE] Lỗi lưu server URL: {e}")


def _on_license_fail(reason: str, message: str) -> None:
    """
    Callback từ periodic check. Chỉ khi license FAIL mới dừng luồng.
    """
    global LICENSE_OK, LICENSE_REASON
    LICENSE_OK = False
    LICENSE_REASON = reason
    
    print(f"🔐 [LICENSE FAIL] reason={reason} message={message}")
    
    # Thêm logic xử lý khi license fail (stop jobs, reset process, etc.)
    # Ví dụ:
    # - network/server error: không làm gì (để tự check lại)
    # - lỗi nghiêm trọng (expired/revoked): stop app hoặc reset


def ensure_license() -> None:
    """
    Ensure license is valid before starting the app.
    Gọi hàm này TRƯỚC khi khởi tạo FastAPI app.
    """
    global LICENSE_OK, LICENSE_REASON, LICENSE_GUARD
    
    LICENSE_OK = False
    LICENSE_REASON = None
    
    # Skip license check trong dev mode (optional)
    is_dev = os.getenv("SKIP_LICENSE_CHECK", "0") == "1"
    if is_dev:
        print("🔐 [LICENSE] SKIP_LICENSE_CHECK=1 -> bypass (DEV MODE ONLY)")
        LICENSE_OK = True
        return
    
    try:
        # Đảm bảo folder config tồn tại
        cfg_dir = _license_config_dir()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        
        from license_core import LicenseGuard
        from license_core.gui import ModernLicenseUI
        
        server_url = _get_license_server_url()
        guard = LicenseGuard(server_url=server_url, product_id=PRODUCT_ID, allow_offline=False)
        
        # Lần check đầu (cache/online)
        result = guard.check_license()
        if result.get("ok"):
            LICENSE_OK = True
            LICENSE_GUARD = guard
            print(f"✅ [LICENSE] {result.get('message', 'Active')}")
        else:
            # License không hợp lệ -> Hiện GUI để user nhập key
            LICENSE_REASON = result.get("reason", "unknown")
            print(f"❌ [LICENSE] {result.get('message', 'Inactive')}")
            print("🔐 [LICENSE] Đang mở GUI để kích hoạt...")
            
            ui = ModernLicenseUI(guard, auto_close=True, allow_edit_server=True)
            ui.show()
            
            # Sau khi UI đóng, thử check lại
            _save_license_server_url_to_settings(getattr(guard, "server_url", server_url))
            result2 = guard.check_license()
            if not result2.get("ok"):
                print(f"❌ [LICENSE] Vẫn chưa kích hoạt thành công. Thoát app.")
                sys.exit(1)
            
            LICENSE_OK = True
            LICENSE_GUARD = guard
            print(f"✅ [LICENSE] {result2.get('message', 'Active')}")
        
        # Start periodic check (2h/lần)
        if LICENSE_GUARD:
            try:
                LICENSE_GUARD.start_periodic_check(interval_hours=2, on_fail=_on_license_fail)
                print("🔐 [LICENSE] Đã bật periodic check (2h/lần)")
            except Exception as e:
                print(f"⚠️ [LICENSE] Không thể bật periodic check: {e}")
    
    except Exception as e:
        # Nếu có lỗi nghiêm trọng trong quá trình khởi tạo license guard
        LICENSE_REASON = "system_error"
        print(f"❌ [LICENSE] Lỗi hệ thống khi kiểm tra license: {e}")
        print(f"🔐 [LICENSE] Đang mở GUI để cấu hình lại...")
        
        try:
            from license_core import LicenseGuard
            from license_core.gui import ModernLicenseUI
            
            server_url = _get_license_server_url()
            guard = LicenseGuard(server_url=server_url, product_id=PRODUCT_ID, allow_offline=False)
            cfg_dir = _license_config_dir()
            
            try:
                ui = ModernLicenseUI(guard, auto_close=True, allow_edit_server=True)
                ui.show()
            except Exception:
                print("❌ [LICENSE] Không thể mở GUI. Thoát app.")
                sys.exit(1)
            
            # Sau khi UI đóng, thử check lại
            _save_license_server_url_to_settings(getattr(guard, "server_url", server_url))
            result = guard.check_license()
            if result.get("ok"):
                LICENSE_OK = True
                LICENSE_GUARD = guard
                try:
                    guard.start_periodic_check(interval_hours=2, on_fail=_on_license_fail)
                except Exception:
                    pass
            else:
                print(f"❌ [LICENSE] Vẫn chưa kích hoạt thành công. Thoát app.")
                sys.exit(1)
        except Exception as e2:
            print(f"❌ [LICENSE] Lỗi nghiêm trọng: {e2}")
            sys.exit(1)


# --- MIDDLEWARE: Block API nếu license không hợp lệ ---
class LicenseMiddleware(BaseHTTPMiddleware):
    """
    Middleware kiểm tra license trước khi xử lý request.
    Cho phép một số route không cần license (static files, root, events stream).
    """
    async def dispatch(self, request: Request, call_next):
        # Cho phép các route không cần license: static files, root, events stream
        path = request.url.path
        
        # Whitelist: các route không cần check license
        whitelist = [
            "/",
            "/api/events",
            "/api/license/",  # Các API license
        ]
        
        # Cho phép static files
        if path.startswith("/_nuxt/") or path.startswith("/assets/"):
            return await call_next(request)
        
        # Cho phép whitelist
        for prefix in whitelist:
            if path.startswith(prefix):
                return await call_next(request)
        
        # Kiểm tra license
        if not LICENSE_OK:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={
                    "error": "License không hợp lệ",
                    "reason": LICENSE_REASON or "Chưa kích hoạt license",
                    "message": "Vui lòng kích hoạt license để sử dụng tool"
                }
            )
        
        return await call_next(request)


# --- CÁCH SỬ DỤNG ---
"""
# Trong file main.py của bạn:

# 1. Import
from main_integration import ensure_license, LicenseMiddleware

# 2. Gọi ensure_license() TRƯỚC khi khởi tạo FastAPI app
ensure_license()

# 3. Khởi tạo FastAPI app
app = FastAPI()

# 4. Thêm middleware
app.add_middleware(LicenseMiddleware)

# 5. Register license routes
from routers import license_routes
app.include_router(license_routes.router)

# 6. Start server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""

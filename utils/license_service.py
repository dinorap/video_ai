"""
Tích hợp license cho Flask (VideoCreator).
File .lic: config/{LICENSE_PRODUCT_ID}.lic
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from utils.path_helper import CONFIG_DIR, is_running_as_exe

LICENSE_OK = False
LICENSE_REASON: Optional[str] = None
LICENSE_GUARD = None

_LICENSE_WHITELIST_PREFIXES = (
    "/api/license/",
    "/api/version",
    "/favicon.ico",
    "/templaces/",
    "/ico/",
    "/static/",
)

_LICENSE_WHITELIST_EXE_EXTRA = (
    "/api/debug/runtime",
)


def _skip_license_check() -> bool:
    """EXE không bao giờ bỏ qua. Dev: chỉ khi SKIP_LICENSE_CHECK=1."""
    if is_running_as_exe():
        return False
    return os.getenv("SKIP_LICENSE_CHECK", "").strip().lower() in ("1", "true", "yes")


def _normalize_server_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def license_file_path() -> Path:
    return CONFIG_DIR / f"{_product_id()}.lic"


def _product_id() -> str:
    from version import LICENSE_PRODUCT_ID
    return LICENSE_PRODUCT_ID


def _default_server_url() -> str:
    from version import LICENSE_SERVER_URL
    return _normalize_server_url(LICENSE_SERVER_URL or "https://license.nanoproai.shop")


def get_license_server_url() -> str:
    """Ưu tiên URL đã lưu trong .lic (Tkinter, có mật khẩu admin), fallback version.py."""
    try:
        from utils.license_core.storage import LicenseStorage

        lic = license_file_path()
        if lic.is_file():
            stored = LicenseStorage(str(lic)).load_server_url()
            if stored and str(stored).strip():
                return _normalize_server_url(str(stored))
    except Exception:
        pass
    return _default_server_url()


def save_license_server_url(server_url: str) -> None:
    server_url = _normalize_server_url(server_url)
    if not server_url:
        return
    try:
        from utils.license_core.storage import LicenseStorage

        lic = license_file_path()
        lic.parent.mkdir(parents=True, exist_ok=True)
        LicenseStorage(str(lic)).save_server_url(server_url)
    except Exception as exc:
        print(f"[LICENSE] save server url failed: {exc}")


def _on_license_fail(reason: str, message: str) -> None:
    global LICENSE_OK, LICENSE_REASON
    LICENSE_OK = False
    LICENSE_REASON = reason
    print(f"[LICENSE FAIL] reason={reason} message={message}")


def _create_guard():
    from utils.license_core import LicenseGuard

    server_url = get_license_server_url()
    lic = license_file_path()
    return LicenseGuard(
        server_url=server_url,
        product_id=_product_id(),
        allow_offline=False,
        license_file=str(lic),
    )


def ensure_license(*, use_gui: bool = True) -> None:
    """Gọi trước khi chạy server. Chưa có key hợp lệ → Tkinter."""
    global LICENSE_OK, LICENSE_REASON, LICENSE_GUARD

    LICENSE_OK = False
    LICENSE_REASON = None

    if _skip_license_check():
        print("[LICENSE] Skipped (SKIP_LICENSE_CHECK=1, dev only)")
        LICENSE_OK = True
        return

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        guard = _create_guard()
        result = guard.check_license()
        if result.get("ok"):
            LICENSE_OK = True
            LICENSE_GUARD = guard
            print(f"[LICENSE] OK — {result.get('message', '')}")
        elif use_gui:
            from utils.license_core.gui import ModernLicenseUI

            print(f"[LICENSE] {result.get('message', 'Inactive')} — opening activation UI...")
            ui = ModernLicenseUI(guard, auto_close=True, allow_edit_server=True)
            ui.show()
            save_license_server_url(getattr(guard, "server_url", get_license_server_url()))
            result2 = guard.check_license()
            if not result2.get("ok"):
                print("[LICENSE] Activation failed. Exit.")
                sys.exit(1)
            LICENSE_OK = True
            LICENSE_GUARD = guard
            print(f"[LICENSE] OK — {result2.get('message', '')}")
        else:
            LICENSE_REASON = result.get("reason", "unknown")
            print(f"[LICENSE] Invalid: {result.get('message')}")
            sys.exit(1)

        if LICENSE_GUARD:
            try:
                LICENSE_GUARD.start_periodic_check(interval_hours=2, on_fail=_on_license_fail)
            except Exception as exc:
                print(f"[LICENSE] periodic check: {exc}")

    except Exception as exc:
        print(f"[LICENSE] System error: {exc}")
        if use_gui:
            try:
                from utils.license_core.gui import ModernLicenseUI

                guard = _create_guard()
                ui = ModernLicenseUI(guard, auto_close=True, allow_edit_server=True)
                ui.show()
                save_license_server_url(getattr(guard, "server_url", get_license_server_url()))
                result = guard.check_license()
                if not result.get("ok"):
                    sys.exit(1)
                LICENSE_OK = True
                LICENSE_GUARD = guard
                guard.start_periodic_check(interval_hours=2, on_fail=_on_license_fail)
            except Exception:
                sys.exit(1)
        else:
            sys.exit(1)


def is_license_request_allowed(path: str) -> bool:
    if path in ("/", "/index.html"):
        return True
    prefixes = _LICENSE_WHITELIST_PREFIXES
    if not is_running_as_exe():
        prefixes = prefixes + _LICENSE_WHITELIST_EXE_EXTRA
    for prefix in prefixes:
        if path.startswith(prefix):
            return True
    if path.startswith("/config/") and LICENSE_OK:
        return True
    return False


def license_middleware():
    """Flask before_request: chặn API khi chưa có license."""
    from flask import jsonify, request

    if _skip_license_check():
        return None
    if LICENSE_OK:
        return None
    path = request.path or ""
    if is_license_request_allowed(path):
        return None
    return jsonify({
        "ok": False,
        "error": "License không hợp lệ",
        "reason": LICENSE_REASON or "not_activated",
        "message": "Vui lòng kích hoạt license key",
        "product_id": _product_id(),
    }), 403


def _load_storage_data() -> dict:
    try:
        from utils.license_core.storage import LicenseStorage

        lic = license_file_path()
        if not lic.is_file():
            return {}
        data = LicenseStorage(str(lic)).load_full_data() or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_license_key() -> str:
    if _skip_license_check():
        return ""
    data = _load_storage_data()
    return str(data.get("license_key") or "").strip()


def get_license_status() -> Dict[str, Any]:
    data = _load_storage_data()
    server_data = data.get("server_data") or {}
    if not isinstance(server_data, dict):
        server_data = {}
    return {
        "license_key": str(data.get("license_key") or "").strip() if LICENSE_OK else "",
        "ok": bool(LICENSE_OK and server_data.get("ok") is True),
        "expire_at": server_data.get("expire_at") if LICENSE_OK else None,
        "product_id": _product_id(),
    }


def activate_license_key(license_key: str) -> Tuple[bool, str, Dict[str, Any]]:
    if _skip_license_check():
        return False, "License check disabled (dev)", {}

    key = (license_key or "").strip().upper()
    if not key:
        return False, "Vui lòng nhập license key", {}

    global LICENSE_OK, LICENSE_GUARD

    try:
        guard = _create_guard()
        ok, msg = guard.activate(key)
        if not ok:
            return False, msg, {}

        result = guard.check_license()
        if not result.get("ok"):
            return False, result.get("message", "Kích hoạt thất bại"), {}

        LICENSE_OK = True
        LICENSE_GUARD = guard
        try:
            guard.start_periodic_check(interval_hours=2, on_fail=_on_license_fail)
        except Exception:
            pass

        status = get_license_status()
        return True, msg, status
    except Exception as exc:
        return False, f"Lỗi hệ thống: {exc}", {}

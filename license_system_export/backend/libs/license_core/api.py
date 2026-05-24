# libs/license_core/api.py
import requests
import time
import threading
import socket
from .hwid import get_hwid
from .storage import LicenseStorage

# --- 1. MAPPING MESSAGE (Việt hóa lỗi) ---
ERROR_MAP = {
    "hwid_mismatch": "❌ Key này đã kích hoạt trên máy khác!",
    "expired": "⚠️ Key đã hết hạn sử dụng.",
    "revoked": "🚫 Key đã bị Admin thu hồi.",
    "license_not_found": "❌ Key không tồn tại trên hệ thống.",
    "license_not_activated": "⚠️ Key chưa được kích hoạt.",
    "server_error": "🔌 Lỗi kết nối Server.",
    "network_error": "📡 Không có mạng Internet.",
    "no_key": "🔑 Chưa nhập key kích hoạt."
}

class LicenseGuard:
    def __init__(self, server_url, product_id, allow_offline=False):
        self.product_id = product_id
        # allow_offline: Deprecated - Không còn hỗ trợ offline mode
        self.hwid = get_hwid()
        self.storage = LicenseStorage(f"{product_id}.lic")

        # Default server URL
        DEFAULT_SERVER_URL = "https://license.nanoproai.shop"
        
        # Ưu tiên: server_url param (từ main.py đã resolve) > stored_url (từ .lic) > default
        # Logic này cho phép main.py override URL khi cần (ví dụ: khi user sửa domain trong GUI)
        stored_url = self.storage.load_server_url()
        base_url = (server_url or stored_url or DEFAULT_SERVER_URL).strip()
        self.server_url = base_url.rstrip("/") if base_url else DEFAULT_SERVER_URL
        
        # Periodic check state
        self._periodic_thread = None
        self._periodic_stop_event = None
        self._on_license_fail = None  # Callback khi license fail

    def _get_msg(self, code):
        """Hàm nội bộ để lấy message tiếng Việt"""
        return ERROR_MAP.get(code, f"Lỗi không xác định ({code})")

    def check_license(self):
        """Hàm chính: Check cache -> Check Server"""
        # 1. LOAD CACHE
        cached_data = self.storage.load_full_data()
        if cached_data and self._validate_cache(cached_data):
             # Lấy expire_at từ cache để hiển thị
            expire_info = cached_data.get("server_data", {}).get("expire_at", "Unknown")
            if expire_info is None:
                expire_info = "Vĩnh viễn"
            return {"ok": True, "message": f"Active (Cache Mode) - Hạn: {expire_info}"}

        # 2. GỌI SERVER
        saved_key = self.storage.load_key_only()
        if not saved_key:
            return {"ok": False, "reason": "no_key", "message": self._get_msg("no_key")}

        try:
            payload = {
                "license_key": saved_key,
                "hwid": self.hwid,
                "product_id": self.product_id
            }
            # Timeout 5s để không treo tool
            response = requests.post(f"{self.server_url}/license/verify", json=payload, timeout=5)
            
            if response.status_code != 200:
                return {"ok": False, "reason": "server_error", "message": self._get_msg("server_error")}
            
            data = response.json()
            
            if data['ok']:
                # Active OK -> Lưu Cache mới (Kèm response từ server + HWID)
                self.storage.save_cache(saved_key, data, self.hwid)
                
                # Trả về kèm thông tin hạn dùng (nếu có)
                expire_at = data.get("expire_at", "Lifetime")
                return {"ok": True, "message": f"Active (Online) - Hạn: {expire_at}"}
            else:
                reason = data.get('reason', 'unknown')
                # Nếu lỗi nghiêm trọng -> Xóa key để bắt nhập lại
                if reason in ['hwid_mismatch', 'revoked', 'expired', 'product_mismatch']:
                    self.storage.clear()
                return {"ok": False, "reason": reason, "message": self._get_msg(reason)}

        except Exception as e:
            # Lỗi mạng: Không cho phép offline mode
            return {"ok": False, "reason": "network_error", "message": self._get_msg("network_error") + f" {str(e)}"}

    def activate(self, license_key):
        """
        Kích hoạt key với xử lý lỗi mạng chi tiết
        """
        try:
            payload = {
                "license_key": license_key,
                "hwid": self.hwid,
                "product_id": self.product_id,
                "device_name": socket.gethostname(),
            }
            
            # Timeout 10s: Đủ lâu để server xử lý, đủ nhanh để không treo tool quá lâu
            response = requests.post(
                f"{self.server_url}/license/activate", 
                json=payload, 
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    self.storage.save_cache(license_key, data, self.hwid)
                    return True, "Kích hoạt thành công!"
                else:
                    reason = data.get('reason', 'unknown')
                    msg = data.get('detail') or data.get('message') or self._get_msg(reason)
                    return False, msg
            else:
                # Xử lý các lỗi HTTP khác (404, 500, 502...)
                try:
                    err = response.json()
                    return False, err.get('detail', f"Lỗi Server ({response.status_code})")
                except:
                    return False, f"Lỗi Server: {response.status_code}"

        # --- BẮT LỖI MẠNG CỤ THỂ ---
        except requests.exceptions.Timeout:
            return False, "⏳ Hết thời gian chờ (Timeout). Vui lòng kiểm tra mạng!"
            
        except requests.exceptions.ConnectionError:
            return False, "🔌 Không thể kết nối Server. Vui lòng kiểm tra Internet hoặc URL Server."
            
        except requests.exceptions.RequestException as e:
            return False, f"📡 Lỗi kết nối không xác định: {str(e)}"
            
        except Exception as e:
            return False, f"❌ Lỗi hệ thống: {str(e)}"

    def _validate_cache(self, data):
        """
        Logic check cache 2h + expire_at + HWID.
        HWID trong cache phải trùng máy hiện tại (chống copy .lic sang máy khác).
        """
        try:
            # 1. Kiểm tra thời gian cache (2h)
            last_check = data.get("last_check", 0)
            if time.time() - last_check >= 7200:  # Quá 2h -> Cache hết hạn
                return False

            # 2. Kiểm tra HWID (chống copy .lic sang máy khác / gửi .lic mới mỗi 2h)
            cached_hwid = data.get("hwid")
            if cached_hwid is None:
                # Cache cũ không có hwid -> bắt verify lại server, rồi save_cache sẽ ghi hwid
                return False
            if cached_hwid != self.hwid:
                return False

            # 3. Kiểm tra expire_at từ server (tránh dùng license đã hết hạn)
            server_data = data.get("server_data", {})
            expire_at = server_data.get("expire_at")

            if expire_at is not None:
                try:
                    if isinstance(expire_at, (int, float)):
                        expire_timestamp = float(expire_at)
                    else:
                        from datetime import datetime
                        expire_str = str(expire_at).strip()
                        try:
                            expire_timestamp = datetime.strptime(expire_str, "%Y-%m-%d %H:%M:%S").timestamp()
                        except ValueError:
                            try:
                                expire_timestamp = datetime.fromisoformat(expire_str.replace("Z", "+00:00")).timestamp()
                            except ValueError:
                                return False
                    if time.time() >= expire_timestamp:
                        return False
                except Exception:
                    return False

            return True
        except Exception:
            return False

    def start_periodic_check(self, interval_hours=2, on_fail=None):
        """
        Bắt đầu check license định kỳ trong background thread.
        
        Args:
            interval_hours: Khoảng thời gian giữa các lần check (mặc định 2 giờ)
            on_fail: Callback function được gọi khi license fail
                     Signature: on_fail(reason, message)
        
        Returns:
            True nếu start thành công, False nếu đã có thread đang chạy
        """
        if self._periodic_thread is not None and self._periodic_thread.is_alive():
            return False  # Đã có thread đang chạy
        
        self._on_license_fail = on_fail
        self._periodic_stop_event = threading.Event()
        
        def _periodic_check_loop():
            interval_seconds = interval_hours * 3600
            while not self._periodic_stop_event.is_set():
                # Đợi interval_hours
                if self._periodic_stop_event.wait(timeout=interval_seconds):
                    break  # Bị stop
                
                # Check license (sẽ tự động bỏ cache nếu quá 2h)
                result = self.check_license()
                
                if not result.get('ok'):
                    reason = result.get('reason', 'unknown')
                    message = result.get('message', 'License check failed')
                    
                    # Gọi callback nếu có
                    if self._on_license_fail:
                        try:
                            self._on_license_fail(reason, message)
                        except Exception as e:
                            # Không để callback lỗi làm crash thread
                            pass
        
        self._periodic_thread = threading.Thread(target=_periodic_check_loop, daemon=True)
        self._periodic_thread.start()
        return True

    def stop_periodic_check(self):
        """
        Dừng periodic check thread.
        """
        if self._periodic_stop_event:
            self._periodic_stop_event.set()
        
        if self._periodic_thread and self._periodic_thread.is_alive():
            self._periodic_thread.join(timeout=5)  # Đợi tối đa 5s
        
        self._periodic_thread = None
        self._periodic_stop_event = None
        self._on_license_fail = None

# libs/license_core/storage.py
import json
import os
import time
import hmac
import hashlib
import base64

# KEY dùng để ký license.
# Ưu tiên dùng hash (SIGNATURE_SECRET_HASH) để tránh giữ secret plaintext trong file config.
OBFUSCATED_SECRET = "U0VQX0RFUF9UUkFJX1ZPX0RPSV9QUk9fTUFYXzIwMjU="  # Base64 của "SEP_DEP_TRAI_VO_DOI_PRO_MAX_2025"

def _decode_secret(obfuscated: str) -> str:
    """Decode obfuscated secret để lấy secret gốc"""
    try:
        return base64.b64decode(obfuscated.encode('utf-8')).decode('utf-8')
    except Exception:
        # Fallback nếu decode lỗi (không nên xảy ra)
        return "SEP_DEP_TRAI_VO_DOI_PRO_MAX_2025"

# Ưu tiên đọc từ file .env.enc đặt cùng thư mục libs/license_core.
# Fallback sang .env để tiện dev local.
try:
    BASE_DIR = os.path.dirname(__file__)
    from .env_secure import load_license_env
    load_license_env(BASE_DIR)
except Exception:
    pass

def _is_sha256_hex(value: str) -> bool:
    v = (value or "").strip().lower()
    if len(v) != 64:
        return False
    return all(c in "0123456789abcdef" for c in v)

def _resolve_signature_key() -> str:
    # 1) Preferred: pre-hashed secret from env.
    env_hash = (os.getenv("SIGNATURE_SECRET_HASH") or "").strip().lower()
    if _is_sha256_hex(env_hash):
        return env_hash

    # 2) Backward compatibility: plaintext env secret -> hash it in-memory.
    env_secret = os.getenv("SIGNATURE_SECRET")
    if env_secret:
        return hashlib.sha256(env_secret.encode("utf-8")).hexdigest()

    # 3) Last fallback for old deployments.
    fallback_secret = _decode_secret(OBFUSCATED_SECRET)
    return hashlib.sha256(fallback_secret.encode("utf-8")).hexdigest()

SIGNATURE_SECRET = _resolve_signature_key()

class LicenseStorage:
    def __init__(self, file_path="license.dat"):
        self.file_path = file_path

    def _sign_data(self, data_str):
        """Tạo chữ ký HMAC-SHA256 (key đã được hash)."""
        return hmac.new(
            SIGNATURE_SECRET.encode('utf-8'), 
            data_str.encode('utf-8'), 
            hashlib.sha256
        ).hexdigest()

    def _read_file(self):
        """Đọc file và KIỂM TRA CHỮ KÝ"""
        if not os.path.exists(self.file_path):
            return None
        try:
            with open(self.file_path, "r", encoding='utf-8') as f:
                wrapped_data = json.load(f)
            
            # Cấu trúc mong đợi: {"payload": "json_string", "signature": "hex"}
            payload_str = wrapped_data.get("payload", "")
            signature = wrapped_data.get("signature", "")
            
            # 1. Tính toán lại chữ ký
            expected_sig = self._sign_data(payload_str)
            
            # 2. So sánh (Dùng compare_digest để chống timing attack)
            if not hmac.compare_digest(expected_sig, signature):
                print("⚠️ Cảnh báo: File license đã bị sửa đổi trái phép!")
                return None # Chữ ký sai -> Coi như không có file
                
            # 3. Chữ ký đúng -> Parse JSON thật ra dùng
            return json.loads(payload_str)
            
        except Exception as e:
            # File lỗi hoặc format cũ -> Reset
            return None

    def _write_file(self, data):
        """Ghi file kèm chữ ký bảo vệ"""
        try:
            # 1. Chuyển data thật thành chuỗi JSON (sort_keys để nhất quán)
            payload_str = json.dumps(data, sort_keys=True)
            
            # 2. Ký tên vào chuỗi đó
            signature = self._sign_data(payload_str)
            
            # 3. Gói lại
            final_content = {
                "payload": payload_str,
                "signature": signature
            }
            
            with open(self.file_path, "w", encoding='utf-8') as f:
                json.dump(final_content, f, indent=4)
                
        except Exception as e:
            print(f"Lỗi ghi file license: {e}")

    # --- CÁC HÀM API KHÔNG ĐỔI (Chỉ thay đổi cách gọi _read/_write bên trong) ---

    def load_full_data(self):
        return self._read_file()

    # --- LƯU / ĐỌC RIÊNG SERVER URL ---
    def load_server_url(self):
        """
        Trả về server_url nếu đã được lưu trong file license.
        Nếu chưa có, trả về None.
        """
        data = self._read_file()
        if data and isinstance(data, dict):
            return data.get("server_url")
        return None

    def save_server_url(self, server_url: str):
        """
        Lưu server_url vào cùng file license, giữ nguyên các field khác nếu có.
        """
        current = self._read_file()
        if not isinstance(current, dict):
            current = {}
        current["server_url"] = server_url
        self._write_file(current)

    def load_key_only(self):
        data = self._read_file()
        if data and isinstance(data, dict):
            return data.get("license_key")
        return None

    def save(self, license_key):
        # Giữ lại các field khác (vd: server_url) nếu có
        data = self._read_file()
        if not isinstance(data, dict):
            data = {}
        data.update({
            "license_key": license_key,
            "updated_at": time.time()
        })
        self._write_file(data)

    def save_cache(self, license_key, server_response, hwid: str = None):
        """Lưu cache kèm HWID để validate khi dùng cache (chống copy .lic sang máy khác)."""
        data = self._read_file()
        if not isinstance(data, dict):
            data = {}
        data.update({
            "license_key": license_key,
            "last_check": time.time(),
            "server_data": server_response
        })
        if hwid is not None:
            data["hwid"] = hwid
        self._write_file(data)
            
    def clear(self):
        """
        Xóa license key và cache, nhưng giữ lại server_url (nếu có)
        """
        data = self._read_file()
        server_url = None
        if data and isinstance(data, dict):
            server_url = data.get("server_url")  # Lưu server_url trước
        
        # Xóa file cũ
        if os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except:
                pass
        
        # Nếu có server_url, tạo lại file chỉ với server_url
        if server_url:
            new_data = {"server_url": server_url}
            self._write_file(new_data)
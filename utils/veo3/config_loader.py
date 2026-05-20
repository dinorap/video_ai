import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import từ utils.veo3.path_helper (trong project này)
from utils.veo3.path_helper import CONFIG_DIR, PROJECTS_DIR

# Các module encrypt/secure không cần thiết cho Veo3, tạo stub functions
def decrypt_prompts_file(path):
    """Stub function - không dùng trong Veo3"""
    return {}

def ensure_prompts_encrypted(src, dst):
    """Stub function - không dùng trong Veo3"""
    pass

def read_settings(config_dir):
    """Đọc settings từ file JSON"""
    settings_file = config_dir / "settings.json"
    if settings_file.exists():
        try:
            return json.loads(settings_file.read_text(encoding="utf-8"))
        except:
            return {}
    return {}

def write_settings(config_dir, data, write_plaintext=True):
    """Ghi settings vào file JSON"""
    settings_file = config_dir / "settings.json"
    try:
        settings_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Error writing settings: {e}")

# Paths
PROMPTS_FILE = CONFIG_DIR / "prompts.json"
PROMPTS_ENCRYPTED_FILE = CONFIG_DIR / "prompts.enc"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
SETTINGS_ENCRYPTED_FILE = CONFIG_DIR / "settings.json.enc"
STYLES_FILE = CONFIG_DIR / "styles.json" # [MỚI]




def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def get_api_key() -> Optional[str]:
    settings = read_settings(CONFIG_DIR)
    return settings.get("API_KEY")


def _split_gemini_key_string(raw: Optional[str]) -> List[str]:
    """Tách nhiều key: xuống dòng, dấu phẩy, hoặc chấm phẩy."""
    if not raw or not isinstance(raw, str):
        return []
    out: List[str] = []
    for part in raw.replace(";", "\n").replace(",", "\n").split("\n"):
        k = part.strip()
        if k:
            out.append(k)
    return out


def _dedupe_gemini_keys(keys: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def get_stored_gemini_keys_flat(settings: Dict[str, Any]) -> List[str]:
    """
    Danh sách key Gemini đang lưu trong settings (thứ tự trong file), không đọc env.
    Dùng cho API hiển thị và khi lưu GEMINI_ACTIVE_INDEX.
    """
    keys: List[str] = []
    raw_list = settings.get("GEMINI_API_KEYS")
    if isinstance(raw_list, list):
        for x in raw_list:
            if isinstance(x, str) and x.strip():
                keys.append(x.strip())
    if not keys:
        s = settings.get("GEMINI_API_KEY")
        if isinstance(s, str) and s.strip():
            keys = _split_gemini_key_string(s)
    return _dedupe_gemini_keys(keys)


def get_gemini_api_keys() -> List[str]:
    """
    Danh sách Gemini API key (để hiển thị / chọn key đang dùng).
    Không còn xoay vòng failover giữa nhiều key khi gọi API — caller chỉ dùng phần tử đầu.

    Thứ tự ưu tiên: chỉ dùng env nếu đã set, không trộn với settings.

    - Env GEMINI_API_KEYS: nhiều key (phân tách bằng dòng mới hoặc dấu phẩy).
    - Env GEMINI_API_KEY: một hoặc nhiều key (cùng quy tắc tách).
    - Settings: GEMINI_API_KEYS (mảng) hoặc GEMINI_API_KEY (chuỗi nhiều dòng); key tại GEMINI_ACTIVE_INDEX đứng đầu.
    """
    import os

    keys: List[str] = []
    env_multi = os.getenv("GEMINI_API_KEYS")
    if env_multi is not None and str(env_multi).strip():
        keys = _split_gemini_key_string(env_multi)
        return _dedupe_gemini_keys(keys)

    env_single = os.getenv("GEMINI_API_KEY")
    if env_single is not None and str(env_single).strip():
        keys = _split_gemini_key_string(env_single)
        return _dedupe_gemini_keys(keys)

    settings = read_settings(CONFIG_DIR)
    keys = get_stored_gemini_keys_flat(settings)
    if not keys:
        return []
    try:
        idx = int(settings.get("GEMINI_ACTIVE_INDEX", 0))
    except (TypeError, ValueError):
        idx = 0
    idx %= len(keys)
    # Key đang chọn đứng đầu; các key còn lại giữ thứ tự trong file (không xoay vòng tròn).
    return [keys[idx]] + [keys[i] for i in range(len(keys)) if i != idx]


def get_gemini_api_key() -> Optional[str]:
    """
    Key đầu tiên trong danh sách (tương thích ngược).
    Ưu tiên env như get_gemini_api_keys(); không trộn env với file settings.
    """
    keys = get_gemini_api_keys()
    return keys[0] if keys else None


def get_prompt_config(prompt_id: str) -> Optional[Dict[str, Any]]:
    # Ưu tiên đọc từ file mã hóa
    if PROMPTS_ENCRYPTED_FILE.exists():
        data = decrypt_prompts_file(PROMPTS_ENCRYPTED_FILE)
    elif PROMPTS_FILE.exists():
        # Tự động mã hóa nếu chưa có file mã hóa
        ensure_prompts_encrypted(PROMPTS_FILE, PROMPTS_ENCRYPTED_FILE)
        if PROMPTS_ENCRYPTED_FILE.exists():
            data = decrypt_prompts_file(PROMPTS_ENCRYPTED_FILE)
        else:
            data = _read_json(PROMPTS_FILE)
    else:
        data = {"prompts": []}
    
    for p in data.get("prompts", []):
        if p.get("id") == prompt_id:
            # Only expose expected fields
            return {
                "id": p.get("id"),
                "temperature": p.get("temperature"),
                "system_instruction_text": p.get("system_instruction_text"),
                "system_instruction_addendum_text": p.get("system_instruction_addendum_text"),
                "system_instruction_addendum_text_extra": p.get("system_instruction_addendum_text_extra"),
                "response_schema": p.get("response_schema"),
            }
    return None


def get_styles() -> Dict[str, Dict[str, str]]:
    """Đọc styles từ file JSON"""
    if not STYLES_FILE.exists():
        return {}
    return _read_json(STYLES_FILE)

def get_style(style_key: str) -> Optional[Dict[str, str]]:
    styles = get_styles()
    return styles.get(style_key)

def add_custom_style(key: str, style_data: Dict[str, str]) -> bool:
    """[MỚI] Thêm style mới vào file JSON"""
    styles = get_styles()
    # Ghi đè hoặc thêm mới
    styles[key] = style_data
    try:
        STYLES_FILE.write_text(json.dumps(styles, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"Lỗi lưu style: {e}")
        return False


def get_projects_dir() -> Path:
    """
    Trả về đường dẫn thư mục projects (storage/projects) và đảm bảo tồn tại.
    """
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    return PROJECTS_DIR

def delete_custom_style(key: str) -> bool:
    """Xóa style khỏi file JSON"""
    styles = get_styles()
    
    if key not in styles:
        return False # Không tìm thấy để xóa
        
    del styles[key] # Xóa khỏi dict
    
    try:
        STYLES_FILE.write_text(json.dumps(styles, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"Lỗi xóa style: {e}")
        return False
def get_settings() -> Dict[str, Any]:
    """Trả về toàn bộ cài đặt, ưu tiên settings.json.enc"""
    return read_settings(CONFIG_DIR)


def load_settings_data() -> Dict[str, Any]:
    """Alias dùng cho routers/services để đọc settings ưu tiên .enc"""
    return read_settings(CONFIG_DIR)


def save_settings_data(data: Dict[str, Any]) -> None:
    """
    Dev mode: ghi cả settings.json + settings.json.enc để dễ debug.
    Exe mode (frozen): chỉ ghi settings.json.enc để tránh lộ plain text.
    """
    is_frozen = bool(getattr(sys, "frozen", False))
    write_settings(CONFIG_DIR, data, write_plaintext=not is_frozen)


def normalize_browser_engine(value: Any) -> str:
    s = str(value or "nst").strip().lower()
    if s in ("chrome_local", "chrome", "local"):
        return "chrome_local"
    return "nst"


def normalize_chrome_local_profiles(raw: Any) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        udd = str(item.get("user_data_dir") or "").strip()
        proxy = str(item.get("proxy") or "").strip()
        proxy_username = str(item.get("proxy_username") or "").strip()
        proxy_password = str(item.get("proxy_password") or "").strip()
        proxy_scheme = str(item.get("proxy_scheme") or "").strip().lower()
        if not pid or not udd:
            continue
        row = {"id": pid, "name": name or pid, "user_data_dir": udd}
        if proxy:
            row["proxy"] = proxy
        if proxy_username:
            row["proxy_username"] = proxy_username
        if proxy_password:
            row["proxy_password"] = proxy_password
        if proxy_scheme in ("http", "socks5"):
            row["proxy_scheme"] = proxy_scheme
        out.append(row)
    return out


def validate_chrome_local_profiles_strict(profiles: List[Dict[str, str]]) -> None:
    """
    Raises ValueError with user-facing message if invalid.
    """
    seen_ids: set[str] = set()
    seen_dirs: set[str] = set()
    for i, p in enumerate(profiles):
        pid = p.get("id") or ""
        udd = (p.get("user_data_dir") or "").strip()
        if pid in seen_ids:
            raise ValueError(f"Trùng id profile ở dòng {i + 1}")
        seen_ids.add(pid)
        key = udd.lower().replace("\\", "/").rstrip("/")
        if key in seen_dirs:
            raise ValueError(f"Trùng user_data_dir: {udd}")
        seen_dirs.add(key)
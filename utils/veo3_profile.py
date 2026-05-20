"""
Veo3 Profile Management
Quản lý profiles và authentication cho Veo3 API
"""
import json
import os
import sys
from typing import Dict, List, Optional


def _get_veo_auth_path() -> str:
    """Lấy đường dẫn đến file veo_auth.json"""
    try:
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, 'config', 'veo_auth.json')
    except Exception:
        return 'config/veo_auth.json'


def load_veo3_profiles() -> List[Dict]:
    """
    Đọc danh sách profiles từ config/veo_auth.json
    
    Returns:
        List[Dict]: Danh sách profiles với cấu trúc:
        [
            {
                "name": "profile_1",
                "sessionId": "...",
                "projectId": "...",
                "access_token": "...",
                "active": true
            },
            ...
        ]
    """
    auth_path = _get_veo_auth_path()
    
    if not os.path.exists(auth_path):
        print(f"[Veo3 Profile] ⚠️ File không tồn tại: {auth_path}")
        return []
    
    try:
        with open(auth_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            return []
        
        # Hỗ trợ cả 2 cấu trúc: {"profiles": {...}} hoặc trực tiếp {...}
        profiles_data = data.get("profiles", data)
        
        if not isinstance(profiles_data, dict):
            return []
        
        profiles = []
        for name, profile_data in profiles_data.items():
            if not isinstance(profile_data, dict):
                continue
            
            profile = {
                "name": name,
                "sessionId": profile_data.get("sessionId", ""),
                "projectId": profile_data.get("projectId", ""),
                "access_token": profile_data.get("access_token", ""),
                "chrome_profile_id": profile_data.get("chrome_profile_id", "Default"),
                "project_url": profile_data.get("project_url", ""),
                "cookie": profile_data.get("cookie", ""),
                "active": profile_data.get("active", True)
            }
            profiles.append(profile)
        
        return profiles
    
    except json.JSONDecodeError as e:
        print(f"[Veo3 Profile] ❌ Lỗi parse JSON: {e}")
        return []
    except Exception as e:
        print(f"[Veo3 Profile] ❌ Lỗi đọc file: {e}")
        return []


def get_active_veo3_profiles() -> List[Dict]:
    """
    Lấy danh sách profiles đang active
    
    Returns:
        List[Dict]: Danh sách profiles có active=True
    """
    all_profiles = load_veo3_profiles()
    return [p for p in all_profiles if p.get("active", True)]


def get_veo3_profile_by_name(profile_name: str) -> Optional[Dict]:
    """
    Lấy profile theo tên
    
    Args:
        profile_name: Tên profile (vd: "profile_1")
    
    Returns:
        Dict hoặc None nếu không tìm thấy
    """
    profiles = load_veo3_profiles()
    for profile in profiles:
        if profile.get("name") == profile_name:
            return profile
    return None


def get_first_active_profile() -> Optional[Dict]:
    """
    Lấy profile active đầu tiên
    
    Returns:
        Dict hoặc None nếu không có profile nào active
    """
    active_profiles = get_active_veo3_profiles()
    return active_profiles[0] if active_profiles else None


def validate_veo3_auth(profile: Dict) -> bool:
    """
    Kiểm tra authentication của profile còn hợp lệ không
    
    Args:
        profile: Dict chứa thông tin profile
    
    Returns:
        bool: True nếu hợp lệ, False nếu thiếu thông tin
    """
    if not isinstance(profile, dict):
        return False
    
    # Kiểm tra các trường bắt buộc
    required_fields = ["sessionId", "projectId", "access_token"]
    for field in required_fields:
        value = profile.get(field, "")
        if not value or not str(value).strip():
            print(f"[Veo3 Profile] ⚠️ Thiếu hoặc rỗng: {field}")
            return False
    
    return True


def set_profile_active(profile_name: str, active: bool = True) -> bool:
    """
    Bật/tắt trạng thái active của profile
    
    Args:
        profile_name: Tên profile
        active: True để bật, False để tắt
    
    Returns:
        bool: True nếu thành công
    """
    auth_path = _get_veo_auth_path()
    
    if not os.path.exists(auth_path):
        print(f"[Veo3 Profile] ⚠️ File không tồn tại: {auth_path}")
        return False
    
    try:
        with open(auth_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if profile_name not in data:
            print(f"[Veo3 Profile] ⚠️ Không tìm thấy profile: {profile_name}")
            return False
        
        data[profile_name]["active"] = active
        
        with open(auth_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"[Veo3 Profile] ✅ Đã {'bật' if active else 'tắt'} profile: {profile_name}")
        return True
    
    except Exception as e:
        print(f"[Veo3 Profile] ❌ Lỗi cập nhật profile: {e}")
        return False


def get_profile_count() -> int:
    """Đếm tổng số profiles"""
    return len(load_veo3_profiles())


def get_active_profile_count() -> int:
    """Đếm số profiles đang active"""
    return len(get_active_veo3_profiles())


def print_profiles_summary():
    """In ra thông tin tóm tắt về profiles (dùng để debug)"""
    profiles = load_veo3_profiles()
    active_profiles = get_active_veo3_profiles()
    
    print(f"\n[Veo3 Profile] 📊 Tổng quan:")
    print(f"  - Tổng số profiles: {len(profiles)}")
    print(f"  - Profiles active: {len(active_profiles)}")
    
    if profiles:
        print(f"\n[Veo3 Profile] 📋 Danh sách:")
        for i, profile in enumerate(profiles, 1):
            name = profile.get("name", "Unknown")
            active = "✅" if profile.get("active", True) else "❌"
            has_session = "✓" if profile.get("sessionId") else "✗"
            has_project = "✓" if profile.get("projectId") else "✗"
            has_token = "✓" if profile.get("access_token") else "✗"
            
            print(f"  {i}. {name} {active}")
            print(f"     Session: {has_session} | Project: {has_project} | Token: {has_token}")


if __name__ == "__main__":
    # Test khi chạy trực tiếp file này
    print("=== VEO3 PROFILE MANAGER TEST ===\n")
    print_profiles_summary()
    
    # Test lấy profile đầu tiên
    first = get_first_active_profile()
    if first:
        print(f"\n[Test] Profile active đầu tiên: {first.get('name')}")
        print(f"[Test] Validation: {'✅ OK' if validate_veo3_auth(first) else '❌ FAIL'}")
    else:
        print("\n[Test] ⚠️ Không có profile nào active")

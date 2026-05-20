# backend/utils/path_helper.py
import sys
import os
from pathlib import Path

def is_running_as_exe():
    """
    Kiểm tra đang chạy dạng EXE (PyInstaller, Nuitka, ...) hay đang chạy code Python bình thường.
    - PyInstaller: có thuộc tính sys.frozen
    - Nuitka: không có sys.frozen, nhưng sys.executable là file .exe (không phải python.exe)
    """
    # PyInstaller / các bundler dùng sys.frozen
    if getattr(sys, "frozen", False):
        return True

    # Heuristic cho Nuitka: executable là .exe nhưng tên không chứa "python"
    exe_name = os.path.basename(sys.executable).lower()
    if exe_name.endswith(".exe") and "python" not in exe_name:
        return True

    return False

def get_base_path():
    """
    Trả về thư mục gốc:
    - Exe: Trả về thư mục chứa file .exe
    - Dev: Trả về thư mục root (tool_youtube) để storage và config ở cùng cấp với backend
    """
    if is_running_as_exe():
        return Path(sys.executable).parent
    else:
        # File này ở backend/utils/path_helper.py
        # parent.parent = backend/
        # parent.parent.parent = tool_youtube/ (root)
        return Path(__file__).resolve().parent.parent.parent

# --- KHỞI TẠO PATH ---
BASE_DIR = get_base_path()

# Khi chạy dev: BASE_DIR = root (tool_youtube/)
# Khi chạy exe: BASE_DIR = thư mục chứa exe

if is_running_as_exe():
    # Exe: config và storage ở cùng cấp với exe
    CONFIG_DIR = BASE_DIR / "config"
    STORAGE_DIR = BASE_DIR / "storage"
    STATIC_DIR = BASE_DIR / "static"
else:
    # Dev: config ở backend/config, storage ở root/storage
    BACKEND_DIR = BASE_DIR / "backend"
    CONFIG_DIR = BACKEND_DIR / "config"
    STORAGE_DIR = BASE_DIR / "storage"
    STATIC_DIR = BASE_DIR / "static"

PROJECTS_DIR = STORAGE_DIR / "projects"

# Tạo folder nếu chưa có (chỉ khi có quyền, không bắt lỗi)
try:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(STORAGE_DIR, exist_ok=True)
    os.makedirs(PROJECTS_DIR, exist_ok=True)
except (PermissionError, OSError):
    # Khi chạy exe, folder có thể đã tồn tại hoặc không có quyền tạo
    # Không sao, sẽ tạo khi cần thiết
    pass


def normalize_script_path(script_path: str) -> str:
    """
    Chuyển đổi đường dẫn script từ frontend (tương đối) sang đường dẫn tuyệt đối.
    
    Frontend gửi: '../storage/projects/Phuong/youtube_url/scripts/video_0.json'
    Hoặc: 'storage/projects/Phuong/youtube_url/scripts/video_0.json'
    
    Trả về: Đường dẫn tuyệt đối dựa trên PROJECTS_DIR
    """
    if not script_path:
        return script_path
    
    # Loại bỏ '../' ở đầu nếu có
    script_path = script_path.replace('../', '').replace('..\\', '')
    
    # Loại bỏ 'storage/projects/' ở đầu nếu có
    if script_path.startswith('storage/projects/'):
        script_path = script_path.replace('storage/projects/', '')
    elif script_path.startswith('storage\\projects\\'):
        script_path = script_path.replace('storage\\projects\\', '')
    
    # Nếu đã là đường dẫn tuyệt đối, trả về luôn
    if os.path.isabs(script_path):
        return script_path
    
    # Tạo đường dẫn tuyệt đối từ PROJECTS_DIR
    normalized = PROJECTS_DIR / script_path.replace('\\', '/')
    return str(normalized.resolve())
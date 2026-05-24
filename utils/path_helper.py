"""
Đường dẫn gốc khi chạy dev hoặc EXE (Nuitka/PyInstaller).
Dev và exe dùng cùng layout: config/, generated/, profile/ cạnh app root.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Union

PathLike = Union[str, Path]

# Các file từng bị ghi nhầm vào utils/config/ (bug path cũ)
_LEGACY_MIGRATIONS: tuple[tuple[Path, Path], ...] = ()


def is_running_as_exe() -> bool:
    if getattr(sys, "frozen", False):
        return True
    exe_name = os.path.basename(sys.executable).lower()
    return exe_name.endswith(".exe") and "python" not in exe_name


def get_base_path() -> Path:
    if is_running_as_exe():
        return Path(sys.executable).resolve().parent
    # utils/path_helper.py -> utils/ -> project root
    return Path(__file__).resolve().parent.parent


def get_bundle_dir() -> Path:
    """Thư mục chứa static/templaces khi đóng gói (PyInstaller _MEIPASS)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return get_base_path()


def pstr(path: PathLike) -> str:
    return str(path)


def resolve_resource(*parts: str) -> Path:
    """Tìm file/thư mục trong BASE_DIR rồi BUNDLE_DIR (assets đóng gói)."""
    for root in (get_base_path(), get_bundle_dir()):
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return get_base_path().joinpath(*parts)


def _init_path_constants() -> None:
    global BASE_DIR, BUNDLE_DIR, CONFIG_DIR, STORAGE_DIR, CONFIG_FILE, TASKS_FILE
    global VEO_AUTH_FILE, GENERATED_DIR, PROFILE_DIR, TEMP_VIDEO_DIR, TMP_UPLOADS_DIR
    global TEMP_DIR, MUSIC_DIR, SCRIPT_DIR, PROMPT_DIR, PROJECTS_DIR
    global TEMPLACES_DIR, THEME_IMG_DIR, ICO_DIR, _LEGACY_MIGRATIONS

    BASE_DIR = get_base_path()
    BUNDLE_DIR = get_bundle_dir()

    CONFIG_DIR = BASE_DIR / "config"
    STORAGE_DIR = BASE_DIR / "storage"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    TASKS_FILE = CONFIG_DIR / "tasks.json"
    VEO_AUTH_FILE = CONFIG_DIR / "veo_auth.json"
    GENERATED_DIR = BASE_DIR / "generated"
    PROFILE_DIR = BASE_DIR / "profile"
    TEMP_VIDEO_DIR = BASE_DIR / "temp_video"
    TMP_UPLOADS_DIR = BASE_DIR / "tmp_uploads"
    TEMP_DIR = BASE_DIR / "temp"
    MUSIC_DIR = CONFIG_DIR / "Music"
    SCRIPT_DIR = CONFIG_DIR / "KichBan"
    PROMPT_DIR = CONFIG_DIR / "prompt"
    PROJECTS_DIR = STORAGE_DIR / "projects"
    TEMPLACES_DIR = resolve_resource("templaces")
    THEME_IMG_DIR = resolve_resource("templaces", "img")
    ICO_DIR = resolve_resource("ico")

    legacy_root = BASE_DIR / "utils" / "config"
    _LEGACY_MIGRATIONS = (
        (legacy_root / "veo_auth.json", VEO_AUTH_FILE),
        (legacy_root / "config.json", CONFIG_FILE),
        (legacy_root / "tasks.json", TASKS_FILE),
    )


_init_path_constants()


def bootstrap_default_config() -> None:
    """Tạo config.json từ template nếu thiếu (máy mới / chỉ giải nén OTA zip)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        return
    if CONFIG_FILE.is_file():
        return
    templates = (
        CONFIG_DIR / "config.dist.json",
        resolve_resource("config", "config.dist.json"),
        BASE_DIR / "config" / "config.dist.json",
    )
    for tpl in templates:
        try:
            if tpl.is_file():
                shutil.copy2(tpl, CONFIG_FILE)
                return
        except Exception:
            pass
    try:
        CONFIG_FILE.write_text(
            '{\n  "API": "",\n  "TTS": "",\n  "API_KEY": "",\n  "CDP_PORT": 9222\n}\n',
            encoding="utf-8",
        )
    except Exception:
        pass


def ensure_runtime_dirs() -> None:
    bootstrap_default_config()
    for d in (
        CONFIG_DIR,
        STORAGE_DIR,
        GENERATED_DIR,
        PROFILE_DIR,
        TEMP_VIDEO_DIR,
        TMP_UPLOADS_DIR,
        TEMP_DIR,
        MUSIC_DIR,
        SCRIPT_DIR,
        PROJECTS_DIR,
        PROMPT_DIR,
    ):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            pass
    if not TASKS_FILE.is_file():
        try:
            TASKS_FILE.write_text("[]\n", encoding="utf-8")
        except Exception:
            pass


def migrate_legacy_paths() -> int:
    """Chuyển file config cũ (utils/config/) sang config/ nếu chưa có."""
    moved = 0
    for src, dst in _LEGACY_MIGRATIONS:
        try:
            if src.is_file() and not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                moved += 1
        except Exception:
            pass
    return moved


def setup_runtime_cwd() -> None:
    """EXE: đặt cwd = thư mục chứa .exe (tránh lỗi khi shortcut mở từ chỗ khác)."""
    if not is_running_as_exe():
        return
    try:
        os.chdir(get_base_path())
    except Exception:
        pass


def normalize_script_path(script_path: str) -> str:
    if not script_path:
        return script_path

    script_path = script_path.replace("../", "").replace("..\\", "")

    if script_path.startswith("storage/projects/"):
        script_path = script_path.replace("storage/projects/", "")
    elif script_path.startswith("storage\\projects\\"):
        script_path = script_path.replace("storage\\projects\\", "")

    if os.path.isabs(script_path):
        return script_path

    normalized = PROJECTS_DIR / script_path.replace("\\", "/")
    return str(normalized.resolve())


def init_frozen_flag() -> None:
    """Nuitka đôi khi không set sys.frozen; dinorap-updater cần cờ này."""
    if is_running_as_exe() and not getattr(sys, "frozen", False):
        try:
            setattr(sys, "frozen", True)
        except Exception:
            pass


def get_paths_diagnostic() -> Dict[str, Any]:
    """Thông tin path để debug dev vs exe."""
    base = get_base_path()
    return {
        "mode": "exe" if is_running_as_exe() else "dev",
        "sys_executable": sys.executable,
        "sys_frozen": bool(getattr(sys, "frozen", False)),
        "cwd": os.getcwd(),
        "base_dir": pstr(base),
        "bundle_dir": pstr(get_bundle_dir()),
        "config_file": pstr(CONFIG_FILE),
        "veo_auth_file": pstr(VEO_AUTH_FILE),
        "tasks_file": pstr(TASKS_FILE),
        "profile_dir": pstr(PROFILE_DIR),
        "generated_dir": pstr(GENERATED_DIR),
        "templaces_dir": pstr(TEMPLACES_DIR),
        "templaces_exists": TEMPLACES_DIR.is_dir(),
        "config_exists": CONFIG_FILE.is_file(),
        "ffmpeg_bundled": (base / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe").is_file(),
    }

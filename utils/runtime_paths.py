"""
Đường dẫn runtime khi chạy EXE (Nuitka) hoặc dev.
Ưu tiên binary đóng gói cạnh app: tools/ffmpeg/bin, tools/chrome/
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from utils.path_helper import CONFIG_FILE, get_base_path, is_running_as_exe

_cached_app_dir: Optional[Path] = None


def get_app_dir() -> Path:
    global _cached_app_dir
    if _cached_app_dir is not None:
        return _cached_app_dir
    _cached_app_dir = get_base_path()
    return _cached_app_dir


def bundled_ffmpeg_bin_dir() -> Path:
    return get_app_dir() / "tools" / "ffmpeg" / "bin"


def bundled_chrome_exe() -> Optional[Path]:
    p = get_app_dir() / "tools" / "chrome" / "chrome.exe"
    return p if p.is_file() else None


def _read_config_ffmpeg_path() -> str:
    try:
        cfg_path = CONFIG_FILE
        if not cfg_path.is_file():
            return ""
        raw = cfg_path.read_text(encoding="utf-8-sig", errors="replace")
        data = json.loads(raw)
        if isinstance(data, dict):
            return str(data.get("FFMPEG_PATH") or data.get("ffmpeg_path") or "").strip()
    except Exception:
        pass
    return ""


def get_ffmpeg_exe() -> str:
    cfg = _read_config_ffmpeg_path()
    if cfg:
        p = Path(cfg)
        if p.is_file():
            return str(p.resolve())
        if p.name.lower() == "ffmpeg" or cfg.lower() == "ffmpeg":
            pass
        else:
            return cfg

    bundled = bundled_ffmpeg_bin_dir() / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled.resolve())

    return "ffmpeg"


def get_ffprobe_exe() -> str:
    ff = Path(get_ffmpeg_exe())
    if ff.name.lower() == "ffmpeg.exe":
        probe = ff.with_name("ffprobe.exe")
        if probe.is_file():
            return str(probe.resolve())
    bundled = bundled_ffmpeg_bin_dir() / "ffprobe.exe"
    if bundled.is_file():
        return str(bundled.resolve())
    return "ffprobe"


def resolve_chrome_executable(settings: Optional[dict] = None) -> Optional[str]:
    settings = settings or {}
    explicit = str(settings.get("CHROME_EXECUTABLE") or "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p.resolve())

    bundled = bundled_chrome_exe()
    if bundled:
        return str(bundled.resolve())

    env_p = os.environ.get("CHROME_PATH") or os.environ.get("GOOGLE_CHROME_BIN")
    if env_p:
        pe = Path(env_p.strip())
        if pe.is_file():
            return str(pe.resolve())

    if os.name == "nt":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
        ]
        for c in candidates:
            try:
                if c.is_file():
                    return str(c.resolve())
            except Exception:
                continue
    else:
        import shutil

        for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
            found = shutil.which(name)
            if found:
                return found
    return None


def init_runtime_environment() -> None:
    """Thêm tools/ffmpeg/bin vào PATH để subprocess 'ffmpeg' hoạt động."""
    bin_dir = bundled_ffmpeg_bin_dir()
    if not (bin_dir / "ffmpeg.exe").is_file():
        return
    b = str(bin_dir.resolve())
    cur = os.environ.get("PATH") or ""
    parts = [p for p in cur.split(os.pathsep) if p]
    if os.path.normcase(b) not in {os.path.normcase(p) for p in parts}:
        os.environ["PATH"] = b + os.pathsep + cur
    os.environ.setdefault("FFMPEG_PATH", str((bin_dir / "ffmpeg.exe").resolve()))

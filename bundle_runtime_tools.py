"""
Tải / cache FFmpeg Windows và copy vào dist/VideoCreator/tools/ffmpeg/bin/
Gọi từ build_fast_c++.py sau copy_resources.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parent
CACHE_BIN = ROOT / "tools" / "ffmpeg" / "bin"
FFMPEG_WIN_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _find_ffmpeg_exe(root: Path) -> Path | None:
    for r, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower() == "ffmpeg.exe":
                return Path(r) / fn
    return None


def _copy_bin_dir(src_bin: Path, dst_bin: Path) -> None:
    dst_bin.mkdir(parents=True, exist_ok=True)
    for item in src_bin.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() not in (".exe", ".dll"):
            continue
        shutil.copy2(item, dst_bin / item.name)


def ensure_ffmpeg_cache() -> Path:
    """Tải ffmpeg essentials vào tools/ffmpeg/bin (cache dự án)."""
    if (CACHE_BIN / "ffmpeg.exe").is_file() and (CACHE_BIN / "ffprobe.exe").is_file():
        print(f"   [OK] ffmpeg cache: {CACHE_BIN}")
        return CACHE_BIN

    print("   [DOWNLOAD] FFmpeg Windows essentials (~80MB, một lần)...")
    tmp = Path(tempfile.mkdtemp(prefix="vc_ffmpeg_"))
    try:
        zpath = tmp / "ffmpeg.zip"
        urlretrieve(FFMPEG_WIN_ZIP_URL, zpath)
        extract = tmp / "extract"
        extract.mkdir()
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(extract)

        found = _find_ffmpeg_exe(extract)
        if not found:
            raise RuntimeError("ffmpeg.exe not found in downloaded package")

        src_bin = found.parent
        CACHE_BIN.mkdir(parents=True, exist_ok=True)
        _copy_bin_dir(src_bin, CACHE_BIN)
        print(f"   [OK] ffmpeg cached -> {CACHE_BIN}")
        return CACHE_BIN
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def bundle_ffmpeg_to(dist_dir: Path) -> None:
    cache = ensure_ffmpeg_cache()
    dst = dist_dir / "tools" / "ffmpeg" / "bin"
    dst.mkdir(parents=True, exist_ok=True)
    for item in cache.iterdir():
        if item.is_file():
            shutil.copy2(item, dst / item.name)
    if not (dst / "ffmpeg.exe").is_file():
        raise RuntimeError(f"bundle failed: {dst / 'ffmpeg.exe'}")
    print(f"   [OK] bundled ffmpeg -> {dst}")


def bundle_optional_chrome_to(dist_dir: Path) -> None:
    """Copy tools/chrome/ nếu dev đã đặt sẵn (không tự tải Chrome)."""
    src = ROOT / "tools" / "chrome"
    exe = src / "chrome.exe"
    if not exe.is_file():
        print("   [SKIP] tools/chrome/chrome.exe (optional, install Chrome on PC)")
        return
    dst = dist_dir / "tools" / "chrome"
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    print(f"   [OK] bundled chrome -> {dst}")


if __name__ == "__main__":
    from version import APP_NAME

    dist = ROOT / "dist" / APP_NAME
    if not dist.is_dir():
        print(f"Missing {dist}")
        sys.exit(1)
    bundle_ffmpeg_to(dist)
    bundle_optional_chrome_to(dist)

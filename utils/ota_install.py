"""OTA install (không phụ thuộc fastapi/dinorap_updater — chạy được trong Nuitka exe)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import threading
import zipfile

import requests

from utils.path_helper import get_base_path, init_frozen_flag, is_running_as_exe

_lock = threading.Lock()
_is_updating = False


def is_updating() -> bool:
    return _is_updating


def cleanup_old_update_artifacts() -> None:
    if not is_running_as_exe():
        return
    app_dir = get_base_path()
    bat_file = app_dir / "update_installer.bat"
    temp_dir = app_dir / "_update_temp"
    try:
        if bat_file.is_file():
            bat_file.unlink()
        if temp_dir.is_dir():
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass


def _download_json(url: str) -> dict:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


def _sha256_file(path: os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_zip_integrity(zip_path: os.PathLike) -> bool:
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            return z.testzip() is None
    except Exception:
        return False


def download_and_install(info: dict) -> None:
    global _is_updating
    try:
        init_frozen_flag()
        if not is_running_as_exe():
            print("[Updater] Dev mode: Cannot update")
            return

        with _lock:
            _is_updating = True
            print("[Updater] Update lock acquired")

        app_dir = get_base_path()
        exe_name = os.path.basename(sys.executable)
        zip_path = app_dir / "update.zip"
        extract_temp_dir = app_dir / "_update_temp"

        print("[Updater] Downloading update.json...")
        meta = _download_json(str(info["meta_url"]))
        expected_hash = str(meta.get("sha256") or "").strip()
        if not expected_hash:
            raise RuntimeError("update.json thiếu trường sha256")

        print("[Updater] Downloading zip...")
        with requests.get(info["download_url"], stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        print("[Updater] Verifying SHA256...")
        real_hash = _sha256_file(zip_path)
        if real_hash.lower() != expected_hash.lower():
            raise RuntimeError("SHA256 mismatch")

        print("[Updater] Testing zip integrity...")
        if not _verify_zip_integrity(zip_path):
            raise RuntimeError("ZIP integrity check failed")

        if extract_temp_dir.is_dir():
            shutil.rmtree(extract_temp_dir, ignore_errors=True)
        extract_temp_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_temp_dir)

        source_dir = extract_temp_dir
        items = os.listdir(extract_temp_dir)
        if len(items) == 1:
            possible_nested = extract_temp_dir / items[0]
            if possible_nested.is_dir():
                if (possible_nested / exe_name).is_file() or (possible_nested / "_internal").is_dir():
                    source_dir = possible_nested

        unsafe_storage = source_dir / "storage"
        if unsafe_storage.is_dir():
            shutil.rmtree(unsafe_storage, ignore_errors=True)

        bat_path = app_dir / "update_installer.bat"
        exe_path = str(app_dir / exe_name)
        bat_content = f"""@echo off
set MAX_RETRY=5
set COUNT=0
title Updating {exe_name}...
echo Waiting for application to close...
timeout /t 3 /nobreak > NUL
:RETRY
set /a COUNT+=1
echo Attempt %COUNT% of %MAX_RETRY%
xcopy "{source_dir}\\*" "{app_dir}\\" /s /e /y /q /i
IF %ERRORLEVEL% NEQ 0 (
    IF %COUNT% GEQ %MAX_RETRY% (
        echo [FATAL] Cannot update application.
        explorer "{app_dir}"
        pause
        exit /b 1
    )
    timeout /t 2 /nobreak > NUL
    GOTO RETRY
)
rmdir /s /q "{extract_temp_dir}"
del "{zip_path}"
start "" "{exe_path}"
del "%~f0" & exit
"""
        bat_path.write_text(bat_content, encoding="utf-8")

        print("[Updater] Launching installer...")
        subprocess.Popen(
            [str(bat_path)],
            shell=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        os._exit(0)
    except Exception as exc:
        print(f"[Updater] Update failed: {exc}")
    finally:
        with _lock:
            _is_updating = False

# uninstall.py
# - Xóa shortcut Desktop (Creat_Video.lnk)
# - Xóa toàn bộ thư mục chứa uninstall.exe (thư mục cài đặt)
# - Hiện thông báo "Gỡ cài đặt thành công!" sau khi xóa xong (UTF-8 chuẩn)

import os
import sys
import subprocess
import tempfile
from pathlib import Path

SHORTCUT_NAME = "VideoCreator"


def _desktop_shortcut_path() -> Path:
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    return desktop / f"{SHORTCUT_NAME}.lnk"


def main():
    # Chỉ chạy logic xóa khi là file build (frozen)
    if not getattr(sys, "frozen", False):
        print("Đang chạy ở chế độ source, bỏ qua gỡ cài đặt thực tế.")
        return

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable)
    else:
        exe_path = Path(__file__).resolve()

    app_dir = exe_path.parent
    exe_name = exe_path.name

    bat_path = Path(tempfile.gettempdir()) / "video_creator_uninstall_runner.bat"
    lnk_path = _desktop_shortcut_path()

    app_dir_s = str(app_dir)
    lnk_s = str(lnk_path)

    bat = rf"""@echo off
chcp 65001 >nul
setlocal

rem ===== Wait for uninstall exe to exit =====
timeout /t 2 >nul

:loop
tasklist | find /i "{exe_name}" >nul
if not errorlevel 1 (
    timeout /t 1 >nul
    goto loop
)

rem ===== Delete Desktop shortcut =====
if exist "{lnk_s}" (
    del /f /q "{lnk_s}" >nul 2>nul
)

rem ===== Delete install folder (folder containing uninstall.exe) =====
rmdir /s /q "{app_dir_s}" >nul 2>nul

rem ===== Success message (PowerShell MessageBox) =====
powershell -NoProfile -ExecutionPolicy Bypass -STA -Command ^
  "Add-Type -AssemblyName System.Windows.Forms; " ^
  "[System.Windows.Forms.MessageBox]::Show('Gỡ cài đặt thành công!','VideoCreator'," ^
  "[System.Windows.Forms.MessageBoxButtons]::OK," ^
  "[System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null"

rem ===== Self delete bat =====
del "%~f0" >nul 2>nul
endlocal
"""

    # QUAN TRỌNG: utf-8-sig (có BOM) để .bat đọc tiếng Việt đúng
    bat_path.write_text(bat, encoding="utf-8-sig")

    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=str(Path(tempfile.gettempdir()))
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
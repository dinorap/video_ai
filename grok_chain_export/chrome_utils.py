"""
Chrome Utilities - Tìm và khởi động Chrome với CDP
===================================================

Module này cung cấp các hàm để:
- Tìm Chrome executable trên hệ thống
- Khởi động Chrome với Chrome DevTools Protocol (CDP)
- Quản lý Chrome profile
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def find_chrome_executable() -> Optional[str]:
    """
    Tìm Chrome executable trên hệ thống.
    
    Returns:
        Đường dẫn đến Chrome executable hoặc None nếu không tìm thấy
    """
    # Kiểm tra biến môi trường
    env_chrome = os.environ.get('CHROME_PATH') or os.environ.get('GOOGLE_CHROME_BIN')
    if env_chrome:
        p = Path(env_chrome.strip())
        if p.is_file():
            return str(p.resolve())
    
    # Windows
    if os.name == 'nt':
        candidates = [
            Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
            Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
            Path(os.environ.get('LOCALAPPDATA', r'C:\Users\Default\AppData\Local')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
        ]
        for p in candidates:
            if p.is_file():
                return str(p.resolve())
    
    # Linux
    else:
        candidates = [
            '/usr/bin/google-chrome',
            '/usr/bin/google-chrome-stable',
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
        ]
        for p in candidates:
            if Path(p).is_file():
                return p
        
        # Tìm trong PATH
        chrome = shutil.which('google-chrome') or shutil.which('chromium')
        if chrome:
            return chrome
    
    return None


def launch_chrome_with_cdp(
    profile_dir: str,
    url: str = "https://grok.com/",
    cdp_port: int = 9222,
    headless: bool = False
) -> subprocess.Popen:
    """
    Khởi động Chrome với Chrome DevTools Protocol.
    
    Args:
        profile_dir: Đường dẫn đến Chrome profile directory
        url: URL để mở khi khởi động
        cdp_port: Port cho CDP (mặc định 9222)
        headless: Chạy ở chế độ headless (không hiển thị UI)
    
    Returns:
        subprocess.Popen object
    
    Raises:
        RuntimeError: Nếu không tìm thấy Chrome
    """
    chrome_path = find_chrome_executable()
    if not chrome_path:
        raise RuntimeError(
            "Chrome not found. Please install Google Chrome or set CHROME_PATH environment variable."
        )
    
    # Tạo profile directory nếu chưa tồn tại
    profile_path = Path(profile_dir)
    profile_path.mkdir(parents=True, exist_ok=True)
    
    # Build command
    cmd = [
        chrome_path,
        f"--user-data-dir={profile_path}",
        f"--remote-debugging-port={cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    
    if headless:
        cmd.extend([
            "--headless=new",
            "--disable-gpu",
        ])
    else:
        cmd.extend([
            "--start-maximized",
            "--new-window",
        ])
    
    cmd.append(url)
    
    # Subprocess kwargs để ẩn console trên Windows
    kwargs = {}
    if os.name == 'nt':
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs['startupinfo'] = si
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        except Exception:
            pass
    
    # Launch Chrome
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        **kwargs
    )
    
    return proc


def get_cdp_endpoint(port: int = 9222) -> str:
    """
    Lấy CDP endpoint URL.
    
    Args:
        port: CDP port
    
    Returns:
        CDP endpoint URL (vd: "http://127.0.0.1:9222")
    """
    return f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    # Test: Tìm Chrome và in đường dẫn
    chrome = find_chrome_executable()
    if chrome:
        print(f"✅ Chrome found: {chrome}")
    else:
        print("❌ Chrome not found")

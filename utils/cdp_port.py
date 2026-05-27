"""
Chrome DevTools Protocol (CDP) helpers — dùng chung cho Grok/Veo3 automation.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Optional

from utils.path_helper import CONFIG_FILE, PROFILE_DIR as _PROFILE_DIR_PATH
from utils.grok.profile import find_chrome

GROK_START_URL = "https://grok.com/"
FLOW_START_URL = "https://labs.google/fx/vi/tools/flow"

PROFILE_DIR = str(_PROFILE_DIR_PATH)


def _win_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    return {}


def load_cdp_port(default: int = 9222) -> int:
    try:
        cfg_path = str(CONFIG_FILE)
        if not os.path.exists(cfg_path):
            return int(default)
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
        raw = cfg.get("CDP_PORT", cfg.get("cdp_port", default))
        n = int(str(raw).strip())
        if 1 <= n <= 65535:
            return n
    except Exception:
        pass
    return int(default)


def is_cdp_ready(port: int, host: str = "127.0.0.1") -> bool:
    """Port phải trả JSON CDP hợp lệ (không chỉ socket mở)."""
    try:
        import requests

        r = requests.get(f"http://{host}:{int(port)}/json/version", timeout=3)
        if r.status_code != 200:
            return False
        data = r.json() or {}
        return bool(data.get("webSocketDebuggerUrl") or data.get("Browser"))
    except Exception:
        return False


async def wait_cdp_ready(port: int, *, timeout_s: float = 25.0, host: str = "127.0.0.1") -> bool:
    deadline = time.time() + float(timeout_s)
    while time.time() < deadline:
        if is_cdp_ready(port, host=host):
            return True
        await asyncio.sleep(0.35)
    return False


def _is_veo3_provider(provider: str) -> bool:
    p = str(provider or "").strip().lower()
    return "veo3" in p or p in ("google", "veo3 (google)")


def _start_url_for_provider(provider: str) -> str:
    return FLOW_START_URL if _is_veo3_provider(provider) else GROK_START_URL


def kill_all_profile_chrome() -> None:
    """Đóng mọi Chrome đang dùng PROFILE_DIR (dọn sạch trước khi thử lại)."""
    try:
        if os.name != "nt":
            return
        prof_path = os.path.abspath(PROFILE_DIR)
        prof_match = prof_path.replace("\\", "\\\\")
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "($_.Name -eq 'chrome.exe') -and "
            f"($_.CommandLine -like '*--user-data-dir={prof_match}*') "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_win_subprocess_kwargs(),
        )
    except Exception:
        pass


def kill_profile_chrome_without_cdp(port: int) -> None:
    """
    Đóng Chrome đang dùng PROFILE_DIR nhưng KHÔNG bật --remote-debugging-port=port.
    Nếu không đóng, Chrome mới sẽ reuse process cũ và CDP không lên.
    """
    try:
        if os.name != "nt":
            return
        prof_path = os.path.abspath(PROFILE_DIR)
        prof_match = prof_path.replace("\\", "\\\\")
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "($_.Name -eq 'chrome.exe') -and "
            f"($_.CommandLine -like '*--user-data-dir={prof_match}*') -and "
            f"($_.CommandLine -notlike '*--remote-debugging-port={int(port)}*') "
            "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_win_subprocess_kwargs(),
        )
    except Exception:
        pass


def start_chrome_with_cdp(port: int, provider: str = "Veo3") -> Optional[int]:
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found")

    try:
        os.makedirs(PROFILE_DIR, exist_ok=True)
    except Exception:
        pass

    url = _start_url_for_provider(provider)
    print(f"[CDP] Mở Chrome → {url} (port={port}, provider={provider})")
    proc = subprocess.Popen(
        [
            chrome,
            f"--user-data-dir={PROFILE_DIR}",
            f"--remote-debugging-port={int(port)}",
            "--remote-debugging-address=127.0.0.1",
            "--start-maximized",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        **_win_subprocess_kwargs(),
    )
    try:
        pid = int(getattr(proc, "pid", None) or 0) or None
    except Exception:
        pid = None
    return pid


async def ensure_chrome_cdp_ready(
    provider: str = "Veo3",
    *,
    port: Optional[int] = None,
    max_attempts: int = 3,
    wait_timeout_s: float = 25.0,
) -> int:
    """
    Đảm bảo Chrome profile + CDP sẵn sàng. Retry khi port chưa lên hoặc Chrome cũ không có CDP.
  """
    cdp_port = int(port if port is not None else load_cdp_port())

    if is_cdp_ready(cdp_port):
        print(f"[CDP] ✅ Port {cdp_port} đã sẵn sàng")
        return cdp_port

    last_err = ""
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        print(f"[CDP] 🔄 Lần {attempt}/{max_attempts}: chuẩn bị Chrome CDP port {cdp_port}...")
        try:
            kill_profile_chrome_without_cdp(cdp_port)
            await asyncio.sleep(0.8)
            start_chrome_with_cdp(cdp_port, provider=provider)
        except Exception as exc:
            last_err = str(exc)
            print(f"[CDP] ⚠️ Không khởi động được Chrome: {exc}")

        if await wait_cdp_ready(cdp_port, timeout_s=wait_timeout_s):
            print(f"[CDP] ✅ Port {cdp_port} sẵn sàng sau lần thử {attempt}")
            return cdp_port

        last_err = f"timeout after {wait_timeout_s}s"
        print(f"[CDP] ⚠️ Port {cdp_port} chưa phản hồi CDP (lần {attempt})")
        if attempt < max(1, int(max_attempts)):
            kill_all_profile_chrome()
            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(0.5)

    raise RuntimeError(
        f"CDP port {cdp_port} is not available"
        + (f" ({last_err})" if last_err else "")
    )

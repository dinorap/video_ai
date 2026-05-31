import asyncio
import threading
import subprocess

from utils.path_helper import CONFIG_FILE

def _win_subprocess_kwargs():
    import os
    if os.name != 'nt':
        return {}
    # Removed hidden window flags to show Chrome normally
    return {}

from utils.grok.profile import (
    PROFILE_DIR,
    find_chrome,
    setting_grok_profile,
    setting_veo3_profile
)

GROK_START_URL = "https://grok.com/"
FLOW_START_URL = "https://labs.google/fx/vi/tools/flow"


def _is_veo3_provider(provider: str) -> bool:
    p = (provider or "").strip().lower()
    return "veo3" in p or p in ("google", "veo3 (google)")


def _start_url_for_provider(provider: str) -> str:
    return FLOW_START_URL if _is_veo3_provider(provider) else GROK_START_URL


def open_profile(provider: str):

    if not provider:
        return

    p = provider.strip().lower()

    if p in ["grok", "grok (x-ai)", "x-ai", "xai"] or "grok chain" in p:
        # Only open profile + navigate to Grok (no CDP). CDP is managed by _GlobalBrowser.
        setting_grok_profile()
        return
        
    if p in ["veo3", "veo3 (google)", "google"]:
        # Veo3: Open Chrome + extract auth data
        setup_veo3_profile_with_auth()
        return

    print(f"Provider not supported: {provider}")


def setup_veo3_profile_with_auth():
    """
    Thiết lập profile Veo3:
    1. Mở Chrome tới Flow (dùng chính Chrome profile của Grok)
    2. Kết nối qua CDP
    3. Trích xuất auth data (sessionId, projectId, access_token)
    4. Lưu vào config/veo_auth.json
    """
    import os
    import sys
    import json
    import time
    
    # 1. Mở Chrome tới Flow
    print("[Veo3 Setup] 🚀 Đang mở Chrome...")
    setting_veo3_profile()
    
    # 2. Đợi Chrome khởi động
    time.sleep(3)
    
    # 3. Kết nối qua CDP và trích xuất auth
    async def _extract_auth_async():
        from playwright.async_api import async_playwright
        from utils.veo3.veo_get_token import auto_collect_veo_auth_from_flow
        
        from utils.cdp_port import load_cdp_port, ensure_chrome_cdp_ready, is_cdp_ready

        cdp_port = load_cdp_port()
        if not is_cdp_ready(cdp_port):
            await ensure_chrome_cdp_ready("Veo3", port=cdp_port, max_attempts=3, wait_timeout_s=28.0)

        print(f"[Veo3 Setup] 🔌 Kết nối CDP qua port {cdp_port}...")
        
        playwright = None
        browser = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(
                f'http://127.0.0.1:{cdp_port}',
                timeout=15000
            )
            
            # Lấy context và page hiện tại
            if not browser.contexts or len(browser.contexts) == 0:
                print("[Veo3 Setup] ❌ Không tìm thấy browser context")
                return False
            
            context = browser.contexts[0]
            pages = context.pages
            
            if not pages or len(pages) == 0:
                print("[Veo3 Setup] ❌ Không tìm thấy page nào")
                return False
            
            # Tìm page có URL Flow
            page = None
            for p in pages:
                try:
                    url = p.url
                    if 'labs.google' in url and 'flow' in url:
                        page = p
                        break
                except Exception:
                    continue
            
            if not page:
                # Nếu không tìm thấy, dùng page đầu tiên và navigate
                page = pages[0]
                print("[Veo3 Setup] 📍 Điều hướng tới Flow...")
                try:
                    await page.goto('https://labs.google/fx/vi/tools/flow', wait_until='networkidle', timeout=30000)
                except Exception as e:
                    print(f"[Veo3 Setup] ⚠️ Lỗi điều hướng: {e}")
            
            print("[Veo3 Setup] 🔍 Đang trích xuất auth data...")
            print("[Veo3 Setup] ℹ️  Vui lòng đợi trong khi hệ thống tự động:")
            print("[Veo3 Setup]    1. Nhập prompt test")
            print("[Veo3 Setup]    2. Click nút Tạo")
            print("[Veo3 Setup]    3. Bắt request để lấy auth token")
            
            # Gọi hàm trích xuất auth (profile_id = "default")
            auth_data = await auto_collect_veo_auth_from_flow(
                page,
                profile_id="default",
                timeout_s=60
            )
            
            if auth_data:
                print("[Veo3 Setup] ✅ Đã trích xuất auth data thành công!")
                print(f"[Veo3 Setup]    - Session ID: {auth_data.get('sessionId', '')[:20]}...")
                print(f"[Veo3 Setup]    - Project ID: {auth_data.get('projectId', '')}")
                print(f"[Veo3 Setup]    - Access Token: {auth_data.get('access_token', '')[:30]}...")
                return True
            else:
                print("[Veo3 Setup] ❌ Không thể trích xuất auth data")
                print("[Veo3 Setup] ℹ️  Vui lòng thử lại hoặc kiểm tra:")
                print("[Veo3 Setup]    - Đã đăng nhập Google chưa?")
                print("[Veo3 Setup]    - Trang Flow có load được không?")
                return False
                
        except Exception as e:
            print(f"[Veo3 Setup] ❌ Lỗi: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # Không đóng browser vì đang dùng chung với Grok
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass
    
    # Chạy async function
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            success = loop.run_until_complete(_extract_auth_async())
            if success:
                print("[Veo3 Setup] 🎉 Hoàn tất thiết lập profile Veo3!")
            else:
                print("[Veo3 Setup] ⚠️  Thiết lập chưa hoàn tất, vui lòng thử lại")
        finally:
            loop.close()
    except Exception as e:
        print(f"[Veo3 Setup] ❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()


class _GlobalBrowser:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self._init_error = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._sema = None
        self._provider = "grok"
        self._download_dir = None
        self._lifecycle_lock = threading.Lock()
        self._spawned_pid = None
        self._cdp_port = None

    def _thread_main(self, provider="grok", download_dir=None):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._provider = provider or "grok"
            self._download_dir = download_dir
            self._loop.run_until_complete(self._async_init(provider=provider, download_dir=download_dir))
        except Exception as exc:
            self._init_error = exc
        finally:
            self._ready.set()
            if self._loop:
                self._loop.run_forever()

    def _is_context_alive(self) -> bool:
        if self._context is None:
            return False
        try:
            # Check if we can still access pages. This will throw if context is closed.
            _ = self._context.pages
            # If we connected via CDP, also check if browser is still connected
            if self._browser:
                # Playwright's browser.is_connected() is the authoritative check for CDP
                if not self._browser.is_connected():
                    return False
            return True
        except Exception:
            # Any error here means the context/browser is no longer usable
            return False

    def _submit(self, coro, timeout=None):
        if self._loop is None:
            raise RuntimeError("Global browser loop is not initialized")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    async def _async_init(self, provider="grok", download_dir=None):
        from playwright.async_api import async_playwright
        import subprocess
        import time
        import os
        import json
        import sys

        from utils.cdp_port import load_cdp_port, ensure_chrome_cdp_ready

        cdp_port = load_cdp_port()
        self._cdp_port = int(cdp_port)

        # Stop existing playwright if any
        if self._playwright:
            try:
                await self._playwright.stop()
            except:
                pass

        self._playwright = await async_playwright().start()

        # Normalize download dir
        download_dir = str(download_dir or "").strip() or None
        if download_dir:
            try:
                download_dir = os.path.abspath(download_dir)
                os.makedirs(download_dir, exist_ok=True)
            except Exception:
                download_dir = None

        # Đảm bảo Chrome + CDP (retry, đóng Chrome cũ không có --remote-debugging-port).
        await ensure_chrome_cdp_ready(
            self._provider,
            port=cdp_port,
            max_attempts=3,
            wait_timeout_s=28.0,
        )

        self._browser = await self._playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{int(cdp_port)}", timeout=20000
        )
        
        # Fix: Ensure we have a valid context and it's not closed
        if self._browser.contexts and len(self._browser.contexts) > 0:
            self._context = self._browser.contexts[0]
        else:
            self._context = await self._browser.new_context(accept_downloads=True, viewport={'width': 1280, 'height': 720}, position={'x': 0, 'y': 0})

        # Try to force download directory via CDP if requested (best-effort)
        if download_dir:
            try:
                pass
            except Exception:
                pass
            # 1) Browser-level (preferred)
            try:
                await self._browser.new_browser_cdp_session().send(
                    "Browser.setDownloadBehavior",
                    {"behavior": "allow", "downloadPath": download_dir},
                )
            except Exception:
                pass

            # 2) Fallback: Page-level download behavior via a temporary page CDP session
            try:
                tmp = await self._context.new_page()
                try:
                    cdp = await self._context.new_cdp_session(tmp)
                    try:
                        await cdp.send(
                            "Browser.setDownloadBehavior",
                            {"behavior": "allow", "downloadPath": download_dir},
                        )
                    except Exception:
                        await cdp.send(
                            "Page.setDownloadBehavior",
                            {"behavior": "allow", "downloadPath": download_dir},
                        )
                finally:
                    try:
                        await tmp.close()
                    except Exception:
                        pass
            except Exception:
                pass

        self._sema = asyncio.Semaphore(5)
        await self._ensure_provider_start_page()
        return

    async def _ensure_provider_start_page(self) -> None:
        """Nếu đã mở Grok trước đó mà chuyển Veo3 — điều hướng sang Google Flow."""
        if not _is_veo3_provider(self._provider):
            return
        if not self._context:
            return
        target = FLOW_START_URL
        try:
            pages = list(self._context.pages or [])
            if not pages:
                page = await self._context.new_page()
                await page.goto(target, wait_until="domcontentloaded", timeout=45000)
                return
            for page in pages:
                try:
                    cur = str(page.url or "")
                except Exception:
                    cur = ""
                if "labs.google" in cur and "flow" in cur:
                    continue
                try:
                    await page.goto(target, wait_until="domcontentloaded", timeout=45000)
                except Exception as exc:
                    print(f"[Browser] Không chuyển tab sang Flow: {exc}")
        except Exception as exc:
            print(f"[Browser] _ensure_provider_start_page: {exc}")

    def ensure_started(self, provider="grok", download_dir=None):
        download_dir = str(download_dir or "").strip() or None
        with self._lifecycle_lock:
            # If thread is up and healthy, reuse it.
            if self._thread and self._thread.is_alive() and self._ready.is_set() and not self._init_error:
                # Only re-init when context is dead/disconnected.
                # Do NOT re-init just because download_dir changed, as that would kill
                # in-flight tabs from other concurrent jobs (image/video).
                if self._is_context_alive():
                    self._provider = provider or self._provider
                    self._download_dir = download_dir
                    if _is_veo3_provider(self._provider):
                        try:
                            self._submit(self._ensure_provider_start_page(), timeout=60)
                        except Exception as exc:
                            print(f"[Browser] Chuyển Flow: {exc}")
                    return

                self._provider = provider or self._provider
                self._download_dir = download_dir
                self._submit(self._async_init(provider=self._provider, download_dir=self._download_dir), timeout=150)
                return

            if self._thread and self._thread.is_alive() and self._ready.is_set() and self._init_error:
                err_s = str(self._init_error)
                if "CDP port" in err_s or "CDP" in err_s.lower():
                    print(f"[Browser] ⚠️ CDP lỗi trước đó — thử khởi động lại Chrome ({err_s})")
                    try:
                        self.close_global_browser()
                    except Exception:
                        pass
                    self._thread = None
                    self._ready.clear()
                    self._init_error = None
                else:
                    raise self._init_error

            self._ready.clear()
            self._init_error = None
            self._thread = threading.Thread(target=self._thread_main, args=(provider, download_dir), daemon=True)
            self._thread.start()
            self._ready.wait(timeout=120)
            if self._init_error:
                raise self._init_error

    def run(self, coro, timeout=None):
        self.ensure_started()
        return self._submit(coro, timeout=timeout)

    async def get_context_async(self):
        if not self._is_context_alive():
            await self._async_init(provider=self._provider, download_dir=self._download_dir)
        return self._context

    async def run_with_tab_slot(self, coro):
        if self._sema is None:
            self._sema = asyncio.Semaphore(5)
        await self._sema.acquire()
        try:
            return await coro
        finally:
            self._sema.release()

    async def reset_async(self):
        await self.close_async()
        await self._async_init(provider=self._provider, download_dir=self._download_dir)

    async def close_async(self):
        # Close everything but do not re-init
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser is not None:
            try:
                # For CDP-connected browsers, browser.close() may only disconnect.
                # To really close Chrome, send the CDP Browser.close command.
                try:
                    sess = await self._browser.new_browser_cdp_session()
                    await sess.send("Browser.close")
                except Exception:
                    pass
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        # Force-kill Chrome process tree if we spawned it (best-effort)
        pid = self._spawned_pid
        self._spawned_pid = None
        if pid:
            try:
                import os
                import subprocess
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_win_subprocess_kwargs())
                else:
                    subprocess.run(["kill", "-9", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        # Fallback: if Flask reloader restarted, we may have lost the PID/browser handle.
        # In that case, try to kill any Chrome process running our profile with CDP enabled.
        try:
            import os
            import subprocess
            if os.name == 'nt':
                prof = str(PROFILE_DIR).replace('\\', '\\\\')
                port = None
                try:
                    port = int(self._cdp_port) if self._cdp_port is not None else None
                except Exception:
                    port = None
                if not port:
                    port = 9222
                ps = (
                    "Get-CimInstance Win32_Process | "
                    "Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*--remote-debugging-port=" + str(int(port)) + "*' -and $_.CommandLine -like '*--user-data-dir="
                    + prof
                    + "*' } | Select-Object -ExpandProperty ProcessId"
                )
                out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], stderr=subprocess.DEVNULL, **_win_subprocess_kwargs())
                pids = []
                try:
                    for line in out.decode(errors='ignore').splitlines():
                        s = str(line).strip()
                        if s.isdigit():
                            pids.append(int(s))
                except Exception:
                    pids = []
                for p in pids:
                    try:
                        subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_win_subprocess_kwargs())
                    except Exception:
                        pass
        except Exception:
            pass

    def close_global_browser(self):
        async def _do():
            await self.close_async()

        with self._lifecycle_lock:
            # 1) Try clean async close
            if self._loop is not None:
                try:
                    self._submit(_do(), timeout=20)
                except Exception:
                    pass

            # 2) MANDATORY HARD KILL (fallback for all cases: crash, restart, hang)
            try:
                import os
                import subprocess
                from utils.grok.profile import PROFILE_DIR
                if os.name == 'nt':
                    prof_path = os.path.abspath(PROFILE_DIR)
                    # Convert to double backslash for WMI/PowerShell matching
                    prof_match = prof_path.replace('\\', '\\\\')

                    port = None
                    try:
                        port = int(self._cdp_port) if self._cdp_port is not None else None
                    except Exception:
                        port = None
                    if not port:
                        port = 9222

                    # Kill by port 9222 OR by profile directory in command line
                    ps_cmd = (
                        "Get-CimInstance Win32_Process | "
                        "Where-Object { "
                        "($_.Name -eq 'chrome.exe') -and "
                        "($_.CommandLine -like '*--remote-debugging-port=" + str(int(port)) + "*' -or $_.CommandLine -like '*--user-data-dir=" + prof_match + "*') "
                        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
                    )
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_win_subprocess_kwargs())
                else:
                    # Unix fallback
                    port = None
                    try:
                        port = int(self._cdp_port) if self._cdp_port is not None else None
                    except Exception:
                        port = None
                    if not port:
                        port = 9222
                    subprocess.run(["pkill", "-9", "-f", f"remote-debugging-port={int(port)}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

            # Reset state
            self._spawned_pid = None

        return True


_GLOBAL_BROWSERS = {
    'default': _GlobalBrowser(),
    'image': _GlobalBrowser(),
    'video': _GlobalBrowser(),
}

# Backward-compatible alias
_GLOBAL_BROWSER = _GLOBAL_BROWSERS['default']


def get_global_browser(kind: str = 'default') -> _GlobalBrowser:
    k = str(kind or 'default').strip().lower()
    if k not in _GLOBAL_BROWSERS:
        k = 'default'
    return _GLOBAL_BROWSERS[k]


def init_global_browser(provider="grok", download_dir=None, kind: str = 'default'):
    get_global_browser(kind).ensure_started(provider=provider, download_dir=download_dir)
    return True


def close_global_browser(kind: str = 'default'):
    return get_global_browser(kind).close_global_browser()


def run_global(coro, timeout=None, provider="grok", kind: str = 'default'):
    """
    Run a coroutine on the global browser's event loop from a different thread.
    This is non-blocking for the Flask main thread.
    """
    gb = get_global_browser(kind)
    gb.ensure_started(provider=provider)
    
    # Sử dụng asyncio.run_coroutine_threadsafe để không block Flask
    future = asyncio.run_coroutine_threadsafe(coro, gb._loop)
    return future.result(timeout=timeout)


def get_global_context(kind: str = 'default'):
    async def _get():
        return await get_global_browser(kind).get_context_async()

    return get_global_browser(kind).run(_get(), timeout=60)


def reset_global_browser(kind: str = 'default'):
    async def _do():
        await get_global_browser(kind).reset_async()

    return get_global_browser(kind).run(_do(), timeout=120)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python control_profile.py <provider>")
    else:
        open_profile(sys.argv[1])
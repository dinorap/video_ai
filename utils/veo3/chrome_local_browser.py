"""
Launch local Chrome instances with separate user-data-dir and remote debugging.
Used when BROWSER_ENGINE=chrome_local (Playwright still connects via CDP).
"""
from __future__ import annotations

import os
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

try:
    from backend.utils.path_helper import BASE_DIR
except Exception:
    try:
        from utils.path_helper import BASE_DIR  # type: ignore
    except Exception:
        BASE_DIR = Path.cwd()

_REGISTRY_LOCK = threading.Lock()
# profile_id -> { "popen": Popen | None, "port": int }
_PROCS: Dict[str, Dict[str, Any]] = {}


def _debug_base_port() -> int:
    try:
        return int(os.environ.get("CHROME_LOCAL_DEBUG_BASE_PORT", "19300") or "19300")
    except (TypeError, ValueError):
        return 19300


def chrome_local_ordered_ids(settings: Dict[str, Any]) -> List[str]:
    """Stable order: as listed in CHROME_LOCAL_PROFILES."""
    raw = settings.get("CHROME_LOCAL_PROFILES") or []
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if pid:
            out.append(pid)
    return out


def user_data_dir_for_profile(settings: Dict[str, Any], profile_id: str) -> Optional[str]:
    raw = settings.get("CHROME_LOCAL_PROFILES") or []
    if not isinstance(raw, list):
        return None
    pid = str(profile_id or "").strip()
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != pid:
            continue
        d = str(item.get("user_data_dir") or "").strip()
        return d if d else None
    return None


def proxy_for_profile(settings: Dict[str, Any], profile_id: str) -> Optional[str]:
    raw = settings.get("CHROME_LOCAL_PROFILES") or []
    if not isinstance(raw, list):
        return None
    pid = str(profile_id or "").strip()
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != pid:
            continue
        p = str(item.get("proxy") or "").strip()
        return p if p else None
    return None


def proxy_auth_for_profile(settings: Dict[str, Any], profile_id: str) -> Tuple[str, str]:
    raw = settings.get("CHROME_LOCAL_PROFILES") or []
    if not isinstance(raw, list):
        return "", ""
    pid = str(profile_id or "").strip()
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != pid:
            continue
        u = str(item.get("proxy_username") or "").strip()
        p = str(item.get("proxy_password") or "").strip()
        return u, p
    return "", ""


def _parse_proxy_input(proxy_value: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """
    Parse proxy input and normalize forms:
    - ip:port:user:pass
    - host:port:user:pass
    - host:port
    - http://user:pass@host:port
    - socks5://user:pass@host:port
    """
    raw = str(proxy_value or "").strip()
    if not raw:
        return None, None, False
    # Hỗ trợ input rút gọn:
    # - host:port:user:pass
    # - ip:port:user:pass
    # - host:port (mặc định http)
    if "://" not in raw:
        parts = raw.split(":")
        if len(parts) >= 4:
            host = parts[0].strip()
            port = parts[1].strip()
            user = parts[2].strip()
            pwd = ":".join(parts[3:]).strip()
            raw = f"http://{user}:{pwd}@{host}:{port}"
        elif len(parts) == 2:
            host = parts[0].strip()
            port = parts[1].strip()
            raw = f"http://{host}:{port}"
    try:
        parsed = urlparse(raw)
    except Exception:
        return None, f"Proxy không hợp lệ: {raw}", True
    scheme = (parsed.scheme or "").strip().lower()
    host = (parsed.hostname or "").strip()
    port = parsed.port
    if not scheme or not host or not port:
        return None, f"Proxy không hợp lệ (thiếu scheme/host/port): {raw}", True
    if scheme not in ("http", "https", "socks4", "socks5"):
        return None, f"Proxy scheme chưa hỗ trợ: {scheme}", True
    return {
        "scheme": scheme,
        "host": host,
        "port": int(port),
        "username": parsed.username or "",
        "password": parsed.password or "",
    }, None, False


def _ensure_proxy_auth_extension(
    user_data_dir: Path,
    *,
    scheme: str,
    host: str,
    port: int,
    username: str,
    password: str,
) -> Path:
    """
    Create/update an unpacked Chrome extension that sets fixed proxy and handles auth.
    """
    ext_dir = user_data_dir / "_proxy_auth_ext"
    ext_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": "ChromeLocal Proxy Auth",
        "version": "1.0.0",
        "manifest_version": 2,
        "permissions": [
            "proxy",
            "tabs",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking",
        ],
        "background": {"scripts": ["background.js"]},
    }
    background_js = f"""
const config = {{
  mode: "fixed_servers",
  rules: {{
    singleProxy: {{
      scheme: {json.dumps(scheme)},
      host: {json.dumps(host)},
      port: {int(port)}
    }},
    bypassList: ["localhost", "127.0.0.1"]
  }}
}};

chrome.proxy.settings.set({{ value: config, scope: "regular" }}, function() {{}});

chrome.webRequest.onAuthRequired.addListener(
  function(details) {{
    return {{
      authCredentials: {{
        username: {json.dumps(username)},
        password: {json.dumps(password)}
      }}
    }};
  }},
  {{ urls: ["<all_urls>"] }},
  ["blocking"]
);
""".strip()
    (ext_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ext_dir / "background.js").write_text(background_js, encoding="utf-8")
    return ext_dir


def port_for_profile(profile_id: str, ordered_ids: List[str]) -> int:
    base = _debug_base_port()
    try:
        idx = ordered_ids.index(str(profile_id))
    except ValueError:
        idx = abs(hash(str(profile_id))) % 400
    return base + idx + 1


def resolve_chrome_executable(settings: Dict[str, Any]) -> Optional[str]:
    explicit = str(settings.get("CHROME_EXECUTABLE") or "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p.resolve())
    env_p = os.environ.get("CHROME_PATH") or os.environ.get("GOOGLE_CHROME_BIN")
    if env_p:
        pe = Path(env_p.strip())
        if pe.is_file():
            return str(pe.resolve())
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"))
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
        for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
            try:
                import shutil

                found = shutil.which(name)
                if found:
                    return found
            except Exception:
                continue
    return None


def get_browser_ws_endpoint(host: str, port: int) -> Optional[str]:
    try:
        r = requests.get(f"http://{host}:{int(port)}/json/version", timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        return (data or {}).get("webSocketDebuggerUrl")
    except Exception:
        return None


def is_debug_port_responding(port: int, host: str = "127.0.0.1") -> bool:
    return bool(get_browser_ws_endpoint(host, port))


def start_profile(
    settings: Dict[str, Any],
    profile_id: str,
    *,
    ordered_ids: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    pid = str(profile_id or "").strip()
    if not pid:
        return False, "profile_id rỗng"
    oid = ordered_ids if ordered_ids is not None else chrome_local_ordered_ids(settings)
    udd = user_data_dir_for_profile(settings, pid)
    if not udd:
        return False, f"Không tìm thấy user_data_dir cho profile {pid[:8]}…"
    path = Path(udd).expanduser()
    if not path.is_absolute():
        path = (Path(BASE_DIR) / path).resolve()
    if not path.is_dir():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, f"Không tạo được user_data_dir: {e}"
    exe = resolve_chrome_executable(settings)
    if not exe:
        return False, "Không tìm thấy chrome.exe (đặt CHROME_EXECUTABLE trong settings hoặc cài Chrome)."

    port = port_for_profile(pid, oid)
    proxy = proxy_for_profile(settings, pid)
    proxy_cfg, proxy_warn, proxy_hard_error = _parse_proxy_input(proxy)
    if proxy_hard_error:
        return False, proxy_warn or "Proxy không hợp lệ"

    with _REGISTRY_LOCK:
        rec = _PROCS.get(pid)
        if rec and rec.get("popen"):
            proc = rec["popen"]
            if proc.poll() is None:
                if is_debug_port_responding(port):
                    return True, "already_running"
                # Stale proc
            try:
                proc.terminate()
            except Exception:
                pass
            _PROCS.pop(pid, None)

    args = [
        exe,
        f"--user-data-dir={path}",
        "--profile-directory=Default",
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--new-window",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-features=RendererCodeIntegrity,ChromeProfilePickerOnStartup",
    ]
    if proxy_cfg:
        server = f"{proxy_cfg['scheme']}://{proxy_cfg['host']}:{proxy_cfg['port']}"
        username = str(proxy_cfg.get("username") or "").strip()
        password = str(proxy_cfg.get("password") or "").strip()
        if not username and not password:
            fallback_user, fallback_pass = proxy_auth_for_profile(settings, pid)
            username = fallback_user
            password = fallback_pass
        scheme = str(proxy_cfg.get("scheme") or "").strip().lower()
        if scheme == "socks5":
            # Với SOCKS5, ép Chromium dùng remote DNS qua proxy để giảm lỗi connection failed theo máy.
            args.append("--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1")
        if username or password:
            ext_dir = _ensure_proxy_auth_extension(
                path,
                scheme=scheme,
                host=str(proxy_cfg["host"]),
                port=int(proxy_cfg["port"]),
                username=username,
                password=password,
            )
            args.append(f"--disable-extensions-except={ext_dir}")
            args.append(f"--load-extension={ext_dir}")
            proxy_warn = (
                f"Dùng proxy auth qua extension cho profile {pid[:8]}… ({server})"
            )
        else:
            args.append(f"--proxy-server={server}")
    else:
        # Hard reset no-proxy mode để tránh dính proxy settings cũ trong profile.
        try:
            shutil.rmtree(path / "_proxy_auth_ext", ignore_errors=True)
        except Exception:
            pass
        args.extend(
            [
                "--no-proxy-server",
                "--proxy-server=direct://",
                "--proxy-bypass-list=*",
                "--proxy-auto-detect=false",
            ]
        )
        print(f"[ChromeLocal] ✅ No proxy mode for profile {pid[:8]}…")

    try:
        # Windows: avoid console window flash for packaged apps
        kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            cnw = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if cnw:
                kwargs["creationflags"] = cnw
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception as e:
        return False, f"Không spawn Chrome: {e}"

    with _REGISTRY_LOCK:
        _PROCS[pid] = {"popen": proc, "port": port}

    if proxy_warn:
        print(f"[ChromeLocal] ⚠️ {proxy_warn}")

    return True, "started"


def stop_profile(profile_id: str) -> bool:
    pid = str(profile_id or "").strip()
    if not pid:
        return False
    with _REGISTRY_LOCK:
        rec = _PROCS.pop(pid, None)
    if not rec:
        return True
    proc = rec.get("popen")
    if not proc:
        return True
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return True


def stop_all_tracked() -> None:
    with _REGISTRY_LOCK:
        keys = list(_PROCS.keys())
    for k in keys:
        stop_profile(k)


def is_tracked_running(profile_id: str) -> bool:
    pid = str(profile_id or "").strip()
    with _REGISTRY_LOCK:
        rec = _PROCS.get(pid)
        if not rec:
            return False
        proc = rec.get("popen")
        if proc and proc.poll() is None:
            port = int(rec.get("port") or 0)
            return port > 0 and is_debug_port_responding(port)
    return False


def wait_until_ready(
    settings: Dict[str, Any],
    profile_id: str,
    *,
    timeout_sec: float = 45.0,
    poll_interval: float = 0.5,
) -> bool:
    pid = str(profile_id or "").strip()
    oid = chrome_local_ordered_ids(settings)
    port = port_for_profile(pid, oid)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if is_debug_port_responding(port):
            return True
        time.sleep(poll_interval)
    return False


def get_ws_endpoint_for_profile(settings: Dict[str, Any], profile_id: str) -> Optional[str]:
    pid = str(profile_id or "").strip()
    oid = chrome_local_ordered_ids(settings)
    port = port_for_profile(pid, oid)
    return get_browser_ws_endpoint("127.0.0.1", port)


def get_assigned_port(settings: Dict[str, Any], profile_id: str) -> int:
    oid = chrome_local_ordered_ids(settings)
    return port_for_profile(str(profile_id), oid)

"""
Unified browser lifecycle: Chrome local only (user-data-dir + CDP).
Playwright always uses connect_over_cdp.
NST browser logic has been removed as per requirements.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Set

_BuildKeyMapFn = Callable[[], Dict[str, str]]
_build_profile_api_key_map_cache: Optional[_BuildKeyMapFn] = None


def register_profile_api_key_map_builder(fn: _BuildKeyMapFn) -> None:
    global _build_profile_api_key_map_cache
    _build_profile_api_key_map_cache = fn


def _profile_api_key_map() -> Dict[str, str]:
    if _build_profile_api_key_map_cache:
        try:
            return _build_profile_api_key_map_cache()
        except Exception:
            return {}
    return {}


from utils.veo3 import chrome_local_browser as clb
from utils.veo3.config_loader import get_settings


def browser_engine_from_settings(settings: Optional[Dict[str, Any]] = None) -> str:
    """Always returns 'chrome_local' since NST is removed."""
    return "chrome_local"


def is_chrome_local(settings: Optional[Dict[str, Any]] = None) -> bool:
    """Always returns True since we only support Chrome local."""
    return True


def chrome_local_profile_pool_ids(settings: Dict[str, Any]) -> List[str]:
    """Get ordered list of Chrome local profile IDs."""
    return clb.chrome_local_ordered_ids(settings)


def local_profile_pool_ids(settings: Dict[str, Any], count: int) -> List[str]:
    """Get pool of local profile IDs, respecting PROFILE_IDS_ACTIVE."""
    all_ids = clb.chrome_local_ordered_ids(settings)
    active = settings.get("PROFILE_IDS_ACTIVE")
    pool: List[str] = []
    if isinstance(active, list) and active:
        pool = [str(p).strip() for p in active if str(p).strip()]
        known = set(all_ids)
        pool = [p for p in pool if p in known]
    if not pool:
        pool = list(all_ids)
    if count < 0:
        return pool
    return pool[: max(0, count)]


def profile_pool_for_run(count: int, settings: Optional[Dict[str, Any]] = None) -> List[str]:
    """Get profile pool for running tasks (Chrome local only)."""
    s = settings if settings is not None else (get_settings() or {})
    return local_profile_pool_ids(s, count)


def list_active_profile_ids(
    settings: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    """List currently active Chrome local profile IDs."""
    s = settings if settings is not None else (get_settings() or {})
    out: Set[str] = set()
    oid = clb.chrome_local_ordered_ids(s)
    for pid in oid:
        if clb.is_tracked_running(pid) or clb.is_debug_port_responding(clb.port_for_profile(pid, oid)):
            out.add(pid)
    return out


def ensure_profiles_started(
    profile_ids: List[str],
    *,
    settings: Optional[Dict[str, Any]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> None:
    """Ensure Chrome local profiles are started."""
    s = settings if settings is not None else (get_settings() or {})
    oid = clb.chrome_local_ordered_ids(s)
    for pid in profile_ids:
        if stop_check and stop_check():
            return
        port = clb.port_for_profile(pid, oid)
        if clb.is_debug_port_responding(port):
            continue
        ok, msg = clb.start_profile(s, pid, ordered_ids=oid)
        if not ok:
            print(f"[ChromeLocal] ⚠️ start {pid[-6:]}: {msg}")


def stop_profiles_by_ids_unified(profile_ids: List[str], settings: Optional[Dict[str, Any]] = None) -> bool:
    """Stop Chrome local profiles by IDs."""
    if not profile_ids:
        return False
    for pid in profile_ids:
        clb.stop_profile(pid)
    return True


async def wait_for_profiles_ready_unified(
    profile_ids: List[str],
    timeout_sec: float = 30.0,
    poll_interval: float = 0.8,
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    """Wait for Chrome local profiles to be ready (CDP responding)."""
    s = settings if settings is not None else (get_settings() or {})
    if not profile_ids:
        return True
    
    oid = clb.chrome_local_ordered_ids(s)
    start = time.monotonic()
    while True:
        if time.monotonic() - start >= timeout_sec:
            print(f"[ChromeLocal] ⚠️ Timeout {timeout_sec}s chờ CDP.")
            return False
        ready = set()
        for pid in profile_ids:
            port = clb.port_for_profile(pid, oid)
            if clb.is_debug_port_responding(port):
                ready.add(pid)
        if len(ready) >= len(profile_ids):
            return True
        await asyncio.sleep(poll_interval)


def get_ws_endpoint_for_profile(
    profile_id: str,
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Get WebSocket endpoint for Chrome local profile."""
    s = settings if settings is not None else (get_settings() or {})
    return clb.get_ws_endpoint_for_profile(s, profile_id)


def create_browser(settings: Optional[Dict[str, Any]] = None) -> str:
    """
    Create/initialize browser engine.
    Returns: 'chrome_local' (NST removed)
    """
    return "chrome_local"

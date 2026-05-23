import json
import os
import threading
import time
import traceback
from typing import Optional

from silent_download import _http_get_json, download_and_prepare_update


from version import GITHUB_REPO as DEFAULT_REPO
from version import GITHUB_USER as DEFAULT_OWNER
from version import UPDATE_ZIP_NAME


def _append_log(app_dir: str, msg: str) -> None:
    try:
        log_path = os.path.join(app_dir, 'temp', 'update_debug.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
            f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass


def _print_progress(msg: str) -> None:
    try:
        print(str(msg))
        try:
            import sys
            sys.stdout.flush()
        except Exception:
            pass
    except Exception:
        pass


def _normalize_tag(tag: str) -> str:
    t = str(tag or "").strip()
    if len(t) >= 2 and (t[0] in ("v", "V")) and t[1].isdigit():
        t = t[1:]
    return t or "0.0.0"


def _version_key(v: str):
    parts = []
    for seg in str(v or "").strip().split("."):
        n = 0
        s = seg.strip()
        i = 0
        while i < len(s) and s[i].isdigit():
            i += 1
        if i:
            try:
                n = int(s[:i])
            except Exception:
                n = 0
        parts.append(n)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:6])


def read_local_version(app_dir: str) -> str:
    cfg = os.path.join(app_dir, "config", "config.json")
    try:
        if not os.path.exists(cfg):
            return "0.0.0"
        raw = open(cfg, "r", encoding="utf-8-sig", errors="replace").read()
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return _normalize_tag(str(obj.get("VERSION") or "").strip())
        except Exception:
            pass
        # fallback regex-ish
        key = '"VERSION"'
        idx = raw.lower().find(key.lower())
        if idx >= 0:
            # naive parse: find next quote after ':'
            tail = raw[idx:]
            c = tail.find(":")
            if c >= 0:
                tail2 = tail[c + 1 :]
                q1 = tail2.find('"')
                if q1 >= 0:
                    tail3 = tail2[q1 + 1 :]
                    q2 = tail3.find('"')
                    if q2 >= 0:
                        return _normalize_tag(tail3[:q2])
    except Exception:
        pass
    return "0.0.0"


def _pick_zip_asset(release_json: dict) -> Optional[str]:
    assets = release_json.get("assets") or []
    if not isinstance(assets, list):
        assets = []

    preferred = UPDATE_ZIP_NAME.lower()

    for a in assets:
        try:
            name = str((a or {}).get("name") or "").lower()
            url = str((a or {}).get("browser_download_url") or "").strip()
            if url and name == preferred:
                return url
        except Exception:
            pass

    for a in assets:
        try:
            name = str((a or {}).get("name") or "").lower()
            url = str((a or {}).get("browser_download_url") or "").strip()
            if url and name.endswith(".zip"):
                return url
        except Exception:
            pass

    return None


def _write_json_atomic(path: str, obj: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: str) -> Optional[dict]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def apply_ready_if_any(app_dir: str) -> bool:
    """If update_ready.json exists, return True if caller should launch updater."""
    ready_path = os.path.join(app_dir, "temp", "update_ready.json")
    return os.path.exists(ready_path)


def check_and_prepare_update_once(
    *,
    app_dir: str,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
) -> bool:
    """One-shot update check.

    Behavior:
    - Best-effort silent
    - Bypasses throttle/lock so it can be used on startup

    Returns:
        True if update_ready.json is created.
    """
    ready_path = os.path.join(app_dir, "temp", "update_ready.json")
    lock_path = os.path.join(app_dir, "temp", "update_check_lock.json")

    try:
        os.makedirs(os.path.join(app_dir, "temp"), exist_ok=True)
    except Exception:
        pass

    try:
        if os.path.exists(ready_path):
            return True
    except Exception:
        pass

    now = time.time()
    try:
        lock = _read_json(lock_path) or {}
        last_success = float(lock.get("last_success_ts") or 0.0)
        _write_json_atomic(lock_path, {"last_attempt_ts": now, "last_success_ts": last_success})
    except Exception:
        pass

    try:
        _append_log(app_dir, 'update_checker: startup one-shot check')
        _print_progress('Checking for updates...')
        local_v = read_local_version(app_dir)
        api_latest = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        rel = _http_get_json(api_latest, timeout_sec=30.0)

        latest = _normalize_tag(str(rel.get("tag_name") or ""))
        _append_log(app_dir, f'update_checker: local={local_v} latest={latest}')
        _print_progress(f'Version: local={local_v} latest={latest}')
        if _version_key(latest) <= _version_key(local_v):
            try:
                _write_json_atomic(lock_path, {"last_attempt_ts": now, "last_success_ts": time.time()})
            except Exception:
                pass
            _print_progress('No update available.')
            return False

        zip_url = _pick_zip_asset(rel)
        if not zip_url:
            _append_log(app_dir, 'update_checker: no zip asset found')
            return False

        try:
            asset_name = str(zip_url).split('/')[-1] or 'asset.zip'
        except Exception:
            asset_name = 'asset.zip'

        _append_log(app_dir, f'update_checker: downloading zip asset={asset_name}')
        _print_progress(f'Downloading update package: {asset_name} ...')
        work_dir = os.path.join(app_dir, "temp")
        meta = download_and_prepare_update(zip_url, work_dir)
        _append_log(app_dir, f'update_checker: download+extract done, extract_dir={meta.get("extract_dir")!r}')
        _print_progress('Download complete. Extracting...')

        payload_root = str(meta.get("payload_root") or "").strip()
        if not payload_root or not os.path.isdir(payload_root):
            _append_log(app_dir, f'update_checker: invalid payload_root={payload_root!r}')
            return False

        _write_json_atomic(
            ready_path,
            {
                "version": latest,
                "path": payload_root,
                "created_ts": time.time(),
            },
        )

        _append_log(app_dir, f'update_checker: update prepared OK -> {ready_path} payload_root={payload_root}')
        _print_progress('Update prepared. Applying update on restart...')
        try:
            _write_json_atomic(lock_path, {"last_attempt_ts": now, "last_success_ts": time.time()})
        except Exception:
            pass
        return True
    except Exception as exc:
        _append_log(app_dir, f'update_checker: ERROR(one-shot) {exc!r}')
        try:
            _append_log(app_dir, traceback.format_exc())
        except Exception:
            pass
        _print_progress(f'Update check failed: {exc!r}')
        return False


def start_background_update_check(
    *,
    app_dir: str,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    interval_sec: float = 1800.0,
) -> None:
    """Start a single daemon thread that checks at most every interval_sec.

    Silent behavior:
    - No UI
    - Best-effort, failures are ignored
    """

    def _worker():
        lock_path = os.path.join(app_dir, "temp", "update_check_lock.json")
        ready_path = os.path.join(app_dir, "temp", "update_ready.json")

        fail_retry_sec = 60.0

        os.makedirs(os.path.join(app_dir, "temp"), exist_ok=True)

        _append_log(app_dir, 'update_checker: worker started')

        while True:
            try:
                # If ready already exists, do nothing
                if os.path.exists(ready_path):
                    _append_log(app_dir, 'update_checker: update_ready.json exists -> sleep')
                    time.sleep(float(interval_sec))
                    continue

                # Throttle using lock file timestamp
                now = time.time()
                lock = _read_json(lock_path) or {}
                last_success = float(lock.get("last_success_ts") or 0.0)
                last_attempt = float(lock.get("last_attempt_ts") or 0.0)

                if last_success and (now - last_success) < float(interval_sec):
                    try:
                        remain = float(interval_sec) - (now - last_success)
                    except Exception:
                        remain = -1.0
                    _append_log(app_dir, f'update_checker: throttled by lock, remaining_sec={remain:.1f}')
                    time.sleep(5.0)
                    continue

                # If last attempt failed/was interrupted, retry sooner
                if last_attempt and (last_success <= 0.0 or last_attempt > last_success) and (now - last_attempt) < float(fail_retry_sec):
                    try:
                        remain = float(fail_retry_sec) - (now - last_attempt)
                    except Exception:
                        remain = -1.0
                    _append_log(app_dir, f'update_checker: throttled after failed attempt, remaining_sec={remain:.1f}')
                    time.sleep(5.0)
                    continue

                _write_json_atomic(lock_path, {"last_attempt_ts": now, "last_success_ts": last_success})

                _append_log(app_dir, 'update_checker: checking GitHub latest release')

                local_v = read_local_version(app_dir)
                api_latest = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
                rel = _http_get_json(api_latest, timeout_sec=30.0)

                latest = _normalize_tag(str(rel.get("tag_name") or ""))
                _append_log(app_dir, f'update_checker: local={local_v} latest={latest}')
                if _version_key(latest) <= _version_key(local_v):
                    _write_json_atomic(lock_path, {"last_attempt_ts": now, "last_success_ts": time.time()})
                    time.sleep(float(interval_sec))
                    continue

                zip_url = _pick_zip_asset(rel)
                if not zip_url:
                    _append_log(app_dir, 'update_checker: no zip asset found -> sleep')
                    _write_json_atomic(lock_path, {"last_attempt_ts": now, "last_success_ts": time.time()})
                    time.sleep(float(interval_sec))
                    continue

                work_dir = os.path.join(app_dir, "temp")
                try:
                    asset_name = str(zip_url).split('/')[-1] or 'asset.zip'
                except Exception:
                    asset_name = 'asset.zip'
                _append_log(app_dir, f'update_checker: downloading zip asset={asset_name}')
                meta = download_and_prepare_update(zip_url, work_dir)

                _append_log(app_dir, f'update_checker: download+extract done, extract_dir={meta.get("extract_dir")!r}')

                # payload_root is the folder to copy from on apply
                payload_root = str(meta.get("payload_root") or "").strip()
                if not payload_root or not os.path.isdir(payload_root):
                    _append_log(app_dir, f'update_checker: invalid payload_root={payload_root!r} extract_dir={meta.get("extract_dir")!r}')
                    time.sleep(float(interval_sec))
                    continue

                _write_json_atomic(
                    ready_path,
                    {
                        "version": latest,
                        "path": payload_root,
                        "created_ts": time.time(),
                    },
                )

                _append_log(app_dir, f'update_checker: update prepared OK -> {ready_path} payload_root={payload_root}')

                _write_json_atomic(lock_path, {"last_attempt_ts": now, "last_success_ts": time.time()})

                time.sleep(float(interval_sec))
            except Exception as exc:
                _append_log(app_dir, f'update_checker: ERROR {exc!r}')
                try:
                    _append_log(app_dir, traceback.format_exc())
                except Exception:
                    pass
                try:
                    _write_json_atomic(lock_path, {"last_attempt_ts": time.time(), "last_success_ts": float((_read_json(lock_path) or {}).get("last_success_ts") or 0.0)})
                except Exception:
                    pass
                try:
                    time.sleep(float(fail_retry_sec))
                except Exception:
                    pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

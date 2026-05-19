# update.py
# - Get GitHub latest release
# - Download latest zip asset
# - Extract to temp
# - Copy overwrite into APP_DIR
# - Update _internal/config.json field "VERSION" (tolerant, even if JSON is broken)

import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
import urllib.request

OWNER = "AnhTuan2003ml"
REPO = "creat_video"
API_LATEST = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
ASSET_PREFIX = "creat_video"
UA = "CreatVideoUpdater"

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

SKIP_NAMES = {"update.py", "update.exe"}


def _read_json_tolerant(path: Path):
    try:
        raw = path.read_text(encoding='utf-8-sig', errors='replace')
    except Exception:
        return None

    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        # Best-effort: try to locate a JSON object boundaries
        try:
            s = raw.find('{')
            e = raw.rfind('}')
            if s >= 0 and e > s:
                obj = json.loads(raw[s:e + 1])
                return obj if isinstance(obj, dict) else None
        except Exception:
            pass
    return None


def ensure_runtime_config(app_dir: Path) -> None:
    cfg_dir = app_dir / "config"
    cfg_path = cfg_dir / "config.json"
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    if cfg_path.exists():
        return

    try:
        cfg_path.write_text('{\n  "ACCOUNT_ID": ""\n}\n', encoding="utf-8")
        print("Created missing config.json ->", cfg_path)
    except Exception as exc:
        print("Failed to create config.json:", exc)


def _pick_app_exe(app_dir: Path) -> Path | None:
    try:
        exes = []
        for p in app_dir.glob("*.exe"):
            if p.name.lower() in ("update.exe",):
                continue
            exes.append(p)
        exes.sort(key=lambda x: x.name.lower())
        return exes[0] if exes else None
    except Exception:
        return None


def _launch_app(app_dir: Path, app_path: Path | None) -> None:
    try:
        target = app_path if app_path else _pick_app_exe(app_dir)
        if not target or not target.exists():
            print("No app exe found to relaunch.")
            return

        print("Launching app ->", target)
        import subprocess
        # Sử dụng shell=True và khởi chạy trực tiếp để Windows nhận diện console từ build.spec
        if os.name == 'nt':
            subprocess.Popen([str(target)], cwd=str(app_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([str(target)], cwd=str(app_dir))
    except Exception as exc:
        print("Failed to launch app:", exc)

# ---------------- Version helpers ----------------

def normalize_tag(tag: str) -> str:
    if not tag:
        return "0.0.0"
    t = str(tag).strip()
    if len(t) >= 2 and (t[0] in ("v", "V")) and t[1].isdigit():
        t = t[1:]
    return t

# ---------------- GitHub ----------------

def get_latest_release():
    req = urllib.request.Request(
        API_LATEST,
        headers={"User-Agent": UA, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def pick_zip_asset(release_json):
    assets = release_json.get("assets", []) or []

    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(".zip") and name.startswith(ASSET_PREFIX.lower()):
            return a.get("browser_download_url")

    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(".zip"):
            return a.get("browser_download_url")

    return None

# ---------------- Download ----------------

def download_file(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = resp.getheader("Content-Length")
        with open(dest, "wb") as f:
            if not total:
                shutil.copyfileobj(resp, f)
                print("Downloaded (no size info).")
                return

            total = int(total)
            downloaded = 0
            chunk_size = 1024 * 64
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                pct = (downloaded * 100) // total
                print(f"\rDownloading... {pct}%", end="")
    print("\nDownload complete.")

# ---------------- Extract ----------------

def safe_extract(zip_path: Path, extract_to: Path):
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)

def find_payload_root(extract_dir: Path) -> Path:
    items = [p for p in extract_dir.iterdir() if p.name not in (".DS_Store", "__MACOSX")]
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return extract_dir

# ---------------- Copy overwrite ----------------

def copy_overwrite(src_root: Path, dst_root: Path):
    for src in src_root.rglob("*"):
        rel = src.relative_to(src_root)
        dst = dst_root / rel

        if src.is_file() and src.name.lower() in SKIP_NAMES:
            continue

        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            try:
                os.chmod(dst, 0o666)
            except:
                pass

        shutil.copy2(src, dst)


def copy_overwrite_retry(src_root: Path, dst_root: Path, retries: int = 5, delay_sec: float = 0.6):
    for src in src_root.rglob('*'):
        rel = src.relative_to(src_root)
        dst = dst_root / rel

        if src.is_file() and src.name.lower() in SKIP_NAMES:
            continue

        if src.is_dir():
            try:
                dst.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        last_exc = None
        for i in range(max(1, int(retries))):
            try:
                if dst.exists():
                    try:
                        os.chmod(dst, 0o666)
                    except Exception:
                        pass
                shutil.copy2(src, dst)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                try:
                    time.sleep(float(delay_sec) + (i * 0.2))
                except Exception:
                    pass

        if last_exc is not None:
            raise last_exc


def apply_ready_update(app_dir: Path, ready_json_path: Path, app_arg: str | None = None) -> int:
    """Apply a previously downloaded update prepared by the main app.

    ready_json expected:
      {"version": "1.2.0", "path": "C:/.../temp/update/..."}
    """
    try:
        meta = _read_json_tolerant(ready_json_path) or {}
    except Exception:
        meta = {}

    version = normalize_tag(str(meta.get('version') or '').strip())
    payload_path = str(meta.get('path') or '').strip()

    if not payload_path:
        print('Invalid update_ready.json: missing path')
        return 1

    payload_root = Path(payload_path)
    if not payload_root.exists() or not payload_root.is_dir():
        print('Payload path not found:', payload_root)
        return 1

    # Wait a bit to ensure the main app process has exited and released file locks
    try:
        time.sleep(2.0)
    except Exception:
        pass

    print('Applying update from:', payload_root)
    copy_overwrite_retry(payload_root, app_dir)

    if version and version != '0.0.0':
        print('Updating config/config.json VERSION...')
        update_config_version(app_dir, version)

    # Cleanup temp folder and ready flag
    try:
        # If payload_root is inside a temp folder, remove its parent "temp/update" safely
        try:
            if payload_root.exists():
                shutil.rmtree(payload_root, ignore_errors=True)
        except Exception:
            pass
        try:
            if ready_json_path.exists():
                ready_json_path.unlink(missing_ok=True)
        except Exception:
            try:
                if ready_json_path.exists():
                    ready_json_path.unlink()
            except Exception:
                pass
    except Exception:
        pass

    ensure_runtime_config(app_dir)

    try:
        app_path = Path(app_arg).resolve() if app_arg else None
    except Exception:
        app_path = None
    _launch_app(app_dir, app_path)
    return 0

# ---------------- Config VERSION update (tolerant) ----------------

def read_text_utf8sig(path: Path) -> str:
    # remove BOM if any
    return path.read_text(encoding="utf-8-sig", errors="replace")

def write_text_utf8(path: Path, text: str):
    path.write_text(text, encoding="utf-8")

def try_parse_json(text: str):
    # remove trailing commas like: "x":1,
    # (best-effort only; still may fail)
    try:
        return json.loads(text)
    except:
        return None

def update_config_version(app_dir: Path, new_version: str):
    cfg = app_dir / "config" / "config.json"
    if not cfg.exists():
        print("config.json not found:", cfg)
        return False

    new_version = normalize_tag(new_version)
    raw = read_text_utf8sig(cfg)

    # 1) Try parse + write pretty JSON if valid
    obj = try_parse_json(raw)
    if isinstance(obj, dict):
        obj["VERSION"] = new_version
        write_text_utf8(cfg, json.dumps(obj, ensure_ascii=False, indent=2))
        print("Updated VERSION (json ok) ->", new_version)
        return True

    # 2) JSON broken -> fallback regex replace
    print("⚠ config.json is invalid JSON -> fallback regex patch VERSION...")

    # Fix common wrong pattern: "VERSION":"VERSION": "1.0.0",
    raw = re.sub(r'"VERSION"\s*:\s*"VERSION"\s*:\s*', '"VERSION": ', raw)

    # Replace existing VERSION
    if re.search(r'"VERSION"\s*:\s*".*?"', raw, flags=re.IGNORECASE):
        patched = re.sub(
            r'("VERSION"\s*:\s*")([^"]*)(")',
            r'\g<1>' + new_version + r'\3',
            raw,
            flags=re.IGNORECASE,
            count=1
        )
        write_text_utf8(cfg, patched)
        print("Updated VERSION (regex replace) ->", new_version)
        return True

    # Insert VERSION after "API": ...
    m = re.search(r'("API"\s*:\s*".*?")\s*(,?)', raw, flags=re.IGNORECASE | re.DOTALL)
    if m:
        insert_pos = m.end()
        comma = ","  # always add comma after API line
        patched = raw[:insert_pos] + f'{comma}\n  "VERSION": "{new_version}"' + raw[insert_pos:]
        write_text_utf8(cfg, patched)
        print("Inserted VERSION (regex insert) ->", new_version)
        return True

    # If cannot locate API, just prepend VERSION at top-level (best-effort)
    patched = '{\n  "VERSION": "' + new_version + '",\n' + raw.lstrip()
    write_text_utf8(cfg, patched)
    print("Prepended VERSION (best-effort) ->", new_version)
    return True


def _version_key(v: str):
    try:
        parts = []
        for x in str(v or '').strip().split('.'):
            m = re.match(r'^(\d+)', x.strip())
            parts.append(int(m.group(1)) if m else 0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:6])
    except Exception:
        return (0, 0, 0)


def read_local_version(app_dir: Path) -> str:
    cfg = app_dir / "config" / "config.json"
    if not cfg.exists():
        return "0.0.0"
    try:
        raw = read_text_utf8sig(cfg)
        obj = try_parse_json(raw)
        if isinstance(obj, dict):
            return normalize_tag(str(obj.get('VERSION') or '').strip())
        m = re.search(r'"VERSION"\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
        if m:
            return normalize_tag(m.group(1))
    except Exception:
        pass
    return "0.0.0"


def is_update_available(app_dir: Path, latest_version: str) -> bool:
    try:
        local_v = read_local_version(app_dir)
        return _version_key(latest_version) > _version_key(local_v)
    except Exception:
        return False

# ---------------- Main ----------------

def main():
    print("APP_DIR:", APP_DIR)

    app_arg = None
    check_only = False
    apply_ready = None
    try:
        if "--app" in sys.argv:
            idx = sys.argv.index("--app")
            if idx + 1 < len(sys.argv):
                app_arg = sys.argv[idx + 1]
    except Exception:
        app_arg = None

    try:
        if "--apply-ready" in sys.argv:
            idx = sys.argv.index("--apply-ready")
            if idx + 1 < len(sys.argv):
                apply_ready = sys.argv[idx + 1]
    except Exception:
        apply_ready = None

    try:
        check_only = "--check-only" in sys.argv
    except Exception:
        check_only = False

    if apply_ready:
        try:
            return apply_ready_update(APP_DIR, Path(apply_ready), app_arg=app_arg)
        except Exception as exc:
            print('Failed to apply-ready update:', exc)
            return 1

    release = get_latest_release()
    tag = release.get("tag_name", "")
    latest_version = normalize_tag(tag)
    print("Latest release:", tag)

    if check_only:
        try:
            ensure_runtime_config(APP_DIR)
        except Exception:
            pass

        if is_update_available(APP_DIR, latest_version):
            print("Update available ->", latest_version)
            return 2
        print("Already up-to-date ->", latest_version)
        return 0

    zip_url = pick_zip_asset(release)
    if not zip_url:
        print("No zip asset found.")
        return 1

    work_dir = Path(tempfile.gettempdir()) / "creat_video_update"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    zip_path = work_dir / "update.zip"
    extract_dir = work_dir / "extract"

    print("Downloading...")
    download_file(zip_url, zip_path)

    print("Extracting...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    safe_extract(zip_path, extract_dir)

    payload_root = find_payload_root(extract_dir)
    print("Payload root:", payload_root)

    print("Copy overwrite into APP_DIR...")
    copy_overwrite(payload_root, APP_DIR)

    print("Updating config/config.json VERSION...")
    update_config_version(APP_DIR, latest_version)

    ensure_runtime_config(APP_DIR)

    print("Update done.")
    shutil.rmtree(work_dir, ignore_errors=True)

    try:
        app_path = Path(app_arg).resolve() if app_arg else None
    except Exception:
        app_path = None
    _launch_app(APP_DIR, app_path)
    return 0

if __name__ == "__main__":
    sys.exit(main())

import json
import os
import shutil
import time
import urllib.request
import zipfile


UA = "VideoCreatorSilentUpdater"


def _ensure_dir(p: str) -> None:
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass


def _http_get_json(url: str, timeout_sec: float = 30.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def download_file(url: str, dest_path: str, timeout_sec: float = 300.0, retries: int = 3) -> None:
    last_exc = None
    for i in range(max(1, int(retries))):
        try:
            _ensure_dir(os.path.dirname(dest_path))
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
                with open(dest_path, "wb") as f:
                    shutil.copyfileobj(resp, f)
            return
        except Exception as exc:
            last_exc = exc
            try:
                time.sleep(1.0 + i)
            except Exception:
                pass

    if last_exc:
        raise last_exc


def extract_zip(zip_path: str, extract_to: str, retries: int = 2) -> None:
    last_exc = None
    for i in range(max(1, int(retries))):
        try:
            try:
                if not zipfile.is_zipfile(zip_path):
                    raise RuntimeError(f"Downloaded file is not a valid zip: {zip_path}")
            except Exception as exc:
                raise exc

            _ensure_dir(extract_to)
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_to)
            return
        except Exception as exc:
            last_exc = exc
            try:
                time.sleep(0.5 + i)
            except Exception:
                pass

    if last_exc:
        raise last_exc


def find_payload_root(extract_dir: str) -> str:
    try:
        items = []
        for name in os.listdir(extract_dir):
            if name in (".DS_Store", "__MACOSX"):
                continue
            items.append(os.path.join(extract_dir, name))
        if len(items) == 1 and os.path.isdir(items[0]):
            return items[0]
    except Exception:
        pass
    return extract_dir


def download_and_prepare_update(zip_url: str, work_dir: str) -> dict:
    """Download zip into work_dir/update.zip, extract to work_dir/update, return paths.

    Returns:
        {
          "zip_path": "...",
          "extract_dir": "...",
          "payload_root": "..."
        }
    """
    _ensure_dir(work_dir)

    zip_path = os.path.join(work_dir, "update.zip")
    extract_dir = os.path.join(work_dir, "update")

    try:
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
    except Exception:
        pass

    download_file(zip_url, zip_path)
    try:
        if not zipfile.is_zipfile(zip_path):
            raise RuntimeError("Downloaded update.zip is not a valid zip")
    except Exception:
        # Let caller log and decide; do not swallow
        raise
    extract_zip(zip_path, extract_dir)
    payload_root = find_payload_root(extract_dir)

    return {
        "zip_path": zip_path,
        "extract_dir": extract_dir,
        "payload_root": payload_root,
    }

"""
Build VideoCreator with Nuitka (standalone folder) for customer distribution.
Tùy chọn --zip: tạo VideoCreator.zip + update.json để upload GitHub Release (OTA).

Usage:
  python build_fast_c++.py              # dev nhanh (giữ cache, không LTO)
  python build_fast_c++.py --dev        # alias
  python build_fast_c++.py --release --clean     # bản gửi khách (LTO)
  python build_fast_c++.py --release --clean --zip   # + ZIP + update.json cho GitHub
  python build_fast_c++.py --clean      # xóa cache + build lại từ đầu
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from version import (
    APP_NAME,
    CURRENT_VERSION,
    GITHUB_REPO,
    GITHUB_USER,
    UPDATE_ZIP_NAME,
)

ROOT = Path(__file__).resolve().parent
ENTRY_POINT = ROOT / "app.py"
ICON_PATH = ROOT / "ico" / "logo.ico"
DIST_ROOT = ROOT / "dist"
DIST_DIR = DIST_ROOT / APP_NAME
CONFIG_DIST = ROOT / "config" / "config.dist.json"

# Mặc định = dev nhanh (giữ cache). Chỉ --release mới bật LTO.
DEV_MODE = "--release" not in sys.argv
RELEASE_MODE = "--release" in sys.argv
CLEAN_BUILD = "--clean" in sys.argv
# --dev = alias rõ ràng (cùng hành vi mặc định)
MAKE_ZIP = "--zip" in sys.argv

JOBS = max(1, min(8, (os.cpu_count() or 4)))

NOFOLLOW_PACKAGES = [
    "google",
    "pyasn1",
    "PIL",
    "proto",
    "grpc",
    "pydantic",
    "httpx",
    "httpcore",
    "anyio",
    "numpy",
    "pandas",
    "matplotlib",
]

# Chỉ liệt kê package chắc chắn dùng; phần còn lại Nuitka theo import từ app.py
INCLUDE_PACKAGES_CANDIDATES = [
    "flask",
    "werkzeug",
    "jinja2",
    "itsdangerous",
    "click",
    "markupsafe",
    "aiohttp",
    "requests",
    "brotli",
    "dinorap_updater",
    "playwright",
    "playwright_stealth",
    "utils",
]


def _import_name(pkg: str) -> str:
    return pkg.replace("-", "_")


def resolve_include_packages() -> list[str]:
    """Chỉ --include-package những gì đã cài (tránh fatal như aiohttp_socks)."""
    resolved: list[str] = []
    for pkg in INCLUDE_PACKAGES_CANDIDATES:
        try:
            __import__(_import_name(pkg))
            resolved.append(pkg)
        except ImportError:
            print(f"   [SKIP] package not installed: {pkg}")
    return resolved

INCLUDE_MODULES = [
    "update_checker",
    "silent_download",
    "version",
    "app",
]

DATA_DIRS = [
    ("templaces", "templaces"),
    ("ico", "ico"),
]

STORAGE_DIRS = [
    "generated",
    "temp_video",
    "tmp_uploads",
    "temp",
    "profile",
    "config/Music",
]

# User data preserved on OTA update (do not ship secrets from dev machine)
RELEASE_ZIP_SKIP_DIRS = {
    "config",
    "generated",
    "temp_video",
    "tmp_uploads",
    "temp",
    "profile",
    "storage",
    ".git",
    "__pycache__",
}
RELEASE_ZIP_SKIP_FILES = {
    UPDATE_ZIP_NAME,
    "update.json",
    "update.zip",
    "update_installer.bat",
    "update.py",
    "update.exe",
}


def _version_without_v() -> str:
    v = CURRENT_VERSION.strip()
    if len(v) >= 2 and v[0] in "vV" and v[1].isdigit():
        return v[1:]
    return v


def clean_old_build() -> None:
    if DEV_MODE and not CLEAN_BUILD:
        print("[CLEAN] DEV MODE -> skip clean (reuse Nuitka cache)")
        return
    print("[CLEAN] Removing old build artifacts...")
    for name in ("build", "dist", f"{APP_NAME}.build", f"{APP_NAME}.dist", f"{APP_NAME}.onefile-build"):
        p = ROOT / name
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            print(f"   [OK] removed {p.name}/")
    for pattern in ("*.build", "*.dist", "*.onefile-build"):
        for p in ROOT.glob(pattern):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                print(f"   [OK] removed {p.name}/")


def run_nuitka_main() -> None:
    print("[BUILD] Nuitka standalone ->", APP_NAME)
    if not ENTRY_POINT.exists():
        raise RuntimeError(f"Entry point missing: {ENTRY_POINT}")

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--msvc=latest",
        f"--jobs={JOBS}",
        "--low-memory",
        f"--output-dir={DIST_ROOT.as_posix()}",
        f"--output-filename={APP_NAME}.exe",
        "--windows-console-mode=force",
        "--company-name=VideoCreator",
        f"--product-name={APP_NAME}",
        f"--file-version={_version_without_v()}.0",
        f"--product-version={_version_without_v()}",
    ]

    for pkg in NOFOLLOW_PACKAGES:
        cmd.append(f"--nofollow-import-to={pkg}")

    for pkg in resolve_include_packages():
        cmd.append(f"--include-package={pkg}")

    for mod in INCLUDE_MODULES:
        cmd.append(f"--include-module={mod}")

    for src, dest in DATA_DIRS:
        src_path = ROOT / src
        if src_path.exists():
            cmd.append(f"--include-data-dir={src_path.as_posix()}={dest}")

    if ICON_PATH.exists():
        cmd.append(f"--windows-icon-from-ico={ICON_PATH.as_posix()}")

    if RELEASE_MODE:
        print("   [MODE] RELEASE (LTO)")
        cmd.extend(["--lto=yes", "--remove-output"])
    else:
        print("   [MODE] DEV / fast")

    cmd.append(str(ENTRY_POINT))

    env = os.environ.copy()
    extra_cl = "/Zm300"
    env["CL"] = (env.get("CL", "") + " " + extra_cl).strip()
    env["_CL_"] = (env.get("_CL_", "") + " " + extra_cl).strip()

    print("   [CMD]", " ".join(cmd[:8]), "...")
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)

    nuitka_dist = None
    for d in DIST_ROOT.iterdir():
        if d.is_dir() and d.name.endswith(".dist"):
            nuitka_dist = d
            break
    if nuitka_dist is None:
        raise RuntimeError("Nuitka .dist folder not found under dist/")

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    shutil.move(str(nuitka_dist), str(DIST_DIR))

    for exe in DIST_DIR.glob("*.exe"):
        target = DIST_DIR / f"{APP_NAME}.exe"
        if exe.name != target.name:
            if target.exists():
                target.unlink()
            exe.rename(target)
        break

    print(f"   [OK] {DIST_DIR}")


def _copy_config_tree() -> None:
    src_cfg = ROOT / "config"
    dst_cfg = DIST_DIR / "config"
    dst_cfg.mkdir(parents=True, exist_ok=True)

    for item in src_cfg.iterdir():
        if item.name in ("config.json", "config.dist.json", "tasks.json", "veo_auth.json"):
            continue
        dst = dst_cfg / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)

    dist_cfg = dst_cfg / "config.json"
    if CONFIG_DIST.exists():
        shutil.copy2(CONFIG_DIST, dist_cfg)
    else:
        shutil.copy2(src_cfg / "config.json", dist_cfg)

    data = json.loads(dist_cfg.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data["VERSION"] = _version_without_v()
        dist_cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("   [OK] config/ (sanitized config.json)")


def copy_resources() -> None:
    print("[BUILD] Copying runtime resources...")
    for src_name, _ in DATA_DIRS:
        src = ROOT / src_name
        dst = DIST_DIR / src_name
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"   [OK] {src_name}/")

    _copy_config_tree()

    for rel in STORAGE_DIRS:
        (DIST_DIR / rel).mkdir(parents=True, exist_ok=True)
    print(f"   [OK] storage dirs ({len(STORAGE_DIRS)})")

    readme = DIST_DIR / "HUONG_DAN.txt"
    readme.write_text(
        f"""{APP_NAME} - Huong dan su dung
================================

1. Giai nen toan bo thu muc vao vi tri ban muon (vi du: C:\\{APP_NAME})
2. Chay {APP_NAME}.exe
3. Trinh duyet se mo http://127.0.0.1:5000

Thu muc quan trong (cung cap voi .exe):
- config/     : cau hinh, kich ban, nhac nen
- profile/    : profile trinh duyet
- generated/  : video/anh da tao

Cap nhat tu GitHub: https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases
File release: {UPDATE_ZIP_NAME}
Phien ban hien tai: {CURRENT_VERSION}
""",
        encoding="utf-8",
    )
    print("   [OK] HUONG_DAN.txt")


def write_update_json(zip_path: Path) -> Path:
    """SHA256 của VideoCreator.zip → update.json (bắt buộc trên GitHub release)."""
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)

    payload = {
        "version": CURRENT_VERSION,
        "sha256": h.hexdigest(),
        "release_notes": f"Release {CURRENT_VERSION}",
    }
    out = ROOT / "update.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"   [OK] update.json (sha256={h.hexdigest()[:16]}...)")
    return out


def create_release_zip() -> tuple[Path, Path]:
    zip_path = ROOT / UPDATE_ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()

    print(f"[ZIP] Creating {UPDATE_ZIP_NAME} for GitHub OTA...")
    print("      (không gồm config/ — ghi đè merge, giữ dữ liệu user)")
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(DIST_DIR):
            dirs[:] = [d for d in dirs if d not in RELEASE_ZIP_SKIP_DIRS]
            for name in files:
                if name in RELEASE_ZIP_SKIP_FILES:
                    continue
                full = Path(root) / name
                arc = full.relative_to(DIST_DIR)
                zf.write(full, arc.as_posix())
                file_count += 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"   [OK] {zip_path} ({size_mb:.2f} MB, {file_count} files)")

    json_path = write_update_json(zip_path)

    print()
    print("=" * 60)
    print("GITHUB RELEASE — upload 2 file:")
    print("=" * 60)
    print(f"  https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/new")
    print(f"  Tag: {CURRENT_VERSION}")
    print(f"  1) {UPDATE_ZIP_NAME}")
    print(f"  2) update.json")
    print("=" * 60)
    return zip_path, json_path


def main() -> None:
    print()
    print("=" * 60)
    print(f"  BUILD {APP_NAME} | {CURRENT_VERSION} | Nuitka")
    print("=" * 60)
    print(f"  Output : {DIST_DIR}")
    print(f"  Jobs   : {JOBS}")
    print()

    try:
        clean_old_build()
        run_nuitka_main()
        copy_resources()
        print()
        print("[SUCCESS] BUILD COMPLETED")
        print(f"  Run: {DIST_DIR / (APP_NAME + '.exe')}")
        if MAKE_ZIP:
            create_release_zip()
    except subprocess.CalledProcessError as exc:
        print(f"\n[FAILED] Nuitka exit code {exc.returncode}")
        sys.exit(exc.returncode or 1)
    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

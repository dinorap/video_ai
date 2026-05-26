"""
Build VideoCreator with Nuitka (standalone folder).

Usage:
  python build_fast_c++.py              # dev nhanh (giu cache)
  python build_fast_c++.py --dev        # alias
  python build_fast_c++.py --release --clean     # ban phat hanh (LTO)
  python build_fast_c++.py --clean      # xoa cache + build lai

Sau build, dong goi update GitHub:
  python pack_release_update.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from version import APP_NAME, CURRENT_VERSION, GITHUB_REPO, GITHUB_USER, UPDATE_ZIP_NAME

ROOT = Path(__file__).resolve().parent
ENTRY_POINT = ROOT / "app.py"
ICON_PATH = ROOT / "ico" / "logo.ico"
DIST_ROOT = ROOT / "dist"
DIST_DIR = DIST_ROOT / APP_NAME
CONFIG_DIST = ROOT / "config" / "config.dist.json"

DEV_MODE = "--release" not in sys.argv
RELEASE_MODE = "--release" in sys.argv
CLEAN_BUILD = "--clean" in sys.argv

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
    "customtkinter",
    "utils",
]

INCLUDE_MODULES = [
    "update_checker",
    "silent_download",
    "version",
    "app",
    "utils.path_helper",
    "utils.runtime_paths",
    "utils.control_profile",
    "utils.control_script",
    "utils.control_ffmpeg",
    "utils.control_music",
    "utils.control_creat_video",
    "utils.control_creat_video_veo3_batch",
    "utils.control_creat_image",
    "utils.control_creat_image_veo3",
    "utils.veo3.veo_get_token",
    "utils.veo3_profile",
    "utils.ota_install",
    "utils.license_service",
    "utils.license_core",
    "utils.license_core.api",
    "utils.license_core.storage",
    "utils.license_core.hwid",
    "utils.license_core.env_secure",
    "utils.license_core.gui",
    "tkinter",
    "customtkinter",
]

BUILD_CONFIG_DIST = [
    ("config/config.dist.json", "config/config.dist.json"),
]

LICENSE_DATA_FILES = [
    ("utils/license_core/.env.enc", "utils/license_core/.env.enc"),
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


def _import_name(pkg: str) -> str:
    return pkg.replace("-", "_")


def resolve_include_packages() -> list[str]:
    resolved: list[str] = []
    for pkg in INCLUDE_PACKAGES_CANDIDATES:
        try:
            __import__(_import_name(pkg))
            resolved.append(pkg)
        except ImportError:
            print(f"   [SKIP] package not installed: {pkg}")
    return resolved


def _version_without_v() -> str:
    v = CURRENT_VERSION.strip()
    if len(v) >= 2 and v[0] in "vV" and v[1].isdigit():
        return v[1:]
    return v


def _nuitka_env(base: dict | None = None) -> dict:
    env = dict(base or os.environ)
    env["NUITKA_ASSUME_YES_FOR_DOWNLOADS"] = "1"
    extra_cl = "/Zm300"
    env["CL"] = (env.get("CL", "") + " " + extra_cl).strip()
    env["_CL_"] = (env.get("_CL_", "") + " " + extra_cl).strip()
    return env


def _run_nuitka_subprocess(cmd: list, *, cwd: Path | None = None) -> None:
    """Chay Nuitka khong hoi Yes/No (tu dong tai MinGW neu can)."""
    subprocess.run(
        cmd,
        check=True,
        cwd=str(cwd or ROOT),
        env=_nuitka_env(),
        input="Yes\n",
        text=True,
    )


def bootstrap_nuitka_toolchain() -> None:
    """Tai compiler cache truoc, tranh prompt giua build."""
    print("[BUILD] Bootstrap Nuitka toolchain (auto Yes)...")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "nuitka",
                "--assume-yes-for-downloads",
                "--version",
            ],
            cwd=ROOT,
            env=_nuitka_env(),
            input="Yes\n",
            text=True,
            check=False,
        )
    except Exception as exc:
        print(f"   [WARN] bootstrap: {exc}")


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

    bootstrap_nuitka_toolchain()

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugin=tk-inter",
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

    for src, dest in LICENSE_DATA_FILES:
        src_path = ROOT / src
        if src_path.exists():
            cmd.append(f"--include-data-files={src_path.as_posix()}={dest}")

    for src, dest in BUILD_CONFIG_DIST:
        src_path = ROOT / src
        if src_path.exists():
            cmd.append(f"--include-data-files={src_path.as_posix()}={dest}")

    if ICON_PATH.exists():
        cmd.append(f"--windows-icon-from-ico={ICON_PATH.as_posix()}")

    if RELEASE_MODE:
        print("   [MODE] RELEASE (LTO)")
        cmd.extend(["--lto=yes", "--remove-output"])
    else:
        print("   [MODE] DEV / fast")

    cmd.append(str(ENTRY_POINT))

    print("   [CMD]", " ".join(cmd[:8]), "...")
    _run_nuitka_subprocess(cmd)

    nuitka_dist = None
    for d in DIST_ROOT.iterdir():
        if d.is_dir() and d.name.endswith(".dist"):
            nuitka_dist = d
            break
    if nuitka_dist is None:
        raise RuntimeError("Nuitka .dist folder not found under dist/")

    if DIST_DIR.exists():
        try:
            shutil.rmtree(DIST_DIR)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot remove {DIST_DIR}. Close {APP_NAME}.exe then rebuild. ({exc})"
            ) from exc
    shutil.move(str(nuitka_dist), str(DIST_DIR))

    # Nuitka đặt tên thư mục theo entry (app.dist) — gộp lên root nếu bị lồng
    nested = DIST_DIR / "app.dist"
    if nested.is_dir() and not (DIST_DIR / f"{APP_NAME}.exe").is_file():
        for item in nested.iterdir():
            dest = DIST_DIR / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest, ignore_errors=True)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
        shutil.rmtree(nested, ignore_errors=True)

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
    dist_tpl = dst_cfg / "config.dist.json"
    if CONFIG_DIST.exists():
        shutil.copy2(CONFIG_DIST, dist_cfg)
        shutil.copy2(CONFIG_DIST, dist_tpl)
    else:
        shutil.copy2(src_cfg / "config.json", dist_cfg)

    data = json.loads(dist_cfg.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data.pop("VERSION", None)
        dist_cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("   [OK] config/")


def copy_resources() -> None:
    print("[BUILD] Copying runtime resources...")
    for src_name, _ in DATA_DIRS:
        src = ROOT / src_name
        dst = DIST_DIR / src_name
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"   [OK] {src_name}/ (synced)")

    _copy_config_tree()

    print("[BUILD] Bundling runtime tools (ffmpeg)...")
    try:
        from bundle_runtime_tools import bundle_ffmpeg_to, bundle_optional_chrome_to

        bundle_ffmpeg_to(DIST_DIR)
        bundle_optional_chrome_to(DIST_DIR)
    except Exception as exc:
        print(f"   [WARN] bundle runtime tools: {exc}")

    for rel in STORAGE_DIRS:
        (DIST_DIR / rel).mkdir(parents=True, exist_ok=True)
    print(f"   [OK] storage dirs ({len(STORAGE_DIRS)})")

    (DIST_DIR / "APP_VERSION").write_text(CURRENT_VERSION + "\n", encoding="utf-8")
    print(f"   [OK] APP_VERSION ({CURRENT_VERSION})")

    readme = DIST_DIR / "HUONG_DAN.txt"
    readme.write_text(
        f"""{APP_NAME} - Huong dan su dung
================================

1. Giai nen toan bo thu muc
2. Chay {APP_NAME}.exe
3. Mo http://127.0.0.1:5000

tools/ffmpeg/bin — da kem san (khong can cai ffmpeg)
Can Google Chrome (cai tren Windows) de tao video Grok/Veo3

Cap nhat: GitHub {GITHUB_USER}/{GITHUB_REPO}
Zip: {UPDATE_ZIP_NAME} + update.json
Phien ban: {CURRENT_VERSION}

Sau build chay: python pack_release_update.py
""",
        encoding="utf-8",
    )
    print("   [OK] HUONG_DAN.txt")


def main() -> None:
    print()
    print("=" * 60)
    print(f"  BUILD {APP_NAME} | {CURRENT_VERSION} | Nuitka")
    print("=" * 60)
    print(f"  Output : {DIST_DIR}")
    print(f"  Jobs   : {JOBS}")
    print("  Pack ZIP: python pack_release_update.py")
    print()

    try:
        clean_old_build()
        run_nuitka_main()
        copy_resources()
        print()
        print("[SUCCESS] BUILD COMPLETED")
        print(f"  Run: {DIST_DIR / (APP_NAME + '.exe')}")
    except subprocess.CalledProcessError as exc:
        print(f"\n[FAILED] Nuitka exit code {exc.returncode}")
        sys.exit(exc.returncode or 1)
    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

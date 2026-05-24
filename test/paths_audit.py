"""
Kiểm tra path dev vs exe (chạy trước/sau build).

Usage:
  python test/paths_audit.py
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULES = [
    "utils.path_helper",
    "utils.runtime_paths",
    "utils.license_service",
    "utils.license_core",
    "utils.license_core.gui",
    "utils.control_profile",
    "utils.control_script",
    "utils.control_music",
    "utils.control_ffmpeg",
    "utils.control_creat_video",
    "utils.control_creat_video_veo3_batch",
    "utils.control_creat_image_veo3",
    "utils.veo3.veo_get_token",
    "utils.veo3_profile",
    "utils.grok.profile",
    "utils.veo3.config_loader",
    "utils.veo3.chrome_local_browser",
    "utils.ota_install",
]

EXPECTED_UNDER_ROOT = [
    "config/config.json",
    "config/config.dist.json",
    "config/KichBan",
    "templaces/html/index.html",
    "ico/logo.ico",
    "utils/license_core/.env.enc",
]


def simulate_exe_checks() -> list[str]:
    """Giả lập sys.executable = VideoCreator.exe (không cần build)."""
    import os

    errors: list[str] = []
    fake_exe = ROOT / "dist" / "VideoCreator" / "VideoCreator.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    if not fake_exe.is_file():
        fake_exe.write_bytes(b"")

    old_exe = sys.executable
    old_cwd = os.getcwd()
    old_frozen = getattr(sys, "frozen", False)
    try:
        sys.executable = str(fake_exe)
        to_drop = [k for k in sys.modules if k == "app" or k.startswith("utils.")]
        for k in to_drop:
            del sys.modules[k]

        import utils.path_helper as ph

        ph.init_frozen_flag()
        ph.setup_runtime_cwd()
        d = ph.get_paths_diagnostic()

        if d["mode"] != "exe":
            errors.append(f"simulate exe: mode={d['mode']}")
        if ph.get_base_path().resolve() != fake_exe.parent.resolve():
            errors.append("simulate exe: base_dir mismatch")
        if not getattr(sys, "frozen", False):
            errors.append("simulate exe: sys.frozen not set")
        if Path(os.getcwd()).resolve() != fake_exe.parent.resolve():
            errors.append("simulate exe: cwd not set to exe dir")

        from utils.veo3.veo_get_token import _veo_auth_path
        from utils.veo3_profile import _get_veo_auth_path

        if Path(str(_veo_auth_path())) != Path(d["veo_auth_file"]):
            errors.append("simulate exe: veo_get_token path mismatch")
        if Path(_get_veo_auth_path()) != Path(d["veo_auth_file"]):
            errors.append("simulate exe: veo3_profile path mismatch")
        if Path(d["config_file"]).parent != Path(d["base_dir"]) / "config":
            errors.append("simulate exe: config not under base/config")

        import utils.control_profile  # noqa: F401
    except Exception as exc:
        errors.append(f"simulate exe failed: {exc}")
    finally:
        sys.executable = old_exe
        try:
            os.chdir(old_cwd)
        except Exception:
            pass
        if not old_frozen and hasattr(sys, "frozen"):
            try:
                delattr(sys, "frozen")
            except Exception:
                pass
        for k in [x for x in sys.modules if x == "app" or x.startswith("utils.")]:
            del sys.modules[k]

    if not errors:
        print("[OK] simulate exe mode")
    return errors


def main() -> int:
    from utils.path_helper import (
        CONFIG_FILE,
        VEO_AUTH_FILE,
        get_base_path,
        get_paths_diagnostic,
        is_running_as_exe,
        pstr,
    )
    from utils.veo3.veo_get_token import _veo_auth_path
    from utils.veo3_profile import _get_veo_auth_path

    print("=== PATH AUDIT ===")
    print(f"mode={'exe' if is_running_as_exe() else 'dev'}")
    print(f"base={get_base_path()}")
    print()

    errors: list[str] = []

    if pstr(_veo_auth_path()) != pstr(VEO_AUTH_FILE):
        errors.append(f"veo_get_token path mismatch: {_veo_auth_path()} != {VEO_AUTH_FILE}")
    if _get_veo_auth_path() != pstr(VEO_AUTH_FILE):
        errors.append(f"veo3_profile path mismatch: {_get_veo_auth_path()} != {VEO_AUTH_FILE}")
    if CONFIG_FILE.parent.name != "config":
        errors.append(f"CONFIG_FILE not under config/: {CONFIG_FILE}")

    for mod_name in MODULES:
        try:
            importlib.import_module(mod_name)
            print(f"[OK] import {mod_name}")
        except Exception as exc:
            errors.append(f"import failed {mod_name}: {exc}")
            print(f"[FAIL] import {mod_name}: {exc}")

    if not is_running_as_exe():
        base = get_base_path()
        for rel in EXPECTED_UNDER_ROOT:
            p = base / rel
            if not p.exists():
                errors.append(f"missing dev asset: {rel}")
                print(f"[WARN] missing {rel}")
            else:
                print(f"[OK] exists {rel}")

    try:
        import app  # noqa: F401
        print("[OK] import app")
    except Exception as exc:
        errors.append(f"import app: {exc}")
        print(f"[FAIL] import app: {exc}")

    diag = get_paths_diagnostic()
    print()
    print("--- diagnostic (dev) ---")
    for k, v in diag.items():
        print(f"  {k}: {v}")

    errors.extend(simulate_exe_checks())

    print()
    if errors:
        print(f"FAILED ({len(errors)} issues)")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

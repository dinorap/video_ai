import os
import subprocess
import shutil
import sys

from utils.path_helper import PROFILE_DIR as _PROFILE_DIR_PATH


def _win_subprocess_kwargs():
    if os.name != 'nt':
        return {}
    # Removed hidden window flags to show Chrome normally
    return {}


_PROJECT_ROOT = str(_PROFILE_DIR_PATH.parent)
PROFILE_DIR = str(_PROFILE_DIR_PATH)


print(f"DEBUG: Profile directory set to: {PROFILE_DIR}")


def find_chrome():
    try:
        from utils.runtime_paths import resolve_chrome_executable

        found = resolve_chrome_executable({})
        if found:
            return found
    except Exception:
        pass

    paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        os.path.expandvars(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"C:\Users\%USERNAME%\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p

    return shutil.which("google-chrome") or shutil.which("chromium")


def setting_grok_profile():
    if not os.path.exists(PROFILE_DIR):
        os.makedirs(PROFILE_DIR, exist_ok=True)

    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found")

    url = "https://grok.com/"

    proc = subprocess.Popen(
        [
            chrome,
            f"--user-data-dir={PROFILE_DIR}",
            "--start-maximized",
            "--new-window",
            url
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return proc

def setting_veo3_profile():
    if not os.path.exists(PROFILE_DIR):
        os.makedirs(PROFILE_DIR, exist_ok=True)

    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found")

    url = "https://labs.google/fx/vi/tools/flow"

    proc = subprocess.Popen(
        [
            chrome,
            f"--user-data-dir={PROFILE_DIR}",
            "--start-maximized",
            "--new-window",
            url
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return proc
if __name__ == "__main__":
    setting_grok_profile()
"""
Ẩn toàn bộ log (print + logging) khi SUPPRESS_ALL_LOGS bật trong settings.
"""
from __future__ import annotations

import builtins
import logging
from typing import Any

_ORIGINAL_PRINT = builtins.print
_suppress_all = False


def is_suppress_all_logs() -> bool:
    return _suppress_all


def set_suppress_all_logs(enabled: bool) -> None:
    global _suppress_all
    _suppress_all = bool(enabled)
    if _suppress_all:
        logging.disable(logging.CRITICAL)
    else:
        logging.disable(logging.NOTSET)


def _should_skip_dev_noise(msg: str) -> bool:
    return "Dev mode: Cannot update" in msg


def _patched_print(*args: Any, **kwargs: Any) -> None:
    if _suppress_all:
        return
    try:
        msg = " ".join(str(a) for a in args)
        if _should_skip_dev_noise(msg):
            return
    except Exception:
        pass
    return _ORIGINAL_PRINT(*args, **kwargs)


def install_print_hook() -> None:
    builtins.print = _patched_print


def load_suppress_from_settings() -> bool:
    """
    Load log suppression setting from config.
    DEFAULT: Always suppress logs (True) for customer builds.
    Only disable via frontend password-protected interface.
    """
    try:
        import json
        from utils.path_helper import CONFIG_FILE

        if not CONFIG_FILE.is_file():
            # No config file: default to SUPPRESSED (hidden logs)
            enabled = True
        else:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Default to True if key doesn't exist (always hide logs by default)
            enabled = bool(data.get("SUPPRESS_ALL_LOGS", True))
    except Exception:
        # On any error: default to SUPPRESSED (safe for customer builds)
        enabled = True

    set_suppress_all_logs(enabled)
    return enabled

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
    try:
        import os
        import json
        import sys
        
        # Determine config path
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
        else:
            exe_dir = os.path.dirname(os.path.abspath(__file__))
            exe_dir = os.path.dirname(exe_dir)  # Go up from utils to project root
        
        config_path = os.path.join(exe_dir, 'config', 'config.json')
        
        if not os.path.exists(config_path):
            enabled = False
        else:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            enabled = bool(data.get("SUPPRESS_ALL_LOGS", False))
    except Exception:
        enabled = False
    
    set_suppress_all_logs(enabled)
    return enabled

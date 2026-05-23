# Chức năng Bật/Tắt Log - Export sang dự án khác

## Tổng quan
Hệ thống này cho phép bật/tắt toàn bộ log (cả `print()` và `logging`) thông qua cấu hình `SUPPRESS_ALL_LOGS` trong settings.

## File cần copy

### 1. `backend/utils/log_suppress.py`
```python
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
        from services.config_loader import load_settings_data

        data = load_settings_data()
        enabled = bool(data.get("SUPPRESS_ALL_LOGS", False))
    except Exception:
        enabled = False
    set_suppress_all_logs(enabled)
    return enabled
```

## Cách tích hợp vào dự án mới

### Bước 1: Copy file
Copy file `log_suppress.py` vào thư mục utils của dự án mới.

### Bước 2: Thêm vào file main (entry point)
Thêm vào đầu file main.py (hoặc file khởi động chính):

```python
# Ẩn log (print + logging) khi SUPPRESS_ALL_LOGS bật
from utils.log_suppress import install_print_hook, load_suppress_from_settings

install_print_hook()

# ... các import khác ...

# Load cấu hình suppress từ settings
try:
    load_suppress_from_settings()
except Exception:
    pass
```

### Bước 3: Thêm cấu hình vào settings.json
Thêm key `SUPPRESS_ALL_LOGS` vào file settings:

```json
{
  "SUPPRESS_ALL_LOGS": false
}
```

- `false`: Hiện log bình thường
- `true`: Ẩn toàn bộ log (print + logging)

## Cách sử dụng

### Bật/tắt log runtime
```python
from utils.log_suppress import set_suppress_all_logs, is_suppress_all_logs

# Tắt log
set_suppress_all_logs(True)

# Bật log
set_suppress_all_logs(False)

# Kiểm tra trạng thái
if is_suppress_all_logs():
    print("Log đang bị tắt")
```

### Tùy chỉnh filter log nhiễu
Sửa hàm `_should_skip_dev_noise()` để lọc các log không mong muốn:

```python
def _should_skip_dev_noise(msg: str) -> bool:
    # Thêm các pattern cần skip
    skip_patterns = [
        "Dev mode: Cannot update",
        "polling request",
        "static media files"
    ]
    return any(pattern in msg for pattern in skip_patterns)
```

## Lưu ý

1. **Thứ tự quan trọng**: Phải gọi `install_print_hook()` TRƯỚC khi import các module khác
2. **Logging module**: Khi `SUPPRESS_ALL_LOGS=True`, logging sẽ disable ở level CRITICAL
3. **Print hook**: Tất cả `print()` sẽ đi qua `_patched_print()` để kiểm tra
4. **Thread-safe**: Biến `_suppress_all` là global, cần cẩn thận khi dùng multi-threading

## Ví dụ đầy đủ

```python
# main.py
import sys

# Bước 1: Install print hook NGAY ĐẦU TIÊN
from utils.log_suppress import install_print_hook, load_suppress_from_settings
install_print_hook()

# Bước 2: Import các module khác
import logging
from fastapi import FastAPI

# Bước 3: Load cấu hình
try:
    load_suppress_from_settings()
except Exception:
    pass

# Bước 4: Sử dụng bình thường
app = FastAPI()

@app.get("/")
def root():
    print("Hello World")  # Sẽ bị ẩn nếu SUPPRESS_ALL_LOGS=True
    logging.info("API called")  # Sẽ bị ẩn nếu SUPPRESS_ALL_LOGS=True
    return {"status": "ok"}
```

## Mở rộng

### Ghi log ra file thay vì ẩn
Nếu muốn ghi log ra file thay vì ẩn hoàn toàn:

```python
import logging
from pathlib import Path

def setup_file_logging(log_file: str = "app.log"):
    """Ghi log ra file thay vì console"""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Tắt console handler
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            # Không thêm StreamHandler để không in ra console
        ]
    )

# Sử dụng
setup_file_logging("logs/app.log")
```

### Chỉ ẩn một số module cụ thể
```python
def set_suppress_for_modules(module_names: list[str], suppress: bool = True):
    """Ẩn log của các module cụ thể"""
    level = logging.CRITICAL if suppress else logging.INFO
    for name in module_names:
        logging.getLogger(name).setLevel(level)

# Ví dụ: Chỉ ẩn log của uvicorn
set_suppress_for_modules(["uvicorn", "uvicorn.access"])
```

# Hướng dẫn Build EXE với Nuitka - Đóng gói ứng dụng Python

Hướng dẫn chi tiết cách đóng gói ứng dụng Python thành file EXE độc lập bằng Nuitka (compile sang C++), có thể chạy trên máy Windows mà không cần cài Python.

---

## 📋 Mục lục

1. [Giới thiệu Nuitka](#giới-thiệu-nuitka)
2. [Chuẩn bị](#chuẩn-bị)
3. [Cấu trúc dự án](#cấu-trúc-dự-án)
4. [Build với Nuitka](#build-với-nuitka)
5. [Troubleshooting](#troubleshooting)
6. [Đóng gói phân phối](#đóng-gói-phân-phối)

---

## 🚀 Giới thiệu Nuitka

**Nuitka** là Python compiler chuyển code Python sang C++, sau đó compile thành binary native. 

### Ưu điểm:
- ⚡ **Performance cao**: Nhanh hơn Python thuần 20-40%
- 🔒 **Bảo mật tốt**: Code được compile thành C++ binary, khó reverse engineer
- 📦 **Kích thước nhỏ**: Nhỏ hơn so với các công cụ đóng gói khác
- 🎯 **Tương thích tốt**: Hỗ trợ hầu hết các Python packages

### Nhược điểm:
- ⏱️ **Build chậm**: Mất 10-30 phút (lần đầu)
- 🛠️ **Yêu cầu C++ compiler**: Cần cài Visual Studio Build Tools trên Windows
- 📚 **Phức tạp hơn**: Cần config nhiều hơn so với các công cụ khác

---

## 🔧 Chuẩn bị

### 1. Cài đặt Nuitka

```bash
pip install nuitka
```

### 2. Cài đặt Visual Studio Build Tools (Windows)

Nuitka cần C++ compiler để hoạt động:

1. Download **Build Tools for Visual Studio** tại: https://visualstudio.microsoft.com/downloads/
2. Chạy installer và chọn: **"Desktop development with C++"**
3. Cài đặt (khoảng 6-8GB)

### 3. Kiểm tra cài đặt

```bash
# Kiểm tra Nuitka
python -m nuitka --version

# Kiểm tra MSVC compiler
python -m nuitka --msvc=latest --version
```

---

## 📁 Cấu trúc dự án

Dự án Python cần có cấu trúc rõ ràng để dễ build:

```
your-project/
├── backend/                 # Hoặc src/, app/, etc.
│   ├── main.py             # Entry point (file chính để chạy)
│   ├── config/             # Config files
│   ├── libs/               # Vendor libraries (nếu có)
│   ├── services/           # Business logic
│   └── requirements.txt
├── frontend/               # Frontend (nếu có)
│   └── .output/public/     # Static files đã build
├── logo.ico                # Icon cho EXE (optional)
└── build_fast_c++.py       # Script build Nuitka
```

### Lưu ý:
- **Entry point**: File Python chính để chạy app (ví dụ: `main.py`, `app.py`, `run.py`)
- **Frontend**: Nếu có frontend (React, Vue, etc.), cần build thành static files trước
- **Config files**: Các file config, templates, data cần copy vào dist sau khi build

---

## ⚡ Build với Nuitka

### Script Build: `build_fast_c++.py`

Tạo file `build_fast_c++.py` trong thư mục gốc dự án:

```python
import os
import sys
import shutil
import subprocess
from pathlib import Path

# ================== CẤU HÌNH - CHỈNH SỬA PHẦN NÀY ==================
APP_NAME = "YourApp"                    # Tên ứng dụng
ENTRY_POINT = Path("backend/main.py")   # File Python chính để chạy
ICON_PATH = Path("logo.ico")            # Icon cho EXE (optional)

# Thư mục chứa code
SOURCE_DIR = Path("backend")            # Hoặc src/, app/, etc.

# Thư mục output
DIST_ROOT = Path("dist")
DIST_DIR = DIST_ROOT / APP_NAME

# Frontend static files (nếu có)
FRONTEND_OUTPUT = Path("frontend/.output/public")  # Hoặc None nếu không có

# Config files cần copy (nếu có)
CONFIG_DIRS = ["config"]                # Danh sách thư mục config

# Storage folders cần tạo (nếu có)
STORAGE_DIRS = ["storage/config"]       # Danh sách thư mục storage

# ================== BUILD FLAGS ==================
DEV_MODE = "--dev" in sys.argv          # Build nhanh, giữ cache
RELEASE_MODE = "--release" in sys.argv  # Build tối ưu (LTO)
CLEAN_BUILD = "--clean" in sys.argv     # Xóa cache, build từ đầu

# ================== PACKAGES KHÔNG COMPILE ==================
# Các package nặng hoặc có vấn đề khi compile sang C++
# Giữ nguyên dạng Python bytecode (.pyc)
NOFOLLOW_PACKAGES = [
    "google",
    "pyasn1",
    "PIL",
    "proto*",
    "grpc*",
    "pydantic*",
    "httpx*",
    "httpcore*",
    "anyio*",
    "websockets*",
]

# ================== PACKAGES CẦN INCLUDE ==================
# Các package cần thiết cho app
INCLUDE_PACKAGES = [
    "uvicorn",
    "fastapi",
    # Thêm các package khác nếu cần
]

# ================== CLEAN ==================
def clean_old_build():
    if DEV_MODE and not CLEAN_BUILD:
        print("[CLEAN] DEV MODE → Skip clean to reuse cache")
        return

    print("[CLEAN] Cleaning old build...")
    for p in ["build", "dist"]:
        if Path(p).exists():
            shutil.rmtree(p)
            print(f"   [OK] Removed {p}/")

# ================== NUITKA BUILD ==================
def run_nuitka():
    print("[BUILD] Running Nuitka (C++ Compilation)...")

    if not ENTRY_POINT.exists():
        raise RuntimeError(f"❌ Entry point không tồn tại: {ENTRY_POINT}")

    # Base command
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--msvc=latest",           # Dùng Visual Studio compiler
        "--jobs=4",                # Số CPU cores (điều chỉnh theo máy)
        "--low-memory",            # Giảm RAM usage
        
        # Output
        "--output-dir=dist",
        f"--output-filename={APP_NAME}.exe",
    ]

    # Plugins
    cmd.append("--enable-plugin=tk-inter")

    # Không compile các package nặng
    for pkg in NOFOLLOW_PACKAGES:
        cmd.append(f"--nofollow-import-to={pkg}")

    # Include packages cần thiết
    for pkg in INCLUDE_PACKAGES:
        cmd.append(f"--include-package={pkg}")

    # Icon
    if ICON_PATH.exists():
        cmd.append(f"--windows-icon-from-ico={ICON_PATH}")
        print(f"   [OK] Using icon: {ICON_PATH}")

    # Release mode: LTO optimization
    if RELEASE_MODE:
        print("   [MODE] RELEASE (LTO enabled)")
        cmd.append("--lto=yes")
        cmd.append("--remove-output")
    else:
        print("   [MODE] DEV FAST BUILD")

    # Entry point
    cmd.append(str(ENTRY_POINT))

    # Setup environment
    env = os.environ.copy()
    
    # PYTHONPATH để Nuitka tìm thấy modules
    pythonpath_parts = [str(SOURCE_DIR)]
    libs_dir = SOURCE_DIR / "libs"
    if libs_dir.exists():
        pythonpath_parts.append(str(libs_dir))
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    
    # Tăng compiler heap để tránh lỗi C1002
    extra_cl = "/Zm300"
    env["CL"] = (env.get("CL", "") + " " + extra_cl).strip()
    env["_CL_"] = (env.get("_CL_", "") + " " + extra_cl).strip()

    # Run Nuitka
    print(f"   [CMD] {' '.join(cmd[:5])} ...")
    subprocess.run(cmd, check=True, env=env)

    # Normalize output
    nuitka_dist = None
    for d in DIST_ROOT.iterdir():
        if d.is_dir() and d.suffix == ".dist":
            nuitka_dist = d
            break

    if nuitka_dist is None:
        raise RuntimeError("❌ Không tìm thấy output .dist của Nuitka")

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)

    shutil.move(str(nuitka_dist), DIST_DIR)

    # Rename exe
    for exe in DIST_DIR.glob("*.exe"):
        exe.rename(DIST_DIR / f"{APP_NAME}.exe")

    print(f"   [OK] Nuitka output ready: {DIST_DIR}")

# ================== COPY RESOURCES ==================
def copy_resources():
    print("[BUILD] Copying resources...")

    # 1. Config directories
    for config_dir in CONFIG_DIRS:
        src = SOURCE_DIR / config_dir
        dst = DIST_DIR / config_dir
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"   [OK] {config_dir}/")

    # 2. Frontend static files
    if FRONTEND_OUTPUT and FRONTEND_OUTPUT.exists():
        dst = DIST_DIR / "static"
        shutil.copytree(FRONTEND_OUTPUT, dst, dirs_exist_ok=True)
        print("   [OK] static/")
    elif FRONTEND_OUTPUT:
        print(f"   [WARN] Frontend output not found: {FRONTEND_OUTPUT}")

    # 3. Storage directories
    for storage_dir in STORAGE_DIRS:
        (DIST_DIR / storage_dir).mkdir(parents=True, exist_ok=True)
    if STORAGE_DIRS:
        print(f"   [OK] Created storage dirs: {len(STORAGE_DIRS)}")

    print("\n[SUCCESS] BUILD COMPLETED")
    print(f"Executable: {DIST_DIR / (APP_NAME + '.exe')}")
    print(f"Folder: {DIST_DIR}")

# ================== MAIN ==================
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  BUILD {APP_NAME} WITH NUITKA")
    print(f"{'='*60}\n")

    try:
        clean_old_build()
        run_nuitka()
        copy_resources()
    except Exception as e:
        print(f"\n❌ BUILD FAILED: {e}")
        sys.exit(1)
```

### Cách sử dụng:

```bash
# 1. Chỉnh sửa phần CẤU HÌNH trong build_fast_c++.py
#    - APP_NAME: Tên ứng dụng
#    - ENTRY_POINT: File Python chính
#    - SOURCE_DIR: Thư mục chứa code
#    - FRONTEND_OUTPUT: Thư mục frontend (nếu có)
#    - CONFIG_DIRS: Các thư mục config cần copy

# 2. Build frontend (nếu có)
cd frontend
npm install
npm run generate  # Hoặc npm run build

# 3. Build EXE
cd ..
python build_fast_c++.py

# Build modes:
python build_fast_c++.py --dev       # Dev mode (nhanh, giữ cache)
python build_fast_c++.py --release   # Release mode (tối ưu LTO)
python build_fast_c++.py --clean     # Clean build (xóa cache)
```

### Kết quả:

```
dist/
└── YourApp/
    ├── YourApp.exe      # File thực thi chính
    ├── config/          # Config files
    ├── static/          # Frontend files (nếu có)
    ├── storage/         # Storage folders
    └── *.dll, *.pyd     # Dependencies
```

---

## 🔍 Troubleshooting

### 1. Lỗi "Module not found" khi chạy EXE

**Nguyên nhân:** Nuitka không tự động detect module

**Giải pháp:**
```python
# Thêm vào INCLUDE_PACKAGES trong build script
INCLUDE_PACKAGES = [
    "uvicorn",
    "fastapi",
    "your_missing_module",  # Thêm module bị thiếu
]
```

### 2. Lỗi "C1002: out of heap space"

**Nguyên nhân:** Compiler hết RAM khi compile module lớn

**Giải pháp:**
```python
# Đã có trong script, tăng giá trị nếu vẫn lỗi
extra_cl = "/Zm500"  # Tăng từ 300 lên 500
```

Hoặc không compile module đó:
```python
NOFOLLOW_PACKAGES = [
    "large_module",  # Thêm module gây lỗi
]
```

### 3. Lỗi "Failed to execute script" khi chạy EXE

**Nguyên nhân:** Thiếu data files (config, templates, etc.)

**Giải pháp:**
```python
# Thêm vào CONFIG_DIRS
CONFIG_DIRS = ["config", "templates", "data"]
```

### 4. EXE chạy chậm lúc khởi động

**Nguyên nhân:** Import quá nhiều packages nặng

**Giải pháp:**
- Lazy import: Import module khi cần dùng, không import ở đầu file
- Thêm vào NOFOLLOW_PACKAGES các package không cần compile

### 5. Antivirus chặn EXE

**Nguyên nhân:** False positive (EXE mới, chưa có reputation)

**Giải pháp:**
- **Code signing certificate** (khuyến nghị cho production)
- Whitelist trong antivirus
- Upload lên VirusTotal để các antivirus học

### 6. Lỗi import khi dùng vendor libs

**Nguyên nhân:** Nuitka không tìm thấy libs trong thư mục tùy chỉnh

**Giải pháp:** Script đã xử lý tự động qua PYTHONPATH. Nếu vẫn lỗi:
```python
# Thêm vào INCLUDE_PACKAGES
INCLUDE_PACKAGES = [
    "your_vendor_lib",
]
```

### 7. Build quá chậm

**Giải pháp:**
```bash
# Dùng dev mode để giữ cache
python build_fast_c++.py --dev

# Tăng số CPU cores
# Sửa trong script: --jobs=8 (thay vì 4)
```

---

## 📦 Đóng gói phân phối

### 1. Tạo ZIP cho GitHub Release

```python
# Thêm vào cuối build_fast_c++.py
import zipfile

def create_release_zip():
    zip_name = f"{APP_NAME}_v1.0.0.zip"
    print(f"\n[ZIP] Creating {zip_name}...")
    
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(DIST_DIR):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(DIST_DIR.parent)
                zipf.write(file_path, arcname)
    
    print(f"   [OK] Created: {zip_name}")

# Gọi sau copy_resources()
create_release_zip()
```

### 2. Tạo Installer với NSIS

Tạo file `installer.nsi`:

```nsis
; installer.nsi
!define APP_NAME "YourApp"
!define VERSION "1.0.0"
!define PUBLISHER "Your Company"

Name "${APP_NAME}"
OutFile "${APP_NAME}_Setup_${VERSION}.exe"
InstallDir "$PROGRAMFILES\${APP_NAME}"

Section "Install"
    SetOutPath "$INSTDIR"
    File /r "dist\${APP_NAME}\*.*"
    
    ; Tạo shortcuts
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_NAME}.exe"
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_NAME}.exe"
    
    ; Uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\*.*"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\${APP_NAME}\*.*"
    RMDir "$SMPROGRAMS\${APP_NAME}"
    Delete "$DESKTOP\${APP_NAME}.lnk"
SectionEnd
```

Build installer:
```bash
# Cài NSIS: https://nsis.sourceforge.io/
makensis installer.nsi
```

---

## 🎯 Checklist Build Production

- [ ] Cài đặt Nuitka và Visual Studio Build Tools
- [ ] Chỉnh sửa cấu hình trong `build_fast_c++.py`
- [ ] Build frontend (nếu có): `npm run generate`
- [ ] Test app locally trước khi build
- [ ] Chuẩn bị icon (.ico file)
- [ ] Build EXE: `python build_fast_c++.py --release`
- [ ] Test EXE trên máy sạch (không có Python)
- [ ] Tạo ZIP hoặc Installer
- [ ] Upload lên GitHub Release
- [ ] Test auto-update (nếu có)

---

## 📚 Tài liệu thêm

- [Nuitka Documentation](https://nuitka.net/)
- [Nuitka User Manual](https://nuitka.net/doc/user-manual.html)
- [NSIS Documentation](https://nsis.sourceforge.io/)

---

## 💡 Tips

### Tối ưu build time:
- Dùng `--dev` mode khi đang phát triển
- Chỉ dùng `--release` khi build cuối cùng
- Tăng `--jobs` nếu máy có nhiều CPU cores

### Tối ưu kích thước:
- Thêm các package không cần thiết vào `NOFOLLOW_PACKAGES`
- Xóa các file không cần trong dist sau khi build

### Tối ưu performance:
- Dùng `--lto=yes` trong release mode
- Profile code để tìm bottleneck trước khi build

---

**Phiên bản**: 2.0  
**Cập nhật**: 2026-05-23

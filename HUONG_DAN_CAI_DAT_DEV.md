# Hướng dẫn Cài đặt và Build Project - Video Creator

Hướng dẫn chi tiết để dev có thể setup môi trường, chạy source code và build thành file EXE với Nuitka.

---

## 📋 Mục lục

1. [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
2. [Cài đặt môi trường](#cài-đặt-môi-trường)
3. [Clone và setup project](#clone-và-setup-project)
4. [Chạy project từ source](#chạy-project-từ-source)
5. [Build EXE với Nuitka](#build-exe-với-nuitka)
6. [Troubleshooting](#troubleshooting)

---

## 🖥️ Yêu cầu hệ thống

### Phần cứng tối thiểu:
- **CPU**: 4 cores trở lên (khuyến nghị 8 cores cho build nhanh)
- **RAM**: 8GB (khuyến nghị 16GB)
- **Ổ cứng**: 15GB trống (cho Visual Studio Build Tools + dependencies)

### Hệ điều hành:
- **Windows 10/11** (64-bit)

### Phần mềm cần cài:
- Python 3.9 - 3.11 (khuyến nghị Python 3.10)
- Git
- Google Chrome (để tạo video với Grok/Veo3)
- Visual Studio Build Tools (cho Nuitka)

---

## 🔧 Cài đặt môi trường

### Bước 1: Cài đặt Python

1. Download Python từ: https://www.python.org/downloads/
2. **Quan trọng**: Tick vào "Add Python to PATH" khi cài đặt
3. Kiểm tra cài đặt:

```bash
python --version
# Kết quả: Python 3.10.x hoặc tương tự

pip --version
# Kết quả: pip 23.x.x
```

### Bước 2: Cài đặt Git

1. Download Git từ: https://git-scm.com/download/win
2. Cài đặt với cấu hình mặc định
3. Kiểm tra:

```bash
git --version
# Kết quả: git version 2.x.x
```

### Bước 3: Cài đặt Visual Studio Build Tools (Quan trọng cho Nuitka!)

Nuitka cần C++ compiler để compile Python sang C++.

1. Download **Build Tools for Visual Studio 2022** từ:
   https://visualstudio.microsoft.com/downloads/
   
   Hoặc link trực tiếp:
   https://aka.ms/vs/17/release/vs_BuildTools.exe

2. Chạy installer và chọn:
   - ✅ **"Desktop development with C++"**
   - ✅ **"MSVC v143 - VS 2022 C++ x64/x86 build tools"**
   - ✅ **"Windows 10/11 SDK"**

3. Cài đặt (khoảng 6-8GB, mất 15-30 phút)

4. Khởi động lại máy sau khi cài xong

5. Kiểm tra:

```bash
# Mở Command Prompt mới và chạy:
python -m nuitka --msvc=latest --version
# Nếu thấy version của Nuitka là OK
```

### Bước 4: Cài đặt Google Chrome

1. Download từ: https://www.google.com/chrome/
2. Cài đặt bình thường
3. Chrome cần thiết để Playwright tạo video với Grok/Veo3

---

## 📦 Clone và Setup Project

### Bước 1: Clone source code

```bash
# Tạo thư mục làm việc
mkdir D:\Projects
cd D:\Projects

# Clone repository
git clone https://github.com/dinorap/video_ai.git
cd video_ai
```

### Bước 2: Tạo Virtual Environment (khuyến nghị)

```bash
# Tạo virtual environment
python -m venv venv

# Kích hoạt virtual environment
# Trên Windows Command Prompt:
venv\Scripts\activate.bat

# Trên Windows PowerShell:
venv\Scripts\Activate.ps1

# Sau khi activate, prompt sẽ có (venv) ở đầu
```

**Lưu ý PowerShell**: Nếu gặp lỗi "cannot be loaded because running scripts is disabled", chạy:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Bước 3: Cài đặt dependencies

```bash
# Upgrade pip trước
python -m pip install --upgrade pip

# Cài đặt tất cả packages từ requirements.txt
pip install -r requirements.txt

# Cài đặt Playwright browsers
playwright install chromium
```

**Giải thích các packages chính:**
- `flask`: Web framework cho backend
- `playwright`: Automation browser để tạo video
- `nuitka`: Compiler Python sang C++ để build EXE
- `aiohttp`, `requests`: HTTP clients
- `customtkinter`: GUI cho license activation
- `dinorap-updater`: Auto-update system

### Bước 4: Cấu hình project

```bash
# Copy file config mẫu
copy config\config.dist.json config\config.json

# Tạo các thư mục cần thiết (nếu chưa có)
mkdir generated
mkdir temp_video
mkdir tmp_uploads
mkdir storage\projects
```

**Chỉnh sửa config** (nếu cần):
- Mở `config/config.json` bằng text editor
- Điều chỉnh các settings theo nhu cầu

---

## 🚀 Chạy Project từ Source

### Chạy development server:

```bash
# Đảm bảo đang ở thư mục gốc của project
# Và virtual environment đã được activate (nếu dùng)

python app.py
```

**Kết quả mong đợi:**
```
[BUILD] Bootstrap Nuitka toolchain (auto Yes)...
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment.
 * Running on http://127.0.0.1:5000
Press CTRL+C to quit
```

### Truy cập ứng dụng:

1. Mở trình duyệt
2. Vào địa chỉ: http://127.0.0.1:5000
3. Giao diện web sẽ hiển thị

### Dừng server:

- Nhấn `Ctrl + C` trong terminal

---

## 🏗️ Build EXE với Nuitka

### Build modes:

Project có 3 chế độ build:

1. **Dev mode** (nhanh, giữ cache):
```bash
python build_fast_c++.py
# Hoặc
python build_fast_c++.py --dev
```

2. **Release mode** (tối ưu, có LTO):
```bash
python build_fast_c++.py --release
```

3. **Clean build** (xóa cache, build từ đầu):
```bash
python build_fast_c++.py --clean
# Hoặc kết hợp
python build_fast_c++.py --release --clean
```

### Quy trình build đầy đủ:

```bash
# 1. Build EXE (lần đầu mất 15-30 phút)
python build_fast_c++.py --release --clean

# 2. Đóng gói thành ZIP cho phân phối
python pack_release_update.py
```

### Kết quả sau khi build:

```
dist/
└── VideoCreator/
    ├── VideoCreator.exe          # File thực thi chính
    ├── config/                   # Config files
    │   ├── config.json
    │   ├── config.dist.json
    │   ├── ffmpeg_effects.json
    │   └── ...
    ├── templaces/                # HTML/CSS/JS templates
    ├── ico/                      # Icons
    ├── tools/                    # FFmpeg và tools khác
    ├── generated/                # Thư mục output
    ├── temp_video/               # Thư mục temp
    ├── HUONG_DAN.txt            # Hướng dẫn sử dụng
    └── *.dll, *.pyd             # Dependencies
```

### Chạy EXE sau khi build:

```bash
# Chạy trực tiếp
dist\VideoCreator\VideoCreator.exe

# Hoặc double-click vào file EXE
```

### Đóng gói để phân phối:

```bash
# Tạo VideoCreator.zip và update.json
python pack_release_update.py
```

Kết quả:
- `VideoCreator.zip`: Toàn bộ thư mục dist/VideoCreator (không bao gồm config và storage)
- `update.json`: Metadata cho auto-update

---

## 🔍 Troubleshooting

### 1. Lỗi "Python was not found"

**Nguyên nhân**: Python chưa được thêm vào PATH

**Giải pháp**:
- Cài lại Python và tick "Add Python to PATH"
- Hoặc thêm Python vào PATH thủ công:
  1. Tìm đường dẫn Python (thường là `C:\Users\<username>\AppData\Local\Programs\Python\Python310`)
  2. Thêm vào System Environment Variables → PATH

### 2. Lỗi "pip install" thất bại

**Nguyên nhân**: Pip cũ hoặc network issue

**Giải pháp**:
```bash
# Upgrade pip
python -m pip install --upgrade pip

# Nếu vẫn lỗi, thử cài từng package:
pip install flask
pip install playwright
pip install nuitka
# ...
```

### 3. Lỗi "playwright install" thất bại

**Giải pháp**:
```bash
# Cài lại Playwright
pip uninstall playwright
pip install playwright

# Cài browser với quyền admin
playwright install chromium --with-deps
```

### 4. Lỗi Nuitka "MSVC not found"

**Nguyên nhân**: Chưa cài Visual Studio Build Tools

**Giải pháp**:
- Cài Visual Studio Build Tools theo Bước 3 ở trên
- Khởi động lại máy sau khi cài
- Kiểm tra lại: `python -m nuitka --msvc=latest --version`

### 5. Lỗi "C1002: out of heap space" khi build

**Nguyên nhân**: Compiler hết RAM

**Giải pháp**: Script đã tự động xử lý bằng cách set `/Zm300`. Nếu vẫn lỗi:
- Đóng các ứng dụng khác để giải phóng RAM
- Hoặc sửa trong `build_fast_c++.py`, dòng 146:
```python
extra_cl = "/Zm500"  # Tăng từ 300 lên 500
```

### 6. Build quá chậm

**Giải pháp**:
```bash
# Dùng dev mode để giữ cache (nhanh hơn nhiều lần sau)
python build_fast_c++.py --dev

# Tăng số CPU cores trong build_fast_c++.py, dòng 35:
JOBS = max(1, min(16, (os.cpu_count() or 4)))  # Tăng từ 8 lên 16
```

### 7. EXE không chạy được trên máy khác

**Nguyên nhân**: Thiếu Visual C++ Redistributable

**Giải pháp**:
- Cài **Visual C++ Redistributable** trên máy đích:
  https://aka.ms/vs/17/release/vc_redist.x64.exe

### 8. Lỗi "Module not found" khi chạy EXE

**Nguyên nhân**: Nuitka không tự động detect module

**Giải pháp**: Thêm module vào `INCLUDE_MODULES` trong `build_fast_c++.py`:
```python
INCLUDE_MODULES = [
    # ... các module hiện có
    "your_missing_module",  # Thêm module bị thiếu
]
```

### 9. Port 5000 đã được sử dụng

**Giải pháp**:
```bash
# Tìm process đang dùng port 5000
netstat -ano | findstr :5000

# Kill process (thay <PID> bằng số PID tìm được)
taskkill /PID <PID> /F

# Hoặc đổi port trong app.py (cuối file):
# app.run(host="0.0.0.0", port=5001)  # Đổi từ 5000 sang 5001
```

---

## 📚 Cấu trúc Project

```
web_creat_video/
├── app.py                          # Entry point chính
├── build_fast_c++.py              # Script build Nuitka
├── pack_release_update.py         # Script đóng gói release
├── requirements.txt               # Python dependencies
├── version.py                     # Version info
│
├── config/                        # Config files
│   ├── config.json               # Config chính
│   ├── config.dist.json          # Config mẫu
│   ├── ffmpeg_effects.json       # FFmpeg effects
│   └── veo_auth.json             # Veo3 authentication
│
├── utils/                         # Utilities
│   ├── control_creat_video.py    # Video creation logic
│   ├── control_creat_video_veo3.py
│   ├── control_ffmpeg.py         # FFmpeg wrapper
│   ├── control_music.py          # Music handling
│   ├── control_script.py         # Script generation
│   ├── path_helper.py            # Path management
│   ├── license_service.py        # License system
│   └── ...
│
├── templaces/                     # Frontend templates
│   ├── html/
│   ├── css/
│   └── js/
│
├── ico/                          # Icons và assets
├── generated/                    # Output videos
├── temp_video/                   # Temporary files
└── dist/                         # Build output (sau khi build)
```

---

## 🎯 Workflow Phát triển

### 1. Development (code và test):
```bash
# Activate venv
venv\Scripts\activate

# Chạy dev server
python app.py

# Code và test trên http://127.0.0.1:5000
```

### 2. Build và test EXE:
```bash
# Build dev (nhanh)
python build_fast_c++.py --dev

# Test EXE
dist\VideoCreator\VideoCreator.exe
```

### 3. Release:
```bash
# Build release (tối ưu)
python build_fast_c++.py --release --clean

# Đóng gói
python pack_release_update.py

# Upload VideoCreator.zip và update.json lên GitHub Release
```

---

## 💡 Tips

### Tăng tốc development:
- Dùng virtual environment để tránh conflict packages
- Dùng `--dev` mode khi build để giữ cache
- Chỉ dùng `--release --clean` khi build cuối cùng

### Tối ưu build time:
- Lần đầu build mất 15-30 phút (download compiler, compile)
- Lần sau chỉ mất 2-5 phút nếu dùng `--dev` (giữ cache)
- Tăng `JOBS` trong build script nếu máy có nhiều CPU cores

### Debug:
- Check logs trong terminal khi chạy `python app.py`
- Check browser console (F12) để debug frontend
- Dùng `print()` để debug Python code

---

## 📞 Liên hệ & Hỗ trợ

- **GitHub**: https://github.com/dinorap/video_ai
- **Issues**: https://github.com/dinorap/video_ai/issues

---

## ✅ Checklist Setup

- [ ] Cài Python 3.10
- [ ] Cài Git
- [ ] Cài Visual Studio Build Tools (Desktop development with C++)
- [ ] Cài Google Chrome
- [ ] Clone repository
- [ ] Tạo virtual environment
- [ ] Cài dependencies: `pip install -r requirements.txt`
- [ ] Cài Playwright browsers: `playwright install chromium`
- [ ] Copy config: `copy config\config.dist.json config\config.json`
- [ ] Test chạy: `python app.py`
- [ ] Test build: `python build_fast_c++.py --dev`

---

**Phiên bản**: 1.0  
**Cập nhật**: 2026-05-26  
**Tác giả**: Video Creator Team

# VideoCreator — Build & GitHub OTA

## Build

```powershell
python build_fast_c++.py --dev
python build_fast_c++.py --release --clean --zip
```

## Upload GitHub Release

1. Sửa `version.py` → `CURRENT_VERSION = "v1.0.2"`
2. `python build_fast_c++.py --release --clean --zip`
3. https://github.com/dinorap/video-release/releases/new
4. Tag = `v1.0.2`
5. Upload **cả hai**:
   - `VideoCreator.zip` (nội dung `dist/VideoCreator`, không có `config/`)
   - `update.json` (SHA256, tự tạo khi `--zip`)

## Cách update trên máy khách

Nút **Cập nhật** → tải ZIP + verify `update.json` → **xcopy ghi đè**:

- File có trong bản mới → thay file cũ
- File chỉ có trên máy (vd `xinchao1.md`) → **giữ nguyên**
- `config/` không nằm trong ZIP → **giữ cấu hình user**

Không dùng `update.exe`.

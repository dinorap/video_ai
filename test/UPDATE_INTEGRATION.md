# Code Update qua GitHub - Tích hợp hoàn tất

Dự án đã được tích hợp tính năng **tự động update qua GitHub releases**.

## ✅ Đã tích hợp

### Backend (Python/Flask)
- ✅ Thêm `dinorap-updater` vào `requirements.txt`
- ✅ Khởi tạo `OTAUpdater` trong `app.py` với config:
  - GitHub User: `dinorap`
  - GitHub Repo: `video-release`
  - Current Version: `v1.0.0`
  - Update ZIP Name: `VideoCreator.zip`
- ✅ Mount updater router tại `/api/update/*`
- ✅ Thêm endpoint `/api/version` để lấy version hiện tại
- ✅ Thêm endpoint `/api/debug/runtime` để debug
- ✅ Exception handler cho Access Denied errors
- ✅ Fix cho Nuitka (set `sys.frozen = True`)
- ✅ Patch để chọn đúng ZIP file trong release

### Frontend (HTML/JavaScript)
- ✅ Thêm nút "Cập nhật" vào header (ẩn mặc định)
- ✅ Hiển thị version trong sidebar
- ✅ Tạo `updater.js` với UpdaterClient class
- ✅ Auto-check update mỗi 60 phút
- ✅ UI dialog đẹp với progress bar
- ✅ Tự động restart sau khi update

## 📦 Cài đặt Dependencies

### Backend
```bash
pip install -r requirements.txt
```

### Frontend
Không cần cài đặt thêm (sử dụng vanilla JavaScript)

## 🚀 Cách sử dụng

### 1. Tạo GitHub Release

1. Vào repository: https://github.com/dinorap/video-release
2. Tạo release mới với tag version (ví dụ: `v1.0.1`)
3. Upload file ZIP build của app với tên **chính xác**: `VideoCreator.zip`
4. Publish release

### 2. Cấu trúc file ZIP

File `VideoCreator.zip` phải chứa toàn bộ app đã build:

```
VideoCreator.zip
├── VideoCreator.exe
├── templaces/
├── utils/
├── config/
├── ico/
└── ... (các file khác)
```

### 3. Update flow

1. User mở app → Auto-check update mỗi 60 phút
2. Nếu có update mới → Hiển thị nút "Cập nhật" ở header
3. User click "Cập nhật" → Hiển thị dialog với release notes
4. User click "Cập nhật ngay" → `POST /api/update/perform`
5. Tải `VideoCreator.zip` + verify SHA256 từ `update.json`
6. **xcopy ghi đè** (file có trong ZIP mới thay file cũ; file chỉ có trên máy được giữ)
7. Restart app tự động

**Không dùng `update.exe`.**

## 🔧 Cấu hình

### Thay đổi version hiện tại

Trong `app.py`, dòng 18:
```python
CURRENT_VERSION = "v1.0.0"  # Thay đổi version ở đây
```

### Thay đổi tên file ZIP

Trong `app.py`, dòng 19:
```python
UPDATE_ZIP_NAME = "VideoCreator.zip"  # Thay đổi tên ZIP ở đây
```

### Thay đổi GitHub repo

Trong `app.py`, dòng 24-26:
```python
updater = OTAUpdater(
    github_user="dinorap",
    github_repo="video-release",  # Thay đổi repo ở đây
    current_version=CURRENT_VERSION
)
```

### Thay đổi tần suất check update

Trong `templaces/js/updater.js`, dòng 238:
```javascript
window.updaterClient.startAutoCheck(60);  // 60 phút
```

## 🔑 API Endpoints

Backend cung cấp các endpoints sau:

- `GET /api/version` - Lấy version hiện tại
- `GET /api/update/check` - Check có update mới không
- `POST /api/update/perform` - Tải, verify, xcopy merge, restart
- `GET /api/debug/runtime` - Debug info (exe path, cwd, frozen status)

### Build & upload release

```powershell
python build_fast_c++.py --release --clean --zip
```

Upload lên GitHub: `VideoCreator.zip` + `update.json` (cùng tag `version.py`).

## ⚠️ Lưu ý quan trọng

1. **GitHub Token**: Nếu repo private, cần config GitHub token trong environment variable `GITHUB_TOKEN`
2. **Permissions**: App cần quyền ghi file để update (chạy với quyền admin nếu cần)
3. **Antivirus**: Một số antivirus có thể block auto-update, cần whitelist app
4. **Testing**: Test kỹ trên môi trường production trước khi release
5. **Rollback**: Nên có cơ chế backup version cũ để rollback nếu cần
6. **ZIP Name**: Tên file ZIP trong release **phải khớp chính xác** với `UPDATE_ZIP_NAME`

## 🐛 Troubleshooting

### Update không hoạt động
1. Check console log để xem error
2. Kiểm tra `/api/debug/runtime` để xác nhận `frozen: true`
3. Kiểm tra tên file ZIP trong release có đúng không
4. Kiểm tra version tag có đúng format `vX.Y.Z` không

### Access Denied error
- Đóng app hoàn toàn
- Chờ vài giây
- Chạy lại app và thử update

### Update không tự động restart
- Kiểm tra app có quyền ghi file không
- Kiểm tra antivirus có block không

## 📚 Tài liệu thêm

- [dinorap-updater GitHub](https://github.com/dinorap/dinorap-updater)
- [video-release GitHub](https://github.com/dinorap/video-release)

## 🎯 Checklist tích hợp

- [x] Cài đặt dependencies backend
- [x] Thêm code vào `app.py`
- [x] Tạo `updater.js`
- [x] Thêm nút update vào header
- [x] Hiển thị version trong sidebar
- [x] Config GitHub repo
- [ ] Tạo GitHub releases repository (nếu chưa có)
- [ ] Test update flow
- [ ] Build và upload release đầu tiên

---

**Tác giả**: Integrated by Kiro AI  
**Ngày tạo**: 2026-05-23  
**Dự án**: web_creat_video  
**GitHub Releases**: https://github.com/dinorap/video-release

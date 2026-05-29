# HƯỚNG DẪN TẠO BẢN CẬP NHẬT (UPDATE)

Tài liệu này hướng dẫn cách tạo file update để phát hành phiên bản mới của VideoCreator.

---

## 📋 CHUẨN BỊ

Trước khi bắt đầu, đảm bảo:
- ✅ Đã cài đặt Python và các thư viện cần thiết
- ✅ Code đã được test kỹ và hoạt động ổn định
- ✅ Đã commit tất cả thay đổi vào Git

---

## 🚀 CÁC BƯỚC THỰC HIỆN

### **BƯỚC 1: Cập nhật số phiên bản**

Mở file `version.py` và thay đổi số phiên bản:

```python
CURRENT_VERSION = "v1.0.7"  # Thay đổi từ v1.0.6 -> v1.0.7
```

**Lưu ý:** 
- Tăng số phiên bản theo quy tắc: v1.0.6 → v1.0.7 → v1.0.8...
- Với thay đổi lớn: v1.0.9 → v1.1.0 hoặc v2.0.0

---

### **BƯỚC 2: Build ứng dụng**

Mở Terminal/Command Prompt tại thư mục dự án và chạy lệnh:

```bash
python build_fast_c++.py --dev
```

**Giải thích:**
- Lệnh này sẽ build ứng dụng thành file exe
- Kết quả được lưu trong thư mục `dist/VideoCreator/`
- Quá trình build có thể mất 5-15 phút tùy máy

**Nếu muốn build bản release chính thức (tối ưu hơn):**
```bash
python build_fast_c++.py --release --clean
```

---

### **BƯỚC 3: Đóng gói file update**

Sau khi build xong, chạy lệnh:

```bash
python pack_release_update.py
```

**Hoặc thêm mô tả phiên bản:**
```bash
python pack_release_update.py --log "Sửa lỗi X, thêm tính năng Y"
```

**Kết quả:**
- ✅ File `VideoCreator.zip` - chứa toàn bộ ứng dụng
- ✅ File `update.json` - chứa thông tin phiên bản và mã hash

**Ví dụ nội dung `update.json`:**
```json
{
    "version": "v1.0.7",
    "sha256": "abc123def456...",
    "release_date": "2026-05-27",
    "update_log": "Sửa lỗi X, thêm tính năng Y"
}
```

---

### **BƯỚC 4: Upload lên GitHub Release**

1. **Truy cập trang Release:**
   ```
   https://github.com/dinorap/video-release/releases
   ```

2. **Tạo Release mới:**
   - Click nút **"Draft a new release"**
   - **Tag version:** Nhập đúng version (ví dụ: `v1.0.7`)
   - **Release title:** Nhập tiêu đề (ví dụ: `VideoCreator v1.0.7`)
   - **Description:** Mô tả các thay đổi trong phiên bản này

3. **Upload 2 file:**
   - 📦 `VideoCreator.zip`
   - 📄 `update.json`

4. **Publish Release:**
   - Click nút **"Publish release"**
   - ✅ Hoàn tất!

---

## 📝 CHECKLIST TRƯỚC KHI RELEASE

- [ ] Đã test kỹ ứng dụng
- [ ] Đã cập nhật số version trong `version.py`
- [ ] Đã build thành công (không có lỗi)
- [ ] Đã tạo file `VideoCreator.zip` và `update.json`
- [ ] Đã kiểm tra nội dung file `update.json` (version đúng)
- [ ] Đã upload 2 file lên GitHub Release
- [ ] Đã test tính năng auto-update từ phiên bản cũ

---

## ⚠️ LƯU Ý QUAN TRỌNG

1. **Số phiên bản phải tăng dần:** Không được giảm hoặc trùng với phiên bản cũ
2. **Tag phải khớp với version:** Tag `v1.0.7` phải khớp với `CURRENT_VERSION = "v1.0.7"`
3. **Không xóa release cũ:** Giữ lại các phiên bản cũ để người dùng có thể rollback nếu cần
4. **Test trước khi release:** Luôn test kỹ trên máy local trước khi publish

---
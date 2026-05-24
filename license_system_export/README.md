# License System - Hệ thống Quản lý License Key

## Mô tả
Hệ thống license key hoàn chỉnh bao gồm:
- Backend: API kiểm tra và kích hoạt license
- Frontend: Giao diện nhập key và hiển thị trạng thái
- License Core: Thư viện xử lý license (check, activate, cache, GUI)

## Cấu trúc thư mục

```
license_system_export/
├── backend/
│   ├── libs/license_core/          # Thư viện license core
│   │   ├── __init__.py
│   │   ├── api.py                  # LicenseGuard - logic chính
│   │   ├── storage.py              # Lưu/đọc license file (.lic)
│   │   ├── hwid.py                 # Lấy hardware ID
│   │   ├── gui.py                  # Giao diện nhập key (CustomTkinter)
│   │   ├── env_secure.py           # Load config từ .env.enc
│   │   └── .env.enc                # Config mã hóa (password, secret)
│   │
│   ├── routers/
│   │   └── license_routes.py       # API routes cho license
│   │
│   └── main_integration.py         # Code tích hợp vào main.py
│
├── frontend/
│   ├── components/
│   │   └── LicensePanel.vue        # Component hiển thị/nhập license
│   │
│   └── composables/
│       └── useLicense.ts           # Composable quản lý license state
│
└── README.md                        # File này
```

## Cài đặt

### 1. Backend

#### Bước 1: Copy thư mục `backend/libs/license_core` vào project
```bash
cp -r license_system_export/backend/libs/license_core your_project/backend/libs/
```

#### Bước 2: Cài đặt dependencies
```bash
pip install requests customtkinter
```

#### Bước 3: Tích hợp vào main.py
Xem file `backend/main_integration.py` để biết cách tích hợp vào FastAPI app của bạn.

Các bước chính:
1. Import `LicenseGuard` và `ModernLicenseUI`
2. Tạo hàm `ensure_license()` để check license khi khởi động
3. Thêm middleware để block API nếu license không hợp lệ
4. Gọi `ensure_license()` trước khi khởi tạo FastAPI app

#### Bước 4: Thêm API routes
Copy file `backend/routers/license_routes.py` vào project và register router:
```python
from routers import license_routes
app.include_router(license_routes.router)
```

### 2. Frontend (Vue 3 + Nuxt)

#### Bước 1: Copy components
```bash
cp license_system_export/frontend/components/LicensePanel.vue your_project/frontend/app/components/
cp license_system_export/frontend/composables/useLicense.ts your_project/frontend/app/composables/
```

#### Bước 2: Sử dụng trong component
```vue
<template>
  <LicensePanel />
</template>

<script setup lang="ts">
import LicensePanel from '~/components/LicensePanel.vue'
</script>
```

## Cấu hình

### Backend Config (.env hoặc .env.enc)

File `backend/libs/license_core/.env.enc` chứa:
```
SIGNATURE_SECRET_HASH=<sha256_hash_of_secret>
ADMIN_PASSWORD_HASH=<sha256_hash_of_admin_password>
```

Để tạo hash mới, chạy:
```python
import hashlib
secret = "your_secret_key"
print(hashlib.sha256(secret.encode()).hexdigest())
```

### License Server URL

Mặc định: `https://license.nanoproai.shop`

Có thể thay đổi trong:
- Backend: `backend/main_integration.py` → `_get_license_server_url()`
- Frontend: Component sẽ tự động lấy từ backend

## API Endpoints

### GET `/api/license/status`
Lấy thông tin license hiện tại
```json
{
  "license_key": "XXXX-XXXX-XXXX",
  "ok": true,
  "expire_at": "2026-12-31 23:59:59",
  "ui_mode": 1,
  "yt_plan": "pro"
}
```

### POST `/api/license/activate`
Kích hoạt license key mới
```json
{
  "license_key": "XXXX-XXXX-XXXX"
}
```

Response:
```json
{
  "ok": true,
  "message": "Kích hoạt thành công!",
  "ui_mode": 1,
  "yt_plan": "pro"
}
```

### GET `/api/license/info`
Lấy thông tin ui_mode và plan (dùng cho gating features)
```json
{
  "ui_mode": 1,
  "yt_plan": "pro"
}
```

## Tính năng

### Backend
- ✅ Check license online/cache (cache 2h)
- ✅ Activate license key
- ✅ HWID binding (chống copy license sang máy khác)
- ✅ Signature verification (chống sửa file .lic)
- ✅ Periodic check (2h/lần) với callback khi fail
- ✅ GUI nhập key (CustomTkinter) - tự động hiện khi chưa có license
- ✅ Middleware block API khi license không hợp lệ

### Frontend
- ✅ Hiển thị trạng thái license (đã kích hoạt / chưa kích hoạt)
- ✅ Form nhập license key
- ✅ Hiển thị ngày hết hạn
- ✅ Toast notification khi activate thành công/thất bại
- ✅ Auto-refresh sau khi activate

## Bảo mật

1. **HWID Binding**: License key chỉ hoạt động trên máy đã kích hoạt
2. **Signature**: File .lic có chữ ký HMAC-SHA256, không thể sửa đổi
3. **Cache Timeout**: Cache chỉ valid 2h, sau đó phải check server
4. **Expire Check**: Kiểm tra ngày hết hạn từ server
5. **Password Protected**: Cấu hình server URL cần password admin

## Lưu ý

- File license được lưu tại: `storage/config/{product_id}.lic`
- Product ID mặc định: `yt_tool` (có thể thay đổi trong code)
- Cần có mạng Internet để activate và check license định kỳ
- GUI sử dụng CustomTkinter, cần cài đặt: `pip install customtkinter`

## Troubleshooting

### Lỗi "License không hợp lệ"
- Kiểm tra kết nối Internet
- Kiểm tra license key đã nhập đúng chưa
- Kiểm tra license server URL

### Lỗi "Key này đã kích hoạt trên máy khác"
- License key đã được kích hoạt trên máy khác
- Liên hệ admin để reset HWID

### GUI không hiện
- Kiểm tra đã cài `customtkinter`: `pip install customtkinter`
- Kiểm tra biến môi trường `SKIP_LICENSE_CHECK` (chỉ dùng dev)

## License Server

Hệ thống này cần một license server để verify/activate keys.
Server cần implement 2 endpoints:

- `POST /license/verify` - Verify license key
- `POST /license/activate` - Activate license key

Payload:
```json
{
  "license_key": "XXXX-XXXX-XXXX",
  "hwid": "hardware_id",
  "product_id": "yt_tool"
}
```

Response:
```json
{
  "ok": true,
  "expire_at": "2026-12-31 23:59:59",
  "ui_mode": 1,
  "yt_plan": "pro"
}
```

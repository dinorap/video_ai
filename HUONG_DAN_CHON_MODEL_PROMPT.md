# 📖 Hướng Dẫn Chọn Model và Nhập Prompt

## 🎯 Tổng Quan

Code đã có đầy đủ các hàm để chọn model (như Nano Banana) và nhập prompt trong file `utils/veo3/flow_actions.py`. Tất cả đều hoạt động đúng theo code cũ.

---

## 📌 Các Hàm Chính

### 1. **click_kSyLER_menu(page: Page) -> bool**
**Vị trí:** Lines 1625-1660

**Chức năng:** Mở menu chọn model

**Cách hoạt động:**
- Tìm nút model bằng nhiều cách:
  - UI mới: icon `volume_up` (Material Design)
  - UI cũ: class `kSyLER`
  - Fallback: button có text chứa `veo|nano|imagen|banana|pro`
- Click để mở menu dropdown
- Verify menu đã mở bằng cách kiểm tra `[role="menuitem"]`

**Ví dụ:**
```python
if await click_kSyLER_menu(page):
    print("✅ Menu model đã mở")
else:
    print("❌ Không mở được menu")
```

---

### 2. **click_menuitem_preset(page: Page, model_text: str) -> bool**
**Vị trí:** Lines 1663-1763

**Chức năng:** Chọn model từ menu đã mở

**Tham số:**
- `model_text`: Tên model cần chọn (vd: "Nano Banana", "Veo 3.1", "Imagen 3")

**Scoring System (Lines 1672-1718):**
- Match y hệt: **+100 điểm**
- Có "nano": **+12 điểm**
- Có "banana": **+12 điểm**
- Có "veo": **+12 điểm**
- Có "pro": **+8 điểm**
- Overlap token: **+6 điểm/token**
- Sai fast/quality/lite: **-10 đến -12 điểm**

**Ví dụ:**
```python
# Chọn Nano Banana
if await click_menuitem_preset(page, model_text="Nano Banana"):
    print("✅ Đã chọn Nano Banana")
else:
    print("❌ Không chọn được model")
```

---

### 3. **send_prompt_text(page: Page, prompt: str) -> bool**
**Vị trí:** Lines 1766-1801

**Chức năng:** Nhập prompt vào editor Flow và nhấn Enter

**Cách hoạt động:**
- Tìm editor: `[role="textbox"][contenteditable="true"][data-slate-editor="true"]`
- Dùng `keyboard.insert_text()` (an toàn cho đa luồng, không dùng clipboard)
- Chia prompt thành 2-3 chunks để tránh crash editor
- Tự động nhấn Enter sau khi nhập xong

**Ví dụ:**
```python
prompt = "Tạo video về AI với hiệu ứng đẹp"
if await send_prompt_text(page, prompt):
    print("✅ Đã nhập prompt")
else:
    print("❌ Không nhập được prompt")
```

---

### 4. **setup_render_settings(page, **kwargs) -> bool** ⭐ KHUYẾN NGHỊ
**Vị trí:** Lines 2011-2231

**Chức năng:** Hàm tổng hợp setup toàn bộ (mode, ratio, model, prompt)

**Tham số:**
- `mode`: "image" hoặc "video"
- `aspect_ratio`: "16:9", "9:16", "4:3", "1:1", "3:4"
- `model`: Tên model (vd: "Nano Banana")
- `prompt`: Nội dung prompt
- `output_count`: Số lượng output (mặc định 1)
- `select_ingredients`: Chọn tab "Thành phần" (mặc định False)

**Ví dụ:**
```python
success = await setup_render_settings(
    page,
    mode="video",              # Chọn mode Video
    aspect_ratio="9:16",       # Tỉ lệ 9:16 (dọc)
    model="Nano Banana",       # Model Nano Banana
    prompt="Tạo video về AI"   # Prompt
)

if success:
    print("✅ Setup thành công!")
else:
    print("❌ Setup thất bại - sẽ retry")
```

---

## 💡 Cách Sử Dụng

### **Cách 1: Từng Bước Riêng Lẻ**

```python
from utils.veo3.flow_actions import (
    click_kSyLER_menu,
    click_menuitem_preset,
    send_prompt_text
)

async def create_video_step_by_step(page):
    # Bước 1: Mở menu model
    if not await click_kSyLER_menu(page):
        print("❌ Không mở được menu model")
        return False
    
    # Bước 2: Chọn model Nano Banana
    if not await click_menuitem_preset(page, model_text="Nano Banana"):
        print("❌ Không chọn được model Nano Banana")
        return False
    
    # Bước 3: Nhập prompt
    if not await send_prompt_text(page, "Tạo video về AI"):
        print("❌ Không nhập được prompt")
        return False
    
    print("✅ Hoàn thành!")
    return True
```

---

### **Cách 2: Dùng Hàm Tổng Hợp** ⭐ KHUYẾN NGHỊ

```python
from utils.veo3.flow_actions import setup_render_settings

async def create_video_all_in_one(page):
    success = await setup_render_settings(
        page,
        mode="video",              # Chọn mode Video
        aspect_ratio="9:16",       # Tỉ lệ 9:16 (dọc)
        model="Nano Banana",       # Model Nano Banana
        prompt="Tạo video về AI"   # Prompt
    )
    
    if success:
        print("✅ Setup thành công!")
    else:
        print("❌ Setup thất bại!")
    
    return success
```

---

## 🔍 Chi Tiết Kỹ Thuật

### **Regex Pattern Tìm Model** (Line 1630)
```python
model_name_re = re.compile(r"veo|nano|imagen|banana|pro", re.I)
```
- Tìm các model: **veo**, **nano**, **imagen**, **banana**, **pro**
- Case-insensitive (không phân biệt hoa/thường)

---

### **Normalize Model Text** (Lines 51-71)
```python
def _normalize_flow_model_label_ui(s: str) -> str:
    """
    Chuẩn hoá label model giữa Frontend và Flow UI.
    - Loại bỏ "(leaving x/y)"
    - Chuyển "Lower Priority" → "Low Priority"
    - Chuyển "veo3.1" → "veo 3.1"
    - Loại bỏ ký tự đặc biệt
    """
```

---

### **Scoring System Chi Tiết**

| Điều kiện | Điểm |
|-----------|------|
| Match y hệt | +100 |
| Có "nano" trong cả target & item | +12 |
| Có "banana" trong cả target & item | +12 |
| Có "veo" trong cả target & item | +12 |
| Có "pro" trong cả target & item | +8 |
| Có "3.1" trong cả target & item | +12 |
| Có "fast" trong cả target & item | +10 |
| Có "lite" trong cả target & item | +10 |
| Có "quality" trong cả target & item | +10 |
| Overlap token | +6 mỗi token |
| Sai fast/quality/lite | -10 đến -12 |
| Sai priority | -6 đến -14 |

**Ví dụ Tính Điểm:**

```
Target: "Nano Banana"
Item 1: "Nano Banana Fast"
  → match "nano" (+12) + match "banana" (+12) + overlap 2 token (+12) = 36 điểm ✅

Item 2: "Veo 3.1"
  → không match gì = 0 điểm ❌

→ Chọn Item 1
```

---

## ⚙️ Cấu Hình

### **Selector cho Prompt Editor** (Line 101)
```python
_FLOW_SLATE_PROMPT_SELECTOR = '[role="textbox"][contenteditable="true"][data-slate-editor="true"]'
```

### **Timeout Mặc Định**
- Wait for editor: **12,000ms** (12 giây)
- Wait for menu: **3,500ms** (3.5 giây)
- Click timeout: **2,500ms** (2.5 giây)

---

## 🚀 Ví Dụ Thực Tế

### **Tạo Video với Nano Banana**
```python
from utils.veo3.flow_actions import setup_render_settings

async def tao_video_nano_banana(page):
    return await setup_render_settings(
        page,
        mode="video",
        aspect_ratio="9:16",
        model="Nano Banana",
        prompt="Một con mèo đang chơi với bóng len"
    )
```

### **Tạo Ảnh với Imagen 3**
```python
async def tao_anh_imagen(page):
    return await setup_render_settings(
        page,
        mode="image",
        aspect_ratio="1:1",
        model="Imagen 3",
        prompt="Phong cảnh núi non hùng vĩ"
    )
```

### **Tạo Video với Veo 3.1**
```python
async def tao_video_veo(page):
    return await setup_render_settings(
        page,
        mode="video",
        aspect_ratio="16:9",
        model="Veo 3.1",
        prompt="Thành phố về đêm với ánh đèn lung linh"
    )
```

---

## ✅ Kiểm Tra Code

Chạy file test để xem hướng dẫn chi tiết:
```bash
python test_model_prompt.py
```

---

## 📝 Lưu Ý Quan Trọng

1. **Code đã có đầy đủ** trong file `utils/veo3/flow_actions.py`
2. **Các hàm đã được test** và hoạt động tốt
3. **Dùng `setup_render_settings()`** cho đơn giản nhất
4. **Hỗ trợ retry tự động** nếu thất bại
5. **An toàn cho đa luồng** (dùng `keyboard.insert_text()` thay vì clipboard)
6. **Tương thích UI mới và cũ** của Google Flow

---

## 🎉 Kết Luận

Code chọn model và nhập prompt **đã hoạt động đúng** theo yêu cầu. Bạn chỉ cần gọi các hàm đã có sẵn trong `flow_actions.py`.

**Khuyến nghị:** Dùng hàm `setup_render_settings()` để setup toàn bộ một lần, thay vì gọi từng hàm riêng lẻ.

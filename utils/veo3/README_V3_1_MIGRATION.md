# VEO API v3.1+ Migration Guide

## 📋 Tổng quan

Google đã thay đổi format API từ **operations format** (cũ) sang **media format** (mới v3.1+). Module này giúp migrate code sang format mới.

## 🔄 Điểm khác biệt chính

### 1. CREATE Response Format

**CŨ (operations):**
```json
{
  "operations": [
    {
      "sceneId": "1",
      "operation": {
        "name": "operations/abc-123-xyz"
      }
    }
  ]
}
```

**MỚI (media):**
```json
{
  "media": [
    {
      "mediaId": "media/abc-123-xyz",
      "video": {...}
    }
  ]
}
```

### 2. Status Check Payload

**CŨ:**
```python
status_payload = {
    "operations": [
        {
            "sceneId": "1",
            "status": "MEDIA_GENERATION_STATUS_ACTIVE",
            "operation": {"name": "operations/xxx"}
        }
    ]
}
```

**MỚI:**
```python
status_payload = {
    "media": [
        {
            "name": "media/xxx",
            "projectId": "project-id"
        }
    ]
}
```

### 3. Status Response Format

**CŨ:**
```json
{
  "operations": [
    {
      "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
      "operation": {
        "metadata": {
          "video": {
            "fifeUrl": "https://..."
          }
        }
      }
    }
  ]
}
```

**MỚI:**
```json
{
  "media": [
    {
      "mediaMetadata": {
        "mediaStatus": {
          "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        }
      }
    }
  ]
}
```

### 4. Video Download

**CŨ:** Tải từ `fifeUrl` (HTTP URL)
```python
video_url = operation["metadata"]["video"]["fifeUrl"]
response = requests.get(video_url)
```

**MỚI:** Tải từ `encodedVideo` (base64)
```python
# GET /v1/media/{mediaId}
response = await page.request.get(f"https://aisandbox-pa.googleapis.com/v1/media/{media_id}")
media_data = await response.json()
encoded_video = media_data["video"]["encodedVideo"]
video_bytes = base64.b64decode(encoded_video)
```

### 5. Thumbnail

**CŨ:** Có URL riêng trong response
```python
thumbnail_url = operation["metadata"]["image"]["fifeUrl"]
```

**MỚI:** KHÔNG CÓ, phải dùng ffmpeg extract
```python
subprocess.run([
    "ffmpeg", "-y", "-i", video_path,
    "-frames:v", "1", thumbnail_path
])
```

## 📦 Module mới: `veo_video_api_v3_1.py`

### Các hàm chính:

#### 1. `poll_video_status_v3_1()`
Poll status với format mới (media array)

```python
status_result = await poll_video_status_v3_1(
    page=page,
    media_id="media/abc-123",
    project_id="project-id",
    access_token="token",
    timeout_seconds=420,
    poll_interval=6
)
# Returns: {"success": True/False, "status": "SUCCESSFUL", ...}
```

#### 2. `download_video_from_encoded_v3_1()`
Download video từ encodedVideo (base64) và tạo thumbnail

```python
download_result = await download_video_from_encoded_v3_1(
    page=page,
    media_id="media/abc-123",
    access_token="token",
    output_path="output/video.mp4",
    ffmpeg_path="ffmpeg"
)
# Returns: {"success": True, "video_path": "...", "thumbnail_path": "..."}
```

#### 3. `full_video_workflow_v3_1()`
Workflow đầy đủ: Poll status → Download video + thumbnail

```python
result = await full_video_workflow_v3_1(
    page=page,
    media_id="media/abc-123",
    project_id="project-id",
    access_token="token",
    output_path="output/video.mp4",
    ffmpeg_path="ffmpeg",
    timeout_seconds=420
)
# Returns: {"success": True, "video_path": "...", "thumbnail_path": "...", "status": "COMPLETED"}
```

#### 4. `parse_media_id_from_create_response()`
Parse mediaId từ CREATE response

```python
media_id = parse_media_id_from_create_response(create_response_body)
# Returns: "media/abc-123-xyz" hoặc None
```

## 🚀 Cách sử dụng

### Import module:

```python
from utils.veo3.veo_video_api_v3_1 import (
    poll_video_status_v3_1,
    download_video_from_encoded_v3_1,
    full_video_workflow_v3_1,
    parse_media_id_from_create_response,
)
```

### Workflow hoàn chỉnh:

```python
# 1. Tạo video (giữ nguyên code cũ)
create_response = await request_create_reference_video_via_browser(
    page, video_payload, access_token
)

# 2. Parse mediaId từ response (THAY ĐỔI)
body = create_response.get("body", "")
media_id = parse_media_id_from_create_response(body)

if not media_id:
    raise ValueError("Không parse được mediaId")

# 3. Chạy workflow mới (THAY ĐỔI)
result = await full_video_workflow_v3_1(
    page=page,
    media_id=media_id,
    project_id=project_id,
    access_token=access_token,
    output_path=out_path,
    ffmpeg_path="ffmpeg",
    timeout_seconds=420
)

if result["success"]:
    print(f"✅ Video: {result['video_path']}")
    print(f"🖼️ Thumbnail: {result['thumbnail_path']}")
else:
    print(f"❌ Error: {result['error']}")
```

## ✅ Đã cập nhật

File `control_creat_video_veo3.py` đã được cập nhật để sử dụng API mới:

- ✅ Import module `veo_video_api_v3_1`
- ✅ Parse `mediaId` từ CREATE response
- ✅ Sử dụng `full_video_workflow_v3_1()` thay vì poll + download cũ
- ✅ Tự động tạo thumbnail bằng ffmpeg

## 🔧 Yêu cầu

- **ffmpeg**: Cần có trong PATH hoặc cấu hình `FFMPEG_PATH` trong `config/config.json`
- **Playwright**: Đã có sẵn trong project

## 📝 Lưu ý

1. **Batch processing**: Hàm `run_video_tasks_veo3()` vẫn dùng code cũ (operations format) vì nó xử lý nhiều video cùng lúc. Có thể migrate sau nếu cần.

2. **Timeout**: Mặc định 420 giây (7 phút) cho poll status. Có thể điều chỉnh qua tham số `timeout_seconds`.

3. **Thumbnail**: Nếu ffmpeg không có hoặc lỗi, video vẫn được tải về nhưng không có thumbnail.

4. **Error handling**: Module mới có error handling tốt hơn với thông báo chi tiết.

## 🐛 Debug

Nếu gặp lỗi, kiểm tra:

1. **Response format**: Log full response để xem có đúng format `media[]` không
2. **mediaId**: Kiểm tra xem parse được mediaId chưa
3. **encodedVideo**: Kiểm tra response GET media có field `video.encodedVideo` không
4. **ffmpeg**: Chạy `ffmpeg -version` để kiểm tra

## 📚 Tham khảo

- File gốc: `utils/veo3/veo_video_api_v3_1.py`
- File đã migrate: `utils/control_creat_video_veo3.py`
- Migration guide trong code: Xem docstring của module

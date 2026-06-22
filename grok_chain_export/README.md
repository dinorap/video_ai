# Grok Video Chain - Module Độc Lập

Module Python độc lập để tạo video Grok với frame chaining (nối cảnh liên tục).

## Tính năng

- ✅ Tạo video từ prompt và ảnh tham chiếu
- ✅ Tự động cắt frame cuối của video để làm ảnh tham chiếu cho cảnh tiếp theo
- ✅ Hỗ trợ tạo chuỗi nhiều video với nhân vật/bối cảnh nhất quán
- ✅ Tự động xử lý download và đợi video render xong
- ✅ Hỗ trợ chọn duration (6s/10s) và quality (480p/720p)
- ✅ Xử lý lỗi giới hạn tài khoản Grok

## Yêu cầu

```bash
pip install playwright asyncio
playwright install chromium
```

Cần có **ffmpeg** trong PATH hoặc chỉ định đường dẫn.

## Cài đặt

Copy thư mục `grok_chain_export` vào dự án của bạn.

## Sử dụng cơ bản

### 1. Tạo một video đơn

```python
import asyncio
from grok_chain_export import GrokVideoChain

async def main():
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos",
        ffmpeg_path="ffmpeg"  # hoặc đường dẫn đầy đủ
    )
    
    # Tạo video từ ảnh và prompt
    video_path = await chain.create_single_video(
        image_path="character.jpg",
        prompt="A character walking in the forest",
        output_name="scene_001.mp4",
        duration="6s",
        quality="720p"
    )
    
    print(f"Video saved: {video_path}")

asyncio.run(main())
```

### 2. Tạo chuỗi video với frame chaining

```python
import asyncio
from grok_chain_export import GrokVideoChain

async def main():
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos"
    )
    
    prompts = [
        "A young warrior standing in a mystical forest",
        "The warrior draws their sword and prepares for battle",
        "The warrior charges forward with determination"
    ]
    
    # Cảnh 1 dùng ảnh tham chiếu, các cảnh sau dùng frame cuối của cảnh trước
    video_paths = await chain.create_video_chain(
        prompts=prompts,
        first_image="warrior_reference.jpg",
        duration="6s",
        quality="720p"
    )
    
    for i, path in enumerate(video_paths, 1):
        print(f"Scene {i}: {path}")

asyncio.run(main())
```

### 3. Tạo video với nhiều ảnh tham chiếu

```python
# Mỗi cảnh có ảnh tham chiếu riêng (không dùng frame chaining)
video_paths = await chain.create_video_chain_with_images(
    prompts=["prompt 1", "prompt 2", "prompt 3"],
    images=["image1.jpg", "image2.jpg", "image3.jpg"],
    duration="10s",
    quality="720p"
)
```

### 4. Chỉ cắt frame từ video có sẵn

```python
from grok_chain_export import extract_last_frame, extract_first_frame

# Cắt frame cuối (để làm ảnh tham chiếu cho cảnh sau)
last_frame = extract_last_frame("scene_001.mp4", "frame_for_scene_002.jpg")

# Cắt frame đầu (để làm thumbnail)
first_frame = extract_first_frame("scene_001.mp4", "thumbnail.jpg")
```

## API Reference

### GrokVideoChain

#### `__init__(profile_dir, output_dir, ffmpeg_path="ffmpeg", cdp_port=9222)`

Khởi tạo Grok Video Chain.

**Parameters:**
- `profile_dir` (str): Đường dẫn đến Chrome profile (để lưu session đăng nhập Grok)
- `output_dir` (str): Thư mục lưu video output
- `ffmpeg_path` (str): Đường dẫn đến ffmpeg executable
- `cdp_port` (int): Port cho Chrome DevTools Protocol

#### `async create_single_video(image_path, prompt, output_name, duration="6s", quality="720p")`

Tạo một video đơn.

**Returns:** Đường dẫn đến file video đã tạo

#### `async create_video_chain(prompts, first_image, duration="6s", quality="720p")`

Tạo chuỗi video với frame chaining.

**Parameters:**
- `prompts` (List[str]): Danh sách prompt cho từng cảnh
- `first_image` (str): Ảnh tham chiếu cho cảnh đầu tiên
- `duration` (str): "6s" hoặc "10s"
- `quality` (str): "480p" hoặc "720p"

**Returns:** List đường dẫn đến các video đã tạo

#### `async create_video_chain_with_images(prompts, images, duration="6s", quality="720p")`

Tạo chuỗi video, mỗi cảnh có ảnh tham chiếu riêng.

**Returns:** List đường dẫn đến các video đã tạo

### Frame Extractor Functions

#### `extract_last_frame(video_path, output_path=None, ffmpeg_path="ffmpeg")`

Cắt frame cuối của video (lùi 0.1s từ EOF để tránh frame đen).

**Returns:** Đường dẫn đến file ảnh

#### `extract_first_frame(video_path, output_path=None, ffmpeg_path="ffmpeg")`

Cắt frame đầu của video.

**Returns:** Đường dẫn đến file ảnh

## Cấu trúc thư mục output

```
output_videos/
├── 001.mp4              # Video cảnh 1
├── 002.mp4              # Video cảnh 2
├── 003.mp4              # Video cảnh 3
├── frame_2.jpg          # Frame cuối cảnh 1 → đầu vào cảnh 2
├── frame_3.jpg          # Frame cuối cảnh 2 → đầu vào cảnh 3
└── frame_4.jpg          # Frame cuối cảnh 3 (nếu cần)
```

## Xử lý lỗi

```python
from grok_chain_export.grok_video import GrokAccountLimitError

try:
    await chain.create_video_chain(prompts, first_image)
except GrokAccountLimitError as e:
    print(f"Tài khoản Grok đã đạt giới hạn: {e}")
    # Đổi tài khoản hoặc đợi reset
except TimeoutError as e:
    print(f"Timeout: {e}")
except Exception as e:
    print(f"Lỗi: {e}")
```

## Tips & Best Practices

1. **Prompt cho cảnh đầu:** Mô tả chi tiết nhân vật và bối cảnh
2. **Prompt cho cảnh sau:** Chỉ mô tả hành động/chuyển động (ảnh ref đã có nhân vật)
3. **Frame cuối:** Nếu bị đen/fade, chỉnh `-sseof` trong `frame_extractor.py` (vd: `-0.5` thay vì `-0.1`)
4. **Chrome Profile:** Đăng nhập Grok một lần, sau đó session được lưu lại
5. **Giới hạn tài khoản:** Grok có giới hạn số video/ngày, cần nhiều tài khoản nếu tạo nhiều

## Troubleshooting

**Q: Chrome không tìm thấy?**
A: Chỉ định đường dẫn Chrome trong `chrome_utils.py` hoặc cài Chromium qua Playwright.

**Q: ffmpeg không tìm thấy?**
A: Cài ffmpeg và thêm vào PATH, hoặc truyền `ffmpeg_path` khi khởi tạo.

**Q: Video không tải về?**
A: Kiểm tra thư mục Downloads, có thể browser đang chặn download tự động.

**Q: Frame cuối bị đen?**
A: Sửa `-sseof -0.1` thành `-0.5` hoặc `-1.0` trong `frame_extractor.py`.

## License

MIT License - Tự do sử dụng trong dự án cá nhân và thương mại.

## Tác giả

Extracted from web_creat_video project

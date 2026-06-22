# Quick Start - Bắt đầu nhanh

## 1. Cài đặt (5 phút)

```bash
# Cài dependencies
pip install playwright
playwright install chromium

# Cài ffmpeg (nếu chưa có)
# Windows: Download từ https://www.gyan.dev/ffmpeg/builds/
# Linux: sudo apt install ffmpeg
# Mac: brew install ffmpeg
```

## 2. Khởi động Chrome với CDP

```bash
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=./chrome_profile

# Linux/Mac
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome_profile
```

**Quan trọng:** Đăng nhập Grok trong Chrome này (chỉ cần 1 lần)

## 3. Tạo video đầu tiên

Tạo file `test.py`:

```python
import asyncio
from grok_chain_export import GrokVideoChain

async def main():
    # Khởi tạo
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos"
    )
    
    # Tạo chuỗi 3 video với frame chaining
    videos = await chain.create_video_chain(
        prompts=[
            "A warrior standing in a forest",
            "The warrior draws their sword",
            "The warrior charges forward"
        ],
        first_image="character.jpg",  # Ảnh tham chiếu cho cảnh 1
        duration="6s",
        quality="720p"
    )
    
    print("✅ Done! Videos:", videos)

asyncio.run(main())
```

Chạy:

```bash
python test.py
```

## 4. Kết quả

Sau khi chạy xong, bạn sẽ có:

```
output_videos/
├── 001.mp4          # Video cảnh 1
├── 002.mp4          # Video cảnh 2
├── 003.mp4          # Video cảnh 3
├── frame_2.jpg      # Frame cuối cảnh 1 → input cảnh 2
└── frame_3.jpg      # Frame cuối cảnh 2 → input cảnh 3
```

## Các tính năng chính

### 1. Tạo video đơn

```python
video = await chain.create_single_video(
    image_path="character.jpg",
    prompt="A warrior in the forest",
    output_name="my_video.mp4"
)
```

### 2. Frame chaining (nối cảnh tự động)

```python
videos = await chain.create_video_chain(
    prompts=["scene 1", "scene 2", "scene 3"],
    first_image="character.jpg"
)
```

### 3. Mỗi cảnh có ảnh riêng

```python
videos = await chain.create_video_chain_with_images(
    prompts=["scene 1", "scene 2"],
    images=["image1.jpg", "image2.jpg"]
)
```

### 4. Chỉ cắt frame

```python
from grok_chain_export import extract_last_frame

frame = extract_last_frame("video.mp4", "frame.jpg")
```

## Tips

1. **Prompt cảnh đầu:** Mô tả chi tiết nhân vật và bối cảnh
2. **Prompt cảnh sau:** Chỉ mô tả hành động (ảnh ref đã có nhân vật)
3. **Frame đen:** Tăng `seek_offset=0.5` trong `extract_last_frame()`
4. **Giới hạn Grok:** Cần nhiều tài khoản nếu tạo nhiều video

## Xem thêm

- `README.md` - Tài liệu đầy đủ
- `INSTALL.md` - Hướng dẫn cài đặt chi tiết
- `example_usage.py` - Nhiều ví dụ khác

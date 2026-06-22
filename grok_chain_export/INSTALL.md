# Hướng dẫn cài đặt Grok Video Chain

## Bước 1: Cài đặt Python dependencies

```bash
pip install -r requirements.txt
```

Hoặc cài thủ công:

```bash
pip install playwright
playwright install chromium
```

## Bước 2: Cài đặt ffmpeg

### Windows:

1. Download ffmpeg từ: https://www.gyan.dev/ffmpeg/builds/
2. Giải nén và thêm vào PATH, hoặc
3. Chỉ định đường dẫn khi khởi tạo: `ffmpeg_path="C:/path/to/ffmpeg.exe"`

### Linux/Mac:

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Mac
brew install ffmpeg
```

## Bước 3: Khởi động Chrome với CDP

Trước khi chạy code, cần khởi động Chrome với Chrome DevTools Protocol:

### Windows:

```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=./chrome_profile
```

### Linux/Mac:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome_profile
```

**Lưu ý:** 
- Đăng nhập Grok trong Chrome này (chỉ cần 1 lần)
- Session sẽ được lưu trong `chrome_profile`
- Giữ Chrome mở trong suốt quá trình chạy code

## Bước 4: Chạy ví dụ

```bash
python example_usage.py
```

Hoặc tạo script riêng:

```python
import asyncio
from grok_chain_export import GrokVideoChain

async def main():
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos"
    )
    
    videos = await chain.create_video_chain(
        prompts=["Scene 1", "Scene 2", "Scene 3"],
        first_image="character.jpg"
    )
    
    print("Done:", videos)

asyncio.run(main())
```

## Troubleshooting

### Lỗi: "Chrome not found"

Cài đặt Google Chrome hoặc set biến môi trường:

```bash
# Windows
set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe

# Linux/Mac
export CHROME_PATH=/usr/bin/google-chrome
```

### Lỗi: "ffmpeg not found"

Cài ffmpeg và thêm vào PATH, hoặc chỉ định đường dẫn:

```python
chain = GrokVideoChain(
    profile_dir="./chrome_profile",
    output_dir="./output_videos",
    ffmpeg_path="C:/path/to/ffmpeg.exe"  # Windows
)
```

### Lỗi: "Connection refused" (CDP)

Chrome chưa chạy hoặc port sai. Kiểm tra:

1. Chrome đang chạy với `--remote-debugging-port=9222`
2. Port không bị chiếm bởi process khác
3. Thử port khác: `cdp_port=9223`

### Frame cuối bị đen

Tăng `seek_offset` trong `frame_extractor.py`:

```python
last_frame = extract_last_frame(
    video_path="scene.mp4",
    output_path="frame.jpg",
    seek_offset=0.5  # Lùi 0.5s thay vì 0.1s
)
```

## Sử dụng trong dự án khác

Copy toàn bộ thư mục `grok_chain_export` vào dự án:

```
your_project/
├── grok_chain_export/
│   ├── __init__.py
│   ├── grok_chain.py
│   ├── grok_video.py
│   ├── frame_extractor.py
│   └── chrome_utils.py
└── your_script.py
```

Trong `your_script.py`:

```python
from grok_chain_export import GrokVideoChain
```

## Yêu cầu hệ thống

- Python 3.8+
- Google Chrome hoặc Chromium
- ffmpeg
- RAM: 4GB+ (khuyến nghị 8GB)
- Kết nối internet ổn định

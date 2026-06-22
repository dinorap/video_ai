# Grok Chain Export - Package Information

## Cấu trúc Package

```
grok_chain_export/
├── __init__.py              # Entry point, exports GrokVideoChain và extract_last_frame
├── grok_chain.py            # Class chính GrokVideoChain
├── grok_video.py            # Core logic tạo video, download, xử lý lỗi
├── frame_extractor.py       # Cắt frame từ video bằng ffmpeg
├── chrome_utils.py          # Tìm Chrome, khởi động với CDP
├── requirements.txt         # Dependencies: playwright
├── README.md                # Tài liệu đầy đủ
├── INSTALL.md               # Hướng dẫn cài đặt chi tiết
├── QUICKSTART.md            # Bắt đầu nhanh
├── example_usage.py         # Ví dụ sử dụng
└── PACKAGE_INFO.md          # File này
```

## Modules

### 1. `__init__.py`
- Export: `GrokVideoChain`, `extract_last_frame`, `extract_first_frame`
- Version: 1.0.0

### 2. `grok_chain.py`
**Class:** `GrokVideoChain`

**Methods:**
- `__init__(profile_dir, output_dir, ffmpeg_path, cdp_port)`
- `create_single_video(image_path, prompt, output_name, duration, quality)` → str
- `create_video_chain(prompts, first_image, duration, quality)` → List[str]
- `create_video_chain_with_images(prompts, images, duration, quality)` → List[str]

### 3. `grok_video.py`
**Classes:**
- `GrokAccountLimitError(Exception)` - Lỗi giới hạn tài khoản
- `VideoJob(dataclass)` - Thông tin job tạo video

**Functions:**
- `download_by_click_save_as(page, out_path, ...)` - Download video
- `_attach_grok_limit_listener(page)` - Theo dõi lỗi API
- `_wait_after_submit(page, holder, ...)` - Đợi sau khi submit
- `_strict_wait_creating_overlay_disappear(page, ...)` - Đợi overlay biến mất

### 4. `frame_extractor.py`
**Functions:**
- `extract_last_frame(video_path, output_path, ffmpeg_path, seek_offset)` → str
- `extract_first_frame(video_path, output_path, ffmpeg_path)` → str
- `extract_frame_at_time(video_path, time_seconds, output_path, ffmpeg_path)` → str

### 5. `chrome_utils.py`
**Functions:**
- `find_chrome_executable()` → Optional[str]
- `launch_chrome_with_cdp(profile_dir, url, cdp_port, headless)` → subprocess.Popen
- `get_cdp_endpoint(port)` → str

## Dependencies

```
playwright>=1.40.0
asyncio (built-in Python 3.8+)
```

External:
- **ffmpeg** - Cắt frame từ video
- **Google Chrome** - Browser để tạo video trên Grok

## Workflow

```
1. Khởi tạo GrokVideoChain
   ↓
2. Connect Chrome qua CDP (port 9222)
   ↓
3. Tạo video cảnh 1 với first_image
   ↓
4. Cắt frame cuối cảnh 1 → frame_2.jpg
   ↓
5. Tạo video cảnh 2 với frame_2.jpg
   ↓
6. Cắt frame cuối cảnh 2 → frame_3.jpg
   ↓
7. Tạo video cảnh 3 với frame_3.jpg
   ↓
8. Hoàn thành: 001.mp4, 002.mp4, 003.mp4
```

## API Summary

### Tạo chuỗi video (Frame Chaining)

```python
chain = GrokVideoChain(
    profile_dir="./chrome_profile",
    output_dir="./output_videos"
)

videos = await chain.create_video_chain(
    prompts=["scene 1", "scene 2", "scene 3"],
    first_image="character.jpg",
    duration="6s",
    quality="720p"
)
# → ["001.mp4", "002.mp4", "003.mp4"]
```

### Tạo video đơn

```python
video = await chain.create_single_video(
    image_path="character.jpg",
    prompt="A warrior in the forest",
    output_name="my_video.mp4"
)
# → "my_video.mp4"
```

### Cắt frame

```python
from grok_chain_export import extract_last_frame

frame = extract_last_frame("video.mp4", "frame.jpg")
# → "frame.jpg"
```

## Error Handling

```python
from grok_chain_export.grok_video import GrokAccountLimitError

try:
    videos = await chain.create_video_chain(...)
except GrokAccountLimitError:
    print("Tài khoản Grok đã đạt giới hạn")
except TimeoutError:
    print("Timeout khi tạo video")
except FileNotFoundError:
    print("File không tồn tại")
```

## Configuration

### Chrome Profile
- Lưu session đăng nhập Grok
- Tránh phải đăng nhập lại mỗi lần
- Path: `./chrome_profile` (mặc định)

### Output Directory
- Lưu video và frame
- Cấu trúc: `001.mp4`, `002.mp4`, `frame_2.jpg`, ...
- Path: `./output_videos` (mặc định)

### CDP Port
- Chrome DevTools Protocol port
- Mặc định: 9222
- Có thể đổi nếu port bị chiếm

### FFmpeg Path
- Mặc định: `"ffmpeg"` (tìm trong PATH)
- Windows: `"C:/path/to/ffmpeg.exe"`
- Linux/Mac: `"/usr/bin/ffmpeg"`

## Performance

- **Thời gian tạo 1 video:** ~2-5 phút (tùy Grok server)
- **RAM usage:** ~500MB - 1GB
- **Disk space:** ~5-20MB/video (6s, 720p)
- **Network:** Cần kết nối ổn định

## Limitations

1. **Grok account limit:** Giới hạn số video/ngày
2. **Video duration:** Chỉ 6s hoặc 10s
3. **Quality:** Chỉ 480p hoặc 720p
4. **Chrome required:** Phải có Chrome/Chromium
5. **Internet required:** Không thể offline

## Use Cases

✅ Tạo video marketing với nhân vật nhất quán
✅ Tạo storyboard động từ kịch bản
✅ Tạo video demo sản phẩm
✅ Tạo content cho social media
✅ Prototype animation ideas

❌ Không phù hợp cho:
- Video dài (>10s)
- Real-time generation
- Batch processing hàng trăm video (giới hạn account)

## License

MIT License - Tự do sử dụng trong dự án cá nhân và thương mại.

## Support

- Issues: Tạo issue trong repo gốc
- Documentation: Xem README.md
- Examples: Xem example_usage.py

## Version History

- **1.0.0** (2026-06-02): Initial release
  - Frame chaining support
  - Single video creation
  - Multi-image support
  - Error handling
  - Full documentation

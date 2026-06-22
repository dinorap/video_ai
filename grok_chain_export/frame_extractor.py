"""
Frame Extractor - Cắt frame từ video bằng ffmpeg
================================================

Module này cung cấp các hàm để cắt frame từ video:
- extract_last_frame: Cắt frame cuối video (để làm ảnh tham chiếu cho cảnh sau)
- extract_first_frame: Cắt frame đầu video (để làm thumbnail)
"""

import subprocess
import os
from pathlib import Path
from typing import Optional


def _get_subprocess_kwargs():
    """Trả về kwargs cho subprocess để ẩn cửa sổ console trên Windows."""
    if os.name != 'nt':
        return {}
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        return {
            'startupinfo': si,
            'creationflags': subprocess.CREATE_NO_WINDOW
        }
    except Exception:
        return {}


def extract_last_frame(
    video_path: str,
    output_path: Optional[str] = None,
    ffmpeg_path: str = "ffmpeg",
    seek_offset: float = 0.1
) -> str:
    """
    Cắt frame cuối của video bằng ffmpeg.
    
    Args:
        video_path: Đường dẫn đến file video
        output_path: Đường dẫn output (nếu None, tự động tạo .last_frame.jpg)
        ffmpeg_path: Đường dẫn đến ffmpeg executable
        seek_offset: Lùi bao nhiêu giây từ cuối video (mặc định 0.1s để tránh frame đen)
    
    Returns:
        Đường dẫn đến file ảnh đã tạo
    
    Example:
        >>> frame = extract_last_frame("scene_001.mp4", "frame_002.jpg")
        >>> print(frame)  # "frame_002.jpg"
    """
    video = Path(video_path)
    if not video.exists():
        raise FileNotFoundError(f"Video không tồn tại: {video_path}")
    
    if output_path is None:
        output = video.with_suffix(".last_frame.jpg")
    else:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        ffmpeg_path,
        "-y",  # Ghi đè file nếu đã tồn tại
        "-sseof", f"-{seek_offset}",  # Seek từ cuối file
        "-i", str(video),
        "-frames:v", "1",  # Chỉ lấy 1 frame
        "-q:v", "2",  # Chất lượng cao
        str(output),
    ]
    
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **_get_subprocess_kwargs()
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode('utf-8', errors='ignore') if e.stderr else ''
        raise RuntimeError(f"ffmpeg failed: {stderr}")
    
    if not output.exists():
        raise RuntimeError(f"Frame extraction failed: output file not created")
    
    return str(output)


def extract_first_frame(
    video_path: str,
    output_path: Optional[str] = None,
    ffmpeg_path: str = "ffmpeg"
) -> str:
    """
    Cắt frame đầu của video bằng ffmpeg.
    
    Args:
        video_path: Đường dẫn đến file video
        output_path: Đường dẫn output (nếu None, tự động tạo .first_frame.jpg)
        ffmpeg_path: Đường dẫn đến ffmpeg executable
    
    Returns:
        Đường dẫn đến file ảnh đã tạo
    
    Example:
        >>> thumbnail = extract_first_frame("scene_001.mp4", "thumbnail.jpg")
    """
    video = Path(video_path)
    if not video.exists():
        raise FileNotFoundError(f"Video không tồn tại: {video_path}")
    
    if output_path is None:
        output = video.with_suffix(".first_frame.jpg")
    else:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        ffmpeg_path,
        "-y",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        str(output),
    ]
    
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **_get_subprocess_kwargs()
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode('utf-8', errors='ignore') if e.stderr else ''
        raise RuntimeError(f"ffmpeg failed: {stderr}")
    
    if not output.exists():
        raise RuntimeError(f"Frame extraction failed: output file not created")
    
    return str(output)


def extract_frame_at_time(
    video_path: str,
    time_seconds: float,
    output_path: str,
    ffmpeg_path: str = "ffmpeg"
) -> str:
    """
    Cắt frame tại thời điểm cụ thể.
    
    Args:
        video_path: Đường dẫn đến file video
        time_seconds: Thời điểm cần cắt (giây)
        output_path: Đường dẫn output
        ffmpeg_path: Đường dẫn đến ffmpeg executable
    
    Returns:
        Đường dẫn đến file ảnh đã tạo
    """
    video = Path(video_path)
    if not video.exists():
        raise FileNotFoundError(f"Video không tồn tại: {video_path}")
    
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        ffmpeg_path,
        "-y",
        "-ss", str(time_seconds),
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        str(output),
    ]
    
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            **_get_subprocess_kwargs()
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode('utf-8', errors='ignore') if e.stderr else ''
        raise RuntimeError(f"ffmpeg failed: {stderr}")
    
    if not output.exists():
        raise RuntimeError(f"Frame extraction failed: output file not created")
    
    return str(output)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python frame_extractor.py <video_path> [output_path]")
        sys.exit(1)
    
    video_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        result = extract_last_frame(video_path, output_path)
        print(f"✅ Frame extracted: {result}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

"""Cắt frame cuối video bằng ffmpeg — dùng cho Grok Chain (nối cảnh)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from utils.control_ffmpeg import _win_subprocess_kwargs
from utils.runtime_paths import get_ffmpeg_exe


def extract_last_frame_ffmpeg(video_path: str) -> str:
    """
    Lấy frame gần cuối video (lùi 0.1s từ EOF) bằng ffmpeg.
    Trả về đường dẫn file .last_frame.jpg (cùng thư mục với video).
    """
    video = Path(video_path)
    output = video.with_suffix(".last_frame.jpg")

    subprocess.run(
        [
            get_ffmpeg_exe(),
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_win_subprocess_kwargs(),
    )
    return str(output)


def extract_last_frame_to(video_path: str, dest_path: str) -> str:
    """Cắt frame cuối và lưu vào dest_path (ghi đè nếu đã tồn tại)."""
    raw = extract_last_frame_ffmpeg(video_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Path(raw).replace(dest)
    return str(dest)

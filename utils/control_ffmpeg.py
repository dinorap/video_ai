
import base64
import os
import subprocess
import tempfile
import uuid
from typing import List

from flask import jsonify, request, send_from_directory


TRANSCODE_DIR = os.path.join(tempfile.gettempdir(), "web_creat_video_transcoded")
os.makedirs(TRANSCODE_DIR, exist_ok=True)


def _win_subprocess_kwargs():
    if os.name != 'nt':
        return {}
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    except Exception:
        si = None
    kw = {}
    try:
        kw['creationflags'] = subprocess.CREATE_NO_WINDOW
    except Exception:
        pass
    if si is not None:
        kw['startupinfo'] = si
    return kw


def _ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, **_win_subprocess_kwargs()).decode("utf-8", errors="ignore").strip()
    try:
        return float(out)
    except Exception:
        return 0.0


def _ffprobe_has_audio(path: str) -> bool:
    try:
        cmd = [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            path,
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, **_win_subprocess_kwargs()).decode("utf-8", errors="ignore").strip()
        return bool(out)
    except Exception:
        return False


def apply_background_music(
    video_path: str,
    music_path: str,
    out_path: str,
    music_volume: float = 0.6,
) -> str:
    """
    Thêm nhạc nền vào video và TẮT HẾT âm thanh gốc của video.
    
    ⚠️ QUAN TRỌNG: Hàm này sẽ LOẠI BỎ HOÀN TOÀN âm thanh gốc của video,
    chỉ giữ lại nhạc nền để tránh bị loạn âm thanh.
    
    Args:
        video_path: Đường dẫn video đầu vào
        music_path: Đường dẫn file nhạc nền
        out_path: Đường dẫn video đầu ra
        music_volume: Volume nhạc nền (0.0-1.0), mặc định 0.6 = 60%
    
    Returns:
        Đường dẫn video đầu ra đã có nhạc nền (không có âm gốc)
    """
    if not video_path or not os.path.exists(video_path):
        raise ValueError("video_path not found")
    if not music_path or not os.path.exists(music_path):
        raise ValueError("music_path not found")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # 🔇 TẮT ÂM THANH GỐC - CHỈ GIỮ NHẠC NỀN
    # Logic: Chỉ map audio từ input[1] (nhạc nền), KHÔNG map audio từ input[0] (video gốc)
    filter_complex = f"[1:a]volume={music_volume}[aout]"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video_path,
        "-stream_loop",
        "-1",
        "-i",
        music_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        out_path,
    ]

    result = subprocess.run(cmd, cwd=TRANSCODE_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_win_subprocess_kwargs())
    
    # Kiểm tra file output thay vì dựa vào exit code (FFmpeg đôi khi trả về exit code sai)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ''
        raise RuntimeError(f"FFmpeg merge failed: {stderr}")
    
    return out_path


def _effect_to_xfade_transition(effect_key: str) -> str:
    k = str(effect_key or "").strip().lower()
    mapping = {
        "fade": "fade",
        "fadeblack": "fadeblack",
        "fadewhite": "fadewhite",
        "dissolve": "dissolve",
        "slideleft": "slideleft",
        "slideright": "slideright",
        "slideup": "slideup",
        "slidedown": "slidedown",
        "wipeleft": "wipeleft",
        "wiperight": "wiperight",
        "wipeup": "wipeup",
        "wipedown": "wipedown",
        "circleopen": "circleopen",
        "circleclose": "circleclose",
        "circlecrop": "circlecrop",
        "rectcrop": "rectcrop",
        "distance": "distance",
        "diagbl": "diagbl",
        "diagbr": "diagbr",
        "diagtl": "diagtl",
        "diagtr": "diagtr",
        "hlslice": "hlslice",
        "hrslice": "hrslice",
        "vuslice": "vuslice",
        "vdslice": "vdslice",
        "smoothleft": "smoothleft",
        "smoothright": "smoothright",
        "smoothup": "smoothup",
        "smoothdown": "smoothdown",
        "pixelize": "pixelize",
        "radial": "radial",
        "fadegrays": "fadegrays",
        "fadefast": "fade",
        "fadeslow": "fade",
    }
    return mapping.get(k, "")


def merge_video_clips(
    clips: List[str],
    out_path: str,
    effect_key: str = "",
    transition_duration: float = 0.5,
) -> str:
    clips = [c for c in (clips or []) if c]
    if len(clips) == 0:
        raise ValueError("No clips")
    if len(clips) == 1:
        # 🔇 Copy video nhưng TẮT audio gốc
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        cmd = [
            "ffmpeg", 
            "-hide_banner", 
            "-loglevel", "error", 
            "-y", 
            "-i", clips[0], 
            "-map", "0:v",  # CHỈ map video
            "-c:v", "copy",  # Copy video codec (nhanh)
            "-an",  # 🔇 TẮT HẾT audio
            out_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_win_subprocess_kwargs())
        return out_path

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    transition = _effect_to_xfade_transition(effect_key)

    # If no transition requested/known => concat demuxer
    if not transition:
        list_file = os.path.join(TRANSCODE_DIR, f"concat_{uuid.uuid4().hex}.txt")
        try:
            with open(list_file, "w", encoding="utf-8") as f:
                for p in clips:
                    safe_p = str(p).replace("'", "'\\''")
                    f.write("file '" + safe_p + "'\n")
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_file,
                "-map", "0:v",  # 🔇 CHỈ map video, KHÔNG map audio
                "-c:v", "copy",  # Copy video codec (nhanh)
                "-an",  # 🔇 TẮT HẾT audio
                out_path,
            ]
            subprocess.run(cmd, cwd=TRANSCODE_DIR, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_win_subprocess_kwargs())
            return out_path
        finally:
            try:
                if os.path.exists(list_file):
                    os.remove(list_file)
            except OSError:
                pass

    # xfade chain
    durations = [_ffprobe_duration(p) for p in clips]
    # fallback if probe fails
    if any(d <= 0 for d in durations):
        transition = ""
        return merge_video_clips(clips, out_path, effect_key="", transition_duration=transition_duration)

    inputs = []
    for p in clips:
        inputs += ["-i", p]

    filter_lines = []
    # video chain
    filter_lines.append(f"[0:v]setpts=PTS-STARTPTS[v0]")
    offset = max(0.0, durations[0] - transition_duration)
    for i in range(1, len(clips)):
        filter_lines.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
        prev = f"vx{i-1}" if i > 1 else "v0"
        out = f"vx{i}"
        filter_lines.append(
            f"[{prev}][v{i}]xfade=transition={transition}:duration={transition_duration}:offset={offset}[{out}]"
        )
        offset += max(0.0, durations[i] - transition_duration)

    v_last = f"vx{len(clips)-1}" if len(clips) > 1 else "v0"

    # 🔇 KHÔNG ghép âm thanh gốc từ các clip (sẽ thêm nhạc nền sau)
    # Chỉ ghép video, bỏ qua audio để tránh loạn âm thanh
    # Audio sẽ được thêm vào sau bằng apply_background_music()

    filter_complex = ";".join(filter_lines)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        f"[{v_last}]",
        # ❌ KHÔNG map audio từ clips gốc
        # "-map", "[aout]",  # ← Đã XÓA dòng này
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-an",  # 🔇 TẮT HẾT audio (không encode audio)
        "-movflags",
        "+faststart",
        out_path,
    ]

    result = subprocess.run(cmd, cwd=TRANSCODE_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_win_subprocess_kwargs())
    
    # Kiểm tra file output thay vì dựa vào exit code (FFmpeg đôi khi trả về exit code sai)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ''
        raise RuntimeError(f"FFmpeg xfade merge failed: {stderr}")
    
    return out_path


def serve_transcoded_handler(filename: str):
    return send_from_directory(TRANSCODE_DIR, filename)


def transcode_video_handler():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Invalid file"}), 400

    job_id = uuid.uuid4().hex
    in_path = os.path.join(TRANSCODE_DIR, f"{job_id}__src")
    out_name = f"{job_id}.mp4"
    out_path = os.path.join(TRANSCODE_DIR, out_name)

    try:
        file.save(in_path)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        in_path,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        out_path,
    ]

    try:
        subprocess.run(cmd, cwd=TRANSCODE_DIR, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_win_subprocess_kwargs())
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "ffmpeg not found"}), 500
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
        return jsonify({"ok": False, "error": err}), 500
    finally:
        try:
            if os.path.exists(in_path):
                os.remove(in_path)
        except OSError:
            pass

    if not os.path.exists(out_path):
        return jsonify({"ok": False, "error": "Transcode failed"}), 500

    return jsonify({"ok": True, "url": f"/transcoded/{out_name}", "mime": "video/mp4"})


def extract_frame_handler():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Invalid file"}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, file.filename)
        out_path = os.path.join(tmpdir, "thumb.jpg")
        file.save(in_path)

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "00:00:01",
            "-i",
            in_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            out_path,
        ]

        try:
            subprocess.run(cmd, cwd=tmpdir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_win_subprocess_kwargs())
        except FileNotFoundError:
            return jsonify({"ok": False, "error": "ffmpeg not found"}), 500
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
            return jsonify({"ok": False, "error": err}), 500

        if not os.path.exists(out_path):
            return jsonify({"ok": False, "error": "Failed to extract frame"}), 500

        with open(out_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        return jsonify({"ok": True, "data_url": f"data:image/jpeg;base64,{b64}"})

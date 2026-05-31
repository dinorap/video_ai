"""
Module tạo video batch qua Veo3 với ghép video ffmpeg (GIỐNG 100% BÊN GROK).
Áp dụng y hệt code bên Grok để ghép video bằng ffmpeg.
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
import shutil
from typing import Any, Dict, List, Optional

from utils.control_creat_video_veo3 import create_video_veo3
from utils.veo3.veo_reference_video_api import (
    normalize_frontend_veo_video_model_label,
    DEFAULT_FRONTEND_VEO_VIDEO_MODEL_LABEL,
)
from utils.control_script import update_task_status, create_video_task
from utils.control_ffmpeg import merge_video_clips, TRANSCODE_DIR, apply_background_music
from utils.video_reference_prompts import prepare_scene_references


_CANCELLED_VIDEO_TASKS = set()


def cancel_video_task(task_id: str) -> bool:
    tid = str(task_id or '').strip()
    if not tid:
        return False
    _CANCELLED_VIDEO_TASKS.add(tid)
    return True


def is_video_task_cancelled(task_id: str) -> bool:
    tid = str(task_id or '').strip()
    if not tid:
        return False
    return tid in _CANCELLED_VIDEO_TASKS


def clear_video_task_cancel(task_id: str) -> None:
    tid = str(task_id or '').strip()
    if not tid:
        return
    try:
        _CANCELLED_VIDEO_TASKS.discard(tid)
    except Exception:
        pass
    # Fix 6: Prevent memory leak in _CANCELLED_VIDEO_TASKS
    if len(_CANCELLED_VIDEO_TASKS) > 1000:
        _CANCELLED_VIDEO_TASKS.clear()


def _get_scenes_dir(out_clips: List[str]) -> str:
    try:
        clips = [str(p) for p in (out_clips or []) if p]
        if not clips:
            return ''
        parents = {os.path.abspath(os.path.dirname(p)) for p in clips}
        if len(parents) != 1:
            return ''
        return list(parents)[0]
    except Exception:
        return ''


def _decode_data_url_to_temp_file(data_url: str, suffix: str = ".png") -> str:
    if not data_url or not str(data_url).startswith("data:image"):
        raise ValueError("Only data:image/* base64 is supported")
    header, b64 = str(data_url).split(",", 1)
    content = base64.b64decode(b64)
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
    except Exception:
        try:
            os.remove(path)
        except Exception:
            pass
        raise
    return path


from utils.path_helper import CONFIG_FILE, get_base_path, pstr


async def _run_one_video_task_veo3(
    context,
    task: Dict[str, Any],
    sem: asyncio.Semaphore,
    cancel_event: Optional[asyncio.Event] = None,
    veo_model_label: str = '',
):
    """
    Chạy 1 task tạo video Veo3 với ghép video ffmpeg (GIỐNG 100% BÊN GROK).
    Độ dài clip: 8s (Flow mặc định, không truyền duration).
    """
    veo_model = normalize_frontend_veo_video_model_label(
        veo_model_label or DEFAULT_FRONTEND_VEO_VIDEO_MODEL_LABEL
    )
    task_id = str(task.get("task_id") or "").strip()
    scenes = task.get("scenes")
    out_clips = task.get("out_clips")
    effect_key = str(task.get("effect_key") or "").strip()
    merged_out = task.get("merged_out") or ""
    music_path = str(task.get("music_path") or "").strip()
    ratio = str(task.get("ratio") or "16:9").strip()
    profile_name = task.get("profile_name")
    account_type = str(task.get("account_type") or "ULTRA").strip()

    if not task_id:
        return None

    # Lấy batch_dir sớm để có thể xóa khi hủy
    batch_dir = ""
    try:
        if merged_out:
            batch_dir = os.path.dirname(os.path.abspath(merged_out))
    except Exception:
        pass
    
    if not isinstance(scenes, list) or len(scenes) == 0:
        update_task_status(task_id, "failed", error="No scenes")
        return None
    if not isinstance(out_clips, list) or len(out_clips) != len(scenes):
        update_task_status(task_id, "failed", error="Invalid out_clips")
        return None
    if not merged_out:
        update_task_status(task_id, "failed", error="Missing merged_out")
        return None

    update_task_status(task_id, "processing", phase="processing")

    tmp_files: List[str] = []
    flow_page = None
    flow_auth: Optional[Dict[str, Any]] = None
    ws_endpoint: Optional[str] = None
    try:
        for idx, scene in enumerate(scenes):
            # Check cancellation
            if is_video_task_cancelled(task_id) or (
                cancel_event is not None
                and getattr(cancel_event, "is_set", None)
                and cancel_event.is_set()
            ):
                update_task_status(task_id, "cancelled", error="Đã hủy")
                # Xóa thư mục batch ngay lập tức
                if batch_dir and os.path.isdir(batch_dir):
                    shutil.rmtree(batch_dir, ignore_errors=True)
                raise asyncio.CancelledError()

            prompt = str(scene.get("prompt") or "").strip()
            if not prompt:
                update_task_status(task_id, "failed", error=f"Thiếu prompt ở cảnh {idx+1}")
                return None

            ref_urls, ref_types, final_prompt = prepare_scene_references(
                scene_prompt=prompt,
                ref_product=str(scene.get("ref_product") or task.get("ref_product") or ""),
                ref_character=str(scene.get("ref_character") or task.get("ref_character") or ""),
                ref_combined=str(
                    scene.get("ref_combined") or scene.get("image") or task.get("ref_combined") or ""
                ),
                default_image=str(task.get("default_image") or ""),
            )
            print(
                f"[Veo3 Video Batch] Cảnh {idx + 1}: "
                f"upload {len(ref_urls)} ảnh, ref_types={ref_types}"
            )
            if not ref_urls:
                update_task_status(
                    task_id,
                    "failed",
                    error=f"Thiếu ảnh tham chiếu ở cảnh {idx+1} (sản phẩm / nhân vật / kết hợp)",
                )
                return None

            ref_paths: List[str] = []
            for u in ref_urls:
                p = _decode_data_url_to_temp_file(u, suffix=".png")
                tmp_files.append(p)
                ref_paths.append(p)

            update_task_status(
                task_id,
                "processing",
                scene_index=idx + 1,
                total_scenes=len(scenes),
                progress_percent=int((idx / max(1, len(scenes))) * 100),
                phase="downloading",
            )

            # Use Semaphore per scene for better tab utilization
            async with sem:
                clip_dir = str(out_clips[idx])
                
                # Gọi create_video_veo3 thay vì create_video_grok
                result = await create_video_veo3(
                    context=context,
                    image_path=ref_paths[0],
                    reference_image_paths=ref_paths,
                    prompt=final_prompt,
                    out_path=clip_dir,
                    ratio=ratio,
                    veo_model_label=veo_model,
                    task_id=task_id,
                    cancel_event=cancel_event,
                    profile_name=profile_name,
                    account_type=account_type,
                    scene_index=idx,
                    flow_page=flow_page,
                    flow_auth=flow_auth,
                    ws_endpoint_external=ws_endpoint,
                    skip_flow_init=(flow_page is not None),
                    skip_render_setup=(idx > 0),
                    keep_session_open=True,
                )
                if result.get("flow_page") is not None:
                    flow_page = result.get("flow_page")
                if isinstance(result.get("flow_auth"), dict):
                    flow_auth = result.get("flow_auth")
                if result.get("ws_endpoint"):
                    ws_endpoint = str(result.get("ws_endpoint"))
                
                if not result.get("ok"):
                    error_msg = result.get("error", "Unknown error")
                    update_task_status(task_id, "failed", error=f"Tạo video scene {idx+1} thất bại: {error_msg}")
                    return None
                
                real_clip_path = result.get("output")
                
                # Check real_clip_path and verify file size
                if not real_clip_path or not os.path.exists(real_clip_path):
                    update_task_status(task_id, "failed", error=f"Download fail scene {idx+1}")
                    return None
                
                if os.path.getsize(real_clip_path) < 200_000:
                    update_task_status(task_id, "failed", error=f"Video scene {idx+1} quá nhỏ hoặc lỗi")
                    return None

                # Handle duplicate filenames by renaming
                unique_name = f"scene_{idx+1}_{os.path.basename(real_clip_path)}"
                new_path = os.path.join(os.path.dirname(real_clip_path), unique_name)
                try:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(real_clip_path, new_path)
                    real_clip_path = new_path
                except Exception:
                    pass

                out_clips[idx] = str(real_clip_path)

            update_task_status(
                task_id,
                "processing",
                scene_index=idx + 1,
                total_scenes=len(scenes),
                progress_percent=int(((idx + 1) / max(1, len(scenes))) * 100),
                phase="downloading",
            )

        # Persist scene map once at the end
        try:
            scenes_dir = _get_scenes_dir(out_clips)
            if scenes_dir and os.path.isdir(scenes_dir):
                map_path = os.path.join(scenes_dir, 'scene_map.json')
                scene_data = {str(i + 1): os.path.basename(out_clips[i]) for i in range(len(out_clips))}
                with open(map_path, 'w', encoding='utf-8') as f:
                    json.dump(scene_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # Final checks before merging
        if is_video_task_cancelled(task_id) or (cancel_event and cancel_event.is_set()):
            update_task_status(task_id, "cancelled", error="Đã hủy")
            if batch_dir and os.path.isdir(batch_dir):
                shutil.rmtree(batch_dir, ignore_errors=True)
            raise asyncio.CancelledError()

        # Verify all clips exist before FFmpeg merge
        for p in out_clips:
            if not os.path.exists(p):
                update_task_status(task_id, "failed", error=f"Missing clip: {p}")
                return None

        update_task_status(
            task_id,
            "processing",
            scene_index=len(scenes),
            total_scenes=len(scenes),
            progress_percent=100,
            phase="merging",
        )

        # ===== GHÉP VIDEO BẰNG FFMPEG (GIỐNG 100% BÊN GROK) =====
        print(f"[Veo3 Batch] 🎬 Bắt đầu ghép {len(out_clips)} video clips với effect: {effect_key}")
        merged_path = merge_video_clips(out_clips, merged_out, effect_key=effect_key)
        print(f"[Veo3 Batch] ✅ Đã ghép video: {merged_path}")

        # Trộn âm thanh (nhạc nền + âm video gốc)
        try:
            music_vol = task.get("music_volume", 60)
            video_vol = task.get("video_audio_volume", 100)
            tmp_audio_out = os.path.join(
                TRANSCODE_DIR,
                f"music_{task_id.replace('-', '')[:12]}_{os.path.basename(merged_out)}",
            )
            if music_path and os.path.exists(music_path):
                print(f"[Veo3 Batch] 🎵 Trộn nhạc nền: {music_path}")
            applied = apply_background_music(
                merged_path,
                music_path if music_path and os.path.exists(music_path) else "",
                tmp_audio_out,
                music_volume=music_vol,
                video_audio_volume=video_vol,
            )
            shutil.copy2(applied, merged_out)
            merged_path = merged_out
            if os.path.exists(tmp_audio_out) and os.path.abspath(tmp_audio_out) != os.path.abspath(merged_out):
                os.remove(tmp_audio_out)
            print(f"[Veo3 Batch] ✅ Đã trộn âm thanh (nhạc + video gốc)")
        except Exception as e:
            print(f"[Veo3 Batch] ⚠️ Lỗi trộn âm thanh: {e}")

        # Prepare for playback (GIỐNG 100% BÊN GROK)
        out_name = os.path.basename(merged_path)
        trans_name = f"{task_id.replace('-', '')[:12]}__{out_name}"
        trans_path = os.path.join(TRANSCODE_DIR, trans_name)
        try:
            if os.path.abspath(os.path.dirname(merged_path)) != os.path.abspath(TRANSCODE_DIR):
                shutil.copy2(merged_path, trans_path)
            else:
                trans_name = os.path.basename(merged_path)
        except Exception:
            trans_name = os.path.basename(merged_path)

        update_task_status(
            task_id,
            "processing",
            result_file=merged_path,
            result_url=f"/transcoded/{trans_name}",
            effect_key=effect_key,
            out_clips=list(out_clips),
            merged_out=str(merged_out),
            scenes_dir=_get_scenes_dir(out_clips),
            progress_percent=100,
            phase="completed",
        )

        update_task_status(task_id, "completed", phase="completed")
        return True

    except asyncio.CancelledError:
        update_task_status(task_id, "cancelled", error="Đã hủy")
        raise
    except Exception as e:
        print(f"[Veo3 Batch] ❌ Lỗi: {e}")
        update_task_status(task_id, "failed", error=str(e))
        return None
    finally:
        if ws_endpoint:
            try:
                from utils.veo3.flow_actions import cleanup_browser
                await cleanup_browser(ws_endpoint)
            except Exception as e:
                print(f"[Veo3 Batch] ⚠️ Lỗi cleanup session Flow: {e}")
        clear_video_task_cancel(task_id)
        for p in tmp_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def run_video_tasks_veo3_batch(
    context,
    provider: str,
    tasks: List[dict],
    max_tabs: int = 3,
    cancel_event: Optional[asyncio.Event] = None,
    veo_model_label: str = '',
):
    """
    Chạy nhiều task tạo video Veo3 với ghép video ffmpeg (GIỐNG 100% BÊN GROK).
    
    Args:
        context: Context chứa thông tin cấu hình
        provider: Provider name (veo3)
        tasks: Danh sách tasks, mỗi task có format:
            {
                "task_id": "uuid",
                "scenes": [{"prompt": "...", "image": "data:image/..."}],
                "out_clips": ["path/to/clip1.mp4", ...],
                "merged_out": "path/to/merged.mp4",
                "effect_key": "fade",
                "music_path": "path/to/music.mp3",
                "ratio": "16:9",
                "quality": "fast",
                "profile_name": "profile1",
                "account_type": "ULTRA",
            }
        max_tabs: Số lượng tab tối đa chạy song song
        cancel_event: Event để hủy tất cả tasks
        veo_model_label: Nhãn model Veo (mặc định Lite [Lower Priority]); độ dài 8s do Flow
    
    Returns:
        List kết quả của từng task
    """
    canonical_model = normalize_frontend_veo_video_model_label(
        veo_model_label or DEFAULT_FRONTEND_VEO_VIDEO_MODEL_LABEL
    )
    print(f"[Veo3 Video Batch] 🎛️ model UI → {canonical_model}")
    try:
        max_tabs = int(max_tabs)
    except Exception:
        max_tabs = 3
    if max_tabs < 1:
        max_tabs = 1

    sem = asyncio.Semaphore(max_tabs)
    jobs = [
        _run_one_video_task_veo3(context, task, sem, cancel_event, canonical_model)
        for task in tasks
    ]

    gathered = await asyncio.gather(*jobs, return_exceptions=True)

    if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
        raise asyncio.CancelledError()

    return gathered

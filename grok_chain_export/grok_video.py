"""
Grok Video Creator - Core module để tạo video trên Grok
=======================================================

Module này chứa logic chính để:
- Upload ảnh lên Grok
- Điền prompt và submit
- Đợi video render xong
- Download video về
"""

import asyncio
import os
from typing import Optional, Callable, List
from dataclasses import dataclass


# Constants
GROK_CONVERSATIONS_NEW_PATH = "/rest/app-chat/conversations/new"
GROK_ACCOUNT_LIMIT_MESSAGE = (
    "Tài khoản đã đạt giới hạn tạo video. "
    "Vui lòng thay đổi tài khoản Grok khác để tiếp tục sử dụng."
)


# Selectors
UPLOAD_INPUT = """
input.hidden[type='file'][name='files'],
input.hidden[type='file']
"""

PROMPT_EDITOR = """
textarea[aria-label='Create video'],
textarea[aria-label='Tạo video'],
div.ProseMirror[contenteditable='true']
"""

SELECTOR_VIDEO_MODE = """
button[role="radio"]:has-text("Video")
"""

SELECTOR_VIDEO_CREATING_OVERLAY = """
div:has-text("Creating"),
div:has-text("Generating"),
div:has-text("Đang tạo")
"""

SELECTOR_RESULT_VIDEO = """
video[src]
"""


# Exceptions
class GrokAccountLimitError(Exception):
    """Grok trả error code 8 / heavy usage — cần đổi tài khoản."""
    pass


@dataclass
class VideoJob:
    """Thông tin job tạo video."""
    image_path: str
    prompt: str
    out_path: str
    task_id: str = ''
    image_paths: Optional[List[str]] = None
    duration: str = '6s'
    quality: str = '720p'


def _grok_should_cancel(
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
) -> bool:
    """Kiểm tra xem có nên cancel không."""
    if cancel_check is not None:
        try:
            if cancel_check():
                return True
        except Exception:
            pass
    if cancel_event is not None and getattr(cancel_event, "is_set", None):
        try:
            if cancel_event.is_set():
                return True
        except Exception:
            pass
    return False


async def _grok_raise_if_cancelled(
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
) -> None:
    """Raise CancelledError nếu đã cancel."""
    if _grok_should_cancel(cancel_check, cancel_event):
        raise asyncio.CancelledError()


def _is_grok_usage_limit_payload(data) -> bool:
    """Kiểm tra xem response có phải là lỗi giới hạn không."""
    if not isinstance(data, dict):
        return False
    err = data.get("error")
    if not isinstance(err, dict):
        return False
    try:
        if int(err.get("code")) == 8:
            return True
    except (TypeError, ValueError):
        pass
    msg = str(err.get("message") or "").lower()
    if "heavy usage" in msg and "try again later" in msg:
        return True
    if "upgrade plan" in msg and "higher limits" in msg:
        return True
    return False


def _attach_grok_limit_listener(page) -> dict:
    """Theo dõi POST conversations/new; set holder['error'] khi gặp giới hạn."""
    holder: dict = {"error": None}

    async def _on_response(response):
        if holder.get("error"):
            return
        try:
            url = str(response.url or "")
            if GROK_CONVERSATIONS_NEW_PATH not in url:
                return
            body = await response.text()
            try:
                import json
                data = json.loads(body)
                if _is_grok_usage_limit_payload(data):
                    holder["error"] = GROK_ACCOUNT_LIMIT_MESSAGE
            except Exception:
                pass
        except Exception:
            pass

    def _schedule(response):
        asyncio.create_task(_on_response(response))

    page.on("response", _schedule)
    return holder


async def _raise_if_grok_limit(holder: dict) -> None:
    """Raise GrokAccountLimitError nếu phát hiện lỗi giới hạn."""
    msg = holder.get("error")
    if msg:
        raise GrokAccountLimitError(str(msg))


async def _wait_after_submit(
    page,
    holder: dict,
    timeout_s: float = 45.0,
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
) -> None:
    """Chờ redirect/video hoặc phát hiện lỗi giới hạn từ API."""
    deadline = asyncio.get_event_loop().time() + float(timeout_s)
    while asyncio.get_event_loop().time() < deadline:
        await _grok_raise_if_cancelled(cancel_check, cancel_event)
        await _raise_if_grok_limit(holder)
        try:
            u = str(page.url or "")
            if "/imagine/post/" in u:
                return
        except Exception:
            pass
        await asyncio.sleep(0.25)
    await _raise_if_grok_limit(holder)


async def _strict_wait_creating_overlay_disappear(
    page,
    timeout_s=240,
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
):
    """Đợi overlay 'Creating' biến mất."""
    overlay = page.locator(SELECTOR_VIDEO_CREATING_OVERLAY)
    try:
        await overlay.first.wait_for(state="visible", timeout=8000)
    except Exception:
        pass

    deadline = asyncio.get_event_loop().time() + float(timeout_s)
    while asyncio.get_event_loop().time() < deadline:
        await _grok_raise_if_cancelled(cancel_check, cancel_event)
        try:
            visible = await overlay.first.is_visible()
            if not visible:
                return
        except Exception:
            return
        await asyncio.sleep(0.5)


def _looks_like_mp4(path: str) -> bool:
    """Kiểm tra xem file có phải MP4 không."""
    try:
        if not path or (not os.path.exists(path)):
            return False
        with open(path, 'rb') as f:
            head = f.read(256)
        return (b'ftyp' in head[:64]) or (b'ftyp' in head)
    except Exception:
        return False


async def _wait_file_stable_pro(
    path,
    min_bytes=200_000,
    stable_ticks=2,
    tick_ms=350,
    timeout_s=120.0,
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
):
    """Đợi file ổn định (không thay đổi size)."""
    last_len = -1
    stable = 0
    deadline = asyncio.get_event_loop().time() + float(timeout_s)

    while asyncio.get_event_loop().time() < deadline:
        await _grok_raise_if_cancelled(cancel_check, cancel_event)
        if not os.path.exists(path):
            await asyncio.sleep(tick_ms / 1000)
            continue

        try:
            curr_len = os.path.getsize(path)
        except Exception:
            curr_len = 0

        if curr_len >= min_bytes and curr_len == last_len:
            stable += 1
            if stable >= stable_ticks:
                return True
        else:
            stable = 0
            last_len = curr_len

        await asyncio.sleep(tick_ms / 1000)
    return False


async def download_by_click_save_as(
    page,
    out_path,
    timeout_ms=240000,
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
):
    """Download video bằng cách click nút Download."""
    out_path = str(out_path or '').strip()
    if not out_path:
        raise ValueError('Missing out_path')
    
    target_dir = os.path.abspath(out_path) if os.path.isdir(out_path) else os.path.dirname(os.path.abspath(out_path))
    os.makedirs(target_dir, exist_ok=True)

    candidate_selectors = [
        'button[aria-label="Tải xuống"]',
        'button[aria-label="Download"]',
        'button:has-text("Tải xuống")',
        'button:has-text("Download")',
        'a[download]'
    ]

    # 1. Wait for overlay to disappear
    await _strict_wait_creating_overlay_disappear(
        page, timeout_s=240, cancel_check=cancel_check, cancel_event=cancel_event
    )
    await _grok_raise_if_cancelled(cancel_check, cancel_event)
    await asyncio.sleep(1.0)

    # 2. Find download button
    chosen = None
    find_deadline = asyncio.get_event_loop().time() + 25
    while asyncio.get_event_loop().time() < find_deadline and not chosen:
        await _grok_raise_if_cancelled(cancel_check, cancel_event)
        for sel in candidate_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    chosen = loc
                    break
            except Exception:
                pass
        if not chosen:
            await asyncio.sleep(0.5)

    if not chosen:
        raise RuntimeError("Download button not found")

    # 3. Expect Download + Click
    async with page.expect_download(timeout=timeout_ms) as download_info:
        try:
            await chosen.scroll_into_view_if_needed()
            try:
                await chosen.click(force=True, timeout=15000, no_wait_after=True)
            except Exception:
                await page.evaluate("(el) => el.click()", await chosen.element_handle())
        except Exception as e:
            raise RuntimeError(f"Click failed: {e}")

    download = await download_info.value

    # Determine real output path
    suggested = download.suggested_filename or "grok_video.mp4"
    final_path = os.path.join(target_dir, suggested)

    # 4. Save and Verify
    await download.save_as(final_path)

    is_stable = await _wait_file_stable_pro(
        final_path,
        min_bytes=200_000,
        cancel_check=cancel_check,
        cancel_event=cancel_event,
    )
    if is_stable and _looks_like_mp4(final_path):
        return final_path

    raise RuntimeError("File verification failed (size < 200KB or unstable)")

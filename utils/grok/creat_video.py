import asyncio
import json
import os
from dataclasses import dataclass
from typing import List, Optional, Callable
import shutil


GROK_CONVERSATIONS_NEW_PATH = "/rest/app-chat/conversations/new"
GROK_ACCOUNT_LIMIT_MESSAGE = (
    "Tài khoản đã đạt giới hạn tạo video. "
    "Vui lòng thay đổi tài khoản Grok khác để tiếp tục sử dụng."
)


class GrokAccountLimitError(Exception):
    """Grok trả error code 8 / heavy usage — cần đổi tài khoản."""


def _grok_should_cancel(
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
) -> bool:
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
    if _grok_should_cancel(cancel_check, cancel_event):
        raise asyncio.CancelledError()


def _is_grok_usage_limit_payload(data) -> bool:
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


def _parse_grok_limit_from_text(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    try:
        return _is_grok_usage_limit_payload(json.loads(raw))
    except json.JSONDecodeError:
        low = raw.lower()
        return (
            '"code": 8' in low or '"code":8' in low
        ) and "heavy usage" in low
    except Exception:
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
            if _parse_grok_limit_from_text(body):
                holder["error"] = GROK_ACCOUNT_LIMIT_MESSAGE
        except Exception:
            pass

    def _schedule(response):
        asyncio.create_task(_on_response(response))

    page.on("response", _schedule)
    return holder


async def _raise_if_grok_limit(holder: dict) -> None:
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


# =========================
# SELECTORS
# =========================

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


# =========================
# DATA CLASS
# =========================

@dataclass
class VideoJob:
    image_path: str
    prompt: str
    out_path: str
    task_id: str = ''
    image_paths: Optional[List[str]] = None


_ACTIVE_VIDEO_PAGES = {}


async def close_task_page(task_id: str) -> bool:
    tid = str(task_id or '').strip()
    if not tid:
        return False
    page = _ACTIVE_VIDEO_PAGES.get(tid)
    if not page:
        return False
    try:
        if not page.is_closed():
            await page.close()
    except Exception:
        pass
    try:
        _ACTIVE_VIDEO_PAGES.pop(tid, None)
    except Exception:
        pass
    return True


# =========================
# FILE STABLE CHECK (GIỐNG C#)
# =========================

async def wait_file_stable(path, min_bytes=50_000, stable_ticks=2, tick_ms=350, timeout_s=90.0):
    stable_count = 0
    last_size = -1
    deadline = asyncio.get_event_loop().time() + float(timeout_s)

    while True:
        if asyncio.get_event_loop().time() >= deadline:
            raise TimeoutError(f"File did not become stable in time: {path}")

        if not os.path.exists(path):
            await asyncio.sleep(tick_ms / 1000)
            continue

        size = os.path.getsize(path)

        if size > 0 and size == last_size and size >= min_bytes:
            stable_count += 1
            if stable_count >= stable_ticks:
                return
        else:
            stable_count = 0

        last_size = size
        await asyncio.sleep(tick_ms / 1000)


async def _click_empty_area(page):
    try:
        size = page.viewport_size
        if size:
            x = size['width'] / 2
            y = size['height'] - 20
            await page.mouse.click(x, y)
            await asyncio.sleep(0.3)
    except Exception:
        pass


async def _strict_wait_creating_overlay_disappear(
    page,
    timeout_s=240,
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
):
    overlay = page.locator(SELECTOR_VIDEO_CREATING_OVERLAY)
    try:
        try:
            await overlay.first.wait_for(state="visible", timeout=8000)
        except Exception:
            pass
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
    try:
        if not path or (not os.path.exists(path)):
            return False
        # MP4 typically has an ftyp box near the start.
        # We don't require exact brands, only that 'ftyp' is present early.
        with open(path, 'rb') as f:
            head = f.read(256)
        return (b'ftyp' in head[:64]) or (b'ftyp' in head)
    except Exception:
        return False


def _find_download_in_default_folder(filename: str) -> str:
    name = str(filename or '').strip()
    if not name:
        return ''

    candidates = []
    try:
        downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        candidates.append(downloads_dir)
    except Exception:
        pass

    # Windows machines sometimes redirect Downloads to OneDrive
    try:
        od = os.environ.get('OneDrive') or os.environ.get('OneDriveConsumer')
        if od:
            od_dl = os.path.join(od, 'Downloads')
            candidates.append(od_dl)
    except Exception:
        pass

    for d in candidates:
        try:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        except Exception:
            pass

    # last resort: find most recent file that starts with filename (some browsers add (1))
    for d in candidates:
        try:
            if not os.path.isdir(d):
                continue
            best = ''
            best_mtime = 0.0
            for fn in os.listdir(d):
                if not fn:
                    continue
                if fn == name or fn.startswith(name + ' ('):
                    fp = os.path.join(d, fn)
                    try:
                        mt = os.path.getmtime(fp)
                    except Exception:
                        mt = 0.0
                    if mt > best_mtime:
                        best = fp
                        best_mtime = mt
            if best:
                return best
        except Exception:
            pass

    return ''


async def _wait_for_recent_download_finished(created_after_ts: float, timeout_s: float = 30.0) -> str:
    deadline = asyncio.get_event_loop().time() + float(timeout_s)
    last_candidate = ''
    while asyncio.get_event_loop().time() < deadline:
        cand = _find_recent_video_in_default_downloads(created_after_ts)
        if cand:
            last_candidate = cand
            # If Chrome is still downloading, it often ends with .crdownload
            if cand.lower().endswith('.crdownload'):
                base = cand[:-len('.crdownload')]
                if os.path.exists(base) and os.path.getsize(base) > 0:
                    return base
                await asyncio.sleep(0.6)
                continue

            # Non-temp video file
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                return cand
        await asyncio.sleep(0.6)

    return last_candidate


def _find_recent_video_in_default_downloads(created_after_ts: float) -> str:
    candidates = []
    try:
        downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        candidates.append(downloads_dir)
    except Exception:
        pass

    try:
        od = os.environ.get('OneDrive') or os.environ.get('OneDriveConsumer')
        if od:
            od_dl = os.path.join(od, 'Downloads')
            candidates.append(od_dl)
    except Exception:
        pass

    best = ''
    best_mtime = 0.0
    for d in candidates:
        fp = _find_recent_video_in_folder(d, created_after_ts)
        if not fp:
            continue
        try:
            mt = os.path.getmtime(fp)
        except Exception:
            mt = 0.0
        if mt > best_mtime:
            best = fp
            best_mtime = mt
    return best


async def _wait_for_recent_download_finished_in_folder(folder: str, created_after_ts: float, timeout_s: float = 30.0) -> str:
    deadline = asyncio.get_event_loop().time() + float(timeout_s)
    last_candidate = ''
    while asyncio.get_event_loop().time() < deadline:
        cand = _find_recent_video_in_folder(folder, created_after_ts)
        if cand:
            last_candidate = cand
            if cand.lower().endswith('.crdownload'):
                base = cand[:-len('.crdownload')]
                if os.path.exists(base) and os.path.getsize(base) > 0:
                    return base
                await asyncio.sleep(0.6)
                continue
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                return cand
        await asyncio.sleep(0.6)
    return last_candidate


def _find_recent_video_in_folder(folder: str, created_after_ts: float) -> str:
    d = str(folder or '').strip()
    if not d:
        return ''

    exts = {'.mp4', '.webm', '.mkv', '.crdownload'}
    best = ''
    best_mtime = 0.0
    try:
        if not os.path.isdir(d):
            return ''
        for fn in os.listdir(d):
            if not fn:
                continue
            _, ext = os.path.splitext(fn)
            if ext.lower() not in exts:
                continue
            fp = os.path.join(d, fn)
            try:
                mt = os.path.getmtime(fp)
            except Exception:
                mt = 0.0
            if mt >= created_after_ts and mt > best_mtime:
                best = fp
                best_mtime = mt
    except Exception:
        return ''

    return best


def _snapshot_video_files(folder: str) -> set:
    d = str(folder or '').strip()
    if not d or not os.path.isdir(d):
        return set()
    exts = {'.mp4', '.webm', '.mkv', '.crdownload'}
    out = set()
    try:
        for fn in os.listdir(d):
            if not fn:
                continue
            _, ext = os.path.splitext(fn)
            if ext.lower() not in exts:
                continue
            out.add(os.path.join(d, fn))
    except Exception:
        return set()
    return out


async def _wait_for_new_video_in_folder(folder: str, before: set, timeout_s: float = 35.0) -> str:
    deadline = asyncio.get_event_loop().time() + float(timeout_s)
    last = ''
    while asyncio.get_event_loop().time() < deadline:
        now = _snapshot_video_files(folder)
        diff = [p for p in now.difference(before) if p]
        cand = ''
        if diff:
            best = ''
            best_mtime = 0.0
            for p in diff:
                try:
                    mt = os.path.getmtime(p)
                except Exception:
                    mt = 0.0
                if mt > best_mtime:
                    best = p
                    best_mtime = mt
            cand = best

        if not cand:
            cand = _find_recent_video_in_folder(folder, 0.0)

        if cand:
            last = cand
            if cand.lower().endswith('.crdownload'):
                base = cand[:-len('.crdownload')]
                if os.path.exists(base) and os.path.getsize(base) > 0:
                    return base
                await asyncio.sleep(0.6)
                continue
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                return cand

        await asyncio.sleep(0.6)

    return last


# =========================
# DOWNLOAD (GIỐNG 100% Grok.cs)
# =========================

async def _wait_file_stable_pro(
    path,
    min_bytes=200_000,
    stable_ticks=2,
    tick_ms=350,
    timeout_s=120.0,
    cancel_check: Optional[Callable[[], bool]] = None,
    cancel_event=None,
):
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

    # 1. Wait for overlay to disappear (Strict like C#)
    await _strict_wait_creating_overlay_disappear(
        page, timeout_s=240, cancel_check=cancel_check, cancel_event=cancel_event
    )
    await _grok_raise_if_cancelled(cancel_check, cancel_event)
    await asyncio.sleep(1.0)  # StepDelayAsync in C#

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

    # 3. Expect Download + Robust Click (Event-based like C#)
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

    # 4. Save and Verify (Like C#)
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


# =========================
# CREATE VIDEO
# =========================

async def create_video_grok(
    context,
    job: VideoJob,
    cancel_event=None,
    timeout_s=420,
    duration='6s',
    quality='720p',
    cancel_check: Optional[Callable[[], bool]] = None,
):

    extra_paths = getattr(job, 'image_paths', None)
    paths: List[str] = []
    if isinstance(extra_paths, list) and extra_paths:
        paths = [str(p).strip() for p in extra_paths if p and os.path.exists(str(p))]
    img = str(getattr(job, 'image_path', '') or '').strip()
    if not paths and img and os.path.exists(img):
        paths = [img]
    pr = str(getattr(job, 'prompt', '') or '').strip()
    if not pr or not paths:
        raise ValueError("Missing prompt/image for video job")

    tid = str(getattr(job, 'task_id', '') or '').strip()
    last_exc = None

    for attempt in range(1, 4):
        await _grok_raise_if_cancelled(cancel_check, cancel_event)

        page = await context.new_page()
        limit_holder: Optional[dict] = None
        try:
            if tid:
                _ACTIVE_VIDEO_PAGES[tid] = page

            limit_holder = _attach_grok_limit_listener(page)

            await page.goto("https://grok.com/imagine", timeout=60000)
            await _grok_raise_if_cancelled(cancel_check, cancel_event)
            await _raise_if_grok_limit(limit_holder)

            upload = page.locator(UPLOAD_INPUT).first
            await upload.wait_for(state="attached", timeout=30000)
            await upload.set_input_files(paths if len(paths) > 1 else paths[0])

            await asyncio.sleep(2)

            try:
                video_mode_btn = page.locator(SELECTOR_VIDEO_MODE).first
                await video_mode_btn.wait_for(state="visible", timeout=10000)
                if await video_mode_btn.get_attribute("aria-checked") != "true":
                    await video_mode_btn.click()
            except Exception:
                pass

            # Select video duration (6s or 10s) and quality (480p or 720p) - must be done BEFORE filling prompt
            try:
                await asyncio.sleep(1.0)
                duration_value = str(duration or '6s').strip()
                quality_value = str(quality or '720p').strip()
                print(f"🔍 Looking for duration button: {duration_value} and quality button: {quality_value}")
                
                # Get all radio buttons
                all_buttons = await page.locator('button[role="radio"]').all()
                print(f"📊 Found {len(all_buttons)} radio buttons")
                
                duration_clicked = False
                quality_clicked = False
                
                for idx, btn in enumerate(all_buttons):
                    try:
                        text = await btn.inner_text()
                        text_clean = text.strip() if text else ''
                        
                        if text_clean == duration_value and not duration_clicked:
                            is_checked = await btn.get_attribute("aria-checked")
                            if is_checked != "true":
                                await btn.click()
                                await asyncio.sleep(0.5)
                                print(f"✅ Clicked duration button: {duration_value}")
                            else:
                                print(f"✅ Duration already selected: {duration_value}")
                            duration_clicked = True
                            
                        elif text_clean == quality_value and not quality_clicked:
                            is_checked = await btn.get_attribute("aria-checked")
                            if is_checked != "true":
                                await btn.click()
                                await asyncio.sleep(0.5)
                                print(f"✅ Clicked quality button: {quality_value}")
                            else:
                                print(f"✅ Quality already selected: {quality_value}")
                            quality_clicked = True
                            
                        if duration_clicked and quality_clicked:
                            break
                    except Exception as e:
                        print(f"  Error checking button {idx}: {e}")
                        continue
            except Exception as e:
                print(f"⚠️ Could not select duration/quality: {e}")

            # Fill prompt and press Enter
            editor = page.locator(PROMPT_EDITOR).first
            await editor.wait_for(timeout=30000)
            await editor.fill(pr)
            await asyncio.sleep(0.5)
            
            # Press Enter to submit
            await editor.press("Enter")
            print("✅ Pressed Enter to submit")

            await _wait_after_submit(
                page,
                limit_holder,
                timeout_s=45.0,
                cancel_check=cancel_check,
                cancel_event=cancel_event,
            )

            try:
                u = str(page.url or '')
            except Exception:
                u = ''

            if '/imagine/post/' in u:
                try:
                    await page.locator('main[tabindex="-1"]').first.click(timeout=3000)
                except Exception:
                    try:
                        await _click_empty_area(page)
                    except Exception:
                        pass

            await asyncio.sleep(2)
            await _raise_if_grok_limit(limit_holder)
            await _grok_raise_if_cancelled(cancel_check, cancel_event)

            video = page.locator(SELECTOR_RESULT_VIDEO).first
            wait_deadline = asyncio.get_event_loop().time() + float(timeout_s)
            while asyncio.get_event_loop().time() < wait_deadline:
                await _grok_raise_if_cancelled(cancel_check, cancel_event)
                try:
                    await video.wait_for(state="visible", timeout=2000)
                    break
                except Exception:
                    await asyncio.sleep(0.5)
            else:
                raise TimeoutError(f"Video không hiện sau {timeout_s}s")

            ready_deadline = asyncio.get_event_loop().time() + 60.0
            while asyncio.get_event_loop().time() < ready_deadline:
                await _grok_raise_if_cancelled(cancel_check, cancel_event)
                try:
                    ready = await page.evaluate(
                        """() => {
                          const v = document.querySelector('video[src]');
                          return !!(v && v.readyState >= 3 && v.src && v.src.length > 50);
                        }"""
                    )
                    if ready:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            else:
                raise TimeoutError("Video chưa sẵn sàng để tải")

            await asyncio.sleep(1)
            result_path = await download_by_click_save_as(
                page,
                job.out_path,
                cancel_check=cancel_check,
                cancel_event=cancel_event,
            )
            return result_path

        except asyncio.CancelledError:
            raise
        except GrokAccountLimitError:
            raise
        except Exception as exc:
            last_exc = exc
        finally:
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                pass

            try:
                if tid and _ACTIVE_VIDEO_PAGES.get(tid) is page:
                    _ACTIVE_VIDEO_PAGES.pop(tid, None)
            except Exception:
                pass

        if attempt < 3:
            try:
                await asyncio.sleep(1.2)
            except Exception:
                pass

    if last_exc is not None:
        raise last_exc
    raise RuntimeError('create_video_grok failed')


# =========================
# WORKER
# =========================

async def worker(name, context, queue: asyncio.Queue, cancel_event):

    while not queue.empty():

        job = await queue.get()

        try:
            await create_video_grok(context, job, cancel_event)
        except Exception as e:
            print(f"[ERROR][{name}] {e}")

        queue.task_done()


# =========================
# RUN MULTI JOB
# =========================

async def run_video_jobs(context, jobs: List[VideoJob], workers=2):

    queue = asyncio.Queue()

    for job in jobs:
        await queue.put(job)

    cancel_event = asyncio.Event()

    tasks = [
        asyncio.create_task(worker(f"W{i+1}", context, queue, cancel_event))
        for i in range(workers)
    ]

    await queue.join()

    for t in tasks:
        t.cancel()

    print("ALL DONE")
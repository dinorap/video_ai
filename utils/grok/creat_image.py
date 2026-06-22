import asyncio
import os
import re

_ACTIVE_IMAGE_PAGES = {}

async def close_task_page(task_id: str) -> bool:
    tid = str(task_id or '').strip()
    if not tid:
        return False
    page = _ACTIVE_IMAGE_PAGES.get(tid)
    if not page:
        return False
    try:
        if not page.is_closed():
            await page.close()
    except Exception:
        pass
    try:
        _ACTIVE_IMAGE_PAGES.pop(tid, None)
    except Exception:
        pass
    return True

UPLOAD_INPUT = """
input.hidden[type='file'][name='files'],
input.hidden[type='file']
"""

PROMPT_EDITOR = """
textarea[aria-label='Create'],
textarea[aria-label='Tạo'],
textarea[placeholder*='imagine'],
textarea[placeholder*='tưởng tượng'],
textarea[placeholder*='Nhập'],
div.tiptap.ProseMirror[contenteditable='true'],
div.ProseMirror[contenteditable='true'],
p[data-placeholder="Type to imagine, @ to reference images"],
p[data-placeholder*='imagine'],
p[data-placeholder*='tưởng tượng']
"""

SELECTOR_SUBMIT_SEND = """
button[type='submit'][aria-label='Submit'],
button[type='submit'][aria-label='Gửi'],
button[aria-label='Submit'],
button[aria-label='Gửi'],
button[type='submit']:has-text('Send'),
button[type='submit']:has-text('Gửi')
"""

SELECTOR_CREATE_BUTTON = """
button:has-text('Create'),
button:has-text('Generate'),
button:has-text('Tạo'),
button:has-text('Tạo ảnh'),
button:has-text('Create image'),
button:has-text('Generate image')
"""

SELECTOR_CREATING_OVERLAY = """
div:has-text("Creating"),
div:has-text("Generating"),
div:has-text("Đang tạo"),
div:has-text("Đang tạo ảnh")
"""

SELECTOR_THUMBNAILS = """
article img
"""

SELECTOR_RESULT_IMAGE = """
.grid img
"""

SELECTOR_ASPECT_BUTTON = """
button[aria-label="Aspect Ratio"],
button[aria-label="Tỷ lệ khung hình"],
button[aria-haspopup="menu"]:has(span:text-matches("\\d+\\s*:\\s*\\d+", "i"))
"""
SELECTOR_IMAGE_MODE = """
button[role="radio"]:has-text("Hình ảnh"),
button[role="radio"]:has-text("Image")
"""

SELECTOR_IMAGE_ATTACHMENTS = """
button[aria-label="Remove"],
button[aria-label="Remove image"],
button[aria-label="Xóa"],
button[aria-label="Xoá"],
button[aria-label="Đóng"],
button[aria-label="Close"],
button[aria-label="Delete"],
button[aria-label="Delete image"]
"""

async def create_image_grok(context, image1, image2, prompt, out_path, ratio="9:16", cancel_event=None, task_id: str = ""):
    page = await context.new_page()

    try:
        tid = str(task_id or '').strip()
        if tid:
            _ACTIVE_IMAGE_PAGES[tid] = page

        if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
            raise asyncio.CancelledError()

        # =====================
        # ensure download folder
        # =====================

        download_dir = os.path.dirname(os.path.abspath(out_path))
        if download_dir:
            os.makedirs(download_dir, exist_ok=True)

        # =====================
        # open imagine page
        # =====================

        await page.goto("https://grok.com/imagine", timeout=60000)

        if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
            raise asyncio.CancelledError()

        # =====================
        # set aspect ratio
        # =====================

        ratio_btn = page.locator(SELECTOR_ASPECT_BUTTON).filter(
            has=page.locator("svg")
        ).first

        await ratio_btn.wait_for(state="visible", timeout=15000)

        ratio_clean = str(ratio or "").strip()

        if ratio_clean:

            # =====================
            # get current ratio
            # =====================
            current_ratio = ""

            try:
                current_ratio = (await ratio_btn.locator("span").inner_text()).strip()
            except:
                pass

            # =====================
            # skip nếu đã đúng
            # =====================
            if current_ratio == ratio_clean:
                print(f"[SKIP] Ratio already = {current_ratio}")

            else:
                await ratio_btn.click()
                await page.wait_for_timeout(300)

                ratio_option = page.locator(
                    f'div[role="menuitem"]:has(span:text-matches("^\\\\s*{re.escape(ratio_clean)}\\\\s*$", "i"))'
                ).first

                await ratio_option.wait_for(state="visible", timeout=10000)
                await ratio_option.scroll_into_view_if_needed()
                await ratio_option.click(force=True)

                await page.wait_for_timeout(500)

                # verify lại
                try:
                    new_ratio = (await ratio_btn.locator("span").inner_text()).strip()
                except:
                    new_ratio = ""

                if new_ratio == ratio_clean:
                    print(f"[OK] Ratio set = {new_ratio}")

        # =====================
        # select IMAGE mode (before upload)
        # =====================

        image_mode_btn = page.locator(SELECTOR_IMAGE_MODE).first

        await image_mode_btn.wait_for(state="visible", timeout=10000)

        # chỉ click nếu chưa được chọn
        aria_checked = await image_mode_btn.get_attribute("aria-checked")

        if aria_checked != "true":
            await image_mode_btn.click()

        await asyncio.sleep(0.5)

        # =====================
        # upload images
        # =====================

        async def _wait_attachments_count_at_least(n: int, timeout_ms: int = 60000):
            n = int(n)
            loc = page.locator(SELECTOR_IMAGE_ATTACHMENTS)
            deadline = asyncio.get_event_loop().time() + (float(timeout_ms) / 1000.0)
            while asyncio.get_event_loop().time() < deadline:
                try:
                    c = await loc.count()
                except Exception:
                    c = 0
                if c >= n:
                    return True
                await asyncio.sleep(0.5)
            return False

        def _norm_img(v):
            s = str(v or '').strip()
            if not s:
                return ''
            low = s.lower()
            if low in ('null', 'none', 'undefined', 'nan'):
                return ''
            return s

        img1 = _norm_img(image1)
        img2 = _norm_img(image2)

        if not img1:
            raise ValueError('Missing image1')

        upload = page.locator(UPLOAD_INPUT).first
        await upload.wait_for(state="attached", timeout=30000)

        if img2:
            await upload.set_input_files([img1, img2])
            await _wait_attachments_count_at_least(2, timeout_ms=60000)
            await asyncio.sleep(1)
        else:
            await upload.set_input_files([img1])
            await _wait_attachments_count_at_least(1, timeout_ms=60000)
            await asyncio.sleep(1)

        if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
            raise asyncio.CancelledError()

        # =====================
        # wait prompt editor
        # =====================

        editor = page.locator(PROMPT_EDITOR).first
        await editor.wait_for(timeout=60000)

        await asyncio.sleep(1)
        await editor.click()
        await asyncio.sleep(0.5)
        await editor.fill(prompt)

        # Snapshot existing thumbnails to avoid picking stale results when multiple tabs are running
        before_srcs = set()
        try:
            thumbs0 = page.locator(SELECTOR_THUMBNAILS)
            c0 = await thumbs0.count()
            if c0 > 0:
                s = await thumbs0.first.get_attribute("src")
                if s:
                    before_srcs.add(str(s))
        except Exception:
            before_srcs = set()

        if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
            raise asyncio.CancelledError()

        # =====================
        # click CREATE
        # =====================
        await asyncio.sleep(1)
        send_btn = page.locator(SELECTOR_SUBMIT_SEND)

        if await send_btn.count() > 0:
            await send_btn.first.click()
        else:
            create_btn = page.locator(SELECTOR_CREATE_BUTTON)
            await create_btn.first.click()

        await page.wait_for_timeout(1000)

        # =====================
        # wait overlay disappear
        # =====================

        overlay = page.locator(SELECTOR_CREATING_OVERLAY)

        try:

            await overlay.first.wait_for(state="visible", timeout=20000)

            await page.wait_for_selector(
                SELECTOR_CREATING_OVERLAY,
                state="hidden",
                timeout=180000
            )

        except:
            pass

        await asyncio.sleep(1)

        # =====================
        # WAIT GENERATED THUMB URL
        # =====================

        thumb_url = None

        for _ in range(150):
            if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
                raise asyncio.CancelledError()

            try:
                img = page.locator("article img").first
                src = await img.get_attribute("src")
                if src and "/generated/" in str(src) and src not in before_srcs:
                    thumb_url = src
                    break
            except Exception:
                pass

            if not thumb_url:
                try:
                    thumbs = page.locator(SELECTOR_THUMBNAILS)
                    c = await thumbs.count()
                    if c > 0:
                        src0 = await thumbs.first.get_attribute("src")
                        if src0 and "/generated/" in str(src0) and src0 not in before_srcs:
                            thumb_url = str(src0)
                            break
                except Exception:
                    pass

            if thumb_url:
                break

            await asyncio.sleep(0.5)

        if not thumb_url:
            raise RuntimeError("Cannot find generated thumbnail url")

        # =====================
        # DOWNLOAD IMAGE BY URL (using request API to avoid navigating away)
        # =====================

        resp = await page.request.get(thumb_url, timeout=120000)

        if resp is None:
            raise RuntimeError("Image response is null")

        body = await resp.body()

        if not body or len(body) < 10000:
            raise RuntimeError("Image body too small")

        with open(out_path, "wb") as f:
            f.write(body)

        for _ in range(10):

            if os.path.exists(out_path) and os.path.getsize(out_path) > 20000:
                return out_path

            await asyncio.sleep(0.5)

        raise RuntimeError("Image file not stable")

    finally:
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass

        try:
            tid = str(task_id or '').strip()
            if tid and _ACTIVE_IMAGE_PAGES.get(tid) is page:
                _ACTIVE_IMAGE_PAGES.pop(tid, None)
        except Exception:
            pass
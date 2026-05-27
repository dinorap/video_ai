"""
Các thao tác Playwright trên trang Google Flow.
Tách riêng để dễ mở rộng: youtube, banana, veo3...
"""


class FlowStoppedError(Exception):
    """Ném khi user bấm Stop trong lúc retry (goto/click project, ...)."""
    pass


import asyncio
from typing import Optional, Callable, Tuple, List
import requests 
from playwright.async_api import async_playwright, Page, Browser, TimeoutError
import random
import re

# Radix tab id suffix trên Flow (tạo ảnh): trigger-LANDSCAPE, …, LANDSCAPE_4_3, SQUARE, …
_FLOW_RATIO_TAB_SUFFIX: dict[str, str] = {
    "16:9": "LANDSCAPE",
    "9:16": "PORTRAIT",
    "4:3": "LANDSCAPE_4_3",
    "1:1": "SQUARE",
    "3:4": "PORTRAIT_3_4",
}


def _normalize_flow_aspect_ratio(raw: Optional[str]) -> str:
    if not raw:
        return "16:9"
    s = str(raw).strip().lower().replace(" ", "").replace("/", ":")
    compact = {"169": "16:9", "916": "9:16", "43": "4:3", "11": "1:1", "34": "3:4"}
    if s in compact:
        return compact[s]
    if s in _FLOW_RATIO_TAB_SUFFIX:
        return s
    return "16:9"


def clamp_aspect_ratio_for_flow_video(raw: Optional[str]) -> str:
    """Flow video chỉ có 16:9 / 9:16 — map tỉ lệ ảnh về tab gần nhất."""
    key = _normalize_flow_aspect_ratio(raw)
    if key in ("4:3", "1:1"):
        return "16:9"
    if key == "3:4":
        return "9:16"
    return key


def _normalize_flow_model_label_ui(s: str) -> str:
    """
    Chuẩn hoá label model giữa Frontend và Flow UI (menu / pill).
    """
    s = (s or "").strip().lower()
    s = " ".join(s.split())
    s = re.sub(
        r"\(\s*(leaving|remaining|left)\s+\d+\s*/\s*\d+\s*\)",
        " ",
        s,
        flags=re.I,
    )
    s = " ".join(s.split())
    s = s.replace("lower priority", "low priority")
    s = s.replace("veo3.1", "veo 3.1")
    s = s.replace("veo3", "veo 3")
    s = s.replace(" - ", " ")
    s = s.replace("[", "").replace("]", "")
    s = re.sub(r"[^a-z0-9.\s]", " ", s)
    s = " ".join(s.split())
    return s


# Cache Playwright instance và browser connections
import threading
import time
import os

# Import playwright_stealth nếu có (optional)
_HAS_STEALTH = False
try:
    from playwright_stealth import Stealth
    _HAS_STEALTH = True
except ImportError as e:
    _HAS_STEALTH = False
    # Chỉ in warning nếu thực sự không tìm thấy module (không phải lỗi khác)
    if "playwright_stealth" in str(e) or "No module named 'playwright_stealth'" in str(e):
        print("[Flow Actions] ⚠️ playwright_stealth chưa được cài đặt. Chạy: pip install playwright-stealth")
    else:
        # Có thể là lỗi khác, in ra để debug
        print(f"[Flow Actions] ⚠️ Lỗi import playwright_stealth: {e}")
except Exception as e:
    _HAS_STEALTH = False
    print(f"[Flow Actions] ⚠️ Lỗi không xác định khi import playwright_stealth: {e}")
_BROWSER_CACHE: dict[str, Browser] = {}
_GLOBAL_LOCK = threading.Lock()
FLOW_LOG_EVENTS_URL = "https://aisandbox-pa.googleapis.com/v1/flow:batchLogFrontendEvents"
FLOW_LOG_EVENTS_KEY = "flow:batchLogFrontendEvents"
FLOW_UPLOAD_IMAGE_KEY = "/v1/flow/uploadImage"
# Ô nhập prompt Flow (Slate). Class sc-* đổi liên tục — chỉ dùng role + slate + contenteditable.
_FLOW_SLATE_PROMPT_SELECTOR = '[role="textbox"][contenteditable="true"][data-slate-editor="true"]'


class UploadPolicyViolationError(Exception):
    """Ném khi upload ảnh tham chiếu bị Google từ chối do policy."""
    pass


async def connect_and_get_page(ws_endpoint: str) -> Optional[Page]:
    # ❌ XÓA HẾT CODE CŨ TRONG HÀM NÀY ĐI Ạ

    # ✅ DÁN CODE MỚI NÀY VÀO:
    if not ws_endpoint: return None
    # 1. Dùng khóa vật lý chặn xung đột khởi tạo
    with _GLOBAL_LOCK: 
        pass 

    # Không tái dùng Browser/Page từ _BROWSER_CACHE giữa hai luồng asyncio khác nhau
    # (vd: NST Setup xong đóng loop, rồi Run YouTube mở loop mới): Playwright gắn với loop tạo ra nó,
    # dùng lại → page.goto lỗi kiểu 'NoneType' object has no attribute 'send'.
    # Cache chỉ để detach/cleanup; mỗi lần vào đây vẫn connect_over_cdp mới cho đúng loop hiện tại.

    try:
        print(f"[Flow Actions] 🔌 Init Playwright riêng cho luồng: {ws_endpoint}...")

        # 2. Tạo Playwright mới tinh (Không dùng biến Global) -> Fix lỗi Closed Pipe
        pw = await async_playwright().start()

        # 3. Kết nối
        browser = await pw.chromium.connect_over_cdp(ws_endpoint)
        
        # 4. 🔥 QUAN TRỌNG: Gắn Playwright vào Browser để nó không bị xóa bộ nhớ
        browser._my_owner_playwright = pw 
        
        # Lưu cache chỉ để cleanup, không dùng để tái sử dụng
        _BROWSER_CACHE[ws_endpoint] = browser

        # 5. Lấy Page
        if not browser.contexts:
            context = await browser.new_context()
        else:
            context = browser.contexts[0]

        if not context.pages:
            page = await context.new_page()
        else:
            page = context.pages[0]

        # 🔥 ẨN AUTOMATION FLAGS - Chống reCAPTCHA v3 phát hiện
        await page.add_init_script("""
            try {
                // 1. TUYỆT ĐỐI KHÔNG CHẠY đoạn sửa navigator.webdriver nữa 
                // (Vì NST đã làm nó thành false rồi, sửa thành undefined là dính chấu ngay).

                // 2. Xóa dấu vết của Playwright (Cái này NST không xóa được, phải tự làm)
                // Biến cdc_ là tử huyệt của Playwright/Puppeteer
                for (const prop in window) {
                    if (prop.match(/^cdc_[a-z0-9]/ig)) {
                        delete window[prop];
                    }
                }
                
                // 3. Fake Permissions (Giữ lại cái này cho chắc ăn, phòng khi popup hiện lên)
                if (window.navigator.permissions) {
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                }

                // 4. Fake Chrome Object (Nếu NST chưa fake kỹ thì bồi thêm)
                if (!window.chrome) {
                    window.chrome = {
                        runtime: { connect: () => {}, sendMessage: () => {} },
                        app: { isInstalled: false }
                    };
                }

            } catch (err) {
                // Lặng lẽ bỏ qua lỗi
            }
        """)

        # 🔥 Áp dụng Stealth Mode nếu có playwright_stealth
        if _HAS_STEALTH:
            try:
                stealth = Stealth()
                await stealth.apply_stealth_async(page)
                print("[Flow Actions] ✅ Đã áp dụng Stealth Mode")
            except Exception as e:
                print(f"[Flow Actions] ⚠️ Lỗi áp dụng Stealth Mode: {e}")

        try: await page.bring_to_front()
        except: pass

        return page

    except Exception as e:
        print(f"[Flow Actions] ❌ Lỗi kết nối CDP: {e}")
        return None
    

async def goto_flow_and_open_project(
    page: Page,
    flow_url: str = "https://labs.google/fx/vi/tools/flow",
    *,
    stop_check: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Điều hướng tới Flow URL.
    
    Lưu ý: Playwright qua CDP không thể điều khiển address bar của Chrome trực tiếp.
    Keyboard events chỉ hoạt động trong nội dung trang web, không phải UI của browser.
    Vì vậy, dùng page.goto() là cách duy nhất và đúng đắn.
    
    Trước khi goto, mô phỏng một số hành vi tự nhiên (di chuột, click) để giống người dùng.
    Sau đó click nút "Dự án mới" hoặc "Tạo dự án".
    """
    try:
        # Bring page to front
        try:
            await page.bring_to_front()
            await asyncio.sleep(random.uniform(0.3, 0.6))
        except Exception:
            pass

        # 🔥 Mô phỏng hành vi người dùng: ấn Ctrl+L (như thể chuẩn bị gõ URL)
        try:
            await page.keyboard.press("Control+L")
            await asyncio.sleep(random.uniform(0.8, 1.5))
        except Exception:
            await asyncio.sleep(random.uniform(0.8, 1.5))

        # 🔥 Dùng goto() để điều hướng thực sự (vì không thể gõ vào address bar qua CDP)
        print(f"[Flow Actions] 🌐 Điều hướng tới Flow...")
        await page.goto(flow_url, wait_until="domcontentloaded", timeout=30_000)
        # Đợi UI Flow render xong (chỗ chọn dự án hiện lên) - tránh bấm khi chưa load
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # 🔥 Warm-up nhẹ sau khi load: move nhỏ để giống người dùng (không scroll)
        try:
            viewport = page.viewport_size or {"width": 1280, "height": 720}
            x = random.randint(120, viewport["width"] - 120)
            y = random.randint(120, viewport["height"] - 120)
            await page.mouse.move(x, y, steps=random.randint(15, 40))
        except Exception:
            pass

    except Exception as e:
        print(f"[Flow Actions] ❌ Lỗi điều hướng tới Flow: {e}")
        # Retry một lần nữa
        try:
            await page.goto(flow_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(random.uniform(1.5, 2.5))
        except Exception as e2:
            print(f"[Flow Actions] ❌ Retry cũng thất bại: {e2}")
            raise

    # Sau khi đã ở Flow -> mở project mới (retry + đợi project ready)
    await wait_and_click_project_button(page, stop_check=stop_check)
    # Đợi ô prompt Slate hiện ra rồi mới cho select_mode/setup chạy
    await wait_for_project_ready(page)
    # Theo flow mới: mở Cài đặt và chọn tab Batch trước khi select_mode/setup.
    await open_settings_and_select_batch(page)


async def wait_for_project_ready(page: Page, timeout_ms: int = 45_000) -> None:
    """
    Đợi đến khi ô nhập prompt Flow (Slate) hiện ra.
    Poll ngắn (tránh vòng 1s/lần + sleep dài sau khi đã visible).
    """
    try:
        prompt = page.locator(_FLOW_SLATE_PROMPT_SELECTOR).first
        deadline = time.monotonic() + max(0.5, timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            try:
                if await prompt.is_visible():
                    await asyncio.sleep(random.uniform(0.1, 0.22))
                    return
            except Exception:
                pass
            await asyncio.sleep(0.14)
    except Exception:
        pass
    raise Exception("Timeout: Không thấy ô nhập prompt sau khi tạo dự án")


_JS_CHECK_AND_DISABLE_AGENT = r"""
async function () {
    const agentBtn = [...document.querySelectorAll('button')]
        .find(b => b.querySelector('.content')?.textContent.trim() === 'Tác nhân');

    if (!agentBtn) {
        return { ok: false, reason: 'Không tìm thấy nút "Tác nhân".' };
    }

    if (agentBtn.getAttribute('aria-pressed') === 'true') {
        ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(type => {
            agentBtn.dispatchEvent(new MouseEvent(type, {
                bubbles: true,
                cancelable: true,
                view: window
            }));
        });
        return { ok: true, reason: 'Tác nhân đang bật -> Đã bấm tắt thành công.' };
    } else {
        return { ok: true, reason: 'Tác nhân chưa bật -> Không cần bấm.' };
    }
}
"""

_JS_OPEN_SETTINGS_AND_BATCH = r"""
async function () {
    const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    const simulateEnterClick = async (el) => {
        el.focus();
        el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
        el.click();
        await wait(50);
    };

    const settingsBtn = Array.from(document.querySelectorAll('button')).find(btn =>
        btn.innerText.includes('Xem chế độ cài đặt lưới ô') ||
        (btn.querySelector('i') && btn.querySelector('i').innerText.includes('settings_2'))
    );

    if (!settingsBtn) {
        return { ok: false, reason: "Không tìm thấy nút Cài đặt (settings_2)." };
    }

    await simulateEnterClick(settingsBtn);
    await wait(180);

    const batchTab = Array.from(document.querySelectorAll('button[role="tab"]')).find(btn =>
        btn.innerText.includes('Batch') ||
        (btn.querySelector('i') && btn.querySelector('i').innerText.includes('campaign_all'))
    );

    if (!batchTab) {
        return { ok: false, reason: "Mở cài đặt rồi nhưng không thấy tab Batch." };
    }

    await simulateEnterClick(batchTab);
    return { ok: true, reason: "Đã mở cài đặt và chọn tab Batch." };
}
"""


async def check_and_disable_agent_button(page: Page) -> bool:
    """
    Kiểm tra và tắt nút "Tác nhân" (Agent) nếu đang bật.
    Phải chạy TRƯỚC khi setup batch settings để các tùy chọn khác hiện ra.
    """
    try:
        result = await page.evaluate(_JS_CHECK_AND_DISABLE_AGENT)
        if result and result.get("ok"):
            reason = result.get("reason", "")
            print(f"[Flow Actions] ✅ {reason}")
            return True
        reason = (result or {}).get("reason") if isinstance(result, dict) else "Không rõ lý do."
        print(f"[Flow Actions] ⚠️ Kiểm tra nút Tác nhân: {reason}")
        return False
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Lỗi kiểm tra nút Tác nhân: {e}")
        return False


async def select_batch_tab_size_medium(page: Page) -> bool:
    """
    Trong dialog Cài đặt > Batch: chọn nhóm kích thước **M** (S / M / L).
    Không dựa vào class sc-*; dùng role=tab + hậu tố Radix MEDIUM hoặc aria-label.
    """
    try:
        m_tab = page.locator(
            'button[role="tab"].flow_tab_slider_trigger[id$="-trigger-MEDIUM"]'
        ).first
        if await m_tab.count() <= 0:
            m_tab = page.locator('button[role="tab"][aria-label="Trung bình"]').first
        await m_tab.wait_for(state="visible", timeout=3_500)
        try:
            sel = await m_tab.get_attribute("aria-selected")
            if (sel or "").strip().lower() == "true":
                print("[Flow Actions] ✅ Batch: kích thước M (Trung bình) đã chọn sẵn.")
                return True
        except Exception:
            pass
        await m_tab.scroll_into_view_if_needed()
        await m_tab.click(delay=random.randint(50, 130), force=True, timeout=4_000)
        await asyncio.sleep(random.uniform(0.12, 0.28))
        print("[Flow Actions] ✅ Batch: đã chọn kích thước M (Trung bình).")
        return True
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Batch: không chọn được nút M (Trung bình): {e}")
        return False


async def open_settings_and_select_batch(page: Page) -> bool:
    """
    Chạy ngay sau khi tạo project: 
    1. Kiểm tra và tắt nút "Tác nhân" nếu đang bật (để các tùy chọn khác hiện ra)
    2. Mở Cài đặt và chọn tab Batch
    3. Chọn cỡ M trong nhóm S/M/L
    """
    try:
        # Bước 1: Kiểm tra và tắt nút "Tác nhân" nếu đang bật
        await check_and_disable_agent_button(page)
        await asyncio.sleep(random.uniform(0.15, 0.3))
        
        # Bước 2: Mở Cài đặt và chọn tab Batch
        result = await page.evaluate(_JS_OPEN_SETTINGS_AND_BATCH)
        if result and result.get("ok"):
            print("[Flow Actions] ✅ Đã mở Cài đặt -> tab Batch.")
            await asyncio.sleep(random.uniform(0.06, 0.14))
            
            # Bước 3: Chọn kích thước M
            await select_batch_tab_size_medium(page)
            return True
        reason = (result or {}).get("reason") if isinstance(result, dict) else "Không rõ lý do."
        print(f"[Flow Actions] ⚠️ Không chuyển được sang tab Batch: {reason}")
        return False
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Lỗi mở Cài đặt -> Batch: {e}")
        return False


async def is_flow_setup_ready(page: Page) -> bool:
    """
    Kiểm tra nhanh xem đang ở màn hình Flow đã có ô prompt Slate chưa.
    Dùng để tránh goto + setup lặp lại khi user vừa bấm Test Setup xong.
    """
    try:
        return await page.locator(_FLOW_SLATE_PROMPT_SELECTOR).first.is_visible()
    except Exception:
        return False


async def wait_and_click_project_button(
    page: Page,
    timeout_ms: int = 30_000,
    max_retries: int = 5,
    *,
    stop_check: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Đợi UI chọn dự án hiện ra, đợi nút tạo dự án VISIBLE rồi mới click. Có retry.
    Nếu stop_check() trả về True thì dừng retry ngay và ném FlowStoppedError.
    """
    last_err = None
    for retry in range(max_retries):
        if stop_check and stop_check():
            raise FlowStoppedError("Stopped by user")
        try:
            # Đợi nút thực sự VISIBLE (không chỉ có trong DOM)
            icon_btn = page.locator("button:has(i:text('add_2'))").first
            try:
                await icon_btn.wait_for(state="visible", timeout=timeout_ms)
            except TimeoutError:
                icon_btn = None

            if icon_btn and await icon_btn.is_visible():
                await asyncio.sleep(random.uniform(0.22, 0.45))  # Đợi UI ổn định rồi mới bấm
                await icon_btn.scroll_into_view_if_needed()
                await icon_btn.click(delay=random.randint(80, 250), force=True)
            else:
                # Fallback theo text - đợi visible rồi mới bấm
                clicked = False
                for text in ["Dự án mới", "Tạo dự án"]:
                    btn = page.locator(f"button:has-text('{text}')").first
                    try:
                        await btn.wait_for(state="visible", timeout=10_000)
                        if await btn.is_visible():
                            await asyncio.sleep(random.uniform(0.22, 0.45))
                            await btn.scroll_into_view_if_needed()
                            await btn.click(delay=random.randint(80, 250), force=True)
                            clicked = True
                            break
                    except TimeoutError:
                        continue
                if not clicked:
                    raise Exception("Không tìm thấy nút tạo dự án (text hoặc icon add_2)")

            # ✅ Xác nhận click đã "ăn": phải thấy ô prompt Slate (contenteditable) xuất hiện.
            # Nếu Playwright đơ click, đoạn này sẽ timeout và retry.
            try:
                await wait_for_project_ready(page, timeout_ms=20_000)
            except Exception:
                # Cho thêm 1 nhịp nhỏ rồi check lại (tránh false negative)
                await asyncio.sleep(random.uniform(0.4, 0.75))
                await wait_for_project_ready(page, timeout_ms=20_000)
            return

        except FlowStoppedError:
            raise
        except Exception as e:
            last_err = e
            if retry < max_retries - 1:
                if stop_check and stop_check():
                    raise FlowStoppedError("Stopped by user")
                print(f"[Flow Actions] ⚠️ Retry tạo dự án lần {retry + 1}/{max_retries}...")
                await asyncio.sleep(random.uniform(2.0, 3.0))

    raise last_err or Exception("Không tìm thấy nút tạo dự án (text hoặc icon add_2)")



async def cleanup_browser(ws_endpoint: str) -> None:
    """
    Đóng sạch browser/contexts đã connect qua Playwright.
    Dùng trước khi gọi NST stop để tránh assertion error.
    """
    global _BROWSER_CACHE
    browser = _BROWSER_CACHE.get(ws_endpoint)
    if not browser:
        return

    try:
        for ctx in list(browser.contexts):
            try:
                await ctx.close()
            except Exception:
                pass
        await browser.close()
        if hasattr(browser, '_my_owner_playwright'):
            await browser._my_owner_playwright.stop()
    except Exception:
        pass

    _BROWSER_CACHE.pop(ws_endpoint, None)


async def cleanup_all_browsers() -> None:
    """
    Cleanup tất cả browser đã cache.
    """
    for ws in list(_BROWSER_CACHE.keys()):
        await cleanup_browser(ws)


async def detach_browser_session(ws_endpoint: str) -> None:
    """
    Chỉ detach Playwright/CDP session khỏi browser đang chạy,
    KHÔNG đóng context/page của Chrome thật.
    """
    global _BROWSER_CACHE
    browser = _BROWSER_CACHE.get(ws_endpoint)
    if not browser:
        return
    try:
        if hasattr(browser, "_my_owner_playwright"):
            await browser._my_owner_playwright.stop()
    except Exception:
        pass
    _BROWSER_CACHE.pop(ws_endpoint, None)


def reset_flow_delay_counter() -> None:
    """
    Hàm giữ lại để tương thích với nst_flow.
    Logic stagger theo luồng đã được gỡ bỏ, nên hiện tại chỉ log cho dễ debug.
    """
    print("[Flow Actions] 🔄 reset_flow_delay_counter() được gọi (stagger per-thread hiện đã tắt).")


async def random_delay_before_action(min_seconds: float = 0.0, max_seconds: float = 0.0) -> None:
    """
    Random delay nhẹ trước khi gửi prompt/upload ảnh để tránh các request dồn cùng một thời điểm.
    Hiện tại KHÔNG còn stagger theo luồng/counter; chỉ dùng khoảng [min_seconds, max_seconds] nếu được truyền vào.

    Args:
        min_seconds: Delay tối thiểu (mặc định 0s)
        max_seconds: Delay tối đa (mặc định 0s – tức là không delay)
    """
    # Chế độ chạy nhanh: bỏ hoàn toàn random delay trước thao tác.
    return


def _is_flow_log_events_request(req) -> bool:
    try:
        url = (req.url or "")
        return url.startswith(FLOW_LOG_EVENTS_URL) or (FLOW_LOG_EVENTS_KEY in url)
    except Exception:
        return False


def _has_flow_upload_event(req) -> bool:
    """
    Ưu tiên bắt đúng event upload/crop từ payload log; nếu không đọc được payload thì fallback theo URL.
    """
    try:
        post = (req.post_data or "") if req else ""
        return ("FLOW_UPLOAD" in post) or ("FLOW_IMAGE_LATENCY" in post) or ("PINHOLE_CROP_IMAGE" in post) or not post
    except Exception:
        return True


async def _wait_for_upload_api_log(page: Page, timeout_seconds: float = 45.0) -> Tuple[bool, Optional[str]]:
    """
    Đợi tín hiệu upload ảnh thành công sau khi set file + bấm Cắt/Lưu.
    Ưu tiên API mới `.../v1/flow/uploadImage` (response 2xx),
    fallback về log events cũ để tương thích ngược.
    """
    done_evt = asyncio.Event()
    log_evt = asyncio.Event()
    ctx = page.context
    result = {"ok": False, "policy_message": None}

    def _on_request(req):
        if done_evt.is_set():
            return
        if _is_flow_log_events_request(req) and _has_flow_upload_event(req):
            log_evt.set()

    def _on_response(resp):
        if done_evt.is_set():
            return
        try:
            url = (resp.url or "")
            status = int(resp.status or 0)
            # API upload mới: chỉ cần thấy response 2xx là đủ xác nhận upload đã lên server.
            if (FLOW_UPLOAD_IMAGE_KEY in url) and (200 <= status < 300):
                result["ok"] = True
                done_evt.set()
                return
            if (FLOW_UPLOAD_IMAGE_KEY in url) and status >= 400:
                async def _parse_policy_error() -> None:
                    policy_message = "Ảnh tham chiếu vi phạm chính sách Google. Vui lòng đổi ảnh khác."
                    try:
                        body = await resp.json()
                        err = (body or {}).get("error", {}) or {}
                        details = err.get("details", []) or []
                        reasons = [str(d.get("reason") or "") for d in details if isinstance(d, dict)]
                        reason_blob = " ".join(reasons).upper()
                        message = str(err.get("message") or "")
                        status_text = str(err.get("status") or "")
                        if "PUBLIC_ERROR_MINOR_UPLOAD" not in reason_blob:
                            policy_message = (
                                "Upload ảnh tham chiếu bị Google từ chối. "
                                "Vui lòng đổi ảnh khác rồi chạy lại."
                            )
                        print(
                            f"[Flow Actions] ❌ UploadImage bị từ chối: "
                            f"status={status_text}, message={message}, reasons={reasons}"
                        )
                    except Exception:
                        pass
                    result["ok"] = False
                    result["policy_message"] = policy_message
                    if not done_evt.is_set():
                        done_evt.set()

                asyncio.create_task(_parse_policy_error())
        except Exception:
            return

    ctx.on("request", _on_request)
    ctx.on("response", _on_response)
    try:
        await asyncio.wait_for(done_evt.wait(), timeout=timeout_seconds)
        return bool(result["ok"]), result["policy_message"]
    except Exception:
        # Fallback tương thích ngược API cũ: nếu có log upload/crop thì coi là thành công.
        if log_evt.is_set():
            return True, None
        return False, None
    finally:
        try:
            ctx.remove_listener("request", _on_request)
        except Exception:
            pass
        try:
            ctx.remove_listener("response", _on_response)
        except Exception:
            pass


async def _select_consistent_voice_after_upload(
    page: Page,
    voice_name: str,
) -> bool:
    """
    Sau khi chọn ảnh upload, mở tab Giọng nói và chọn voice theo tên.
    Mục tiêu: đồng nhất giọng nhân vật trước khi gửi prompt.
    """
    chosen = str(voice_name or "").strip()
    if not chosen:
        return False
    try:
        # Giống flow test: sau khi upload ảnh phải bấm + thêm 1 lần để mở panel chọn giọng.
        create_btn = page.locator("button").filter(has=page.locator("i", has_text="add_2")).first
        await create_btn.wait_for(state="visible", timeout=12_000)
        await create_btn.scroll_into_view_if_needed()
        await create_btn.click(delay=random.randint(80, 180))
        await asyncio.sleep(random.uniform(0.35, 0.75))

        voice_tabs = page.locator('button[role="tab"]').filter(
            has_text=re.compile(r"Giọng nói|Voice", re.I),
        )
        await voice_tabs.first.wait_for(state="visible", timeout=10_000)
        await voice_tabs.first.scroll_into_view_if_needed()
        await voice_tabs.first.click(delay=random.randint(80, 180))
        await asyncio.sleep(random.uniform(0.25, 0.6))

        dialog_voice = page.locator('[role="dialog"]').filter(
            has=page.locator('[data-testid="virtuoso-item-list"]'),
        ).last
        list_root = dialog_voice.get_by_test_id("virtuoso-item-list")
        await list_root.wait_for(state="visible", timeout=10_000)

        quick = dialog_voice.locator("#quick-search-input").first
        if await quick.count() == 0:
            quick = page.locator("#quick-search-input").first
        await quick.wait_for(state="visible", timeout=10_000)
        await quick.scroll_into_view_if_needed()
        await quick.click()
        await quick.fill("")
        await quick.fill(chosen)
        await asyncio.sleep(random.uniform(0.25, 0.6))

        first_row = list_root.locator("div[data-item-index]").first
        await first_row.wait_for(state="visible", timeout=8_000)
        play_btn = first_row.locator("button").filter(
            has=page.locator("i", has_text="play_arrow"),
        ).first
        await play_btn.wait_for(state="visible", timeout=5_000)
        voice_info_div = play_btn.locator("xpath=preceding-sibling::div[1]")
        await voice_info_div.wait_for(state="visible", timeout=5_000)
        await voice_info_div.scroll_into_view_if_needed()
        await voice_info_div.click(delay=random.randint(80, 180))
        await asyncio.sleep(random.uniform(0.2, 0.45))
        print(f"[Flow Actions] 🎙️ Đã chọn voice đồng nhất: {chosen}")
        return True
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Không chọn được voice đồng nhất ({chosen}): {e}")
        return False


async def move_mouse_randomly(page: Page, duration_seconds: float) -> None:
    """
    Logic 80/20 "Stealth Waiting": 80% đứng im (tự nhiên) + 20% rung động nhẹ (tránh zombie tab).
    
    Sau khi gửi prompt, người dùng thật thường đứng im chờ kết quả (không "múa chuột").
    Nhưng cần một vài "rung động" nhẹ ở cuối để Google biết trình duyệt vẫn active.
    
    Args:
        page: Playwright Page object
        duration_seconds: Tổng thời gian chờ (giây)
    """
    start_time = asyncio.get_event_loop().time()
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    
    try:
        # Chia nhỏ thời gian chờ để "rung" nhẹ nhiều lần (không tăng tổng delay)
        # Tăng nhẹ tần suất & biên độ di chuyển cho tự nhiên hơn.
        segments = max(1, int(duration_seconds // 8))
        for i in range(segments):
            # Giữ phần lớn thời gian ở trạng thái idle
            await asyncio.sleep(duration_seconds / segments * 0.7)

            # Rung nhẹ 1 lần mỗi segment
            try:
                current_x = random.randint(100, viewport["width"] - 100)
                current_y = random.randint(100, viewport["height"] - 100)
                offset_x = random.randint(-20, 20)
                offset_y = random.randint(-20, 20)
                await page.mouse.move(
                    current_x + offset_x,
                    current_y + offset_y,
                    steps=random.randint(8, 18)
                )
            except Exception:
                pass

            # Phần thời gian còn lại của segment
            await asyncio.sleep(duration_seconds / segments * 0.3)
                    
    except Exception as e:
        # Nếu có lỗi, vẫn đảm bảo delay đủ thời gian
        print(f"[Flow Actions] ⚠️ Lỗi di chuyển chuột: {e}")
    finally:
        # 🔥 QUAN TRỌNG: Đảm bảo delay đủ thời gian ngay cả khi có exception
        elapsed = asyncio.get_event_loop().time() - start_time
        remaining = duration_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)


def _bezier_point(p0_x: float, p0_y: float, c_x: float, c_y: float, p1_x: float, p1_y: float, t: float) -> tuple[float, float]:
    """Điểm trên đường cong Bezier bậc 2: B(t) = (1-t)²P0 + 2(1-t)tC + t²P1."""
    u = 1.0 - t
    x = u * u * p0_x + 2 * u * t * c_x + t * t * p1_x
    y = u * u * p0_y + 2 * u * t * c_y + t * t * p1_y
    return (x, y)


async def _move_along_curve(
    page: Page,
    last_x: float, last_y: float,
    target_x: float, target_y: float,
    x_min: int, x_max: int, y_min: int, y_max: int,
    stop_event: asyncio.Event,
    curve_strength: float = 1.0,
) -> tuple[float, float]:
    """
    Di chuột theo đường cong Bezier từ (last_x, last_y) đến (target_x, target_y).
    curve_strength: độ lệch control point so với đoạn thẳng (pixel). Càng lớn càng cong.
    Trả về (x, y) cuối cùng (đã clamp).
    """
    mid_x = (last_x + target_x) / 2
    mid_y = (last_y + target_y) / 2
    dx = target_x - last_x
    dy = target_y - last_y
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    perp_x = -dy / length * curve_strength * random.uniform(30, 100)
    perp_y = dx / length * curve_strength * random.uniform(30, 100)
    if random.random() < 0.5:
        perp_x, perp_y = -perp_x, -perp_y
    c_x = mid_x + perp_x
    c_y = mid_y + perp_y
    steps = random.randint(20, 45)
    for i in range(steps):
        if stop_event.is_set():
            return (last_x, last_y)
        t_linear = (i + 1) / steps
        t = t_linear * t_linear * (3 - 2 * t_linear)
        x, y = _bezier_point(last_x, last_y, c_x, c_y, target_x, target_y, t)
        jitter_x = random.uniform(-1.5, 1.5)
        jitter_y = random.uniform(-1.5, 1.5)
        x = max(x_min, min(x_max, int(x + jitter_x)))
        y = max(y_min, min(y_max, int(y + jitter_y)))
        try:
            await page.mouse.move(x, y, steps=random.randint(2, 5))
        except Exception:
            return (last_x, last_y)
        delay = 0.012 + 0.028 * (1 - 2 * abs(t_linear - 0.5))
        await asyncio.sleep(random.uniform(delay * 0.8, delay * 1.2))
    return (max(x_min, min(x_max, int(target_x))), max(y_min, min(y_max, int(target_y))))


async def run_human_like_mouse_until(page: Page, stop_event: asyncio.Event) -> None:
    """
    Di chuột lung tung trong viewport (đường cong, hover ngẫu nhiên, đôi khi rê quá rồi quay lại)
    cho đến khi stop_event được set. Chỉ move, không scroll.
    """
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    margin = 80
    w, h = viewport["width"], viewport["height"]
    x_min = margin
    x_max = max(w - margin, margin + 1)
    y_min = margin
    y_max = max(h - margin, margin + 1)
    last_x = (x_min + x_max) // 2
    last_y = (y_min + y_max) // 2
    try:
        while not stop_event.is_set():
            # Hover lung tung: ~25% là rung nhẹ tại chỗ (5–25px), còn lại đi xa
            if random.random() < 0.25:
                target_x = last_x + random.uniform(-25, 25)
                target_y = last_y + random.uniform(-25, 25)
                target_x = max(x_min, min(x_max, target_x))
                target_y = max(y_min, min(y_max, target_y))
            else:
                target_x = random.randint(x_min, x_max)
                target_y = random.randint(y_min, y_max)

            # Rê quá nút rồi quay lại: ~22% đi qua đích một chút rồi mới về đích
            overshoot_then_return = random.random() < 0.22
            if overshoot_then_return:
                dx = target_x - last_x
                dy = target_y - last_y
                dist = (dx * dx + dy * dy) ** 0.5 or 1.0
                over = random.uniform(25, 65)
                past_x = target_x + (dx / dist) * over + random.uniform(-15, 15)
                past_y = target_y + (dy / dist) * over + random.uniform(-15, 15)
                past_x = max(x_min, min(x_max, past_x))
                past_y = max(y_min, min(y_max, past_y))
                last_x, last_y = await _move_along_curve(
                    page, last_x, last_y, past_x, past_y,
                    x_min, x_max, y_min, y_max, stop_event, curve_strength=0.8
                )
                if stop_event.is_set():
                    return
                last_x, last_y = await _move_along_curve(
                    page, last_x, last_y, target_x, target_y,
                    x_min, x_max, y_min, y_max, stop_event, curve_strength=0.6
                )
            else:
                last_x, last_y = await _move_along_curve(
                    page, last_x, last_y, target_x, target_y,
                    x_min, x_max, y_min, y_max, stop_event, curve_strength=1.0
                )

            if stop_event.is_set():
                return
            # Nghỉ giữa các lần di: đôi khi lâu (tự nhiên)
            if random.random() < 0.35:
                pause = random.uniform(1.2, 3.5)
            else:
                pause = random.uniform(0.2, 0.9)
            waited = 0.0
            while waited < pause:
                if stop_event.is_set():
                    return
                await asyncio.sleep(min(0.08, pause - waited))
                waited += 0.08
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Di chuột chờ ảnh/video: {e}")


# Nút mode (Video/Hình ảnh) chỉ có nhãn ngắn trên dòng đầu; nút model có dòng đầu là tên model (không khớp prefix).
_MODE_MENU_FIRST_LINE_MAX = 52
_MODE_MENU_FULL_TEXT_MAX = 72

# Pill chọn Video/Hình ảnh: Google dùng crop_16_9 hoặc tên symbol crop_landscape / crop_portrait / crop_square
# (đổi theo tỉ lệ) — không hard-code một icon cố định.
_FLOW_MATERIAL_ASPECT_ICON_RE = re.compile(
    r"crop_(?:\d+_\d+|landscape|portrait|square)",
    re.I,
)


def _text_looks_like_flow_mode_menu_trigger(text: str) -> bool:
    """
    Nút dropdown chọn mode: dòng đầu innerText bắt đầu bằng Video / Hình ảnh / Image.
    Không dùng tên model hay emoji (đổi liên tục); không dựa class sc-* (hash).
    """
    if not text:
        return False
    raw = text.strip()
    if not raw:
        return False
    first_line = " ".join(raw.splitlines()[0].split())
    if not first_line:
        return False
    if len(first_line) > _MODE_MENU_FIRST_LINE_MAX:
        return False
    t = " ".join(raw.split())
    if len(t) > _MODE_MENU_FULL_TEXT_MAX:
        return False
    if first_line.startswith("Video"):
        return True
    if first_line.startswith("Hình ảnh"):
        return True
    if re.match(r"^Image\b", first_line):
        return True
    return False


def _inner_text_has_flow_crop_icon_name(text: str) -> bool:
    """Có icon tỉ lệ Material trong pill: crop_16_9 hoặc crop_landscape / crop_portrait / crop_square."""
    if not text:
        return False
    return bool(_FLOW_MATERIAL_ASPECT_ICON_RE.search(text))


async def _resolve_flow_mode_menu_trigger(page: Page):
    """
    Trả về Locator nút mở menu chọn Image/Video (Radix), hoặc None.

    - UI cũ: dòng đầu Video / Hình ảnh / Image.
    - UI mới: pill hiển thị tên model + icon chữ crop_* + x1 — bắt qua ``i``/innerText
      có ``crop_W_H``, không dựa vào tên model (Nano Banana, v.v.).
    """
    buttons = page.locator('button[aria-haspopup="menu"]')
    try:
        n = await buttons.count()
    except Exception:
        n = 0

    # 1) Legacy: nhãn mode trên dòng đầu
    for i in range(n):
        el = buttons.nth(i)
        try:
            if not await el.is_visible():
                continue
            txt = ((await el.inner_text()) or "").strip()
            if _text_looks_like_flow_mode_menu_trigger(txt):
                return el
        except Exception:
            continue

    # 2) UI mới: button menu + icon crop_* (google-symbols: số crop_16_9 hoặc crop_landscape / portrait / square)
    try:
        with_overlay = page.locator('button[aria-haspopup="menu"]').filter(
            has=page.locator("i", has_text=_FLOW_MATERIAL_ASPECT_ICON_RE)
        ).filter(has=page.locator('[data-type="button-overlay"]'))
        if await with_overlay.count() > 0:
            cand = with_overlay.first
            if await cand.is_visible():
                return cand
    except Exception:
        pass
    try:
        crop_icons = page.locator('button[aria-haspopup="menu"]').filter(
            has=page.locator("i", has_text=_FLOW_MATERIAL_ASPECT_ICON_RE)
        )
        if await crop_icons.count() > 0:
            cand = crop_icons.first
            if await cand.is_visible():
                return cand
    except Exception:
        pass

    # 3) Fallback: innerText gộp vẫn có crop_W_H (icon là text node)
    for i in range(n):
        el = buttons.nth(i)
        try:
            if not await el.is_visible():
                continue
            txt = ((await el.inner_text()) or "").strip()
            if _inner_text_has_flow_crop_icon_name(txt):
                return el
        except Exception:
            continue
    return None


def _menu_inner_text_looks_like_mode_switch(blob: str) -> bool:
    """Menu chọn Image/Video: có Video và (Hình ảnh hoặc Image)."""
    if not blob:
        return False
    low = " ".join(blob.lower().split())
    if "video" not in low:
        return False
    if "hình ảnh" in low:
        return True
    return bool(re.search(r"\bimage\b", low))


async def _first_visible_role_menu(page: Page):
    """Menu Radix đang visible (có thể nhiều menu — ưu tiên menu chọn mode Image/Video)."""
    menus = page.locator('[role="menu"]')
    try:
        n = await menus.count()
    except Exception:
        return None
    for i in range(n):
        m = menus.nth(i)
        try:
            if not await m.is_visible():
                continue
            blob = (await m.inner_text()) or ""
            if _menu_inner_text_looks_like_mode_switch(blob):
                return m
        except Exception:
            continue
    for i in range(n):
        m = menus.nth(i)
        try:
            if await m.is_visible():
                return m
        except Exception:
            continue
    return None


async def _visible_mode_switch_menu_open(page: Page) -> bool:
    """Có đúng menu dropdown chọn Video / Hình ảnh đang mở (không nhầm menu model/Batch…)."""
    menus = page.locator('[role="menu"]')
    try:
        n = await menus.count()
    except Exception:
        return False
    for i in range(n):
        m = menus.nth(i)
        try:
            if not await m.is_visible():
                continue
            blob = (await m.inner_text()) or ""
            if _menu_inner_text_looks_like_mode_switch(blob):
                return True
        except Exception:
            continue
    return False


async def _is_flow_mode_dropdown_menu_visible(page: Page) -> bool:
    """Có bất kỳ [role=menu] visible (dùng ít — tránh nhầm với menu mode)."""
    menus = page.locator('[role="menu"]')
    try:
        n = await menus.count()
    except Exception:
        return False
    for i in range(n):
        try:
            if await menus.nth(i).is_visible():
                return True
        except Exception:
            continue
    return False


def _menu_item_text_matches_video_mode(txt: str) -> bool:
    line = " ".join((txt or "").strip().splitlines()[0].split())
    return bool(line.startswith("Video") and len(line) < 96)


def _menu_item_text_matches_image_mode(txt: str) -> bool:
    line = " ".join((txt or "").strip().splitlines()[0].split())
    if line.startswith("Hình ảnh"):
        return True
    return bool(re.match(r"^Image\b", line))


async def page_has_flow_mode_slider_tabs(page: Page) -> bool:
    """Trang có tab chọn IMAGE/VIDEO (id Radix *-trigger-IMAGE|VIDEO)."""
    for suf in ("IMAGE", "VIDEO"):
        try:
            loc = page.locator(f'[role="tab"][id$="-trigger-{suf}"]').first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def click_flow_mode_slider_tab(page: Page, mode: str) -> bool:
    """
    UI mới Flow: tab Radix Hình ảnh / Video — id *-trigger-IMAGE | *-trigger-VIDEO.
    Một locator gộp (CSS ,) + một lần wait — tránh 4 selector × timeout 4s lần lượt (cực chậm khi khớp sai).
    """
    m = (mode or "").strip().lower()
    if m not in ("image", "video"):
        return False
    suffix = "IMAGE" if m == "image" else "VIDEO"
    loc = None
    combined = page.locator(
        f'button[role="tab"][id$="-trigger-{suffix}"],'
        f'button[role="tab"].flow_tab_slider_trigger[id$="-trigger-{suffix}"],'
        f'[role="tab"][id$="-trigger-{suffix}"],'
        f'button[id$="-trigger-{suffix}"]'
    ).first
    try:
        await combined.wait_for(state="visible", timeout=650)
        if await combined.count() > 0:
            loc = combined
    except Exception:
        pass
    # Tab có trong DOM nhưng overlay/animation làm visible chậm — bấm force thay vì chờ thêm vài giây.
    if loc is None:
        try:
            await combined.wait_for(state="attached", timeout=400)
            if await combined.count() > 0:
                loc = combined
        except Exception:
            pass
    if loc is None:
        try:
            tablist = page.locator('[role="tablist"]').first
            if await tablist.count() > 0:
                if m == "image":
                    cand = tablist.locator('[role="tab"]').filter(
                        has_text=re.compile(r"Hình\s*ảnh|^Image\b", re.I)
                    ).first
                else:
                    cand = tablist.locator('[role="tab"]').filter(
                        has_text=re.compile(r"^Video\b")
                    ).first
                if await cand.count() > 0:
                    await cand.wait_for(state="visible", timeout=550)
                    loc = cand
        except Exception:
            pass
    if loc is None:
        return False
    try:
        try:
            if ((await loc.get_attribute("aria-selected")) or "").strip().lower() == "true":
                return True
        except Exception:
            pass
        await loc.scroll_into_view_if_needed()
        try:
            await loc.click(delay=random.randint(55, 130), timeout=3_500)
        except Exception:
            await loc.click(delay=random.randint(55, 130), force=True, timeout=3_500)
        return True
    except Exception as e:
        print(f"[Flow Actions] ⚠️ click_flow_mode_slider_tab: {e}")
        return False


async def click_flow_mode_menu_item(page: Page, mode: str) -> bool:
    """
    Chọn Video / Hình ảnh trong menu đã mở. Chỉ tìm trong [role=menu] —
    tránh click_tab_by_text toàn trang khớp nhầm nút trigger (bật/tắt dropdown).
    """
    m = (mode or "").strip().lower()
    if m not in ("image", "video"):
        return False
    try:
        menu = await _first_visible_role_menu(page)
        if menu is None:
            return False
        await menu.wait_for(state="visible", timeout=3_500)
        items = menu.locator('[role="menuitem"], [role="option"], button, [role="menuitemcheckbox"]')
        try:
            n = await items.count()
        except Exception:
            n = 0
        for idx in range(n):
            el = items.nth(idx)
            try:
                if not await el.is_visible():
                    continue
                txt = ((await el.inner_text()) or "").strip()
            except Exception:
                continue
            if m == "video" and not _menu_item_text_matches_video_mode(txt):
                continue
            if m == "image" and not _menu_item_text_matches_image_mode(txt):
                continue
            await el.scroll_into_view_if_needed()
            await el.click(delay=random.randint(50, 130), timeout=3_500)
            return True
        return False
    except Exception as e:
        print(f"[Flow Actions] ⚠️ click_flow_mode_menu_item: {e}")
        return False


async def click_combobox_preset(page: Page) -> bool:
    """
    Mở menu chọn mode (Image/Video): UI cũ hrlPny hoặc UI mới nút Video/Hình ảnh + crop_*.
    Chỉ bỏ qua click khi đúng menu mode (Video + Hình ảnh/Image) đã mở — không nhầm menu khác.
    """
    try:
        if await _visible_mode_switch_menu_open(page):
            return True

        preset_btn = await _resolve_flow_mode_menu_trigger(page)
        if preset_btn is None:
            legacy = page.locator("button.hrlPny[aria-haspopup='menu']").first
            try:
                if await legacy.count() > 0 and await legacy.is_visible():
                    preset_btn = legacy
            except Exception:
                preset_btn = None
        if preset_btn is None:
            return False

        await preset_btn.wait_for(state="visible", timeout=4_500)
        await preset_btn.scroll_into_view_if_needed()
        # Một lần click thật; tránh pointerdown + dispatch click rồi click lần 2 làm toggle đóng menu.
        await preset_btn.click(delay=random.randint(60, 140), timeout=5_000)
        end = time.monotonic() + 2.85
        while time.monotonic() < end:
            if await _visible_mode_switch_menu_open(page):
                return True
            await asyncio.sleep(0.12)
        await asyncio.sleep(0.1)
        if await _visible_mode_switch_menu_open(page):
            return True
        try:
            await preset_btn.click(delay=random.randint(60, 140), force=True, timeout=3_000)
            end2 = time.monotonic() + 2.35
            while time.monotonic() < end2:
                if await _visible_mode_switch_menu_open(page):
                    return True
                await asyncio.sleep(0.12)
            return await _visible_mode_switch_menu_open(page)
        except Exception:
            return await _visible_mode_switch_menu_open(page)
    except Exception:
        return False


async def _tab_button_looks_selected(btn) -> bool:
    """
    Heuristic giống click_tab_by_text: aria-selected / aria-pressed / data-state / class.
    """
    try:
        for attr in ("aria-selected", "aria-pressed"):
            try:
                v = await btn.get_attribute(attr)
                if v is not None and str(v).strip().lower() == "true":
                    return True
            except Exception:
                pass
        try:
            v = await btn.get_attribute("data-state")
            if v is not None and str(v).strip().lower() in {"active", "selected", "on", "true"}:
                return True
        except Exception:
            pass
        try:
            cls = await btn.get_attribute("class")
            if cls and any(tok in str(cls).lower() for tok in ("selected", "active", "is-selected", "is-active")):
                return True
        except Exception:
            pass
    except Exception:
        return False
    return False


async def click_flow_aspect_ratio_tab(
    page: Page, *, aspect_ratio: Optional[str] = None, portrait: Optional[bool] = None
) -> bool:
    """
    Chọn tab tỉ lệ Flow (Radix): LANDSCAPE (16:9), PORTRAIT (9:16),
    LANDSCAPE_4_3 (4:3), SQUARE (1:1), PORTRAIT_3_4 (3:4).

    - aspect_ratio: ưu tiên nếu có (chuẩn hoá qua _normalize_flow_aspect_ratio).
    - portrait: legacy — aspect_ratio=None thì True => 9:16, False => 16:9.
    """
    if aspect_ratio is not None and str(aspect_ratio).strip():
        key = _normalize_flow_aspect_ratio(aspect_ratio)
    elif portrait is not None:
        key = "9:16" if portrait else "16:9"
    else:
        key = "16:9"
    suffix = _FLOW_RATIO_TAB_SUFFIX.get(key, "LANDSCAPE")
    candidates = [
        page.locator(f'button[role="tab"][id$="-trigger-{suffix}"]').first,
        page.locator(f'button[role="tab"][aria-controls$="-content-{suffix}"]').first,
    ]
    for btn in candidates:
        try:
            if await btn.count() <= 0:
                continue
            await btn.wait_for(state="visible", timeout=10_000)
            await btn.scroll_into_view_if_needed()
            if await _tab_button_looks_selected(btn):
                # Đã đúng tab — không click thêm (tránh Radix toggle/chuyển tab).
                return True
            await btn.focus()
            await btn.dispatch_event(
                "keydown",
                {"key": "Enter", "code": "Enter", "keyCode": 13, "which": 13, "bubbles": True},
            )
            await asyncio.sleep(0.12)
            if await _tab_button_looks_selected(btn):
                return True
            for _ in range(3):
                await btn.click(delay=random.randint(60, 160), force=True, timeout=4_000)
                await asyncio.sleep(0.18)
                if await _tab_button_looks_selected(btn):
                    return True
            return True
        except Exception:
            continue

    ratio_label = key

    def _matcher_strict(txt: str) -> bool:
        """
        Chỉ khớp nhãn tỉ lệ thật, không khớp \"16:9\" bên trong \"916:9\".
        Cho phép hậu tố (UI: icon + label ở cuối).
        """
        s = (txt or "").strip()
        if key == "9:16":
            if re.search(r"9:16\s*$", s):
                return True
            return bool(re.search(r"(?<![0-9])9:16(?![0-9])", s))
        if key == "16:9":
            if re.search(r"16:9\s*$", s):
                return True
            return bool(re.search(r"(?<![0-9])16:9(?![0-9])", s))
        if key == "4:3":
            if re.search(r"4:3\s*$", s):
                return True
            return bool(re.search(r"(?<![0-9:])4:3(?![0-9])", s))
        if key == "1:1":
            if re.search(r"1:1\s*$", s):
                return True
            return bool(re.search(r"(?<![0-9:])1:1(?![0-9])", s))
        if key == "3:4":
            if re.search(r"3:4\s*$", s):
                return True
            return bool(re.search(r"(?<![0-9:])3:4(?![0-9])", s))
        return False

    return await click_tab_by_text(page, text_matcher=_matcher_strict, label=ratio_label)


async def verify_flow_aspect_ratio_selected(
    page: Page,
    *,
    aspect_ratio: Optional[str] = None,
    portrait: Optional[bool] = None,
    timeout_ms: int = 2500,
) -> bool:
    """Xác nhận tab tỉ lệ đang active (Radix), có fallback regex nhãn tỉ lệ."""
    if aspect_ratio is not None and str(aspect_ratio).strip():
        key = _normalize_flow_aspect_ratio(aspect_ratio)
    elif portrait is not None:
        key = "9:16" if portrait else "16:9"
    else:
        key = "16:9"
    suffix = _FLOW_RATIO_TAB_SUFFIX.get(key, "LANDSCAPE")
    label = key
    ratio_re = re.compile(rf"(?<![0-9]){re.escape(label)}(?![0-9])")
    end = time.monotonic() + max(0.2, timeout_ms / 1000.0)
    while time.monotonic() < end:
        for sel in (
            f'button[role="tab"][id$="-trigger-{suffix}"]',
            f'button[role="tab"][aria-controls$="-content-{suffix}"]',
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() <= 0 or not await loc.is_visible():
                    continue
                if await _tab_button_looks_selected(loc):
                    return True
            except Exception:
                pass
        try:
            loc2 = (
                page.locator("button[aria-selected='true']").filter(has_text=ratio_re).first
            )
            if await loc2.count() > 0 and await loc2.is_visible():
                return True
            loc3 = (
                page.locator("button[aria-pressed='true']").filter(has_text=ratio_re).first
            )
            if await loc3.count() > 0 and await loc3.is_visible():
                return True
        except Exception:
            pass
        await asyncio.sleep(0.15)
    return False


async def click_tab_by_text(page: Page, text_matcher, label: str) -> bool:
    """
    Theo test_flow_buttons.py:
    tìm button theo text rồi focus + Enter + click.
    """
    try:
        buttons = page.locator("button")
        count = await buttons.count()
        target_idx = -1
        for idx in range(count):
            el = buttons.nth(idx)
            try:
                txt = (await el.inner_text()) or ""
            except Exception:
                continue
            if text_matcher(txt):
                target_idx = idx
                break
        if target_idx < 0:
            print(f"[Flow Actions] ⚠️ Không tìm thấy button '{label}'.")
            return False

        btn = buttons.nth(target_idx)
        await btn.wait_for(state="visible", timeout=10_000)
        await btn.scroll_into_view_if_needed()
        # ✅ Nếu đã đúng trạng thái từ phiên trước:
        # Vẫn click lại cho "chắc" (best-effort) nhưng KHÔNG yêu cầu UI phải đổi.
        # (Flow thường nhớ state nên click không làm gì; nếu vẫn cố verify-change sẽ sai.)
        if await _tab_button_looks_selected(btn):
            # Tab đã active — không click (tránh một số Radix tab toggle sang tab khác).
            try:
                await btn.focus()
            except Exception:
                pass
            return True
        await btn.focus()
        await btn.dispatch_event(
            "keydown",
            {"key": "Enter", "code": "Enter", "keyCode": 13, "which": 13, "bubbles": True},
        )
       
        await asyncio.sleep(0.12)

        # Nếu Enter đã chọn xong thì KHÔNG click thêm để tránh toggle bật/tắt.
        if await _tab_button_looks_selected(btn):
            return True

        # Fallback: Enter chưa ăn → click thật + verify aria-selected.
        for _ in range(3):
            try:
                await btn.click(delay=random.randint(60, 160), force=True, timeout=4_000)
            except Exception:
                try:
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.08)
                    await btn.click(delay=random.randint(60, 160), force=True, timeout=4_000)
                except Exception:
                    pass
            await asyncio.sleep(0.18)
            if await _tab_button_looks_selected(btn):
                return True

        # Nếu không verify được theo các tín hiệu selection, vẫn best-effort True:
        # vì Flow có thể không expose selected state qua attribute/class.
        return True
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Lỗi click tab '{label}': {e}")
        return False


async def _verify_tab_selected(page: Page, label: str, timeout_ms: int = 2500) -> bool:
    """
    Verify button tab được chọn bằng aria-selected=true và có text chứa label.
    Nếu không verify được thì trả False để caller retry từ combobox preset.
    """
    end = time.monotonic() + max(0.2, timeout_ms / 1000.0)
    while time.monotonic() < end:
        try:
            # Ưu tiên aria-selected / aria-pressed (tùy phiên bản Flow UI)
            loc1 = page.locator("button[aria-selected='true']").filter(has_text=label).first
            if await loc1.count() > 0 and await loc1.is_visible():
                return True
            loc2 = page.locator("button[aria-pressed='true']").filter(has_text=label).first
            if await loc2.count() > 0 and await loc2.is_visible():
                return True
        except Exception:
            pass
        await asyncio.sleep(0.15)
    return False


async def _flow_ratio_tabs_visible(page: Page) -> bool:
    """Tab ratio 9:16 / 16:9 đã render và visible (thường nằm trong popover sau khi bấm pill Video)."""
    for pat in ("16:9", "9:16"):
        try:
            loc = page.locator('button[role="tab"]').filter(has_text=pat).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
            loc2 = page.locator("button").filter(has_text=pat).first
            if await loc2.count() > 0 and await loc2.is_visible():
                txt = " ".join((((await loc2.inner_text()) or "").strip()).split())
                if pat in txt and len(txt) < 28:
                    return True
        except Exception:
            continue
    return False


async def ensure_flow_mode_control_popover_open(page: Page) -> bool:
    """
    Pill Video / Hình ảnh (+ crop + x1): phải mở popover/panel trước khi chọn ratio/x1/…
    Chỉ bấm trigger khi chưa thấy tab 9:16/16:9 visible (tránh toggle đóng nếu đã mở).
    """
    try:
        if await _flow_ratio_tabs_visible(page):
            return True
        trig = await _resolve_flow_mode_menu_trigger(page)
        if trig is None:
            return False
        try:
            if ((await trig.get_attribute("aria-expanded")) or "").lower() == "true":
                await asyncio.sleep(0.35)
                if await _flow_ratio_tabs_visible(page):
                    return True
        except Exception:
            pass
        await trig.scroll_into_view_if_needed()
        await trig.click(delay=random.randint(55, 130), timeout=4_500)
        await asyncio.sleep(random.uniform(0.22, 0.45))
        if not await _flow_ratio_tabs_visible(page):
            print(
                "[Flow Actions] ⚠️ Đã bấm pill mode nhưng chưa thấy tab 9:16/16:9 — có thể UI khác hoặc cần thêm thao tác."
            )
        return True
    except Exception as e:
        print(f"[Flow Actions] ⚠️ ensure_flow_mode_control_popover_open: {e}")
        return False


async def _ensure_create_panel_open(page: Page) -> None:
    """
    Đảm bảo panel setup (Ngang/Dọc/1x) đang mở.
    Một số UI đóng panel ngay sau khi chọn mode, cần bấm lại nút add_2.
    """
    if await _wait_for_tab_candidates(
        page, ["Dọc", "Ngang", "1x", "x1", "9:16", "16:9"], timeout_ms=1200
    ):
        return
    try:
        create_btn = page.locator("button").filter(has=page.locator("i", has_text="add_2")).first
        await create_btn.wait_for(state="visible", timeout=5_000)
        await create_btn.click(delay=random.randint(80, 180))
        await asyncio.sleep(random.uniform(0.35, 0.7))
    except Exception:
        pass


async def _wait_for_flow_duration_tab_row(page: Page, timeout_ms: int = 1200) -> bool:
    """
    Video AI: có hàng tab thời lượng (4s, 8s, …) role=tab. Ảnh thường không có — probe ngắn để không tốn thời gian.
    """
    end = time.monotonic() + max(0.15, timeout_ms / 1000.0)
    dur_re = re.compile(r"^\s*\d+s\s*$", re.I)
    while time.monotonic() < end:
        try:
            tabs = page.locator('button[role="tab"]')
            n = await tabs.count()
            for i in range(min(n, 120)):
                t = tabs.nth(i)
                if await t.count() <= 0 or not await t.is_visible():
                    continue
                txt = ((await t.inner_text()) or "").strip()
                if dur_re.match(txt):
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.12)
    return False


async def _wait_for_tab_candidates(page: Page, candidates, timeout_ms: int = 8000) -> bool:
    """
    Chờ UI tab render ổn định trước khi click bước tiếp theo.
    """
    rounds = max(1, int(timeout_ms / 300))
    for _ in range(rounds):
        buttons = page.locator("button")
        count = await buttons.count()
        for idx in range(count):
            el = buttons.nth(idx)
            try:
                txt = (await el.inner_text()) or ""
            except Exception:
                continue
            if any(c in txt for c in candidates):
                return True
        await asyncio.sleep(0.3)
    return False


async def _click_flow_model_menu_trigger(page: Page) -> bool:
    """
    UI Flow mới: pill model dùng icon Material 'arrow_drop_down' trong <i>.
    Dùng JavaScript để force click giống code test thành công của user.
    """
    try:
        # Kiểm tra menu đã mở chưa
        menu_items = page.locator('[role="menuitem"]')
        if await menu_items.count() > 0:
            try:
                await menu_items.first.wait_for(state="visible", timeout=500)
                print(f"[Flow Actions] ✅ Menu model đã mở sẵn")
                return True
            except Exception:
                pass
        
        # 🔥 Dùng JavaScript để force click button - giống code test thành công
        clicked = await page.evaluate("""() => {
            const btn = [...document.querySelectorAll('button[aria-haspopup="menu"]')]
                .find(button => {
                    const icon = button.querySelector('i');
                    return icon && icon.textContent.trim() === 'arrow_drop_down';
                });

            if (!btn) {
                console.log('❌ Không tìm thấy nút mở menu model');
                return false;
            }

            btn.scrollIntoView({ block: 'center' });
            btn.focus();

            btn.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true,
                pointerType: 'mouse'
            }));

            btn.dispatchEvent(new MouseEvent('mousedown', {
                bubbles: true,
                cancelable: true
            }));

            btn.dispatchEvent(new MouseEvent('mouseup', {
                bubbles: true,
                cancelable: true
            }));

            btn.dispatchEvent(new MouseEvent('click', {
                bubbles: true,
                cancelable: true
            }));

            console.log('✅ Đã force click menu model');
            return true;
        }""")
        
        if not clicked:
            print(f"[Flow Actions] ❌ Không tìm thấy button menu model với icon arrow_drop_down")
            return False
        
        print(f"[Flow Actions] 🖱️ Đã click button mở menu model")
        
        # Đợi menu hiện ra
        print(f"[Flow Actions] ⏳ Đợi menu hiện ra...")
        end = time.monotonic() + 3.5
        while time.monotonic() < end:
            await asyncio.sleep(0.15)
            menu_items = page.locator('[role="menuitem"]')
            if await menu_items.count() > 0:
                # Verify menu items thực sự visible
                try:
                    await menu_items.first.wait_for(state="visible", timeout=500)
                    print(f"[Flow Actions] ✅ Menu đã mở với {await menu_items.count()} items")
                    return True
                except Exception:
                    continue
        
        print(f"[Flow Actions] ⚠️ Menu chưa hiện sau 3.5s")
        return False
            
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Lỗi click menu model: {e}")
        return False
    
    # Fallback: thử icon patterns như cũ
    icon_patterns = ["volume_up", "arrow_drop_down"]
    
    for icon_name in icon_patterns:
        try:
            rows = page.locator("button").filter(has=page.locator("i", has_text=icon_name))
            n = await rows.count()
            for i in range(n):
                btn = rows.nth(i)
                try:
                    if await btn.count() <= 0 or not await btn.is_visible():
                        continue
                    in_popup = await btn.evaluate(
                        """el => !!el.closest('[role="menu"],[role="listbox"],[data-radix-menu-content],[data-radix-select-content]')"""
                    )
                    if in_popup:
                        continue
                    txt = ((await btn.inner_text()) or "").strip()
                    if txt and not model_name_re.search(txt):
                        continue
                    
                    await btn.scroll_into_view_if_needed()
                    await btn.focus()
                    try:
                        await btn.click(delay=random.randint(70, 150), timeout=2_500)
                    except Exception:
                        await btn.dispatch_event("pointerdown", {"bubbles": True, "pointerType": "mouse"})
                        await btn.dispatch_event("click", {"bubbles": True, "cancelable": True})
                    
                    end = time.monotonic() + 2.5
                    while time.monotonic() < end:
                        await asyncio.sleep(0.12)
                        menu_items = page.locator('[role="menuitem"]')
                        popup_buttons = page.locator("[role='dialog'] button, [role='listbox'] button, [role='menu'] button")
                        if await menu_items.count() > 0 or await popup_buttons.count() > 0:
                            await asyncio.sleep(random.uniform(0.2, 0.4))
                            print(f"[Flow Actions] ✅ Đã mở menu model sau retry (icon: {icon_name})")
                            return True
                    
                except Exception:
                    continue
        except Exception:
            pass
    
    return False









async def click_kSyLER_menu(page: Page) -> bool:
    """
    Theo test_flow_buttons.py:
    click menu model bằng button.kSyLER.
    """
    model_name_re = re.compile(r"veo|nano|imagen|banana|pro", re.I)
    # UI mới (volume_up + sc-*): mở đúng pill model, không dính nút veo khác trên trang.
    if await _click_flow_model_menu_trigger(page):
        return True
    candidates = [
        page.locator("button.kSyLER[aria-haspopup='menu']").first,
        page.locator("button[aria-haspopup='menu']").filter(has_text=model_name_re).first,
        page.locator("button").filter(has=page.locator("i", has_text="arrow_drop_down")).first,
        # UI mới có class hash (sc-...) và không luôn có aria-haspopup.
        page.locator("button").filter(has_text=model_name_re).first,
    ]
    for btn in candidates:
        try:
            if await btn.count() <= 0:
                continue
            await btn.wait_for(state="visible", timeout=5_000)
            await btn.scroll_into_view_if_needed()
            await btn.focus()
            try:
                await btn.click(delay=random.randint(70, 150), timeout=2_500)
            except Exception:
                await btn.dispatch_event("pointerdown", {"bubbles": True, "pointerType": "mouse"})
                await btn.dispatch_event("click", {"bubbles": True, "cancelable": True})
            await asyncio.sleep(random.uniform(0.15, 0.35))
            menu_items = page.locator('[role="menuitem"]')
            popup_buttons = page.locator("[role='dialog'] button, [role='listbox'] button, [role='menu'] button")
            if await menu_items.count() > 0 or await popup_buttons.count() > 0:
                return True
        except Exception:
            continue
    return False


def _score_flow_model_match(target_norm: str, item_norm: str) -> int:
    """Điểm khớp nhãn model UI Flow (sau _normalize_flow_model_label_ui)."""
    if not target_norm or not item_norm:
        return -1
    if target_norm == item_norm:
        return 100
    if target_norm in item_norm or item_norm in target_norm:
        return 85
    target_set = set(target_norm.split())
    item_set = set(item_norm.split())
    score = len(target_set & item_set) * 6
    if "veo" in target_set and "veo" in item_set:
        score += 10
    if "3.1" in target_norm and "3.1" in item_norm:
        score += 8
    if "lite" in target_set and "lite" in item_set:
        score += 14
    if "fast" in target_set and "fast" in item_set:
        score += 14
    if "quality" in target_set and "quality" in item_set:
        score += 14
    if "priority" in target_set and "priority" in item_set:
        score += 10
    if "low" in target_set and "low" in item_set:
        score += 6
    if ("fast" in target_set) != ("fast" in item_set):
        score -= 12
    if ("quality" in target_set) != ("quality" in item_set):
        score -= 12
    if ("lite" in target_set) != ("lite" in item_set):
        score -= 14
    if "priority" in target_set and "priority" not in item_set:
        score -= 12
    if "priority" not in target_set and "priority" in item_set:
        score -= 6
    return score


async def _list_visible_menuitem_labels(page: Page) -> List[str]:
    labels: List[str] = []
    try:
        items = page.locator('[role="menuitem"]')
        n = await items.count()
        for idx in range(n):
            el = items.nth(idx)
            try:
                if not await el.is_visible():
                    continue
                txt = ((await el.inner_text()) or "").strip()
                if txt:
                    labels.append(txt)
            except Exception:
                continue
    except Exception:
        pass
    return labels


async def click_menuitem_preset(page: Page, model_text: Optional[str] = None) -> bool:
    """Chọn model trong menu Flow (fuzzy match Playwright + fallback JS)."""
    target_text = (model_text or "").strip()
    if not target_text:
        print("[Flow Actions] ⚠️ Thiếu model_text từ frontend.")
        return False

    target_norm = _normalize_flow_model_label_ui(target_text)
    min_score = 18

    try:
        menu = await _first_visible_role_menu(page)
        if menu is not None:
            await menu.wait_for(state="visible", timeout=3_500)
        items = page.locator('[role="menuitem"]')
        n = await items.count()
        best_idx = -1
        best_score = -1
        best_label = ""
        for idx in range(n):
            el = items.nth(idx)
            try:
                if not await el.is_visible():
                    continue
                txt = ((await el.inner_text()) or "").strip()
                if not txt:
                    continue
                item_norm = _normalize_flow_model_label_ui(txt)
                score = _score_flow_model_match(target_norm, item_norm)
                if score > best_score:
                    best_score = score
                    best_idx = idx
                    best_label = txt
            except Exception:
                continue

        if best_idx >= 0 and best_score >= min_score:
            el = items.nth(best_idx)
            await el.scroll_into_view_if_needed()
            await el.click(delay=random.randint(50, 130), timeout=3_500)
            print(f"[Flow Actions] ✅ Đã chọn model '{best_label}' (score={best_score})")
            return True
    except Exception as e:
        print(f"[Flow Actions] ⚠️ click_menuitem_preset (playwright): {e}")

    try:
        clicked = await page.evaluate(
            """(modelName) => {
            const norm = (s) => String(s || '').toLowerCase()
                .replace(/\\[|\\]/g, '')
                .replace(/lower priority/g, 'low priority')
                .replace(/veo3\\.1/g, 'veo 3.1').replace(/veo3/g, 'veo 3')
                .replace(/\\s+/g, ' ').trim();
            const target = norm(modelName);
            const scoreMatch = (a, b) => {
                if (!a || !b) return -1;
                if (a === b) return 100;
                if (a.includes(b) || b.includes(a)) return 85;
                const t1 = a.split(' '), t2 = b.split(' ');
                const common = t1.filter(w => t2.includes(w)).length;
                let s = common * 6;
                if (a.includes('lite') && b.includes('lite')) s += 14;
                if (a.includes('fast') && b.includes('fast')) s += 14;
                if (a.includes('quality') && b.includes('quality')) s += 14;
                if (a.includes('priority') && b.includes('priority')) s += 10;
                return s;
            };
            const items = [...document.querySelectorAll('div[role="menuitem"]')];
            let best = null, bestScore = -1, bestText = '';
            for (const el of items) {
                const text = norm((el.innerText || el.textContent || '').trim());
                if (!text) continue;
                const sc = scoreMatch(target, text);
                if (sc > bestScore) { bestScore = sc; best = el; bestText = (el.innerText || '').trim(); }
            }
            if (best && bestScore >= 18) {
                (best.querySelector('button') || best).click();
                return { ok: true, label: bestText, score: bestScore };
            }
            return {
                ok: false,
                labels: items.map(el => (el.innerText || el.textContent || '').trim()).filter(Boolean)
            };
        }""",
            target_text,
        )
        if isinstance(clicked, dict) and clicked.get("ok"):
            print(
                f"[Flow Actions] ✅ Đã chọn model '{clicked.get('label')}' "
                f"(JS score={clicked.get('score')})"
            )
            return True
        menu_labels: List[str] = []
        if isinstance(clicked, dict):
            menu_labels = list(clicked.get("labels") or [])
        if not menu_labels:
            menu_labels = await _list_visible_menuitem_labels(page)
        print(f"[Flow Actions] ⚠️ Không tìm thấy model '{target_text}' trong menu.")
        if menu_labels:
            print(f"[Flow Actions] 📋 Model có trong menu: {menu_labels}")
        return False
    except Exception as e:
        print(f"[Flow Actions] ⚠️ click_menuitem_preset (JS): {e}")
        return False


async def send_prompt_text(page: Page, prompt: str, *, wait_ms: int = 12_000) -> bool:
    """
    Nhập prompt vào textarea Flow và nhấn Enter.
    Dùng keyboard.insert_text() - không dùng clipboard hệ thống, an toàn cho đa luồng.
    Trả về True nếu nhập thành công.
    """
    if not prompt:
        return False

    try:
        editor = page.locator('[contenteditable="true"]').first
        await editor.wait_for(state="visible", timeout=wait_ms)
        await editor.scroll_into_view_if_needed()
        await editor.focus()

        # 🔥 XÓA TEXT CŨ trước khi nhập text mới (Ctrl+A -> Delete)
        await page.keyboard.press("Control+A")
        await asyncio.sleep(random.uniform(0.05, 0.1))
        await page.keyboard.press("Backspace")
        await asyncio.sleep(random.uniform(0.1, 0.2))

        # Nhập text bằng keyboard.insert_text theo 2–3 lần "paste" thay vì từng ký tự.
        # Vẫn tránh gửi một khối quá dài một lần (dễ làm editor crash).
        total_len = len(prompt)
        max_chunks = 3
        # Tính kích thước mỗi lần paste sao cho tối đa ~3 lần
        chunk_size = max(1, (total_len + max_chunks - 1) // max_chunks)

        for i in range(0, total_len, chunk_size):
            chunk = prompt[i : i + chunk_size]
            await page.keyboard.insert_text(chunk)
            await asyncio.sleep(random.uniform(0.1, 0.2))

        await asyncio.sleep(random.uniform(0.8, 1.2))
        await page.keyboard.press("Enter")
        return True
    except TimeoutError:
        print("⚠️ Không tìm thấy contenteditable editor để nhập prompt (timeout).")
        return False
    except Exception as e:
        print(f"⚠️ Lỗi nhập prompt: {e}")
        return False


async def select_mode(
    page: Page,
    mode: str,
    *,
    stop_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """
    Mở dropdown mode một lần (click_combobox_preset), rồi chọn mục trong [role=menu]
    (click_flow_mode_menu_item) — tránh bấm nhầm trigger làm bật/tắt liên tục.
    """
    async def _is_mode_already_selected(target_mode: str) -> bool:
        """
        Heuristic để nhận ra mode hiện tại trong Flow UI.
        Lý do tồn tại:
        - Có lúc UI đã ở đúng mode (vd: Video) nên click lại không tạo thay đổi DOM,
          hoặc nút "Video" không còn hiện/innerText thay đổi → logic click sẽ fail giả.
        """
        try:
            m = (target_mode or "").strip().lower()
            if m not in ("image", "video"):
                return False

            # 0) Tab Flow: id *-trigger-IMAGE / *-trigger-VIDEO (không phụ thuộc class sc-*).
            try:
                if m == "image":
                    for sel in (
                        '[role="tab"][id$="-trigger-IMAGE"][aria-selected="true"]',
                        'button[role="tab"][id$="-trigger-IMAGE"][aria-selected="true"]',
                    ):
                        t = page.locator(sel).first
                        if await t.count() > 0 and await t.is_visible():
                            return True
                if m == "video":
                    for sel in (
                        '[role="tab"][id$="-trigger-VIDEO"][aria-selected="true"]',
                        'button[role="tab"][id$="-trigger-VIDEO"][aria-selected="true"]',
                    ):
                        t = page.locator(sel).first
                        if await t.count() > 0 and await t.is_visible():
                            return True
            except Exception:
                pass

            # 1) Tab mode thật (role=tab): tránh mọi button aria-selected khác (S/M/L, Batch…).
            try:
                if m == "video":
                    loc = (
                        page.locator('button[role="tab"][aria-selected="true"]')
                        .filter(has_text="Video")
                        .first
                    )
                    if await loc.count() > 0 and await loc.is_visible():
                        return True
                else:
                    loc = (
                        page.locator('button[role="tab"][aria-selected="true"]')
                        .filter(has_text="Hình ảnh")
                        .first
                    )
                    if await loc.count() > 0 and await loc.is_visible():
                        return True
                    loc2 = (
                        page.locator('button[role="tab"][aria-selected="true"]')
                        .filter(has_text="Image")
                        .first
                    )
                    if await loc2.count() > 0 and await loc2.is_visible():
                        return True
            except Exception:
                pass

            # 2) UI cũ / pill có nhãn mode trên dòng đầu (không phải pill model+crop_*).
            try:
                trig = await _resolve_flow_mode_menu_trigger(page)
                if trig is not None:
                    txt = ((await trig.inner_text()) or "").strip()
                    first = " ".join(txt.splitlines()[0].split()) if txt else ""
                    # Pill mới: dòng đầu là tên model; không suy ra Image/Video từ đây.
                    if _inner_text_has_flow_crop_icon_name(txt) and not _text_looks_like_flow_mode_menu_trigger(
                        txt
                    ):
                        pass
                    elif m == "video" and first.startswith("Video"):
                        return True
                    elif m == "image" and (
                        first.startswith("Hình ảnh") or re.match(r"^Image\b", first)
                    ):
                        return True
            except Exception:
                pass

            return False
        except Exception:
            return False

    mode_label = "Hình ảnh / Image" if mode == "image" else "Video"
    if stop_check and stop_check():
        raise FlowStoppedError("Stopped by user")

    # Không return sớm theo heuristic trang đóng: dễ nhầm (vd tab khác aria-selected, "Thành phần").
    # Luôn mở menu mode rồi chọn/verify — trùng mode thì thao tác thường no-op.

    # Thêm cơ chế retry nội bộ: nếu Playwright đơ, thử mở combobox + chọn lại tối đa 2 lần.
    for attempt in range(2):
        try:
            if stop_check and stop_check():
                raise FlowStoppedError("Stopped by user")

            # Chờ tab IMAGE/VIDEO cực ngắn rồi thử slider; không thì xuống combobox (tránh kẹt chờ vài giây).
            has_tab_ui = await page_has_flow_mode_slider_tabs(page)
            if not has_tab_ui:
                try:
                    await page.locator(
                        '[role="tab"][id$="-trigger-IMAGE"], [role="tab"][id$="-trigger-VIDEO"]'
                    ).first.wait_for(state="visible", timeout=320)
                    has_tab_ui = True
                except Exception:
                    for _ in range(10):
                        if await page_has_flow_mode_slider_tabs(page):
                            has_tab_ui = True
                            break
                        await asyncio.sleep(0.035)

            if has_tab_ui:
                ok_slider = await click_flow_mode_slider_tab(page, mode)
                if ok_slider:
                    await asyncio.sleep(random.uniform(0.12, 0.28))
                    if await _is_mode_already_selected(mode):
                        print(f"✅ Đã chọn mode {mode_label} (tab slider)")
                        return True
                await asyncio.sleep(0.06)
                ok_slider2 = await click_flow_mode_slider_tab(page, mode)
                if ok_slider2:
                    await asyncio.sleep(random.uniform(0.14, 0.32))
                    if await _is_mode_already_selected(mode):
                        print(f"✅ Đã chọn mode {mode_label} (tab slider, lần 2)")
                        return True
                print(
                    f"⚠️ Tab mode {mode_label} chưa khớp sau khi bấm (attempt {attempt+1}/2) — "
                    "kiểm tra Flow đã hiện tab Hình ảnh/Video."
                )
                if attempt < 1:
                    await asyncio.sleep(random.uniform(0.35, 0.65))
                continue

            # UI cũ: dropdown mode → [role=menu] (không có tab -trigger-IMAGE/VIDEO).
            ok_combo = await click_combobox_preset(page)
            if not ok_combo:
                print(f"⚠️ Không mở được combobox preset để chọn mode {mode_label} (attempt {attempt+1}/2)")
                if await _is_mode_already_selected(mode):
                    print(f"✅ Mode {mode_label} đã đúng (verify) dù không mở được combobox")
                    return True
                # Fallback: UI cũ / edge — thử click trực tiếp nút mode (không qua menu).
                try:
                    if mode == "video":
                        direct = page.locator("button", has_text="Video").first
                    else:
                        direct = page.locator("button", has_text="Hình ảnh").first
                        if await direct.count() <= 0:
                            direct = page.locator("button", has_text="Image").first
                    if await direct.count() > 0 and await direct.is_visible():
                        await direct.scroll_into_view_if_needed()
                        await direct.click(delay=random.randint(60, 140), force=True, timeout=4_000)
                        await asyncio.sleep(random.uniform(0.6, 1.0))
                        if await _is_mode_already_selected(mode):
                            print(f"✅ Đã chọn mode {mode_label} (direct)")
                            return True
                except Exception:
                    pass
                continue

            # Chỉ click mục trong [role=menu] — không dùng click_tab_by_text toàn trang (khớp nhầm nút trigger → đóng menu).
            ok = await click_flow_mode_menu_item(page, mode)
            if ok:
                # Đợi tab mode thực sự apply xong rồi mới setup ratio/x1/model.
                await asyncio.sleep(random.uniform(0.35, 0.65))
                # Verify thêm lần nữa theo heuristic để tránh case click "ăn" nhưng UI không đổi.
                if await _is_mode_already_selected(mode):
                    print(f"✅ Đã chọn mode {mode_label}")
                    return True
                # Nếu verify fail: tiếp tục retry attempt tiếp theo.
        except FlowStoppedError:
            raise
        except Exception as e:
            print(f"⚠️ Lỗi khi chọn mode {mode_label} (attempt {attempt+1}/2): {e}")

        # Nhịp nhỏ trước khi retry lần nữa
        if attempt < 1:
            await asyncio.sleep(random.uniform(0.35, 0.65))

    # Nếu click fail nhưng UI thực tế đã ở đúng mode (vd: đã là Video sẵn) -> accept.
    if await _is_mode_already_selected(mode):
        print(f"✅ Mode {mode_label} đã đúng (verify) dù thao tác chọn không đổi UI")
        return True

    print(f"⚠️ Không chọn được mode {mode_label} sau nhiều lần thử")
    return False


async def verify_mode_selected(page: Page, mode: str, timeout_ms: int = 3000) -> bool:
    """
    Xác minh combobox đang hiển thị đúng mode đã chọn.
    Đã tắt: luôn trả True để tránh fail do combobox hiển thị text khác (VD "từ văn bản sang video" vs text_to_video).
    """
    return True


async def setup_render_settings(
    page: Page,
    *,
    output_count: int = 1,
    ratio: bool = True,  # legacy: True = 9:16, False = 16:9 khi aspect_ratio không truyền
    aspect_ratio: Optional[str] = None,
    model: str = None,
    select_ingredients: bool = False,
    mode: Optional[str] = None,
    prompt: Optional[str] = None,
) -> bool:
    """
    Setup mới theo test_flow_buttons:
    - chọn mode (Image/Video) nếu truyền vào
    - chọn ratio theo tab Dọc/Ngang
    - luôn chọn x1
    - video AI: nếu có hàng tab thời lượng (4s/8s/…) thì chọn 8s trước menu model
    - AI tab: chọn thêm tab Thành phần
    - mở menu model
    - chọn model theo text frontend gửi
    - nhập prompt nếu truyền vào
    Trả về True nếu toàn bộ setup (bao gồm model nếu có) thành công; False nếu có lỗi (ratio/1x/tab/model).
    """
    success = True
    try:
        # Chọn mode trước (Image/Video) nếu được truyền vào
        if mode and str(mode).strip().lower() in ("image", "video"):
            ok_mode = await select_mode(page, mode)
            if not ok_mode:
                print(f"[Flow Actions] ⚠️ Không chọn được mode '{mode}' – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success
            await asyncio.sleep(random.uniform(0.35, 0.65))
        
        await _ensure_create_panel_open(page)
        # UI mới: tab 9:16/16:9 nằm trong popover mở từ pill Video/Hình ảnh — mở trước khi click ratio.
        await ensure_flow_mode_control_popover_open(page)
        # Flow UI: Radix tabs (16:9, 9:16, 4:3, 1:1, 3:4), không còn "Dọc/Ngang" ổn định.
        if aspect_ratio is not None and str(aspect_ratio).strip():
            ratio_label = _normalize_flow_aspect_ratio(aspect_ratio)
            await _wait_for_tab_candidates(
                page, ["9:16", "16:9", "4:3", "1:1", "3:4", "Dọc", "Ngang"], timeout_ms=9000
            )
            ok_ratio = await click_flow_aspect_ratio_tab(page, aspect_ratio=aspect_ratio)
            verify_ratio = await verify_flow_aspect_ratio_selected(
                page, aspect_ratio=aspect_ratio, timeout_ms=2500
            )
        else:
            ratio_label = "9:16" if ratio else "16:9"
            await _wait_for_tab_candidates(
                page, ["9:16", "16:9", "4:3", "1:1", "3:4", "Dọc", "Ngang"], timeout_ms=9000
            )
            ok_ratio = await click_flow_aspect_ratio_tab(page, portrait=ratio)
            verify_ratio = await verify_flow_aspect_ratio_selected(page, portrait=ratio, timeout_ms=2500)
        if not ok_ratio:
            print(f"[Flow Actions] ⚠️ Không chọn được tab ratio '{ratio_label}' – sẽ yêu cầu retry toàn bộ setup.")
            success = False
            return success
        # Verify ratio thật sự selected (nếu UI có aria-selected)
        if not verify_ratio:
            print(f"[Flow Actions] ⚠️ Ratio '{ratio_label}' chưa được chọn (verify fail) – sẽ yêu cầu retry toàn bộ setup.")
            success = False
            return success

        # Theo yêu cầu: luôn chọn 1x (fallback hỗ trợ UI cũ hiển thị x1).
        await _wait_for_tab_candidates(page, ["1x", "x1"], timeout_ms=9000)
        ok_x1 = await click_tab_by_text(
            page,
            text_matcher=lambda s: s.strip() in {"1x", "x1"},
            label="1x",
        )
        if not ok_x1:
            print("[Flow Actions] ⚠️ Không chọn được tab '1x' – sẽ yêu cầu retry toàn bộ setup.")
            success = False
            return success
        if not (
            await _verify_tab_selected(page, "1x", timeout_ms=2500)
            or await _verify_tab_selected(page, "x1", timeout_ms=900)
        ):
            print("[Flow Actions] ⚠️ Tab '1x' chưa được chọn (verify fail) – sẽ yêu cầu retry toàn bộ setup.")
            success = False
            return success

        # Video AI: sau x1 bấm tab 8s (flow_tab_slider_trigger) rồi mới tới model / Thành phần.
        if await _wait_for_flow_duration_tab_row(page, timeout_ms=1400):
            await asyncio.sleep(random.uniform(0.1, 0.25))
            await _wait_for_tab_candidates(page, ["8s"], timeout_ms=9000)
            ok_8s = await click_tab_by_text(
                page,
                text_matcher=lambda s: s.strip() == "8s",
                label="8s",
            )
            if not ok_8s:
                print("[Flow Actions] ⚠️ Không chọn được tab '8s' – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success
            if not await _verify_tab_selected(page, "8s", timeout_ms=2500):
                print("[Flow Actions] ⚠️ Tab '8s' chưa được chọn (verify fail) – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success

        # AI tab (mode video): chọn thêm tab Thành phần như default.
        if select_ingredients:
            await _wait_for_tab_candidates(page, ["Thành phần"], timeout_ms=9000)
            ok_ing = await click_tab_by_text(
                page,
                text_matcher=lambda s: "Thành phần" in s,
                label="Thành phần",
            )
            if not ok_ing:
                print("[Flow Actions] ⚠️ Không chọn được tab 'Thành phần' – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success
            if not await _verify_tab_selected(page, "Thành phần", timeout_ms=2500):
                print("[Flow Actions] ⚠️ Tab 'Thành phần' chưa được chọn (verify fail) – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success
        async def _verify_model_applied(expected_model: str, timeout_ms: int = 2500) -> bool:
            """
            Verify sau khi click model để tránh false-positive "click xong nhưng chưa apply".
            Dùng logic mới: tìm button có icon volume_up (UI mới) hoặc button.kSyLER (UI cũ).
            """
            expected_norm = _normalize_flow_model_label_ui(expected_model)
            rounds = max(1, int(timeout_ms / 250))
            for _ in range(rounds):
                try:
                    trigger_txt = ""
                    
                    # ✅ UI mới: button có icon volume_up (Material Design)
                    rows = page.locator("button").filter(
                        has=page.locator("i", has_text="volume_up")
                    )
                    n = await rows.count()
                    for i in range(n):
                        btn = rows.nth(i)
                        try:
                            if await btn.count() <= 0 or not await btn.is_visible():
                                continue
                            in_popup = await btn.evaluate(
                                """el => !!el.closest('[role="menu"],[role="listbox"],[data-radix-menu-content],[data-radix-select-content]')"""
                            )
                            if in_popup:
                                continue
                            trigger_txt = ((await btn.inner_text()) or "").strip()
                            if trigger_txt:
                                break
                        except Exception:
                            continue
                    
                    # ✅ UI cũ: button.kSyLER (fallback)
                    if not trigger_txt:
                        trigger = page.locator("button.kSyLER").first
                        if await trigger.count() > 0 and await trigger.is_visible():
                            trigger_txt = ((await trigger.inner_text()) or "").strip()
                    
                    # ✅ Fallback: button có text model (veo|nano|imagen|banana|pro)
                    if not trigger_txt:
                        trigger2 = page.locator("button").filter(
                            has_text=re.compile(r"veo|nano|imagen|banana|pro", re.I)
                        ).first
                        if await trigger2.count() > 0 and await trigger2.is_visible():
                            trigger_txt = ((await trigger2.inner_text()) or "").strip()

                    # ✅ So sánh normalized text
                    if trigger_txt:
                        txt_norm = _normalize_flow_model_label_ui(trigger_txt)
                        if expected_norm and (
                            expected_norm == txt_norm
                            or expected_norm in txt_norm
                            or txt_norm in expected_norm
                        ):
                            return True
                    
                    # ✅ Nếu menu đóng (không có menuitem) → model đã apply
                    items = page.locator('[role="menuitem"]')
                    if await items.count() == 0:
                        return True
                except Exception:
                    pass
                await asyncio.sleep(0.25)
            return False

        # Mở menu model và chọn model nếu được truyền vào
        if model and str(model).strip():
            await asyncio.sleep(random.uniform(0.25, 0.5))
            
            # Retry logic: thử mở menu model tối đa 3 lần
            ok_menu = False
            for menu_attempt in range(3):
                ok_menu = await click_kSyLER_menu(page)
                if ok_menu:
                    break
                if menu_attempt < 2:
                    print(f"[Flow Actions] ⚠️ Lần {menu_attempt + 1}: Không mở được menu model, thử lại...")
                    await asyncio.sleep(random.uniform(0.5, 0.8))
            
            if not ok_menu:
                print(f"[Flow Actions] ⚠️ Không mở được menu model sau 3 lần thử – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success
            
            # Đợi menu hiện ra hoàn toàn
            await asyncio.sleep(random.uniform(0.35, 0.65))
            
            # Verify menu đã mở (có menuitem visible)
            try:
                menu_items = page.locator('[role="menuitem"]')
                await menu_items.first.wait_for(state="visible", timeout=3000)
            except Exception as e:
                print(f"[Flow Actions] ⚠️ Menu model không hiện menuitem sau khi click: {e}")
                success = False
                return success
            
            ok_model = await click_menuitem_preset(page, model_text=model)
            if not ok_model:
                print(f"[Flow Actions] ⚠️ Không chọn được model '{model}' – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success
            await asyncio.sleep(random.uniform(0.35, 0.65))
            
            # Verify model đã được chọn
            verify_model = await _verify_model_applied(model, timeout_ms=2500)
            if not verify_model:
                print(f"[Flow Actions] ⚠️ Model '{model}' chưa được apply (verify fail) – sẽ yêu cầu retry toàn bộ setup.")
                success = False
                return success
    
    except Exception as e:
        print(f"⚠️ Setup settings warning: {e}")
        success = False
    
    return success
    
async def upload_master_image_playwright(
    page: Page,
    image_path: str,
    *,
    wait_for_api_log: bool = True,
    consistent_voice_enabled: bool = False,
    consistent_voice_name: Optional[str] = None,
) -> bool:
    """
    Upload ảnh theo flow mới giống test_upload_master_image.py:
    1) Click nút add_2 (Tạo)
    2) Click nút upload (Tải hình ảnh lên)
    3) Chọn file
    4) (Tuỳ chọn) chọn voice đồng nhất sau upload nếu bật cờ consistent_voice_enabled.
    5) Mặc định: chờ API log upload xuất hiện rồi mới trả về True.
       Nếu wait_for_api_log=False: trả về True sau khi chọn file (không chờ API).
    """
    import os
    if not os.path.exists(image_path):
        print(f"[Flow Actions] ❌ Không tìm thấy ảnh: {image_path}")
        return False

    print(f"[Flow Actions] 🖼️ Uploading: {os.path.basename(image_path)}")

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            # Retry theo yêu cầu: đợi 4-5s cho UI ổn định rồi bấm lại upload.
            if attempt > 1:
                settle_s = random.uniform(4.0, 5.0)
                print(f"[Flow Actions] ♻️ Upload retry {attempt}/{max_attempts}: đợi {settle_s:.1f}s rồi thử lại...")
                await asyncio.sleep(settle_s)

            api_wait_task = None
            if wait_for_api_log:
                # Bắt API listener TRƯỚC khi thao tác upload để tránh miss event
                wait_s = float(os.environ.get("FLOW_API_WAIT_SECONDS", "45") or "45")
                api_wait_task = asyncio.create_task(
                    _wait_for_upload_api_log(page, timeout_seconds=max(5.0, wait_s)),
                )

            # 1) Click nút Tạo (icon add_2)
            create_btn = page.locator("button").filter(has=page.locator("i", has_text="add_2")).first
            await create_btn.wait_for(state="visible", timeout=12_000)
            await create_btn.scroll_into_view_if_needed()
            await create_btn.click(delay=random.randint(80, 180))
            await asyncio.sleep(random.uniform(0.4, 0.8))

            # 2) Click nút Upload: ưu tiên tìm div khớp innerText (giống console Flow mới)
            upload_label = re.compile(
                r"Tải hình ảnh lên|Upload image|Upload an image|画像|上传|이미지",
                re.I,
            )

            def _upload_icon():
                return page.locator("i", has_text="upload")

            upload_btn = (
                page.locator("div.fxheTi")
                .filter(has=_upload_icon())
                .filter(has_text=upload_label)
                .first
            ).or_(
                page.locator("div[class*='fxheTi']")
                .filter(has=_upload_icon())
                .filter(has_text=upload_label)
                .first
            ).or_(
                page.locator("div")
                .filter(has=_upload_icon())
                .filter(has_text=upload_label)
                .first
            ).or_(
                page.locator("button")
                .filter(has=_upload_icon())
                .filter(has_text=upload_label)
                .first
            ).or_(
                page.locator("[role='button']").filter(has=_upload_icon()).first
            ).or_(
                page.locator("button").filter(has=_upload_icon()).first
            ).or_(
                page.locator("div").filter(has=_upload_icon()).first
            )

            # 3) Chọn file
            try:
                async with page.expect_file_chooser(timeout=10_000) as fc_info:
                    clicked = await page.evaluate(
                        """(texts) => {
                            for (const t of texts) {
                                const el = [...document.querySelectorAll("div")].find(
                                    (node) => node.innerText.trim() === t
                                );
                                if (el) {
                                    el.scrollIntoView({ block: "center", inline: "nearest" });
                                    el.click();
                                    return true;
                                }
                            }
                            return false;
                        }""",
                        [
                            "Tải hình ảnh lên",
                            "Upload image",
                            "Upload an image",
                        ],
                    )
                    if not clicked:
                        await upload_btn.wait_for(state="visible", timeout=12_000)
                        await upload_btn.scroll_into_view_if_needed()
                        await upload_btn.click(delay=random.randint(80, 180))
                file_chooser = await fc_info.value
                await file_chooser.set_files(image_path)
            except Exception:
                # Fallback nếu UI render input file trực tiếp
                file_input = page.locator("input[type='file']").first
                await file_input.wait_for(state="attached", timeout=8_000)
                await file_input.set_input_files(image_path)

            await asyncio.sleep(
                random.uniform(1.2, 1.8) if wait_for_api_log else random.uniform(0.25, 0.55),
            )

            if consistent_voice_enabled and (consistent_voice_name or "").strip():
                await _select_consistent_voice_after_upload(page, str(consistent_voice_name).strip())

            if not wait_for_api_log:
                print("[Flow Actions] ⏭️ Bỏ chờ API log upload (caller xử lý tiếp).")
                return True

            # 4) Đợi API upload log xong rồi caller mới gửi prompt
            assert api_wait_task is not None
            saw_api, policy_message = await api_wait_task
            if policy_message:
                raise UploadPolicyViolationError(policy_message)
            if saw_api:
                print("[Flow Actions] ✅ Đã thấy API log upload.")
                
                # 5) Sau khi upload thành công, click nút "Thêm vào câu lệnh"
                try:
                    await asyncio.sleep(random.uniform(0.3, 0.6))
                    clicked = await page.evaluate("""() => {
                        const btn = [...document.querySelectorAll('button')]
                            .find(btn => btn.innerText.trim().includes('Thêm vào câu lệnh'));
                        
                        if (btn) {
                            btn.dispatchEvent(new MouseEvent('click', {
                                bubbles: true,
                                cancelable: true,
                                view: window
                            }));
                            return true;
                        }
                        return false;
                    }""")
                    if clicked:
                        print("[Flow Actions] ✅ Đã click 'Thêm vào câu lệnh'.")
                        await asyncio.sleep(random.uniform(0.2, 0.4))
                    else:
                        print("[Flow Actions] ⚠️ Không tìm thấy nút 'Thêm vào câu lệnh'.")
                except Exception as e:
                    print(f"[Flow Actions] ⚠️ Lỗi click 'Thêm vào câu lệnh': {e}")
                
                return True
            print("[Flow Actions] ❌ Không bắt được API log upload trong timeout.")
        except UploadPolicyViolationError:
            raise
        except Exception as e:
            print(f"[Flow Actions] ❌ Lỗi upload ảnh (attempt {attempt}/{max_attempts}): {e}")

    return False


async def _click_voice_scene_add_button(page: Page) -> bool:
    """
    Card cảnh có icon google-symbols 'add' (trắng) + 'voice_selection' (vd aria-label tên giọng).
    """
    try:
        btn = (
            page.locator("button")
            .filter(has=page.locator("i", has_text="voice_selection"))
            .filter(has=page.locator("i", has_text="add"))
            .first
        )
        await btn.wait_for(state="visible", timeout=8_000)
        await btn.scroll_into_view_if_needed()
        await btn.click(delay=random.randint(80, 180))
        print("[Flow Actions] ➕ Đã click nút card (voice_selection + add).")
        await asyncio.sleep(random.uniform(0.6, 1.2))
        return True
    except Exception as e:
        print(f"[Flow Actions] ⚠️ Không click được nút card voice_selection+add: {e}")
        return False


async def click_add_next_scene_playwright(
    page: Page,
    *,
    consistent_voice_enabled: bool = False,
) -> bool:
    """
    Thao tác: Click nút Add (dấu cộng) để thêm cảnh tiếp theo.
    - Mặc định (consistent_voice_enabled=False): chỉ click thumbnail add như cũ.
    - Nếu consistent_voice_enabled=True: click thumbnail add trước, rồi click card voice+add.
    Trả về True nếu đạt đủ bước theo chế độ.
    """
    ok_thumb = False
    try:
        clicked = await page.evaluate(
            """
            () => {
                const allButtons = Array.from(document.querySelectorAll('button'));
                const targetBtn = allButtons.find(btn => {
                    const hasImg = btn.querySelector('img') !== null;
                    const hasAddIcon = (btn.innerText || '').includes('add');
                    return hasImg && hasAddIcon;
                });
                if (!targetBtn) return false;
                targetBtn.focus();
                targetBtn.dispatchEvent(new PointerEvent('pointerdown', {
                    bubbles: true, cancelable: true, pointerType: 'mouse', button: 0
                }));
                targetBtn.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                targetBtn.click();
                return true;
            }
            """
        )
        if clicked:
            print("[Flow Actions] ➕ Đã click Add Next Scene (thumbnail add logic mới).")
            await asyncio.sleep(random.uniform(1.2, 2.0))
            ok_thumb = True
        else:
            print("[Flow Actions] ❌ Không tìm thấy nút Add Next Scene theo logic thumbnail mới.")
    except Exception as e:
        print(f"[Flow Actions] ❌ Lỗi click next scene (thumbnail): {e}")

    if not consistent_voice_enabled:
        return ok_thumb

    # Đồng nhất giọng: bắt buộc đi thêm bước card voice sau khi add ảnh.
    if not ok_thumb:
        return False
    ok_voice = await _click_voice_scene_add_button(page)
    return ok_thumb and ok_voice
    
    
def download_image(url: str, save_path: str):
    """Hàm tải ảnh từ URL lưu vào đường dẫn save_path"""
    try:
        # Timeout 30s để tránh treo nếu mạng lag
        response = requests.get(url, stream=True, timeout=30)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"[Download Error] {e}")
    return False


def download_video_by_media_id(
    media_id: str,
    save_path: str,
    *,
    cookies: Optional[dict] = None,
    user_agent: Optional[str] = None,
    max_retries: int = 3,
    timeout: int = 60,
) -> bool:
    """
    Tải video bằng media-id qua endpoint redirect của Flow:
    https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=<media_id>
    Dùng requests để tránh CORS như cách test_download_video_by_media_id.py.
    """
    if not media_id:
        return False

    import time

    download_api = f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}"
    for attempt in range(max_retries):
        try:
            sess = requests.Session()
            sess.headers.update(
                {
                    "User-Agent": user_agent or "Mozilla/5.0",
                    "Referer": "https://labs.google/fx/vi/tools/flow",
                    "Origin": "https://labs.google",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                }
            )
            if cookies:
                sess.cookies.update(cookies)

            with sess.get(download_api, stream=True, timeout=timeout, allow_redirects=True) as resp:
                if resp.status_code != 200:
                    raise Exception(f"status={resp.status_code}, url={resp.url}")
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception as e:
            if attempt >= max_retries - 1:
                print(f"[Flow Actions] ❌ Tải video theo media-id lỗi: {e}")
                return False
            time.sleep(3)
    return False
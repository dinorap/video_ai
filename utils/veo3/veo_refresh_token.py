"""
VEO API - Refresh access_token đơn giản

Dùng sessionId và projectId CŨ từ file JSON, chỉ lấy access_token MỚI khi goto Flow.
"""

import asyncio
import json
from typing import Dict, Any
from playwright.async_api import Page  # type: ignore


async def refresh_access_token_simple(
    page: Page,
    old_session_id: str,
    old_project_id: str,
    timeout_seconds: int = 30
) -> Dict[str, Any]:
    """
    Lấy access_token MỚI từ /api/auth/session.
    Dùng sessionId và projectId CŨ từ file JSON.
    
    Args:
        page: Playwright page (đã goto Flow project)
        old_session_id: sessionId cũ từ veo_auth.json
        old_project_id: projectId cũ từ veo_auth.json
        timeout_seconds: Timeout
    
    Returns:
        {
            "success": True/False,
            "access_token": str (token mới),
            "cookie": str (cookie mới),
            "session_id": str (dùng lại cũ),
            "project_id": str (dùng lại cũ),
            "error": str (nếu có)
        }
    """
    try:
        # Kiểm tra page đang ở labs.google
        current_url = page.url or ""
        if "labs.google" not in current_url:
            return {
                "success": False,
                "error": "Page không ở labs.google domain"
            }
        
        # Gọi /api/auth/session để lấy access_token MỚI
        auth_url = "https://labs.google/fx/api/auth/session"
        
        try:
            resp = await page.context.request.get(auth_url, timeout=timeout_seconds * 1000)
            
            if not resp.ok:
                return {
                    "success": False,
                    "error": f"HTTP {resp.status} khi gọi /api/auth/session"
                }
            
            body = await resp.text()
            data = json.loads(body or "{}")
            access_token = data.get("access_token")
            
            if not access_token:
                return {
                    "success": False,
                    "error": "Không có access_token trong response"
                }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Exception khi gọi /api/auth/session: {e}"
            }
        
        # Lấy cookie MỚI từ browser
        cookie_header = ""
        try:
            cookies = await page.context.cookies()
            parts = []
            for c in cookies:
                domain = str(c.get("domain") or "").lstrip(".").lower()
                if not (domain.endswith("google.com") or domain.endswith("labs.google")):
                    continue
                name = c.get("name")
                value = c.get("value")
                if name and value is not None:
                    parts.append(f"{name}={value}")
            cookie_header = "; ".join(parts)
        except Exception as e:
            print(f"⚠️ Lỗi lấy cookie: {e}")
        
        print(f"✅ Refresh token thành công!")
        print(f"   - access_token MỚI: {access_token[:30]}...")
        print(f"   - cookie MỚI: {len(cookie_header)} chars")
        print(f"   - session_id CŨ: {old_session_id}")
        print(f"   - project_id CŨ: {old_project_id}")
        
        return {
            "success": True,
            "access_token": access_token,  # MỚI
            "cookie": cookie_header,        # MỚI
            "session_id": old_session_id,   # CŨ (giữ nguyên)
            "project_id": old_project_id    # CŨ (giữ nguyên)
        }
    
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Exception: {e}",
            "traceback": traceback.format_exc()
        }


# ============================================================================
# FLOW ĐƠN GIẢN
# ============================================================================

"""
FLOW SỬ DỤNG:

1. Có file veo_auth.json cũ với sessionId và projectId:
   {
     "sessionId": ";1773218083687",
     "projectId": "abc-xyz-123",
     "access_token": "old-token-expired",
     "cookie": "old-cookie"
   }

2. Goto Flow project (dùng projectId cũ):
   await page.goto(f"https://labs.google/fx/vi/tools/flow/project/{old_project_id}")

3. Gọi hàm refresh:
   result = await refresh_access_token_simple(page, old_session_id, old_project_id)

4. Nhận được:
   {
     "success": True,
     "access_token": "new-fresh-token",  # MỚI
     "cookie": "new-cookie-string",      # MỚI
     "session_id": ";1773218083687",     # CŨ (giữ nguyên)
     "project_id": "abc-xyz-123"         # CŨ (giữ nguyên)
   }

5. Lưu lại vào file JSON và dùng ngay!

---

ĐIỂM QUAN TRỌNG:
- sessionId và projectId: GIỮ NGUYÊN từ file cũ
- access_token và cookie: LẤY MỚI từ /api/auth/session
- Chỉ cần goto Flow project 1 lần, không cần gửi prompt hay click gì cả
- Nhanh, đơn giản, ổn định
- Tránh lỗi UNAUTHENTICATED: "Request had invalid authentication credentials"
"""

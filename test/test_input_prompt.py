"""
Test script: Nhập prompt và lấy recaptcha token từ Chrome profile đang chạy sẵn.
Chỉ cần chạy: python test_input_prompt.py
"""

import asyncio
import sys
import os

# Add utils to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from utils.veo3.flow_actions import connect_and_get_page, send_prompt_text
from utils.veo3.veo_get_token import fetch_recaptcha_token_via_page

async def main():
    # Kết nối tới Chrome đang chạy qua CDP
    CDP_URL = "http://localhost:9222"
    
    print("=" * 60)
    print("🧪 TEST: Nhập prompt và lấy recaptcha token")
    print("=" * 60)
    
    # Nhập prompt từ user
    prompt_input = input("\n📝 Nhập prompt (Enter để dùng 'a'): ").strip()
    if not prompt_input:
        prompt_input = "a"
    
    print(f"\n✅ Sẽ gửi prompt: '{prompt_input}'")
    print(f"🔌 Kết nối tới CDP: {CDP_URL}")
    
    try:
        # Kết nối qua CDP
        page = await connect_and_get_page(CDP_URL)
        if not page:
            print("❌ Không thể kết nối tới Chrome qua CDP")
            return
        
        print(f"✅ Đã kết nối tới page: {page.url}")
        
        # 🔥 Nhập prompt TRƯỚC KHI gọi fetch_recaptcha_token_via_page
        print(f"\n⏳ Đang nhập prompt '{prompt_input}' và nhấn Enter...")
        ok = await send_prompt_text(page, prompt_input)
        if not ok:
            print("❌ Không thể nhập prompt")
            return
        
        print(f"✅ Đã nhập prompt và nhấn Enter")
        
        # Gọi hàm lấy recaptcha token (chỉ đợi bắt, không nhập nữa)
        print(f"\n⏳ Đang đợi bắt recaptcha token...")
        
        recaptcha_token = await fetch_recaptcha_token_via_page(
            page,
            prompt_for_token=prompt_input,  # Không dùng nữa nhưng giữ để tương thích
            timeout=30,
        )
        
        if recaptcha_token:
            print("\n" + "=" * 60)
            print("✅ ĐÃ LẤY ĐƯỢC RECAPTCHA TOKEN!")
            print("=" * 60)
            print(f"\n📋 Token (full):\n{recaptcha_token}")
            print(f"\n📊 Độ dài: {len(recaptcha_token)} ký tự")
            print("=" * 60)
        else:
            print("\n❌ Không lấy được recaptcha token")
        
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

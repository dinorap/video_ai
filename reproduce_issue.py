import asyncio
import sys
import os

# Add current directory to sys.path to import utils
sys.path.append(os.getcwd())

from utils.control_profile import init_global_browser, get_global_browser

async def test_init():
    print("Attempting to initialize global browser (kind='image')...")
    try:
        # This mimics what app.py does
        init_global_browser(provider="grok", kind='image')
        print("init_global_browser returned True")
        
        gb = get_global_browser('image')
        print(f"Browser thread alive: {gb._thread.is_alive()}")
        
        async def check_ctx():
            ctx = await gb.get_context_async()
            print(f"Context obtained: {ctx is not None}")
            if ctx:
                page = await ctx.new_page()
                await page.goto("about:blank")
                print(f"Page title: {await page.title()}")
                await page.close()
        
        # Run the check on the global browser's loop
        future = asyncio.run_coroutine_threadsafe(check_ctx(), gb._loop)
        future.result(timeout=30)
        print("SUCCESS: Global browser is working correctly.")
        
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_init())

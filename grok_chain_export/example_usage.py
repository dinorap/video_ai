"""
Example Usage - Ví dụ sử dụng Grok Video Chain
==============================================

File này chứa các ví dụ cách sử dụng module grok_chain_export.
"""

import asyncio
from grok_chain_export import GrokVideoChain, extract_last_frame


async def example_single_video():
    """Ví dụ 1: Tạo một video đơn."""
    print("=" * 60)
    print("Example 1: Create Single Video")
    print("=" * 60)
    
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos",
        ffmpeg_path="ffmpeg"  # Hoặc đường dẫn đầy đủ đến ffmpeg.exe
    )
    
    video_path = await chain.create_single_video(
        image_path="character.jpg",  # Thay bằng đường dẫn ảnh của bạn
        prompt="A young warrior standing in a mystical forest, cinematic lighting",
        output_name="scene_001.mp4",
        duration="6s",
        quality="720p"
    )
    
    print(f"\n✅ Video created: {video_path}")


async def example_video_chain():
    """Ví dụ 2: Tạo chuỗi video với frame chaining."""
    print("=" * 60)
    print("Example 2: Create Video Chain with Frame Chaining")
    print("=" * 60)
    
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos"
    )
    
    prompts = [
        "A young warrior standing in a mystical forest, holding a sword, cinematic lighting",
        "The warrior draws their sword and prepares for battle, dynamic movement",
        "The warrior charges forward with determination, action scene"
    ]
    
    video_paths = await chain.create_video_chain(
        prompts=prompts,
        first_image="warrior_reference.jpg",  # Ảnh tham chiếu cho cảnh đầu
        duration="6s",
        quality="720p"
    )
    
    print("\n" + "=" * 60)
    print("✅ All videos created:")
    for i, path in enumerate(video_paths, 1):
        print(f"   Scene {i}: {path}")
    print("=" * 60)


async def example_video_chain_with_images():
    """Ví dụ 3: Tạo chuỗi video, mỗi cảnh có ảnh riêng."""
    print("=" * 60)
    print("Example 3: Create Video Chain with Individual Images")
    print("=" * 60)
    
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos"
    )
    
    prompts = [
        "A warrior in the forest",
        "A warrior in the mountains",
        "A warrior in the desert"
    ]
    
    images = [
        "forest_scene.jpg",
        "mountain_scene.jpg",
        "desert_scene.jpg"
    ]
    
    video_paths = await chain.create_video_chain_with_images(
        prompts=prompts,
        images=images,
        duration="10s",
        quality="720p"
    )
    
    print("\n✅ All videos created:")
    for i, path in enumerate(video_paths, 1):
        print(f"   Scene {i}: {path}")


def example_extract_frame():
    """Ví dụ 4: Chỉ cắt frame từ video có sẵn."""
    print("=" * 60)
    print("Example 4: Extract Frame from Video")
    print("=" * 60)
    
    # Cắt frame cuối
    last_frame = extract_last_frame(
        video_path="scene_001.mp4",
        output_path="frame_for_scene_002.jpg",
        ffmpeg_path="ffmpeg"
    )
    print(f"✅ Last frame extracted: {last_frame}")
    
    # Nếu frame cuối bị đen, thử tăng seek_offset
    last_frame_safe = extract_last_frame(
        video_path="scene_001.mp4",
        output_path="frame_safe.jpg",
        ffmpeg_path="ffmpeg",
        seek_offset=0.5  # Lùi 0.5s thay vì 0.1s
    )
    print(f"✅ Last frame (safe) extracted: {last_frame_safe}")


async def example_with_error_handling():
    """Ví dụ 5: Xử lý lỗi."""
    print("=" * 60)
    print("Example 5: Error Handling")
    print("=" * 60)
    
    from grok_chain_export.grok_video import GrokAccountLimitError
    
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos"
    )
    
    try:
        video_paths = await chain.create_video_chain(
            prompts=["Scene 1", "Scene 2", "Scene 3"],
            first_image="character.jpg",
            duration="6s",
            quality="720p"
        )
        print("✅ Success!")
        
    except GrokAccountLimitError as e:
        print(f"❌ Grok account limit reached: {e}")
        print("   → Please switch to another Grok account")
        
    except TimeoutError as e:
        print(f"❌ Timeout: {e}")
        print("   → Video generation took too long")
        
    except FileNotFoundError as e:
        print(f"❌ File not found: {e}")
        print("   → Check if image/video files exist")
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


async def example_with_cancel():
    """Ví dụ 6: Hủy giữa chừng."""
    print("=" * 60)
    print("Example 6: Cancellation")
    print("=" * 60)
    
    import threading
    
    chain = GrokVideoChain(
        profile_dir="./chrome_profile",
        output_dir="./output_videos"
    )
    
    # Tạo cancel event
    cancel_event = asyncio.Event()
    
    # Giả lập: sau 30s thì cancel
    async def auto_cancel():
        await asyncio.sleep(30)
        cancel_event.set()
        print("⚠️  Cancellation requested!")
    
    # Chạy song song
    cancel_task = asyncio.create_task(auto_cancel())
    
    try:
        video_paths = await chain.create_video_chain(
            prompts=["Scene 1", "Scene 2", "Scene 3"],
            first_image="character.jpg",
            cancel_event=cancel_event
        )
        print("✅ Completed!")
        
    except asyncio.CancelledError:
        print("❌ Operation cancelled by user")
        
    finally:
        cancel_task.cancel()


async def main():
    """Chạy tất cả ví dụ."""
    print("\n" + "=" * 60)
    print("GROK VIDEO CHAIN - EXAMPLES")
    print("=" * 60 + "\n")
    
    # Uncomment ví dụ bạn muốn chạy:
    
    # await example_single_video()
    # await example_video_chain()
    # await example_video_chain_with_images()
    # example_extract_frame()  # Không cần await
    # await example_with_error_handling()
    # await example_with_cancel()
    
    print("\n💡 Tip: Uncomment the example you want to run in main()")
    print("💡 Make sure Chrome is running with CDP enabled:")
    print("   chrome.exe --remote-debugging-port=9222 --user-data-dir=./chrome_profile")


if __name__ == "__main__":
    asyncio.run(main())

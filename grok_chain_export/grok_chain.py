"""
Grok Video Chain - Main class để tạo chuỗi video với frame chaining
===================================================================

Class chính để sử dụng: GrokVideoChain
"""

import asyncio
import os
from pathlib import Path
from typing import List, Optional
from playwright.async_api import async_playwright

from .frame_extractor import extract_last_frame
from .chrome_utils import get_cdp_endpoint
from .grok_video import (
    VideoJob,
    GrokAccountLimitError,
    UPLOAD_INPUT,
    PROMPT_EDITOR,
    SELECTOR_VIDEO_MODE,
    SELECTOR_RESULT_VIDEO,
    _attach_grok_limit_listener,
    _raise_if_grok_limit,
    _wait_after_submit,
    _grok_raise_if_cancelled,
    download_by_click_save_as,
)


class GrokVideoChain:
    """
    Class chính để tạo video Grok với frame chaining.
    
    Example:
        chain = GrokVideoChain(
            profile_dir="./chrome_profile",
            output_dir="./output_videos"
        )
        
        videos = await chain.create_video_chain(
            prompts=["scene 1", "scene 2", "scene 3"],
            first_image="character.jpg"
        )
    """
    
    def __init__(
        self,
        profile_dir: str,
        output_dir: str,
        ffmpeg_path: str = "ffmpeg",
        cdp_port: int = 9222
    ):
        """
        Khởi tạo GrokVideoChain.
        
        Args:
            profile_dir: Đường dẫn đến Chrome profile (để lưu session)
            output_dir: Thư mục lưu video output
            ffmpeg_path: Đường dẫn đến ffmpeg executable
            cdp_port: Port cho Chrome DevTools Protocol
        """
        self.profile_dir = Path(profile_dir)
        self.output_dir = Path(output_dir)
        self.ffmpeg_path = ffmpeg_path
        self.cdp_port = cdp_port
        
        # Tạo thư mục nếu chưa tồn tại
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_single_video(
        self,
        image_path: str,
        prompt: str,
        output_name: str = "output.mp4",
        duration: str = "6s",
        quality: str = "720p",
        cancel_check: Optional[callable] = None,
        cancel_event=None
    ) -> str:
        """
        Tạo một video đơn.
        
        Args:
            image_path: Đường dẫn đến ảnh tham chiếu
            prompt: Prompt mô tả video
            output_name: Tên file output
            duration: "6s" hoặc "10s"
            quality: "480p" hoặc "720p"
            cancel_check: Function để kiểm tra cancel
            cancel_event: Event để signal cancel
        
        Returns:
            Đường dẫn đến video đã tạo
        """
        output_path = self.output_dir / output_name
        
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(
                get_cdp_endpoint(self.cdp_port)
            )
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            
            try:
                limit_holder = _attach_grok_limit_listener(page)
                
                await page.goto("https://grok.com/imagine", timeout=60000)
                await _grok_raise_if_cancelled(cancel_check, cancel_event)
                await _raise_if_grok_limit(limit_holder)
                
                # Upload image
                upload = page.locator(UPLOAD_INPUT).first
                await upload.wait_for(state="attached", timeout=30000)
                await upload.set_input_files(image_path)
                await asyncio.sleep(2)
                
                # Select Video mode
                try:
                    video_mode_btn = page.locator(SELECTOR_VIDEO_MODE).first
                    await video_mode_btn.wait_for(state="visible", timeout=10000)
                    if await video_mode_btn.get_attribute("aria-checked") != "true":
                        await video_mode_btn.click()
                except Exception:
                    pass
                
                # Select duration and quality
                await self._select_duration_quality(page, duration, quality)
                
                # Fill prompt and submit
                editor = page.locator(PROMPT_EDITOR).first
                await editor.wait_for(timeout=30000)
                await editor.fill(prompt)
                await asyncio.sleep(0.5)
                await editor.press("Enter")
                print("✅ Pressed Enter to submit")
                
                await _wait_after_submit(
                    page, limit_holder, timeout_s=45.0,
                    cancel_check=cancel_check, cancel_event=cancel_event
                )
                
                # Wait for video
                await asyncio.sleep(2)
                await _raise_if_grok_limit(limit_holder)
                await _grok_raise_if_cancelled(cancel_check, cancel_event)
                
                video = page.locator(SELECTOR_RESULT_VIDEO).first
                wait_deadline = asyncio.get_event_loop().time() + 420.0
                while asyncio.get_event_loop().time() < wait_deadline:
                    await _grok_raise_if_cancelled(cancel_check, cancel_event)
                    try:
                        await video.wait_for(state="visible", timeout=2000)
                        break
                    except Exception:
                        await asyncio.sleep(0.5)
                else:
                    raise TimeoutError("Video không hiện sau 420s")
                
                # Wait for video ready
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
                    page, str(output_path),
                    cancel_check=cancel_check, cancel_event=cancel_event
                )
                
                return result_path
                
            finally:
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass
    
    async def create_video_chain(
        self,
        prompts: List[str],
        first_image: str,
        duration: str = "6s",
        quality: str = "720p",
        cancel_check: Optional[callable] = None,
        cancel_event=None
    ) -> List[str]:
        """
        Tạo chuỗi video với frame chaining.
        
        Cảnh 1 dùng first_image, các cảnh sau dùng frame cuối của cảnh trước.
        
        Args:
            prompts: List prompt cho từng cảnh
            first_image: Ảnh tham chiếu cho cảnh đầu tiên
            duration: "6s" hoặc "10s"
            quality: "480p" hoặc "720p"
        
        Returns:
            List đường dẫn đến các video đã tạo
        """
        video_paths = []
        last_frame_path = None
        
        for i, prompt in enumerate(prompts, start=1):
            print(f"\n{'='*60}")
            print(f"🎬 Creating Scene {i}/{len(prompts)}")
            print(f"{'='*60}")
            
            # Xác định ảnh input
            if i == 1:
                input_image = first_image
                print(f"📸 Using first image: {os.path.basename(first_image)}")
            else:
                if not last_frame_path or not os.path.exists(last_frame_path):
                    raise RuntimeError(f"Missing frame for scene {i}")
                input_image = last_frame_path
                print(f"📸 Using frame from previous scene: {os.path.basename(last_frame_path)}")
            
            # Tạo video
            output_name = f"{i:03d}.mp4"
            print(f"💬 Prompt: {prompt}")
            
            video_path = await self.create_single_video(
                image_path=input_image,
                prompt=prompt,
                output_name=output_name,
                duration=duration,
                quality=quality,
                cancel_check=cancel_check,
                cancel_event=cancel_event
            )
            
            video_paths.append(video_path)
            print(f"✅ Video saved: {video_path}")
            
            # Cắt frame cuối cho cảnh tiếp theo (trừ cảnh cuối)
            if i < len(prompts):
                frame_output = self.output_dir / f"frame_{i+1}.jpg"
                print(f"✂️  Extracting last frame for next scene...")
                last_frame_path = extract_last_frame(
                    video_path,
                    str(frame_output),
                    self.ffmpeg_path
                )
                print(f"✅ Frame saved: {last_frame_path}")
        
        print(f"\n{'='*60}")
        print(f"🎉 All {len(prompts)} scenes completed!")
        print(f"{'='*60}\n")
        
        return video_paths
    
    async def create_video_chain_with_images(
        self,
        prompts: List[str],
        images: List[str],
        duration: str = "6s",
        quality: str = "720p",
        cancel_check: Optional[callable] = None,
        cancel_event=None
    ) -> List[str]:
        """
        Tạo chuỗi video, mỗi cảnh có ảnh tham chiếu riêng (không dùng frame chaining).
        
        Args:
            prompts: List prompt cho từng cảnh
            images: List ảnh tham chiếu cho từng cảnh
            duration: "6s" hoặc "10s"
            quality: "480p" hoặc "720p"
        
        Returns:
            List đường dẫn đến các video đã tạo
        """
        if len(prompts) != len(images):
            raise ValueError(f"Number of prompts ({len(prompts)}) must match number of images ({len(images)})")
        
        video_paths = []
        
        for i, (prompt, image) in enumerate(zip(prompts, images), start=1):
            print(f"\n{'='*60}")
            print(f"🎬 Creating Scene {i}/{len(prompts)}")
            print(f"{'='*60}")
            print(f"📸 Using image: {os.path.basename(image)}")
            print(f"💬 Prompt: {prompt}")
            
            output_name = f"{i:03d}.mp4"
            
            video_path = await self.create_single_video(
                image_path=image,
                prompt=prompt,
                output_name=output_name,
                duration=duration,
                quality=quality,
                cancel_check=cancel_check,
                cancel_event=cancel_event
            )
            
            video_paths.append(video_path)
            print(f"✅ Video saved: {video_path}")
        
        print(f"\n{'='*60}")
        print(f"🎉 All {len(prompts)} scenes completed!")
        print(f"{'='*60}\n")
        
        return video_paths
    
    async def _select_duration_quality(self, page, duration: str, quality: str):
        """Helper để chọn duration và quality."""
        try:
            await asyncio.sleep(1.0)
            duration_value = str(duration or '6s').strip()
            quality_value = str(quality or '720p').strip()
            
            all_buttons = await page.locator('button[role="radio"]').all()
            
            duration_clicked = False
            quality_clicked = False
            
            for btn in all_buttons:
                try:
                    text = await btn.inner_text()
                    text_clean = text.strip() if text else ''
                    
                    if text_clean == duration_value and not duration_clicked:
                        is_checked = await btn.get_attribute("aria-checked")
                        if is_checked != "true":
                            await btn.click()
                            await asyncio.sleep(0.5)
                        duration_clicked = True
                        
                    elif text_clean == quality_value and not quality_clicked:
                        is_checked = await btn.get_attribute("aria-checked")
                        if is_checked != "true":
                            await btn.click()
                            await asyncio.sleep(0.5)
                        quality_clicked = True
                        
                    if duration_clicked and quality_clicked:
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️  Could not select duration/quality: {e}")

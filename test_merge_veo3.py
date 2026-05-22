"""
Script test ghép 2 video trong temp_video bằng API ghép của Veo3.
Kiểm tra xem âm thanh gốc đã bị loại bỏ chưa.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.control_ffmpeg import merge_video_clips, apply_background_music, TRANSCODE_DIR


def test_merge_videos():
    """Test ghép 2 video trong temp_video"""
    
    print("\n" + "="*70)
    print("🧪 TEST GHÉP VIDEO VEO3 - KIỂM TRA TẮT ÂM THANH GỐC")
    print("="*70)
    
    # Đường dẫn 2 video test (dùng absolute path)
    video1 = os.path.abspath(os.path.join("temp_video", "001.mp4"))
    video2 = os.path.abspath(os.path.join("temp_video", "002.mp4"))
    
    # Kiểm tra file tồn tại
    if not os.path.exists(video1):
        print(f"❌ Không tìm thấy: {video1}")
        return False
    if not os.path.exists(video2):
        print(f"❌ Không tìm thấy: {video2}")
        return False
    
    print(f"✅ Tìm thấy video 1: {video1}")
    print(f"✅ Tìm thấy video 2: {video2}")
    
    # Output path
    output_merged = os.path.join(TRANSCODE_DIR, "test_merged_veo3.mp4")
    output_with_music = os.path.join(TRANSCODE_DIR, "test_merged_veo3_with_music.mp4")
    
    print("\n" + "-"*70)
    print("📝 BƯỚC 1: GHÉP 2 VIDEO (KHÔNG CÓ ÂM THANH GỐC)")
    print("-"*70)
    
    try:
        # Test ghép video với effect fade
        merged_path = merge_video_clips(
            clips=[video1, video2],
            out_path=output_merged,
            effect_key="fade",  # Dùng xfade transition
            transition_duration=0.5
        )
        print(f"✅ Đã ghép video thành công: {merged_path}")
        print(f"   📊 Kích thước: {os.path.getsize(merged_path) / 1024 / 1024:.2f} MB")
        
        # Kiểm tra video có audio không bằng ffprobe
        import subprocess
        cmd = [
            "ffprobe",
            "-hide_banner",
            "-loglevel", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            merged_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        has_audio = bool(result.stdout.strip())
        
        if has_audio:
            print(f"   ⚠️ Video vẫn còn audio stream (KHÔNG ĐÚNG!)")
            return False
        else:
            print(f"   ✅ Video KHÔNG có audio stream (ĐÚNG RỒI!)")
        
    except Exception as e:
        print(f"❌ Lỗi khi ghép video: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test thêm nhạc nền
    music_dir = os.path.abspath(os.path.join("config", "Music"))
    if os.path.isdir(music_dir):
        music_files = [f for f in os.listdir(music_dir) if f.lower().endswith(('.mp3', '.wav', '.m4a'))]
        if music_files:
            music_path = os.path.abspath(os.path.join(music_dir, music_files[0]))
            
            print("\n" + "-"*70)
            print("📝 BƯỚC 2: THÊM NHẠC NỀN (CHỈ CÓ NHẠC NỀN, KHÔNG CÓ ÂM GỐC)")
            print("-"*70)
            print(f"🎵 Nhạc nền: {music_files[0]}")
            
            try:
                final_path = apply_background_music(
                    video_path=merged_path,
                    music_path=music_path,
                    out_path=output_with_music,
                    music_volume=0.6
                )
                print(f"✅ Đã thêm nhạc nền thành công: {final_path}")
                print(f"   📊 Kích thước: {os.path.getsize(final_path) / 1024 / 1024:.2f} MB")
                
                # Kiểm tra video có audio không
                cmd = [
                    "ffprobe",
                    "-hide_banner",
                    "-loglevel", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    final_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                has_audio = bool(result.stdout.strip())
                
                if has_audio:
                    print(f"   ✅ Video có audio stream (nhạc nền)")
                else:
                    print(f"   ⚠️ Video KHÔNG có audio stream (KHÔNG ĐÚNG!)")
                    return False
                
            except Exception as e:
                print(f"❌ Lỗi khi thêm nhạc nền: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    print("\n" + "="*70)
    print("✅ TEST THÀNH CÔNG!")
    print("="*70)
    print(f"📁 Video đã ghép (không có âm gốc): {output_merged}")
    if os.path.exists(output_with_music):
        print(f"📁 Video có nhạc nền: {output_with_music}")
    print("\n💡 Hãy mở các file trên để kiểm tra:")
    print("   - Video ghép chỉ có hình, KHÔNG có tiếng")
    print("   - Video có nhạc nền chỉ có nhạc, KHÔNG có tiếng gốc")
    print("="*70 + "\n")
    
    return True


if __name__ == "__main__":
    try:
        success = test_merge_videos()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ LỖI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

"""
Test script to merge Grok videos from temp_video folder
This will test the video merging with transition effects and audio preservation
"""
import os
import sys
from utils.control_ffmpeg import merge_video_clips, _ffprobe_duration, _ffprobe_has_audio

def test_merge_grok_videos():
    print("=" * 60)
    print("Testing Grok Video Merging")
    print("=" * 60)
    
    # Input clips from temp_video folder (use absolute paths for Windows)
    base_dir = os.path.abspath(os.path.dirname(__file__))
    clips = [
        os.path.join(base_dir, "temp_video", "001.mp4"),
        os.path.join(base_dir, "temp_video", "002.mp4")
    ]
    
    # Check if files exist
    print("\n1. Checking input files...")
    for clip in clips:
        if not os.path.exists(clip):
            print(f"   ❌ File not found: {clip}")
            return
        size_mb = os.path.getsize(clip) / (1024 * 1024)
        duration = _ffprobe_duration(clip)
        has_audio = _ffprobe_has_audio(clip)
        print(f"   ✓ {clip}")
        print(f"     - Size: {size_mb:.2f} MB")
        print(f"     - Duration: {duration:.2f}s")
        print(f"     - Has audio: {'Yes' if has_audio else 'No'}")
    
    # Test 1: Merge without transition (concat demuxer)
    print("\n2. Test 1: Merging without transition (concat demuxer)...")
    output1 = os.path.join(base_dir, "temp_video", "merged_no_transition.mp4")
    try:
        merge_video_clips(clips, output1, effect_key="", transition_duration=0.5)
        if os.path.exists(output1):
            duration = _ffprobe_duration(output1)
            has_audio = _ffprobe_has_audio(output1)
            size_mb = os.path.getsize(output1) / (1024 * 1024)
            print(f"   ✓ Merged successfully: {output1}")
            print(f"     - Duration: {duration:.2f}s")
            print(f"     - Has audio: {'Yes' if has_audio else 'No'}")
            print(f"     - Size: {size_mb:.2f} MB")
        else:
            print(f"   ❌ Output file not created")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Merge with fade transition
    print("\n3. Test 2: Merging with fade transition (xfade)...")
    output2 = os.path.join(base_dir, "temp_video", "merged_with_fade.mp4")
    try:
        merge_video_clips(clips, output2, effect_key="fade", transition_duration=0.5)
        if os.path.exists(output2):
            duration = _ffprobe_duration(output2)
            has_audio = _ffprobe_has_audio(output2)
            size_mb = os.path.getsize(output2) / (1024 * 1024)
            print(f"   ✓ Merged successfully: {output2}")
            print(f"     - Duration: {duration:.2f}s")
            print(f"     - Has audio: {'Yes' if has_audio else 'No'}")
            print(f"     - Size: {size_mb:.2f} MB")
        else:
            print(f"   ❌ Output file not created")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Merge with dissolve transition
    print("\n4. Test 3: Merging with dissolve transition (xfade)...")
    output3 = os.path.join(base_dir, "temp_video", "merged_with_dissolve.mp4")
    try:
        merge_video_clips(clips, output3, effect_key="dissolve", transition_duration=0.5)
        if os.path.exists(output3):
            duration = _ffprobe_duration(output3)
            has_audio = _ffprobe_has_audio(output3)
            size_mb = os.path.getsize(output3) / (1024 * 1024)
            print(f"   ✓ Merged successfully: {output3}")
            print(f"     - Duration: {duration:.2f}s")
            print(f"     - Has audio: {'Yes' if has_audio else 'No'}")
            print(f"     - Size: {size_mb:.2f} MB")
        else:
            print(f"   ❌ Output file not created")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)
    print("\nExpected behavior:")
    print("- Without transition: Total duration = sum of all clips")
    print("- With transition: Total duration = sum - (transition_duration × (n-1))")
    print("- All outputs should have audio preserved from original clips")
    print("\nCheck the debug logs above for [DEBUG] Clip durations")

if __name__ == "__main__":
    test_merge_grok_videos()

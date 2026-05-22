"""
Script tạo package để upload lên GitHub Release cho OTA update
Sử dụng với dinorap-updater (không cần update.json)
"""
import os
import shutil
import sys
from datetime import datetime

# Cấu hình
CURRENT_VERSION = "v1.0.1"  # Version mới (phải > v1.0.0)
ZIP_NAME = "VideoCreator.zip"  # Tên file ZIP (PHẢI KHỚP với UPDATE_ZIP_NAME trong app.py)

# Thư mục cần loại trừ (dữ liệu người dùng)
EXCLUDED_DIRS = ["config", "storage", "generated", "temp_video", "tmp_uploads", ".venv", "__pycache__", ".git"]
EXCLUDED_FILES = [".gitignore", "*.pyc", "*.log"]

def create_release_package():
    """Tạo ZIP package để upload lên GitHub Release"""
    
    print("=" * 60)
    print(f"📦 TẠO PACKAGE UPDATE CHO VERSION {CURRENT_VERSION}")
    print("=" * 60)
    
    # Thư mục hiện tại (root project)
    project_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Tạo thư mục tạm để copy files
    temp_dir = os.path.join(project_dir, "temp_release")
    if os.path.exists(temp_dir):
        print(f"🧹 Xóa thư mục tạm cũ: {temp_dir}")
        shutil.rmtree(temp_dir)
    
    os.makedirs(temp_dir)
    print(f"📁 Tạo thư mục tạm: {temp_dir}")
    
    # Copy toàn bộ project vào thư mục tạm (trừ excluded)
    print("\n📋 Đang copy files...")
    copied_count = 0
    skipped_count = 0
    
    for item in os.listdir(project_dir):
        # Skip excluded directories
        if item in EXCLUDED_DIRS or item == "temp_release":
            print(f"  ⏭️  Bỏ qua: {item}/")
            skipped_count += 1
            continue
        
        src = os.path.join(project_dir, item)
        dst = os.path.join(temp_dir, item)
        
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.log'))
                print(f"  ✅ Copy thư mục: {item}/")
            else:
                shutil.copy2(src, dst)
                print(f"  ✅ Copy file: {item}")
            copied_count += 1
        except Exception as e:
            print(f"  ⚠️  Lỗi copy {item}: {e}")
            skipped_count += 1
    
    print(f"\n📊 Tổng kết: {copied_count} items copied, {skipped_count} items skipped")
    
    # Tạo file ZIP
    print(f"\n🗜️  Đang nén thành {ZIP_NAME}...")
    zip_path = os.path.join(project_dir, ZIP_NAME.replace('.zip', ''))
    shutil.make_archive(zip_path, 'zip', temp_dir)
    
    final_zip = f"{zip_path}.zip"
    zip_size = os.path.getsize(final_zip) / (1024 * 1024)  # MB
    
    # Cleanup temp directory
    print(f"\n🧹 Xóa thư mục tạm...")
    shutil.rmtree(temp_dir)
    
    print("\n" + "=" * 60)
    print("✅ HOÀN TẤT!")
    print("=" * 60)
    print(f"📦 File ZIP: {final_zip}")
    print(f"📏 Kích thước: {zip_size:.2f} MB")
    print(f"🏷️  Version: {CURRENT_VERSION}")
    print(f"📅 Ngày tạo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    print("\n" + "=" * 60)
    print("📝 HƯỚNG DẪN UPLOAD LÊN GITHUB RELEASE:")
    print("=" * 60)
    print("1. Vào: https://github.com/dinorap/video-release/releases/new")
    print(f"2. Tag version: {CURRENT_VERSION}")
    print(f"3. Release title: VideoCreator {CURRENT_VERSION}")
    print("4. Description: Mô tả các thay đổi (release notes)")
    print(f"5. Upload file: {ZIP_NAME}")
    print("6. Click 'Publish release'")
    print("\n⚠️  LƯU Ý: Tên file ZIP PHẢI là 'VideoCreator.zip' (đúng như config)")
    print("=" * 60)
    
    return final_zip

if __name__ == "__main__":
    try:
        create_release_package()
    except Exception as e:
        print(f"\n❌ LỖI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

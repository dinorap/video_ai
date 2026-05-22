import hashlib
import json
import os

ZIP_FILE = "VideoCreator.zip"

def calculate_sha256(filepath):
    """Tính SHA256 hash của file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(8192), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

if not os.path.exists(ZIP_FILE):
    print(f"❌ Không tìm thấy file {ZIP_FILE}")
    print(f"   Vui lòng đảm bảo file ZIP nằm trong thư mục hiện tại")
    exit(1)

print(f"📦 Đang tính SHA256 hash của {ZIP_FILE}...")
sha256 = calculate_sha256(ZIP_FILE)

update_info = {
    "version": "v1.0.1",
    "sha256": sha256,
    "release_notes": "Phiên bản đầu tiên với tính năng OTA update"
}

# Lưu file update.json
with open("update.json", "w", encoding="utf-8") as f:
    json.dump(update_info, f, indent=2, ensure_ascii=False)

print(f"✅ Đã tạo file update.json")
print(f"\nNội dung:")
print(json.dumps(update_info, indent=2, ensure_ascii=False))
print(f"\n📋 Các bước tiếp theo:")
print(f"1. Truy cập: https://github.com/dinorap/video-release/releases/tag/v1.0.1")
print(f"2. Click 'Edit release'")
print(f"3. Kéo thả file 'update.json' vào phần assets")
print(f"4. Click 'Update release'")
print(f"5. Refresh trang web của bạn - nút cập nhật sẽ xuất hiện!")

from dinorap_updater import OTAUpdater
import json

CURRENT_VERSION = "v1.0.0"

updater = OTAUpdater(
    github_user="dinorap",
    github_repo="video-release",
    current_version=CURRENT_VERSION
)

print(f"Current Version: {CURRENT_VERSION}")
print(f"\nChecking for updates...")

result = updater.check_for_update()
print(f"\nResult:")
print(json.dumps(result, indent=2, ensure_ascii=False))

# Kiểm tra GitHub API trực tiếp
import requests
print(f"\n" + "="*60)
print("Direct GitHub API Check:")
print("="*60)
r = requests.get('https://api.github.com/repos/dinorap/video-release/releases/latest')
if r.status_code == 200:
    data = r.json()
    print(f"Latest Release Tag: {data['tag_name']}")
    print(f"Published At: {data['published_at']}")
    print(f"Assets:")
    for asset in data['assets']:
        print(f"  - {asset['name']} ({asset['size']} bytes)")
        print(f"    URL: {asset['browser_download_url']}")

"""Tạo lại update.json từ VideoCreator.zip đã build (sau khi có --zip hoặc zip thủ công)."""
import hashlib
import json
import sys
from pathlib import Path

from version import CURRENT_VERSION, UPDATE_ZIP_NAME

ROOT = Path(__file__).resolve().parent
ZIP_PATH = ROOT / UPDATE_ZIP_NAME


def main() -> None:
    if not ZIP_PATH.is_file():
        print(f"[ERROR] Không thấy {ZIP_PATH}")
        print("Chạy: python build_fast_c++.py --release --clean --zip")
        sys.exit(1)

    h = hashlib.sha256()
    with open(ZIP_PATH, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)

    payload = {
        "version": CURRENT_VERSION,
        "sha256": h.hexdigest(),
        "release_notes": f"Release {CURRENT_VERSION}",
    }
    out = ROOT / "update.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

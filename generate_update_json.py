"""Chi tao lai update.json tu VideoCreator.zip (da co zip)."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from version import CURRENT_VERSION, UPDATE_ZIP_NAME

ROOT = Path(__file__).resolve().parent
ZIP_FILE = ROOT / UPDATE_ZIP_NAME
JSON_FILE = ROOT / "update.json"


def main() -> None:
    if not ZIP_FILE.is_file():
        print(f"[ERROR] Missing {ZIP_FILE} — run pack_release_update.py")
        sys.exit(1)

    log = " ".join(sys.argv[1:]).strip() or f"Release {CURRENT_VERSION}"

    h = hashlib.sha256()
    with open(ZIP_FILE, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            h.update(block)

    data = {
        "version": CURRENT_VERSION,
        "sha256": h.hexdigest(),
        "release_date": datetime.now().strftime("%Y-%m-%d"),
        "update_log": log,
        "release_notes": log,
    }
    JSON_FILE.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()

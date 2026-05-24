"""
Nén dist/VideoCreator thành VideoCreator.zip + update.json (upload GitHub Release).

Trước khi nén: xóa file user trong config/ + storage/ (không ghi đè máy khách khi OTA)
vẫn giữ config.dist.json, KichBan/, prompt/, Music/ trong zip.

Usage:
  python pack_release_update.py
  python pack_release_update.py --log "Mo ta phien ban"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from version import APP_NAME, CURRENT_VERSION, GITHUB_REPO, GITHUB_USER, UPDATE_ZIP_NAME

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist" / APP_NAME
ZIP_BASE = ROOT / UPDATE_ZIP_NAME.replace(".zip", "")
ZIP_FILE = ROOT / UPDATE_ZIP_NAME
JSON_FILE = ROOT / "update.json"

EXCLUDED_DIRS = ("storage",)
CONFIG_USER_FILES = ("config.json", "tasks.json", "veo_auth.json")


def remove_excluded_dirs() -> None:
  for folder_name in EXCLUDED_DIRS:
    folder_path = DIST_DIR / folder_name
    if folder_path.is_dir():
      print(f"[CLEAN] Removing {folder_path} before zip...")
      shutil.rmtree(folder_path)


def remove_user_config_files() -> None:
  cfg = DIST_DIR / "config"
  if not cfg.is_dir():
    return
  for name in CONFIG_USER_FILES:
    p = cfg / name
    if p.is_file():
      print(f"[CLEAN] Removing user file from zip: config/{name}")
      p.unlink()


def pack_zip() -> None:
  if not DIST_DIR.is_dir():
    print(f"[ERROR] Not found: {DIST_DIR}")
    print("Run first: python build_fast_c++.py --release --clean")
    sys.exit(1)

  if ZIP_FILE.exists():
    ZIP_FILE.unlink()

  print(f"[ZIP] Archiving {DIST_DIR} -> {ZIP_FILE.name}...")
  shutil.make_archive(str(ZIP_BASE), "zip", root_dir=str(DIST_DIR))

  if not ZIP_FILE.is_file():
    print(f"[ERROR] Failed to create {ZIP_FILE}")
    sys.exit(1)

  size_mb = ZIP_FILE.stat().st_size / (1024 * 1024)
  print(f"   [OK] {ZIP_FILE} ({size_mb:.2f} MB)")


def write_update_json(update_log: str) -> None:
  print(f"[HASH] SHA256 {ZIP_FILE.name}...")
  sha256_hash = hashlib.sha256()
  with open(ZIP_FILE, "rb") as f:
    for block in iter(lambda: f.read(4096), b""):
      sha256_hash.update(block)
  file_hash = sha256_hash.hexdigest()

  data = {
    "version": CURRENT_VERSION,
    "sha256": file_hash,
    "release_date": datetime.now().strftime("%Y-%m-%d"),
    "update_log": update_log or f"Release {CURRENT_VERSION}",
    "release_notes": update_log or f"Release {CURRENT_VERSION}",
  }

  JSON_FILE.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")

  print("-" * 40)
  print(f"version : {CURRENT_VERSION}")
  print(f"sha256  : {file_hash}")
  print(f"json    : {JSON_FILE}")
  print("-" * 40)
  print("Upload to GitHub release:")
  print(f"  https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases")
  print(f"  Tag: {CURRENT_VERSION}")
  print(f"  Assets: {UPDATE_ZIP_NAME} + update.json")


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--log", default="", help="Release notes")
  args = parser.parse_args()

  remove_excluded_dirs()
  remove_user_config_files()
  pack_zip()
  write_update_json(args.log)


if __name__ == "__main__":
  main()

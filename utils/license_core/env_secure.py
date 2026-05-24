import base64
import json
import os
from pathlib import Path


# NOTE: This is obfuscation, not strong cryptography.
_OBFUSCATED_ENV_KEY = "bGljZW5zZV9jb3JlX2Vudl9rZXlfMjAyNg=="


def _key_bytes() -> bytes:
    try:
        return base64.b64decode(_OBFUSCATED_ENV_KEY.encode("utf-8"))
    except Exception:
        return b"license_core_env_key_2026"


def _xor_stream(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    out = bytearray(len(data))
    key_len = len(key)
    for i, b in enumerate(data):
        out[i] = b ^ key[i % key_len]
    return bytes(out)


def _parse_env_text(env_text: str) -> None:
    for raw_line in env_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        value = v.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_license_env(base_dir: str) -> None:
    base = Path(base_dir)
    enc_path = base / ".env.enc"
    plain_path = base / ".env"

    if enc_path.exists():
        try:
            payload = json.loads(enc_path.read_text(encoding="utf-8"))
            blob = payload.get("data", "")
            decoded = base64.b64decode(blob.encode("utf-8"))
            plain = _xor_stream(decoded, _key_bytes()).decode("utf-8")
            _parse_env_text(plain)
            return
        except Exception:
            pass

    # Dev fallback: keep supporting local .env
    try:
        from dotenv import load_dotenv  # type: ignore

        if plain_path.exists():
            load_dotenv(str(plain_path))
        else:
            load_dotenv()
    except Exception:
        pass

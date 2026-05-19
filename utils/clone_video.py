import os
import json
import re
import time
import requests

import sys

OPENAI_TIMEOUT = 90
GEMINI_TIMEOUT = 180


def _write_debug_response(tag: str, status_code, body: str):
    try:
        base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out_dir = os.path.join(base_dir, "temp")
        os.makedirs(out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"clone_video_api_{tag}_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"status={status_code}\n")
            f.write(body if body is not None else "")
    except Exception:
        pass


BASE_PROMPT = '''
You are a professional video analysis system specialized in converting a single input video 
into reusable multi-scene prompts for Veo 3.

INPUT:
- Video: {VIDEO_PATH}
- Target product: {TARGET_PRODUCT}
- Target language: {language}
- Audio behavior mode: {AUDIO_MODE}

=====================================================
GLOBAL OUTPUT LANGUAGE RULE (CRITICAL)
=====================================================

� ALL textual content inside the ""prompt"" field MUST be written in {language}.
� {language} defines the language of the ENTIRE prompt output, not audio only.

This applies to:
- All descriptive sentences
- All embedded instructions
- All fixed phrases (duration, style rules, reference instructions)
- Scene descriptions

� JSON KEY NAMES and STRUCTURE MUST ALWAYS remain in English:
  - scene
  - prompt
  - audio

� ONLY string VALUES are translated into {language}.

=====================================================
STYLE RULE � REALISTIC LIVE-ACTION ONLY
=====================================================

� All scenes MUST be described as realistic live-action camera footage.
� The visual style MUST be natural and photographic, NOT stylized.
� ABSOLUTELY FORBIDDEN in style or implication:
  � cartoon
  � anime
  � comic
  � illustration
  � painting
  � 3D render / CGI look
� If the source video or reference frames look stylized or cartoon-like,
  you MUST reinterpret them as realistic live-action footage of a real human
  captured by a camera.

=====================================================
BACKGROUND RULE (REMOVED COMPLETELY)
=====================================================

� The system MUST NOT mention any background.
� MUST NOT infer or describe:
  � scenery
  � location
  � lighting
  � objects in the environment
  � weather
  � atmosphere / mood
� Background placeholders MUST NOT appear.

=====================================================
NO OBJECT REFERENCE RULE (CRITICAL)
=====================================================

� The system MUST NOT name, mention, or describe ANY object.
� Scene description MUST ONLY contain:
  � human posture
  � human movement
  � body orientation
  � minimal neutral expression

� The ONLY place where {TARGET_PRODUCT} may appear is in the fixed header line:
  �The first image is the product reference ({TARGET_PRODUCT})��

=====================================================
FULL BODY SHOT RULE (STRONG)
=====================================================

� The character MUST ALWAYS be fully visible from head to toe.
� Camera MUST maintain a stable full-body distance.
� MUST NOT zoom, crop, or switch shot scale.
� Any close-up in the source MUST be reinterpreted as a full-body shot.

=====================================================
MOVING FULL-BODY CAMERA RULE
=====================================================

� When the character walks or moves:
  � The camera MUST follow the character.
  � Full-body framing MUST remain constant.
  � The camera MUST NOT move closer or zoom.

=====================================================
NO APPEARANCE RULE
=====================================================

� NEVER describe:
  � facial features
  � body shape
  � hairstyle
  � clothing details
  � accessories
� Expressions allowed ONLY if neutral/minimal.
� NEVER describe mouth or lip movement.

=====================================================
MOVEMENT LOGIC RULE
=====================================================

� Movements MUST be minimal and realistic.

Allowed:
- standing still
- walking / stepping
- slight body rotation
- slight weight shift

Allowed to repeat naturally:
? walking
? body rotation

Disallowed:
- pointing
- expressive gestures
- acting poses
- touching face/body
- dance-like motion
- kneeling or squatting

=====================================================
AUTO-SKIP SITTING RULE
=====================================================

� ALL sitting actions MUST be ignored.
� Replace with a neutral full-body standing pose.

=====================================================
NO REPEATED ACTIONS RULE
=====================================================

� Repeated actions MUST be compressed into ONE description.
� EXCEPT walking and rotation, which may repeat naturally.

=====================================================
NO TRANSITIONS RULE
=====================================================

� MUST NOT use transitional words:
  � then
  � after that
  � next
  � begins to
� Describe ONLY the final or continuous action state.

=====================================================
CAMERA CONSISTENCY RULE
=====================================================

� Camera angle, distance, and framing MUST remain constant.
� Full-body framing MUST NEVER change.

=====================================================
SCENE SPLIT RULE
=====================================================

� Analyze the video by audio segmentation.
� One scene = one continuous speech OR one continuous silence.
� Each scene duration MUST be exactly 8 seconds.

=====================================================
AUDIO MODE RULES
=====================================================

If {AUDIO_MODE} = ""silent"":
- No dialogue.
- No communicative gestures.
- ""audio"" MUST be """";
- ""prompt"" language MUST still be {language}.

If {AUDIO_MODE} = ""voiced"":
- Translate speech into {language}.
- Embed dialogue using EXACT format (translated):

  ""While maintaining a neutral pose, the character says in {language}: '�' ""

- ""audio"" MUST contain ONLY the dialogue text in {language}.
- NEVER describe mouth or lip movement.

=====================================================
OUTPUT FORMAT (JSON ONLY)
=====================================================

The system MUST output EXACTLY this structure:

[
    {
      ""scene"": {i},
      ""prompt"":
        ""? ALL CONTENT HERE MUST BE WRITTEN IN {language}.
         duration: 8 seconds.
         realistic live-action footage, no cartoon, no illustration.
         The first image is the product reference ({TARGET_PRODUCT}).
         Use it ONLY for the product's appearance.
         The second image is the character reference.
         Use it ONLY for the character's appearance.
         Scene {i}: The character is fully visible from head to toe
         in a stable full-body shot. [Describe ONLY human pose and motion.
         No objects. No background. No appearance details.
         No sitting. No transitions. No mouth movement.
         Walking and rotation may repeat naturally.
         Camera MUST remain full-body and MUST NOT zoom or crop.]"",
      ""audio"": ""If voiced: ONLY dialogue in {language}. If silent: ''""
    }
]


=====================================================
ABSOLUTE REQUIREMENTS
=====================================================

� FULL-BODY framing ALWAYS
� REALISTIC live-action ONLY
� ZERO objects
� ZERO background
� ZERO appearance description
� ZERO sitting
� ZERO transitions
� ZERO mouth movement
� VALID JSON ONLY

=====================================================
OUTPUT LANGUAGE ENFORCEMENT (ABSOLUTE)
=====================================================
You MUST write the entire value of each output field ""prompt"" in {language}.
This includes translating ALL fixed lines such as:
- ""duration: 8 seconds.""
- ""realistic live-action footage, no cartoon, no illustration.""
- ""The first image is the product reference ({TARGET_PRODUCT}).""
- ""Use it ONLY for the product's appearance.""
- ""The second image is the character reference.""
- ""Use it ONLY for the character's appearance.""
- ""Scene {i}: ...""
NO ENGLISH is allowed inside ""prompt"" when {language} is Vietnamese.
Only JSON keys remain in English.
'''


# =========================
# Normalize language
# =========================

def normalize_language(language: str) -> str:
    s = (language or "").strip()

    if not s:
        return "English"

    lower = s.lower()

    if "vi?t" in lower or lower == "vi" or "vietnam" in lower:
        return "Vietnamese"

    if "english" in lower or lower == "en":
        return "English"

    return s


# =========================
# MIME TYPE
# =========================

def guess_mime_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()

    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".wmv": "video/x-ms-wmv",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
        ".flv": "video/x-flv",
        ".ts": "video/mp2t",
        ".mpeg": "video/mpeg",
        ".mpg": "video/mpeg"
    }.get(ext, "application/octet-stream")


# =========================
# JSON UTIL
# =========================

def try_parse_json(text):

    try:
        obj = json.loads(text)
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except:
        return None


def strip_markdown(text):

    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)

    if m:
        return m.group(1).strip()

    return text.strip()


def extract_json_substring(text):

    m = re.search(r"\{.*\}", text, re.S)

    if m:
        return m.group(0)

    m = re.search(r"\[.*\]", text, re.S)

    if m:
        return m.group(0)

    return ""


def ensure_json_output(ai_text):

    if not ai_text:
        return local_error_json("Empty AI content.")

    parsed = try_parse_json(ai_text)

    if parsed:
        return parsed

    cleaned = strip_markdown(ai_text)

    parsed = try_parse_json(cleaned)

    if parsed:
        return parsed

    extracted = extract_json_substring(cleaned)

    if extracted:
        parsed = try_parse_json(extracted)

        if parsed:
            return parsed

    return local_error_json("AI returned non-JSON text.", ai_text)


def ensure_json_or_return_raw(body):

    parsed = try_parse_json(body)

    if parsed:
        return parsed

    return local_error_json("HTTP error but response is not JSON.", body)


def local_error_json(message, raw_text=""):

    return json.dumps(
        {
            "ok": False,
            "error": message,
            "raw_text": raw_text
        },
        indent=2,
        ensure_ascii=False
    )


# =========================
# OPENAI CALL
# =========================

def call_openai(api_key, model, prompt):

    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    } 

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You must output valid JSON only. Do not add any extra text."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    r = requests.post(url, headers=headers, json=payload, timeout=OPENAI_TIMEOUT)

    return r.status_code, r.text


def extract_openai_text(body):

    data = json.loads(body)

    if not data["choices"]:
        return ""

    return data["choices"][0]["message"]["content"]


# =========================
# GEMINI UPLOAD
# =========================

def gemini_resumable_upload(api_key, file_path):

    mime = guess_mime_type(file_path)
    file_name = os.path.basename(file_path)

    url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}"

    meta = {
        "file": {
            "displayName": file_name,
            "mimeType": mime
        }
    }

    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Type": mime
    }

    r = requests.post(url, headers=headers, json=meta)

    if not r.ok:
        return None, r.text

    upload_url = r.headers.get("X-Goog-Upload-URL")

    if not upload_url:
        return None, "Missing upload URL"

    with open(file_path, "rb") as f:
        data = f.read()

    headers = {
        "X-Goog-Upload-Command": "upload, finalize",
        "X-Goog-Upload-Offset": "0",
        "Content-Type": mime
    }

    r = requests.post(upload_url, headers=headers, data=data)

    if not r.ok:
        return None, r.text

    body = r.json()

    return body["file"], None


# =========================
# WAIT ACTIVE
# =========================

def gemini_wait_active(api_key, file_name):

    url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"

    start = time.time()

    while True:

        r = requests.get(url)

        if not r.ok:
            return False, r.text

        data = r.json()

        state = data.get("state")

        if state == "ACTIVE":
            return True, data

        if state == "FAILED":
            return False, data

        if time.time() - start > 180:
            return False, "Gemini processing timeout"

        time.sleep(2)


# =========================
# GEMINI GENERATE
# =========================

def gemini_generate(api_key, model, file_uri, mime_type, prompt):

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "file_data": {
                            "mime_type": mime_type,
                            "file_uri": file_uri
                        }
                    },
                    {"text": prompt}
                ]
            }
        ]
    }

    r = requests.post(url, json=payload, timeout=GEMINI_TIMEOUT)

    return r.status_code, r.text


def extract_gemini_text(body):

    try:
        data = json.loads(body)
    except Exception:
        return ""

    candidates = data.get("candidates", [])
    if not candidates:
        return ""

    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    if not isinstance(content, dict):
        return ""

    parts = content.get("parts", [])
    if not isinstance(parts, list) or not parts:
        return ""

    chunks = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        t = p.get("text")
        if isinstance(t, str) and t.strip():
            chunks.append(t)

    text = "\n".join(chunks)
    if not text:
        return ""

    text = re.sub(r"[\r\n]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# =========================
# DELETE FILE
# =========================

def gemini_delete_file(api_key, file_name):

    url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"

    try:
        r = requests.delete(url)
        return r.status_code, r.text
    except Exception as exc:
        return 0, str(exc)


# =========================
# MAIN FUNCTION
# =========================

def generate_prompt_json(
    api_key,
    model,
    video_path,
    target_product,
    language,
    audio_mode="silent"
):

    if not os.path.exists(video_path):
        return local_error_json("Video file not found")

    lang = normalize_language(language)

    prompt = BASE_PROMPT \
        .replace("{VIDEO_PATH}", video_path) \
        .replace("{TARGET_PRODUCT}", target_product) \
        .replace("{language}", lang) \
        .replace("{AUDIO_MODE}", audio_mode)

    # OPENAI
    if model.startswith("gpt-"):

        status, body = call_openai(api_key, model, prompt)

        if status != 200:
            return ensure_json_or_return_raw(body)

        text = extract_openai_text(body)

        return ensure_json_output(text)

    # GEMINI
    if model.startswith("gemini-"):

        file_name = ""
        try:
            file_info, err = gemini_resumable_upload(api_key, video_path)

            if err:
                return ensure_json_or_return_raw(str(err))

            file_name = file_info.get("name", "")
            file_uri = file_info.get("uri", "")
            mime = file_info.get("mimeType", "")

            if not file_name or not file_uri or not mime:
                return local_error_json("Gemini upload returned invalid file info")

            ok, body = gemini_wait_active(api_key, file_name)

            if not ok:
                return ensure_json_or_return_raw(str(body))

            status, body = gemini_generate(api_key, model, file_uri, mime, prompt)

            if status != 200:
                return ensure_json_or_return_raw(body)

            text = extract_gemini_text(body)

            return ensure_json_output(text)
        finally:
            if file_name:
                try:
                    gemini_delete_file(api_key, file_name)
                except Exception:
                    pass

    return local_error_json("Unsupported model prefix")
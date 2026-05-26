"""
Reference image prompts for video generation (Veo3 / Grok).
Mutually exclusive: slot 3 (combined) OR slots 1+2 (product/character), never both.
Injects reference text immediately before "Scene N:" in the prompt.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

REFERENCE_PROMPTS = {
    "character": (
        "Use the image as the character reference only. "
        "Use it ONLY for the character's appearance."
    ),
    "product": (
        "Use the image as the product reference only. "
        "Use it ONLY for the product's appearance."
    ),
    "character_and_product": (
        "Use the image as both the character and outfit reference. "
        "Use it ONLY for the character's and product's appearance."
    ),
}

_TWO_IMAGE_INSTRUCTION = (
    "Use the first image as the product reference only. "
    "Use it ONLY for the product's appearance. "
    "Use the second image as the character reference only. "
    "Use it ONLY for the character's appearance."
)

_SCENE_MARK_RE = re.compile(r"\bScene\s+\d+\s*:", re.IGNORECASE)

# Legacy + dynamic reference blocks to strip before re-injecting
_LEGACY_REFERENCE_PATTERNS = [
    re.compile(
        r"The first image is the product reference[^.]*\.\s*"
        r"Use it ONLY for the product'?s appearance\.\s*"
        r"The second image is the character reference[^.]*\.\s*"
        r"Use it ONLY for the character'?s appearance\.\s*",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"The first image is the product reference[^.]*\.\s*"
        r"Use it ONLY for the product'?s appearance\.\s*"
        r"The second image is the character reference[^.]*\.\s*",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"The first image is the product reference[^.]*\.\s*"
        r"The second image is the character reference[^.]*\.\s*",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"Use it ONLY for the product'?s appearance\.\s*", re.IGNORECASE),
    re.compile(r"Use it ONLY for the character'?s appearance\.\s*", re.IGNORECASE),
    re.compile(
        r"Use the image as the product reference only\.\s*"
        r"Use it ONLY for the product'?s appearance\.\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"Use the image as the character reference only\.\s*"
        r"Use it ONLY for the character'?s appearance\.\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"Use the image as both the character and outfit reference\.\s*"
        r"Use it ONLY for the character'?s and product'?s appearance\.\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"Use the first image as the product reference only\.\s*"
        r"Use it ONLY for the product'?s appearance\.\s*"
        r"Use the second image as the character reference only\.\s*"
        r"Use it ONLY for the character'?s appearance\.\s*",
        re.IGNORECASE,
    ),
    re.compile(r"Use the image as the product reference only\.\s*", re.IGNORECASE),
    re.compile(r"Use the image as the character reference only\.\s*", re.IGNORECASE),
    re.compile(
        r"Use the image as both the character and outfit reference\.\s*", re.IGNORECASE
    ),
    re.compile(r"Use the first image as the product reference only\.\s*", re.IGNORECASE),
    re.compile(r"Use the second image as the character reference only\.\s*", re.IGNORECASE),
]


def strip_legacy_reference_block(text: str) -> str:
    """Remove old or previously injected reference lines from a scene prompt."""
    s = str(text or "")
    if not s.strip():
        return ""
    for pat in _LEGACY_REFERENCE_PATTERNS:
        s = pat.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def build_reference_instruction(ref_types: Sequence[str]) -> str:
    """Build reference instruction from exclusive slot types (1 or 2 images only)."""
    types = [t for t in ref_types if t in REFERENCE_PROMPTS]
    n = len(types)
    if n == 0:
        return ""
    if n == 1:
        return REFERENCE_PROMPTS[types[0]]
    if n == 2 and types[0] == "product" and types[1] == "character":
        return _TWO_IMAGE_INSTRUCTION
    return ""


def compose_video_prompt(base_prompt: str, ref_types: Sequence[str]) -> str:
    """Strip old reference text and insert new block immediately before Scene N:."""
    core = strip_legacy_reference_block(base_prompt)
    instr = build_reference_instruction(ref_types)
    if not instr:
        return core
    if not core:
        return instr
    m = _SCENE_MARK_RE.search(core)
    if m:
        before = core[: m.start()].rstrip()
        after = core[m.start() :].lstrip()
        if before:
            return f"{before} {instr} {after}".strip()
        return f"{instr} {after}".strip()
    return f"{core.rstrip()} {instr}".strip()


def _non_empty_data_url(value: Optional[str]) -> str:
    v = str(value or "").strip()
    if v.startswith("data:image"):
        return v
    return ""


def resolve_exclusive_reference_urls(
    ref_product: Optional[str] = None,
    ref_character: Optional[str] = None,
    ref_combined: Optional[str] = None,
    *,
    default_image: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """
    Slot 3 (combined) OR slots 1–2 (product/character), never both.
    default_image applies only as slot 3 when slots 1–2 are empty.
    """
    product = _non_empty_data_url(ref_product)
    character = _non_empty_data_url(ref_character)
    combined = _non_empty_data_url(ref_combined)

    if combined:
        return [combined], ["character_and_product"]

    if product or character:
        urls: List[str] = []
        types: List[str] = []
        if product:
            urls.append(product)
            types.append("product")
        if character:
            urls.append(character)
            types.append("character")
        return urls, types

    fallback = _non_empty_data_url(default_image)
    if fallback:
        return [fallback], ["character_and_product"]

    return [], []


def prepare_scene_references(
    *,
    scene_prompt: str,
    ref_product: Optional[str] = None,
    ref_character: Optional[str] = None,
    ref_combined: Optional[str] = None,
    default_image: Optional[str] = None,
) -> Tuple[List[str], List[str], str]:
    """
    Returns:
        (data_urls_in_upload_order, ref_types, final_prompt)
    """
    ref_urls, ref_types = resolve_exclusive_reference_urls(
        ref_product,
        ref_character,
        ref_combined,
        default_image=default_image,
    )
    core = strip_legacy_reference_block(scene_prompt)
    if not ref_urls:
        return [], [], core

    final_prompt = compose_video_prompt(core, ref_types)
    return ref_urls, ref_types, final_prompt

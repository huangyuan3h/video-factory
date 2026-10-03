"""Language-aware edge-tts voice mapping.

A video's spoken language and its TTS voice must agree: an English script
narrated by a Chinese neural voice sounds broken (and vice versa). When a caller
requests ``language=en`` but leaves the default Chinese voice in place, the
pipeline silently swaps in the English default rather than speaking English with
a Mandarin voice.

The mapping is intentionally small and pure so it is cheap to unit test:

* :data:`DEFAULT_VOICES` — one solid, natural voice per supported language.
* :data:`VOICE_PROFILES` — optional Chinese voice presets (default unchanged).
* :func:`normalize_language` — collapse ``en-US`` / ``EN`` / ``zh`` to a code.
* :func:`voice_language` — read the language prefix off an edge voice id.
* :func:`resolve_voice` — keep an explicit, language-matching voice; otherwise
  fall back to the language default (backward compatible with a Chinese
  pipeline that passes no language at all).
* :func:`resolve_voice_profile` — map an optional profile name to a voice id.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "zh"

# Documented defaults. ``zh`` uses Yunjian, the steady male narration voice
# chosen as the global Video Factory default; ``en`` uses Aria, a natural
# US-English narration voice that works well for documentary / explainer content
# (the growth target for the YouTube path).
DEFAULT_VOICES: dict[str, str] = {
    "zh": "zh-CN-YunjianNeural",
    "en": "en-US-AriaNeural",
    "ja": "ja-JP-NanamiNeural",
}

# Optional Chinese voice presets (2026-10-02 polish). The global default stays
# Yunjian; setting ``TTS_VOICE_PROFILE`` (or passing a profile name where a
# voice is accepted) swaps to one of these more natural candidates for A/B.
# All four are edge-tts zh-CN Neural voices actually available as of 2026-10
# (see `edge_tts.list_voices()`; older Yunhao/Yunye/etc. no longer return audio).
VOICE_PROFILES: dict[str, dict[str, str]] = {
    "default": {
        "voice": "zh-CN-YunjianNeural",
        "description": "Yunjian (Male, Steady) — current default, unchanged",
    },
    "warm-female": {
        "voice": "zh-CN-XiaoxiaoNeural",
        "description": "Xiaoxiao (Female, Natural) — warm female, good for news/narrative",
    },
    "sunny-male": {
        "voice": "zh-CN-YunxiNeural",
        "description": "Yunxi (Male, Sunny) — brighter male, good for explainer/tech",
    },
    "gentle-female": {
        "voice": "zh-CN-XiaoyiNeural",
        "description": "Xiaoyi (Female, Gentle) — gentle female, good for emotional/book content",
    },
}

DEFAULT_VOICE_PROFILE = "default"


def normalize_language(language: str | None) -> str:
    """Return a short lowercase language code (``en-US`` -> ``en``)."""
    code = (language or "").strip().lower()
    if not code:
        return DEFAULT_LANGUAGE
    return code.split("-")[0].split("_")[0] or DEFAULT_LANGUAGE


def voice_language(voice: str | None) -> str | None:
    """Language prefix of an edge voice id (``en-US-AriaNeural`` -> ``en``).

    Edge voice ids are ``<lang>-<REGION>-<Name>``; requiring a 2-letter language
    *and* a region code avoids mistaking a custom id like ``my-narrator`` for a
    language.
    """
    if not voice:
        return None
    parts = voice.strip().split("-")
    if len(parts) < 2:
        return None
    lang, region = parts[0].strip(), parts[1].strip()
    if len(lang) != 2 or not lang.isalpha():
        return None
    if len(region) != 2 or not region.isalpha():
        return None
    return lang.lower()


def resolve_voice(language: str | None, requested_voice: str | None = None) -> str:
    """Pick the TTS voice for ``language``.

    An explicit ``requested_voice`` is respected when it already matches the
    requested language. A mismatched voice is replaced by the language default
    so the narration is never spoken in the wrong language. Unknown/custom voice
    ids (no recognizable language prefix) are left untouched.
    """
    lang = normalize_language(language)
    default = DEFAULT_VOICES.get(lang, DEFAULT_VOICES[DEFAULT_LANGUAGE])
    requested = (requested_voice or "").strip()
    if not requested:
        return default
    if voice_language(requested) == lang:
        return requested
    if voice_language(requested) is None:
        # Custom/unrecognized voice id — trust the caller.
        return requested
    return default


def default_voice(language: str | None) -> str:
    """Language default voice (ignores any caller-supplied voice)."""
    return DEFAULT_VOICES.get(normalize_language(language), DEFAULT_VOICES[DEFAULT_LANGUAGE])


def resolve_voice_profile(profile: str | None) -> str:
    """Map an optional voice profile name to an edge-tts voice id.

    ``None``/empty/``default``/unknown -> global default (Yunjian, unchanged).
    Known profiles (``warm-female``, ``sunny-male``, ``documentary-male``) return
    their candidate voice. Matching is case-insensitive and strips whitespace.
    """
    key = (profile or "").strip().lower()
    if not key or key == DEFAULT_VOICE_PROFILE:
        return DEFAULT_VOICES[DEFAULT_LANGUAGE]
    entry = VOICE_PROFILES.get(key)
    if entry:
        return entry["voice"]
    return DEFAULT_VOICES[DEFAULT_LANGUAGE]


def list_voice_profiles() -> dict[str, dict[str, str]]:
    """All optional voice profiles (name -> {voice, description})."""
    return {name: dict(info) for name, info in VOICE_PROFILES.items()}

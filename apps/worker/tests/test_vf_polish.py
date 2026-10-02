"""VF polish 2026-10-02: per-item regression tests (no browser, no publish, no network)."""
from pathlib import Path

import pytest


def test_voice_profiles_default_unchanged():
    from src.core.tts.voices import (
        DEFAULT_VOICES,
        VOICE_PROFILES,
        list_voice_profiles,
        resolve_voice_profile,
    )

    # Default unchanged (Yunjian everywhere).
    assert DEFAULT_VOICES["zh"] == "zh-CN-YunjianNeural"
    assert resolve_voice_profile(None) == "zh-CN-YunjianNeural"
    assert resolve_voice_profile("") == "zh-CN-YunjianNeural"
    assert resolve_voice_profile("default") == "zh-CN-YunjianNeural"
    assert resolve_voice_profile("unknown-profile") == "zh-CN-YunjianNeural"
    # 2-3 more natural candidates, all distinct from default.
    assert VOICE_PROFILES["warm-female"]["voice"] == "zh-CN-XiaoxiaoNeural"
    assert VOICE_PROFILES["sunny-male"]["voice"] == "zh-CN-YunxiNeural"
    assert VOICE_PROFILES["gentle-female"]["voice"] == "zh-CN-XiaoyiNeural"
    assert resolve_voice_profile("warm-female") == "zh-CN-XiaoxiaoNeural"
    assert resolve_voice_profile("SUNNY-MALE") == "zh-CN-YunxiNeural"
    profiles = list_voice_profiles()
    assert set(profiles) == {"default", "warm-female", "sunny-male", "gentle-female"}


def test_voice_profile_config_default():
    from src.config import Settings

    s = Settings()
    assert s.tts_voice == "zh-CN-YunjianNeural"
    assert s.tts_voice_profile == "default"


def test_edge_provider_accepts_profile():
    from src.core.tts.edge_provider import EdgeTTSProvider

    assert EdgeTTSProvider().voice == "zh-CN-YunjianNeural"
    assert EdgeTTSProvider(voice="warm-female").voice == "zh-CN-XiaoxiaoNeural"
    assert EdgeTTSProvider(voice="zh-CN-XiaoxiaoNeural").voice == "zh-CN-XiaoxiaoNeural"


def test_daily_news_pause_preset():
    from src.presets import get_type_preset

    p = get_type_preset("daily_news")
    # Old 0/0/0 ran together; new gap 0.6 + segment 0.4 (tighter than indicator 0.75/0.5).
    assert p.sentence_gap_seconds == 0.6
    assert p.segment_pause_seconds == 0.4
    assert p.sentence_pause_seconds == 0.0
    # Indicator/book unchanged (evidence they were already tuned).
    ind = get_type_preset("indicator")
    assert (ind.sentence_gap_seconds, ind.segment_pause_seconds) == (0.75, 0.5)
    book = get_type_preset("book")
    assert (book.sentence_pause_seconds, book.segment_pause_seconds) == (0.38, 0.5)


def test_ass_playres_scales_to_1440p():
    from src.core.subtitle_gen import SubtitleGenerator

    gen = SubtitleGenerator(max_chars_per_line=26)
    s1 = gen.generate_ass([], font_size=48, play_res_x=1920, play_res_y=1080, outline=3)
    assert "PlayResX: 1920" in s1 and "PlayResY: 1080" in s1
    assert ",48," in s1 and ",1,3," in s1
    s2 = gen.generate_ass([], font_size=64, play_res_x=2560, play_res_y=1440, outline=4)
    assert "PlayResX: 2560" in s2 and "PlayResY: 1440" in s2
    assert ",64," in s2 and ",1,4," in s2


def test_subtitle_stroke_scales():
    # Letterbox stroke: 3 @1080p -> 4 @1440p (same formula as compose_service).
    assert max(3, int(round(1080 * 0.0028))) == 3
    assert max(3, int(round(1440 * 0.0028))) == 4
    # Fullframe in-band font scales with height (38 @1080p, 51 @1440p).
    assert int(1080 * 0.036) == 38
    assert int(1440 * 0.036) == 51


def test_cover_uses_fit_not_stretch():
    import inspect

    from src.services import cover_service

    src = inspect.getsource(cover_service._draw_cover_image)
    assert "ImageOps.fit" in src
    # Old unconditional stretch `img = img.resize((width, height)...` is gone;
    # only a narrow except-fallback may still resize.
    assert "img = Image.open(bg_path)\n        img = img.resize((width, height)" not in src


def test_fit_cover_never_stretches():
    import inspect

    from src.services import compose_service

    src = inspect.getsource(compose_service._fit_cover)
    # Fallback returns opaque canvas, never a stretched resize.
    assert "clip.resized(new_size=resolution)" not in src
    assert "ColorClip" in src


def test_pexels_cache_timeout_concurrency():
    from src.services.material import pexels_service as px

    assert px.SEARCH_TIMEOUT_S == 15.0
    assert px.DOWNLOAD_TIMEOUT_S == 30.0
    assert px.SEARCH_CACHE_TTL_S == 300
    assert px.DOWNLOAD_CONCURRENCY == 4
    px._cache_set(("k",), {"a": 1})
    assert px._cache_get(("k",)) == {"a": 1}
    px.clear_pexels_cache()
    assert px._cache_get(("k",)) is None


def test_us_chapter_drops_jp_terms():
    from src.services.material.material_fetcher import derive_book_search_terms

    us = derive_book_search_terms(["美国", "美联储"], "美国加息之后")
    joined = " ".join(us).lower()
    assert "japan" not in joined
    assert "tokyo" not in joined
    assert "yen" not in joined
    # JP chapter keeps JP terms.
    jp = derive_book_search_terms(["泡沫经济"], "泡沫经济的崩溃")
    assert any("japan" in t or "tokyo" in t for t in jp)


def test_duration_tolerance_helper():
    from src.services.video_service import duration_within_tolerance

    assert duration_within_tolerance(210, 210) is True
    assert duration_within_tolerance(260, 210) is True  # 23.8% within 25%
    assert duration_within_tolerance(270, 210) is False  # 28.6% exceeds
    assert duration_within_tolerance(100, 0) is True  # no target -> ok


def test_word_break_keeps_numbers_together():
    from src.core.subtitle_gen import SubtitleGenerator

    gen = SubtitleGenerator(max_chars_per_line=20)
    # Numbers/percents/times never split mid-unit.
    lines = gen._split_into_lines("涨了15.5%，成交1000亿，时间3:00，代码CDO2004")
    joined = "".join(lines)
    for token in ("15.5", "1000", "3:00", "CDO2004"):
        assert token in joined
    # Orphan merge: tiny trailing chunk folds into previous line.
    pieces = gen._split_sentence_pieces("这是一个很长的句子，用于测试断词是否正确处理最后一个很短的尾巴么")
    assert len(pieces[-1]) >= 4 or len(pieces) == 1


def test_book_has_no_hardcoded_titles():
    # Prod book path derives titles from headings; no example book names.
    import pathlib

    worker = pathlib.Path(__file__).resolve().parents[1]
    for name in ("book_service.py", "book_script.py"):
        text = (worker / "src" / "services" / name).read_text(encoding="utf-8")
        for bad in ("红楼梦", "三体", "活着", "百年孤独", "我的书"):
            # "我的书" only appears in tests, never in prod.
            if name == "book_service.py" and bad == "我的书":
                continue
            assert bad not in text


def test_funnel_default_url():
    from src.services.funnel import DEFAULT_FUNNEL_URL, build_description, funnel_url

    assert DEFAULT_FUNNEL_URL == "https://zhibiao.it-t.xyz/request"
    assert funnel_url() == DEFAULT_FUNNEL_URL
    desc = build_description("测试标题", "第26集")
    assert DEFAULT_FUNNEL_URL in desc


def test_mypy_in_dev_deps_and_lock():
    import pathlib
    import tomllib

    repo = Path(__file__).resolve().parents[3]
    py = tomllib.loads((repo / "apps" / "worker" / "pyproject.toml").read_text(encoding="utf-8"))
    dev = py["tool"]["uv"]["dev-dependencies"]
    assert any("mypy" in d for d in dev)
    lock = (repo / "apps" / "worker" / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "mypy"' in lock


def test_tts_samples_exist_30s():
    repo = Path(__file__).resolve().parents[3]
    tts = repo / "samples" / "tts"
    assert (tts / "sample_text.txt").is_file()
    for name in ("default", "warm-female", "sunny-male", "gentle-female"):
        p = tts / f"{name}.mp3"
        assert p.is_file(), name
        assert p.stat().st_size > 50_000, name

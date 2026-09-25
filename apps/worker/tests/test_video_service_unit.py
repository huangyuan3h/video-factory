"""Unit tests for src/services/video_service.py.

Every external dependency (LLM, TTS, material fetching, ffmpeg/compose, DB,
publishers, cover/subtitle generation) is mocked. Only TaskLogger is real,
since it merely writes files into a tmp dir.
"""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.subtitle_gen import Subtitle
from src.core.task_logger import TaskLogger
from src.services import video_service as vs


def _request(**overrides):
    """Build a lightweight request stand-in with sensible defaults."""
    base = dict(
        title="测试标题",
        voice="zh-CN-XiaoxiaoNeural",
        voice_rate="+0%",
        resolution_width=1920,
        resolution_height=1080,
        text_content="原始内容",
        system_prompt="",
        series_id=None,
        rewrite_content=False,
        generate_subtitle=True,
        generate_cover=True,
        fps=30,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_seg(text="段落内容", keywords=None, duration=30):
    seg = MagicMock()
    seg.text = text
    seg.keywords = keywords if keywords is not None else ["关键词1", "关键词2"]
    seg.duration_estimate = duration
    return seg


@dataclass(frozen=True)
class _FrozenRequest:
    text_content: str = "原始内容"
    title: str = "测试"
    system_prompt: str = "系统提示"
    rewrite_content: bool = True
    voice: str = "v"
    resolution_width: int = 1920
    resolution_height: int = 1080


# ---------------------------------------------------------------------------
# _ensure_not_cancelled
# ---------------------------------------------------------------------------


def test_ensure_not_cancelled_passes_when_no_flag(tmp_path):
    tl = TaskLogger("enc-ok", tmp_path)
    vs._ensure_not_cancelled(tl)


def test_ensure_not_cancelled_raises_when_flag_set(tmp_path):
    tl = TaskLogger("enc-cancel", tmp_path)
    tl.cancel_file.write_text("1", encoding="utf-8")
    with pytest.raises(vs.GenerationCancelled):
        vs._ensure_not_cancelled(tl)


# ---------------------------------------------------------------------------
# _init_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_task_without_series(tmp_path):
    tl = TaskLogger("init-noseries", tmp_path)
    await vs._init_task(tl, _request(series_id=None))
    assert "series_id" not in tl.status
    assert tl.current_step == 1


@pytest.mark.asyncio
async def test_init_task_with_series(tmp_path):
    tl = TaskLogger("init-series", tmp_path)
    await vs._init_task(tl, _request(series_id="series-42"))
    assert tl.status["series_id"] == "series-42"


# ---------------------------------------------------------------------------
# _get_ai_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ai_client_found(tmp_path):
    tl = TaskLogger("ai-found", tmp_path)
    client = MagicMock()
    client.model = "gpt-test"
    with patch.object(vs, "get_active_ai_client", AsyncMock(return_value=client)):
        assert await vs._get_ai_client(tl) is client


@pytest.mark.asyncio
async def test_get_ai_client_not_found_raises(tmp_path):
    tl = TaskLogger("ai-none", tmp_path)
    with patch.object(vs, "get_active_ai_client", AsyncMock(return_value=None)):
        with pytest.raises(ValueError):
            await vs._get_ai_client(tl)


# ---------------------------------------------------------------------------
# _maybe_rewrite_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_rewrite_skipped_when_not_requested(tmp_path):
    tl = TaskLogger("rw-skip", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock()
    await vs._maybe_rewrite_content(ai, _request(rewrite_content=False), tl)
    ai.optimize_content.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_rewrite_with_explicit_prompt(tmp_path):
    tl = TaskLogger("rw-explicit", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="重写后的内容")
    ai.get_fallback_client = MagicMock()
    req = _request(rewrite_content=True, rewrite_prompt="请精简")
    await vs._maybe_rewrite_content(ai, req, tl)
    ai.optimize_content.assert_awaited_once()
    assert ai.optimize_content.await_args.kwargs["system_prompt"] == "请精简"
    ai.get_fallback_client.assert_not_called()
    assert req.content == "重写后的内容"
    assert tl.status["files"]["rewritten_content"].endswith("rewritten.txt")


@pytest.mark.asyncio
async def test_maybe_rewrite_uses_fallback_client(tmp_path):
    tl = TaskLogger("rw-fallback", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="primary")
    fallback = MagicMock()
    fallback.model = "fallback-model"
    fallback.base_url = "http://fallback"
    fallback.optimize_content = AsyncMock(return_value="fallback-rewritten")
    ai.get_fallback_client = MagicMock(return_value=fallback)
    req = _request(rewrite_content=True)
    await vs._maybe_rewrite_content(ai, req, tl)
    ai.optimize_content.assert_not_called()
    fallback.optimize_content.assert_awaited_once()
    assert req.content == "fallback-rewritten"


@pytest.mark.asyncio
async def test_maybe_rewrite_fallback_same_client(tmp_path):
    tl = TaskLogger("rw-same", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="same")
    ai.get_fallback_client = MagicMock(return_value=ai)
    req = _request(rewrite_content=True)
    await vs._maybe_rewrite_content(ai, req, tl)
    ai.optimize_content.assert_awaited_once()
    assert req.content == "same"


@pytest.mark.asyncio
async def test_maybe_rewrite_fallback_lookup_raises(tmp_path):
    tl = TaskLogger("rw-fallback-err", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="kept")
    ai.get_fallback_client = MagicMock(side_effect=RuntimeError("no fallback"))
    req = _request(rewrite_content=True)
    await vs._maybe_rewrite_content(ai, req, tl)
    ai.optimize_content.assert_awaited_once()
    assert req.content == "kept"


@pytest.mark.asyncio
async def test_maybe_rewrite_frozen_request_uses_object_setattr(tmp_path):
    tl = TaskLogger("rw-frozen", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="冻结重写")
    req = _FrozenRequest()
    await vs._maybe_rewrite_content(ai, req, tl)
    assert object.__getattribute__(req, "content") == "冻结重写"


@pytest.mark.asyncio
async def test_maybe_rewrite_alias_flag(tmp_path):
    tl = TaskLogger("rw-alias", tmp_path)
    ai = MagicMock()
    ai.optimize_content = AsyncMock(return_value="优化")
    ai.get_fallback_client = MagicMock(return_value=ai)
    req = _request(rewrite_content=False, optimize_content=True)
    await vs._maybe_rewrite_content(ai, req, tl)
    ai.optimize_content.assert_awaited_once()


# ---------------------------------------------------------------------------
# _generate_script
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_script(tmp_path):
    tl = TaskLogger("script", tmp_path)
    script = MagicMock()
    script.model_dump.return_value = {"title": "t", "segments": []}
    script.segments = [_make_seg("第一段", ["a", "b"]), _make_seg("第二段", ["c"])]
    ai = MagicMock()
    ai.generate_script = AsyncMock(return_value=script)
    req = _request(text_content="内容", title="标题", system_prompt="系统")

    result = await vs._generate_script(ai, req, tl)
    assert result is script
    ai.generate_script.assert_awaited_once_with(
        content="内容", title="标题", system_prompt="系统"
    )
    assert tl.status["files"]["script"].endswith("script.json")
    assert (tmp_path / "script.json").exists()


# ---------------------------------------------------------------------------
# _synthesize_audio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_audio(tmp_path):
    tl = TaskLogger("tts", tmp_path)
    script = MagicMock()
    script.segments = [_make_seg("a"), _make_seg("b")]
    tts = MagicMock()
    tts.synthesize = AsyncMock()
    tts.get_duration = AsyncMock(side_effect=[10.0, 20.0])
    fake_cls = MagicMock(return_value=tts)
    req = _request(voice="v", voice_rate="+10%")

    with patch.object(vs, "EdgeTTSEngine", fake_cls), patch.object(vs, "_ensure_not_cancelled"):
        segs, total = await vs._synthesize_audio(script, req, tmp_path, tl)

    fake_cls.assert_called_once_with(voice="v", rate="+10%")
    assert total == 30.0
    assert [s["index"] for s in segs] == [0, 1]
    assert segs[0]["audio_path"] == tmp_path / "segment_0.mp3"
    assert segs[1]["duration"] == 20.0
    assert tts.synthesize.await_count == 2
    assert tl.status["files"]["audio_0"] == str(tmp_path / "segment_0.mp3")


@pytest.mark.asyncio
async def test_synthesize_audio_cancel_midway(tmp_path):
    tl = TaskLogger("tts-cancel", tmp_path)
    tl.cancel_file.write_text("1", encoding="utf-8")
    script = MagicMock()
    script.segments = [_make_seg("a")]
    with patch.object(vs, "EdgeTTSEngine", MagicMock()):
        with pytest.raises(vs.GenerationCancelled):
            await vs._synthesize_audio(script, _request(), tmp_path, tl)


# ---------------------------------------------------------------------------
# _fetch_materials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_materials_videos_path(tmp_path, monkeypatch):
    tl = TaskLogger("mat-videos", tmp_path)
    fetcher = MagicMock()
    vids = [tmp_path / "v1.mp4"]
    fetcher.fetch_videos = AsyncMock(return_value=vids)
    fetcher.fetch_images = AsyncMock()
    script = MagicMock()
    script.segments = [_make_seg(duration=100)]
    req = _request()
    segment_audios = [{"index": 0, "duration": 40.0}]

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, tl, segment_audios)

    assert result == vids
    fetcher.fetch_images.assert_not_called()
    kwargs = fetcher.fetch_videos.await_args.kwargs
    assert kwargs["count"] == 4  # from segment_audios duration 40s
    assert kwargs["orientation"] == "landscape"
    assert req._materials_per_segment == [vids]


@pytest.mark.asyncio
async def test_fetch_materials_images_fallback(tmp_path):
    tl = TaskLogger("mat-images", tmp_path)
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[])
    imgs = [tmp_path / "i1.jpg"]
    fetcher.fetch_images = AsyncMock(return_value=imgs)
    script = MagicMock()
    script.segments = [_make_seg(duration=5)]
    req = _request()

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, tl)

    assert result == imgs
    fetcher.fetch_images.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_materials_placeholder_fallback(tmp_path):
    tl = TaskLogger("mat-placeholder", tmp_path)
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[])
    fetcher.fetch_images = AsyncMock(return_value=[])
    script = MagicMock()
    script.segments = [_make_seg(duration=5)]
    req = _request()
    placeholder = MagicMock()

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path), patch(
        "src.services.cover_service._create_gradient_background", return_value=placeholder
    ):
        result = await vs._fetch_materials(script, req, tl)

    assert result == [tmp_path / "images" / "placeholder_seg0.png"]
    placeholder.save.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_materials_placeholder_failure(tmp_path):
    tl = TaskLogger("mat-placeholder-err", tmp_path)
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[])
    fetcher.fetch_images = AsyncMock(return_value=[])
    script = MagicMock()
    script.segments = [_make_seg(duration=5)]
    req = _request()

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path), patch(
        "src.services.cover_service._create_gradient_background",
        side_effect=RuntimeError("no pill"),
    ):
        result = await vs._fetch_materials(script, req, tl)

    assert result == []


@pytest.mark.asyncio
async def test_fetch_materials_caps_at_20(tmp_path):
    tl = TaskLogger("mat-cap", tmp_path)
    fetcher = MagicMock()
    many = [tmp_path / f"m{i}.mp4" for i in range(5)]
    fetcher.fetch_videos = AsyncMock(return_value=many)
    fetcher.fetch_images = AsyncMock()
    script = MagicMock()
    script.segments = [_make_seg(duration=100) for _ in range(5)]
    req = _request()

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, tl)

    assert len(result) == 20
    assert len(req._materials_per_segment) == 5


@pytest.mark.asyncio
async def test_fetch_materials_portrait_orientation(tmp_path):
    tl = TaskLogger("mat-portrait", tmp_path)
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[tmp_path / "v.mp4"])
    script = MagicMock()
    script.segments = [_make_seg(duration=10)]
    req = _request(resolution_width=1080, resolution_height=1920)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        await vs._fetch_materials(script, req, tl)

    assert fetcher.fetch_videos.await_args.kwargs["orientation"] == "portrait"


@pytest.mark.asyncio
async def test_fetch_materials_square_resolution_current_behaviour(tmp_path):
    tl = TaskLogger("mat-square", tmp_path)
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[tmp_path / "v.mp4"])
    script = MagicMock()
    script.segments = [_make_seg(duration=10)]
    req = _request(resolution_width=1080, resolution_height=1080)

    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        await vs._fetch_materials(script, req, tl)

    # NOTE: the inline orientation expression makes the "square" branch
    # unreachable (rw >= rh short-circuits for equal dims), so equal dims
    # currently resolve to "landscape". Documented here as current behaviour.
    assert fetcher.fetch_videos.await_args.kwargs["orientation"] == "landscape"


@pytest.mark.asyncio
async def test_fetch_materials_uses_general_settings_keys(tmp_path):
    tl = TaskLogger("mat-settings", tmp_path)
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[tmp_path / "v.mp4"])
    script = MagicMock()
    script.segments = [_make_seg(duration=10)]
    req = _request()
    ctor = MagicMock(return_value=fetcher)

    with patch.object(
        vs,
        "get_general_settings",
        AsyncMock(return_value={"pexels_api_key": "pk", "pixabay_api_key": "pb"}),
    ), patch.object(vs, "MaterialFetcher", ctor), patch.object(vs.settings, "assets_dir", tmp_path):
        await vs._fetch_materials(script, req, tl)

    assert ctor.call_args.kwargs["pexels_api_key"] == "pk"
    assert ctor.call_args.kwargs["pixabay_api_key"] == "pb"


# ---------------------------------------------------------------------------
# _generate_subtitles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_subtitles_skipped(tmp_path):
    tl = TaskLogger("sub-skip", tmp_path)
    result = await vs._generate_subtitles([], 0.0, _request(generate_subtitle=False), tmp_path, tl)
    assert result == []
    assert tl.current_step == 5


@pytest.mark.asyncio
async def test_generate_subtitles_generated(tmp_path):
    tl = TaskLogger("sub-gen", tmp_path)
    subtitles = [Subtitle(1, 0.0, 5.0, "一"), Subtitle(2, 5.0, 12.0, "二")]
    gen = MagicMock()
    gen.generate_for_segments = MagicMock(return_value=subtitles)
    gen.save_ass = AsyncMock()
    segment_audios = [{"text": "一"}, {"text": "二"}]
    req = _request(subtitle_font="Arial", subtitle_color="&H0000FF00")

    with patch.object(vs, "SubtitleGenerator", MagicMock(return_value=gen)):
        result = await vs._generate_subtitles(segment_audios, 12.0, req, tmp_path, tl)

    assert result == subtitles
    gen.generate_for_segments.assert_called_once_with(segment_audios)
    gen.save_ass.assert_awaited_once()
    assert gen.save_ass.await_args.kwargs["font_name"] == "Arial"
    assert tl.status["files"]["subtitles"].endswith("subtitles.ass")


# ---------------------------------------------------------------------------
# _generate_cover
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_cover_skipped(tmp_path):
    tl = TaskLogger("cover-skip", tmp_path)
    assert await vs._generate_cover(_request(generate_cover=False), tmp_path, tl) is None
    assert tl.current_step == 6


@pytest.mark.asyncio
async def test_generate_cover_generated(tmp_path):
    tl = TaskLogger("cover-gen", tmp_path)
    cover = tmp_path / "cover.png"
    with patch.object(vs, "get_general_settings", AsyncMock(return_value={"pexels_api_key": "k"})), patch.object(
        vs, "generate_cover_image", AsyncMock(return_value=cover)
    ) as gen:
        result = await vs._generate_cover(_request(title="标题"), tmp_path, tl)

    assert result == cover
    assert gen.await_args.kwargs["pexels_api_key"] == "k"
    assert tl.status["files"]["cover"] == str(cover)


# ---------------------------------------------------------------------------
# _compose_final_video
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compose_final_video(tmp_path):
    tl = TaskLogger("compose", tmp_path)
    out = tmp_path / "output.mp4"
    req = _request(fps=25)
    req._materials_per_segment = [[tmp_path / "a.mp4"]]
    bg = Path("/tmp/bg.mp3")

    with patch.object(vs, "_resolve_bg_music_path", MagicMock(return_value=bg)), patch.object(
        vs, "compose_video", AsyncMock(return_value=out)
    ) as comp:
        result = await vs._compose_final_video(
            req, tmp_path, tl, [tmp_path / "a.mp4"], [{"index": 0}], [], 5.0
        )

    assert result == out
    kwargs = comp.await_args.kwargs
    assert kwargs["bg_music_path"] == bg
    assert kwargs["fps"] == 25
    assert kwargs["materials_per_segment"] == [[tmp_path / "a.mp4"]]


# ---------------------------------------------------------------------------
# _resolve_bg_music_path
# ---------------------------------------------------------------------------


def test_resolve_bg_music_explicit_path(tmp_path, monkeypatch):
    tl = TaskLogger("bg-explicit", tmp_path)
    music = tmp_path / "explicit.mp3"
    music.write_bytes(b"x")
    req = SimpleNamespace(background_music=str(music))
    assert vs._resolve_bg_music_path(req, tl) == music


def test_resolve_bg_music_assets_candidate(tmp_path, monkeypatch):
    tl = TaskLogger("bg-assets", tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    music = music_dir / "unit-candidate.mp3"
    music.write_bytes(b"x")
    monkeypatch.setattr(vs.settings, "assets_dir", tmp_path)
    req = SimpleNamespace(background_music="unit-candidate.mp3")
    assert vs._resolve_bg_music_path(req, tl) == music


def test_resolve_bg_music_scan_fallback(tmp_path, monkeypatch):
    tl = TaskLogger("bg-scan", tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    music = music_dir / "song.mp3"
    music.write_bytes(b"x")
    monkeypatch.setattr(vs.settings, "assets_dir", tmp_path)
    req = SimpleNamespace(background_music=None)
    assert vs._resolve_bg_music_path(req, tl) == music


def test_resolve_bg_music_none(tmp_path):
    tl = TaskLogger("bg-none", tmp_path)
    req = SimpleNamespace()
    with patch.object(vs.Path, "exists", return_value=False):
        assert vs._resolve_bg_music_path(req, tl) is None


# ---------------------------------------------------------------------------
# _mark_completed
# ---------------------------------------------------------------------------


def test_mark_completed(tmp_path):
    task_id = "mark-done"
    vs.video_tasks[task_id] = {}
    tl = TaskLogger(task_id, tmp_path)
    video = tmp_path / "out.mp4"
    vs._mark_completed(task_id, tl, video)

    assert vs.video_tasks[task_id]["status"] == "completed"
    assert vs.video_tasks[task_id]["progress"] == 1.0
    assert vs.video_tasks[task_id]["message"] == "视频生成完成"
    assert vs.video_tasks[task_id]["video_path"] == str(video)
    assert "completed_at" in vs.video_tasks[task_id]


# ---------------------------------------------------------------------------
# _auto_publish_if_requested
# ---------------------------------------------------------------------------


def _publish_session_maker(account):
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = account
    session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


@pytest.mark.asyncio
async def test_auto_publish_none_requested(tmp_path):
    tl = TaskLogger("pub-none", tmp_path)
    vs.video_tasks["pub-none"] = {"message": "m"}
    get_pub = MagicMock()
    with patch("src.database.async_session_maker", MagicMock()), patch(
        "src.publishers.get_publisher", get_pub
    ):
        await vs._auto_publish_if_requested(SimpleNamespace(), tmp_path / "v.mp4", tl, "pub-none")
    get_pub.assert_not_called()
    assert "published_to" not in vs.video_tasks["pub-none"]


@pytest.mark.asyncio
async def test_auto_publish_non_list_value(tmp_path):
    tl = TaskLogger("pub-badtype", tmp_path)
    vs.video_tasks["pub-badtype"] = {"message": "m"}
    req = SimpleNamespace(publish_to=123)
    with patch("src.database.async_session_maker", MagicMock()):
        await vs._auto_publish_if_requested(req, tmp_path / "v.mp4", tl, "pub-badtype")
    assert "published_to" not in vs.video_tasks["pub-badtype"]


@pytest.mark.asyncio
async def test_auto_publish_no_account(tmp_path):
    tl = TaskLogger("pub-noacc", tmp_path)
    vs.video_tasks["pub-noacc"] = {"message": "m"}
    req = SimpleNamespace(publish_to="youtube", content="desc")
    maker = _publish_session_maker(None)
    get_pub = MagicMock()
    with patch("src.database.async_session_maker", maker), patch(
        "src.publishers.get_publisher", get_pub
    ):
        await vs._auto_publish_if_requested(req, tmp_path / "v.mp4", tl, "pub-noacc")

    get_pub.assert_not_called()
    assert vs.video_tasks["pub-noacc"]["published_to"] == []
    assert vs.video_tasks["pub-noacc"]["message"] == "m"


@pytest.mark.asyncio
async def test_auto_publish_success(tmp_path):
    tl = TaskLogger("pub-ok", tmp_path)
    vs.video_tasks["pub-ok"] = {"message": "m"}
    acc = MagicMock(credentials=None, cookies=None, folder_id=None)
    req = SimpleNamespace(publish_to="youtube", title="T", content="desc", folder_id=None)
    pub = MagicMock()
    pub.upload = AsyncMock(return_value=MagicMock(success=True, post_url="http://p", post_id="id1"))
    maker = _publish_session_maker(acc)
    get_pub = MagicMock(return_value=pub)

    with patch("src.database.async_session_maker", maker), patch(
        "src.publishers.get_publisher", get_pub
    ):
        await vs._auto_publish_if_requested(req, tmp_path / "v.mp4", tl, "pub-ok")

    assert vs.video_tasks["pub-ok"]["published_to"][0]["platform"] == "youtube"
    assert "已发布到 1 个平台" in vs.video_tasks["pub-ok"]["message"]


@pytest.mark.asyncio
async def test_auto_publish_failure_result(tmp_path):
    tl = TaskLogger("pub-fail", tmp_path)
    vs.video_tasks["pub-fail"] = {"message": "m"}
    acc = MagicMock(credentials=None, cookies=None, folder_id=None)
    req = SimpleNamespace(publish_to="douyin", title="T", content="desc")
    pub = MagicMock()
    pub.upload = AsyncMock(return_value=MagicMock(success=False, error="rejected", post_url=None, post_id=None))
    maker = _publish_session_maker(acc)

    with patch("src.database.async_session_maker", maker), patch(
        "src.publishers.get_publisher", MagicMock(return_value=pub)
    ):
        await vs._auto_publish_if_requested(req, tmp_path / "v.mp4", tl, "pub-fail")

    assert vs.video_tasks["pub-fail"]["published_to"][0]["error"] == "rejected"


@pytest.mark.asyncio
async def test_auto_publish_exception_path(tmp_path):
    tl = TaskLogger("pub-exc", tmp_path)
    vs.video_tasks["pub-exc"] = {"message": "m"}
    acc = MagicMock(credentials=None, cookies=None, folder_id=None)
    req = SimpleNamespace(publish_to="youtube", title="T", content="desc")
    pub = MagicMock()
    pub.upload = AsyncMock(side_effect=RuntimeError("network down"))
    maker = _publish_session_maker(acc)

    with patch("src.database.async_session_maker", maker), patch(
        "src.publishers.get_publisher", MagicMock(return_value=pub)
    ):
        await vs._auto_publish_if_requested(req, tmp_path / "v.mp4", tl, "pub-exc")

    assert "network down" in vs.video_tasks["pub-exc"]["published_to"][0]["error"]


# ---------------------------------------------------------------------------
# _handle_error
# ---------------------------------------------------------------------------


def test_handle_error_cancelled(tmp_path):
    task_id = "err-cancel"
    vs.video_tasks[task_id] = {}
    tl = TaskLogger(task_id, tmp_path)
    vs._handle_error(task_id, tl, vs.GenerationCancelled("任务已取消"))
    assert vs.video_tasks[task_id]["status"] == "cancelled"
    assert vs.video_tasks[task_id]["message"] == "任务已取消"


def test_handle_error_failed(tmp_path):
    task_id = "err-fail"
    vs.video_tasks[task_id] = {}
    tl = TaskLogger(task_id, tmp_path)
    vs._handle_error(task_id, tl, RuntimeError("boom"))
    assert vs.video_tasks[task_id]["status"] == "failed"
    assert vs.video_tasks[task_id]["error"] == "boom"


# ---------------------------------------------------------------------------
# run_video_generation
# ---------------------------------------------------------------------------


def _run_helpers(**overrides):
    helpers = dict(
        _init_task=AsyncMock(),
        _get_ai_client=AsyncMock(return_value=MagicMock()),
        _maybe_rewrite_content=AsyncMock(),
        _generate_script=AsyncMock(return_value=MagicMock()),
        _synthesize_audio=AsyncMock(return_value=([], 0.0)),
        _fetch_materials=AsyncMock(return_value=[]),
        _generate_subtitles=AsyncMock(return_value=[]),
        _generate_cover=AsyncMock(return_value=None),
        _compose_final_video=AsyncMock(return_value=Path("/tmp/out.mp4")),
        _mark_completed=MagicMock(),
        _auto_publish_if_requested=AsyncMock(),
    )
    helpers.update(overrides)
    return helpers


def test_run_video_generation_happy_path(tmp_path):
    task_id = "run-ok"
    vs.video_tasks[task_id] = {}
    helpers = _run_helpers()
    with patch.multiple(vs, **helpers):
        vs.run_video_generation(task_id, _request(), tmp_path)

    assert vs.video_tasks[task_id]["task_dir"] == str(tmp_path)
    assert vs.video_tasks[task_id]["log_file"] == str(tmp_path / "task.log")
    helpers["_mark_completed"].assert_called_once()
    helpers["_auto_publish_if_requested"].assert_awaited_once()


def test_run_video_generation_handles_error(tmp_path):
    task_id = "run-err"
    vs.video_tasks[task_id] = {}
    helpers = _run_helpers(_get_ai_client=AsyncMock(side_effect=RuntimeError("llm down")))
    with patch.multiple(vs, **helpers):
        vs.run_video_generation(task_id, _request(), tmp_path)

    assert vs.video_tasks[task_id]["status"] == "failed"
    assert vs.video_tasks[task_id]["error"] == "llm down"
    helpers["_mark_completed"].assert_not_called()

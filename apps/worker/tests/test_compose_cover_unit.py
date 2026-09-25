"""Unit tests for compose_service and cover_service with MoviePy fully mocked.

MoviePy rendering is slow and needs ffmpeg, so every clip class used by
``compose_service`` is replaced with a tiny chainable fake. PIL is exercised for
real (it is fast) using small image sizes.
"""

import shutil
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.core.task_logger import TaskLogger
from src.services import compose_service as cs
from src.services import cover_service as cov


class FakeClip:
    """Minimal chainable stand-in for a MoviePy clip."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.start = kwargs.get("start", 0.0)
        self.duration = kwargs.get("duration", 1.0)
        self.size = kwargs.get("size")
        self.effects = []
        self.position = None
        self.audio = None
        self.volume = None
        self.subclip = None
        self.written_path = None
        self.write_kwargs = None

    def with_start(self, start):
        self.start = start
        return self

    def with_duration(self, duration):
        self.duration = duration
        return self

    def with_volume_scaled(self, volume):
        self.volume = volume
        return self

    def resized(self, new_size=None, **kwargs):
        self.size = new_size
        return self

    def subclipped(self, start, end):
        self.subclip = (start, end)
        return self

    def with_effects(self, effects):
        self.effects = effects
        return self

    def with_position(self, position):
        self.position = position
        return self

    def with_audio(self, audio):
        self.audio = audio
        return self

    def write_videofile(self, path, **kwargs):
        self.written_path = path
        self.write_kwargs = kwargs


@contextmanager
def patch_moviepy(**overrides):
    """Patch every MoviePy symbol imported by compose_service.

    Each patched callable returns ``FakeClip`` by default; callers can override
    a name with any callable to customise behaviour or capture instances.
    """
    with patch.multiple(
        cs,
        AudioFileClip=DEFAULT,
        VideoFileClip=DEFAULT,
        ImageClip=DEFAULT,
        TextClip=DEFAULT,
        ColorClip=DEFAULT,
        CompositeAudioClip=DEFAULT,
        CompositeVideoClip=DEFAULT,
        AudioLoop=DEFAULT,
        CrossFadeIn=DEFAULT,
        CrossFadeOut=DEFAULT,
    ) as mocks:
        for name, mock in mocks.items():
            mock.side_effect = overrides.get(name, FakeClip)
        yield mocks


def _subtitle(text="字幕内容", start=0.0, end=2.0):
    return SimpleNamespace(text=text, start_time=start, end_time=end)


def _logger(task_id, task_dir):
    return TaskLogger(task_id, task_dir)


# --------------------------------------------------------------------------- #
# compose_service
# --------------------------------------------------------------------------- #


def test_find_font_path_existing_then_missing(tmp_path, monkeypatch):
    existing = tmp_path / "font.ttc"
    existing.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cs, "FONT_PATHS", ["/no/such/font.ttf", str(existing)])
    assert cs._find_font_path() == str(existing)

    monkeypatch.setattr(cs, "FONT_PATHS", ["/no/such/font.ttf"])
    assert cs._find_font_path() is None


def test_create_audio_track_segments_use_audio_loop(tmp_path):
    logger = _logger("audio-loop", tmp_path)
    segment_audios = [
        {"index": 1, "audio_path": tmp_path / "s1.mp3", "duration": 2.0},
        {"index": 0, "audio_path": tmp_path / "s0.mp3", "duration": 3.0},
    ]
    bg = tmp_path / "bg.mp3"
    bg.write_bytes(b"x")

    def audio_factory(path):
        clip = FakeClip()
        clip.duration = 1.0 if "bg" in path else 2.0
        return clip

    with patch_moviepy(AudioFileClip=audio_factory) as mocks:
        result = cs._create_audio_track(segment_audios, bg, duration=10.0, task_logger=logger)

    assert isinstance(result, FakeClip)
    # segments are sorted by index -> s0 loaded first
    assert mocks["AudioFileClip"].call_args_list[0].args[0].endswith("s0.mp3")
    mocks["AudioLoop"].assert_called_once_with(duration=10.0)
    # two segment clips + one bg clip
    assert mocks["AudioFileClip"].call_count == 3
    assert mocks["CompositeAudioClip"].call_count == 2


def test_create_audio_track_subclips_long_bg(tmp_path):
    logger = _logger("audio-subclip", tmp_path)
    segment_audios = [{"index": 0, "audio_path": tmp_path / "s.mp3", "duration": 2.0}]
    bg = tmp_path / "bg.mp3"
    bg.write_bytes(b"x")
    created = {}

    def audio_factory(path):
        clip = FakeClip()
        clip.duration = 60.0 if "bg" in path else 2.0
        created[path] = clip
        return clip

    with patch_moviepy(AudioFileClip=audio_factory) as mocks:
        cs._create_audio_track(segment_audios, bg, duration=10.0, task_logger=logger)

    bg_clip = created[str(bg)]
    assert bg_clip.subclip == (0, 10.0)
    assert bg_clip.volume == 0.2
    mocks["AudioLoop"].assert_not_called()


def test_create_audio_track_ignores_missing_bg(tmp_path):
    logger = _logger("audio-nobg", tmp_path)
    segment_audios = [{"index": 0, "audio_path": tmp_path / "s.mp3", "duration": 2.0}]
    missing = tmp_path / "missing.mp3"

    with patch_moviepy() as mocks:
        result = cs._create_audio_track(segment_audios, missing, duration=5.0, task_logger=logger)

    assert isinstance(result, FakeClip)
    mocks["AudioFileClip"].assert_called_once()
    mocks["CompositeAudioClip"].assert_called_once()


def test_create_audio_track_raises_on_empty_segments(tmp_path):
    """Regression: zero audio clips must fail clearly, not via moviepy max()."""
    logger = _logger("audio-empty", tmp_path)

    with patch_moviepy() as mocks:
        with pytest.raises(ValueError, match="没有可用的音频片段"):
            cs._create_audio_track([], None, duration=5.0, task_logger=logger)

    mocks["CompositeAudioClip"].assert_not_called()


def test_create_video_track_per_segment(tmp_path):
    logger = _logger("video-seg", tmp_path)
    clip_mp4 = tmp_path / "clip.mp4"
    still = tmp_path / "pic.png"
    segment_audios = [
        {"index": 0, "duration": 4.0},
        {"index": 1, "duration": 6.0},
    ]
    materials_per_segment = [[clip_mp4, still], []]

    with patch_moviepy() as mocks:
        clips = cs._create_video_track(
            [],
            (64, 36),
            10.0,
            logger,
            segment_audios=segment_audios,
            materials_per_segment=materials_per_segment,
        )

    assert len(clips) == 2
    mocks["VideoFileClip"].assert_called_once_with(str(clip_mp4))
    mocks["ImageClip"].assert_called_once_with(str(still))
    # second segment had no material but clips exist, so no colour fallback
    mocks["ColorClip"].assert_not_called()
    assert any("无素材" in entry["message"] for entry in logger.logs)


def test_create_video_track_crossfades_consecutive_stills(tmp_path):
    logger = _logger("video-crossfade", tmp_path)
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    created = []

    def image_factory(path):
        clip = FakeClip()
        clip.source_path = path
        created.append(clip)
        return clip

    with patch_moviepy(ImageClip=image_factory) as mocks:
        clips = cs._create_video_track(
            [],
            (64, 36),
            8.0,
            logger,
            segment_audios=[{"index": 0, "duration": 8.0}],
            materials_per_segment=[[a, b]],
            transition_seconds=0.5,
        )

    assert len(clips) == 2
    first, second = clips
    # The second still starts before the first ends: a real temporal overlap
    # (borrowed from the adjacent hold, not added to the timeline).
    assert second.start < first.start + first.duration
    assert first.effects and second.effects
    # First still must not fade in (video would open on background); later
    # stills and all-but-last fade.
    assert mocks["CrossFadeIn"].call_count == 1
    assert mocks["CrossFadeOut"].call_count == 1
    assert any("过渡" in entry["message"] for entry in logger.logs)


def test_create_video_track_no_transition_keeps_hard_cuts(tmp_path):
    logger = _logger("video-hardcut", tmp_path)
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"

    with patch_moviepy() as mocks:
        clips = cs._create_video_track(
            [],
            (64, 36),
            8.0,
            logger,
            segment_audios=[{"index": 0, "duration": 8.0}],
            materials_per_segment=[[a, b]],
        )

    assert len(clips) == 2
    assert clips[0].duration == 4.0
    assert clips[1].start == 4.0
    mocks["CrossFadeIn"].assert_not_called()
    mocks["CrossFadeOut"].assert_not_called()


def test_create_video_track_flat_materials(tmp_path):
    logger = _logger("video-flat", tmp_path)
    clip_mp4 = tmp_path / "a.mp4"
    still = tmp_path / "b.jpg"

    with patch_moviepy() as mocks:
        clips = cs._create_video_track([clip_mp4, still], (64, 36), 10.0, logger)

    assert len(clips) == 2
    mocks["VideoFileClip"].assert_called_once_with(str(clip_mp4))
    mocks["ImageClip"].assert_called_once_with(str(still))
    mocks["ColorClip"].assert_not_called()


def test_create_video_track_material_error_falls_back(tmp_path):
    logger = _logger("video-err", tmp_path)
    bad = tmp_path / "bad.jpg"

    def raising_image(path):
        raise RuntimeError("cannot load")

    with patch_moviepy(ImageClip=raising_image) as mocks:
        clips = cs._create_video_track([bad], (64, 36), 10.0, logger)

    assert len(clips) == 1
    mocks["ColorClip"].assert_called_once()
    assert any("加载素材失败" in entry["message"] for entry in logger.logs)


def test_create_video_track_per_segment_material_error(tmp_path):
    logger = _logger("video-seg-err", tmp_path)
    bad = tmp_path / "bad.jpg"

    def raising_image(path):
        raise RuntimeError("cannot load")

    with patch_moviepy(ImageClip=raising_image) as mocks:
        clips = cs._create_video_track(
            [],
            (64, 36),
            4.0,
            logger,
            segment_audios=[{"index": 0, "duration": 4.0}],
            materials_per_segment=[[bad]],
        )

    assert len(clips) == 1
    mocks["ColorClip"].assert_called_once()
    assert any("加载素材失败" in entry["message"] for entry in logger.logs)


def test_create_video_track_no_materials(tmp_path):
    logger = _logger("video-empty", tmp_path)

    with patch_moviepy() as mocks:
        clips = cs._create_video_track([], (64, 36), 10.0, logger)

    assert len(clips) == 1
    mocks["ColorClip"].assert_called_once()


def test_create_video_track_prepends_cover_title_card(tmp_path):
    logger = _logger("video-cover", tmp_path)
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")
    still = tmp_path / "b.jpg"

    with patch_moviepy() as mocks:
        clips = cs._create_video_track(
            [still],
            (64, 36),
            9.0,
            logger,
            cover_path=cover,
            cover_hold_seconds=3.0,
            start_offset=3.0,
        )

    # Cover is the first clip at t=0; the still starts after the title card.
    assert len(clips) == 2
    assert clips[0].start == 0.0
    assert clips[0].duration == 3.0
    assert clips[1].start == 3.0
    mocks["ImageClip"].assert_any_call(str(cover))


def test_fit_cover_real_clip_fills_resolution_without_stretch():
    """A 4:3 still in a 16:9 frame must be scaled+cropped, not stretched."""
    clip = cs.ColorClip(size=(400, 300), color=(200, 0, 0), duration=1.0)

    fitted = cs._fit_cover(clip, (160, 90))

    assert fitted.size == (160, 90)


def test_fit_cover_real_vertical_clip_fills_landscape_frame():
    clip = cs.ColorClip(size=(300, 400), color=(0, 0, 200), duration=1.0)

    fitted = cs._fit_cover(clip, (160, 90))

    assert fitted.size == (160, 90)


def test_fit_cover_uses_uniform_scale_and_center_crop():
    """Verify the scale is ``max(W/w, H/h)`` and the crop is centered."""

    class RecordingClip:
        def __init__(self, w, h):
            self.w = w
            self.h = h
            self.scale = None
            self.crop = None

        def resized(self, scale=None, new_size=None, **kwargs):
            self.scale = scale if scale is not None else new_size
            if isinstance(self.scale, (int, float)):
                self.w = int(round(self.w * self.scale))
                self.h = int(round(self.h * self.scale))
            return self

        def cropped(self, x_center, y_center, width, height):
            self.crop = (x_center, y_center, width, height)
            self.w = width
            self.h = height
            return self

    clip = RecordingClip(400, 300)

    fitted = cs._fit_cover(clip, (160, 90))

    # 400x300 -> scale max(0.4, 0.3) = 0.4 -> 160x120, then crop 160x90 centered.
    assert clip.scale == 0.4
    assert clip.crop == (80.0, 60.0, 160, 90)
    assert (fitted.w, fitted.h) == (160, 90)


def test_fit_cover_missing_size_falls_back_to_resize():
    class NoSizeClip:
        def __init__(self):
            self.resized_with = None

        def resized(self, new_size=None, **kwargs):
            self.resized_with = new_size
            return self

    clip = NoSizeClip()

    fitted = cs._fit_cover(clip, (160, 90))

    assert fitted is clip
    assert clip.resized_with == (160, 90)


def test_fit_cover_resize_error_falls_back():
    class BadClip:
        def __init__(self):
            self.w = 400
            self.h = 300
            self.fallback = None

        def resized(self, scale=None, new_size=None, **kwargs):
            if scale is not None and new_size is None:
                raise RuntimeError("cannot scale")
            self.fallback = new_size
            return self

    clip = BadClip()

    fitted = cs._fit_cover(clip, (160, 90))

    assert fitted is clip
    assert clip.fallback == (160, 90)


def test_create_subtitle_track_shifts_with_offset(tmp_path, monkeypatch):
    logger = _logger("subs-offset", tmp_path)
    monkeypatch.setattr(cs, "FONT_PATHS", ["/no/such/font.ttf"])

    with patch_moviepy() as mocks:
        clips = cs._create_subtitle_track(
            [_subtitle("你好", 0.0, 2.0)], (64, 36), logger, start_offset=3.0
        )

    assert clips[0].start == 3.0
    assert mocks["TextClip"].call_count == 1


def test_create_subtitle_track_normal(tmp_path, monkeypatch):
    logger = _logger("subs", tmp_path)
    monkeypatch.setattr(cs, "FONT_PATHS", ["/no/such/font.ttf"])
    subtitles = [_subtitle("你好", 0.0, 2.0), _subtitle("世界", 2.0, 4.0)]

    with patch_moviepy() as mocks:
        clips = cs._create_subtitle_track(subtitles, (64, 36), logger)

    assert len(clips) == 2
    assert mocks["TextClip"].call_count == 2
    first = clips[0]
    assert first.position == ("center", 36 - 200)
    assert first.start == 0.0
    assert first.duration == 2.0


def test_create_subtitle_track_textclip_error(tmp_path):
    logger = _logger("subs-err", tmp_path)

    def raising_text(**kwargs):
        raise ValueError("no font")

    with patch_moviepy(TextClip=raising_text):
        clips = cs._create_subtitle_track([_subtitle()], (64, 36), logger)

    assert clips == []
    assert any("创建字幕失败" in entry["message"] for entry in logger.logs)


def test_create_subtitle_track_outer_failure(tmp_path, monkeypatch):
    logger = _logger("subs-outer", tmp_path)

    def raising_find_font():
        raise RuntimeError("font scan failed")

    monkeypatch.setattr(cs, "_find_font_path", raising_find_font)
    with patch_moviepy():
        clips = cs._create_subtitle_track([_subtitle()], (64, 36), logger)

    assert clips == []
    assert any("字幕轨道创建失败" in entry["message"] for entry in logger.logs)


def test_compose_video_sync_writes_output(tmp_path):
    logger = _logger("compose", tmp_path)
    final_clips = []

    def composite_factory(*args, **kwargs):
        clip = FakeClip(*args, **kwargs)
        final_clips.append(clip)
        return clip

    def audio_factory(path):
        clip = FakeClip()
        clip.duration = 1.0
        return clip

    segment_audios = [{"index": 0, "audio_path": tmp_path / "a.mp3", "duration": 2.0}]

    with patch_moviepy(AudioFileClip=audio_factory, CompositeVideoClip=composite_factory):
        output = cs._compose_video_sync(
            tmp_path,
            logger,
            [],
            segment_audios,
            [_subtitle()],
            None,
            5.0,
            (64, 36),
            30,
        )

    assert output == tmp_path / "output.mp4"
    assert final_clips[0].written_path == str(tmp_path / "output.mp4")
    assert final_clips[0].write_kwargs["fps"] == 30


def test_compose_video_sync_with_cover_extends_duration(tmp_path):
    logger = _logger("compose-cover", tmp_path)
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")
    final_clips = []

    def composite_factory(*args, **kwargs):
        clip = FakeClip(*args, **kwargs)
        final_clips.append(clip)
        return clip

    def audio_factory(path):
        clip = FakeClip()
        clip.duration = 1.0
        return clip

    segment_audios = [{"index": 0, "audio_path": tmp_path / "a.mp3", "duration": 2.0}]

    with patch_moviepy(
        AudioFileClip=audio_factory, CompositeVideoClip=composite_factory
    ) as mocks:
        output = cs._compose_video_sync(
            tmp_path,
            logger,
            [],
            segment_audios,
            [_subtitle()],
            None,
            5.0,
            (64, 36),
            30,
            materials_per_segment=[[tmp_path / "a.jpg"]],
            cover_path=cover,
            cover_hold_seconds=3.0,
        )

    assert output == tmp_path / "output.mp4"
    # 5s narration + 3s cover title card.
    assert final_clips[0].duration == 8.0
    # The cover ImageClip is the first clip handed to CompositeVideoClip.
    first_composite_clip = final_clips[0].args[0][0]
    assert first_composite_clip.start == 0.0
    mocks["ImageClip"].assert_any_call(str(cover))


@pytest.mark.asyncio
async def test_compose_video_async_delegates(tmp_path):
    logger = _logger("compose-async", tmp_path)
    expected = tmp_path / "output.mp4"

    with patch.object(cs, "_compose_video_sync", return_value=expected) as mock_sync:
        result = await cs.compose_video(
            tmp_path,
            logger,
            [],
            [],
            [],
            None,
            1.0,
            (64, 36),
            fps=24,
            materials_per_segment=[],
        )

    assert result == expected
    mock_sync.assert_called_once()



class _FakeResponse:
    def __init__(self, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


class _FakeAsyncClient:
    calls = []
    fail = False

    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        type(self).calls.append((url, kwargs))
        if type(self).fail:
            raise RuntimeError("network boom")
        if "search" in url:
            return _FakeResponse(
                {"photos": [{"id": 7, "src": {"large": "http://images.local/x.jpg"}}]}
            )
        return _FakeResponse(content=b"fake-image-bytes")


@pytest.fixture
def fake_httpx(monkeypatch):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.fail = False
    monkeypatch.setattr(cov.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_fetch_background_no_key(tmp_path):
    logger = _logger("bg-nokey", tmp_path)
    result = await cov._fetch_background(["x"], None, logger, (64, 36))
    assert result is None


@pytest.mark.asyncio
async def test_fetch_background_translated_portrait(tmp_path, fake_httpx):
    logger = _logger("bg-portrait", tmp_path)
    result = await cov._fetch_background(["体检报告"], "key", logger, (36, 64))

    assert result is not None
    assert result.name == "bg.jpg"
    assert result.exists()
    params = fake_httpx.calls[0][1]["params"]
    assert params["query"] == "medical report"
    assert params["orientation"] == "portrait"
    # image download happened as a second request
    assert any("search" not in url for url, _ in fake_httpx.calls)
    shutil.rmtree(result.parent, ignore_errors=True)


@pytest.mark.asyncio
async def test_fetch_background_square_orientation(tmp_path, fake_httpx):
    logger = _logger("bg-square", tmp_path)
    result = await cov._fetch_background(["抽象"], "key", logger, (64, 64))

    assert result is not None
    assert fake_httpx.calls[0][1]["params"]["orientation"] == "square"
    assert fake_httpx.calls[0][1]["params"]["query"] == "抽象"
    shutil.rmtree(result.parent, ignore_errors=True)


@pytest.mark.asyncio
async def test_fetch_background_exception_returns_none(tmp_path, fake_httpx):
    fake_httpx.fail = True
    logger = _logger("bg-fail", tmp_path)
    result = await cov._fetch_background(["x"], "key", logger, (64, 36))

    assert result is None
    assert any("获取背景图片失败" in entry["message"] for entry in logger.logs)


def test_create_gradient_background():
    img = cov._create_gradient_background(8, 8)
    assert isinstance(img, Image.Image)
    assert img.size == (8, 8)


def test_load_font_success(tmp_path, monkeypatch):
    logger = _logger("font-ok", tmp_path)
    sentinel = MagicMock()
    monkeypatch.setattr(cov.ImageFont, "truetype", lambda path, size: sentinel)
    assert cov._load_font(20, logger) is sentinel


def test_load_font_all_fail(tmp_path, monkeypatch):
    logger = _logger("font-fail", tmp_path)

    def raising_truetype(*args, **kwargs):
        raise OSError("no font")

    monkeypatch.setattr(cov.ImageFont, "truetype", raising_truetype)
    assert cov._load_font(20, logger) is None
    assert any("默认字体" in entry["message"] for entry in logger.logs)


def test_wrap_text_short_and_long():
    font = ImageFont.load_default()
    draw = ImageDraw.Draw(Image.new("RGB", (100, 100)))
    long_text = "这是一段非常非常长的文字内容需要换行显示"

    short_lines = cov._wrap_text("Hi", font, 1000, draw)
    assert short_lines == ["Hi"]

    long_lines = cov._wrap_text(long_text, font, 20, draw)
    assert len(long_lines) > 1
    assert "".join(long_lines) == long_text


def test_draw_cover_image_with_background(tmp_path):
    logger = _logger("draw-bg", tmp_path)
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (80, 60), (10, 200, 10)).save(bg)

    output = cov._draw_cover_image(bg, "封面标题", (200, 200), logger, tmp_path)

    assert output == tmp_path / "cover.png"
    assert output.exists()
    with Image.open(output) as rendered:
        assert rendered.size == (200, 200)


def test_draw_cover_image_without_background(tmp_path):
    logger = _logger("draw-nobg", tmp_path)
    output = cov._draw_cover_image(None, "封面标题文字", (200, 200), logger, tmp_path)
    assert output.exists()


def test_draw_cover_image_default_font(tmp_path, monkeypatch):
    logger = _logger("draw-default", tmp_path)
    monkeypatch.setattr(cov, "_load_font", lambda *args, **kwargs: None)
    output = cov._draw_cover_image(None, "标题", (200, 200), logger, tmp_path)
    assert output == tmp_path / "cover.png"
    assert output.exists()


@pytest.mark.asyncio
async def test_generate_cover_image(tmp_path):
    logger = _logger("gen-cover", tmp_path)
    with patch.object(cov, "_fetch_background", AsyncMock(return_value=None)):
        output = await cov.generate_cover_image(
            tmp_path, logger, "标题", ["关键词"], None, (200, 200)
        )

    assert output == tmp_path / "cover.png"
    assert output.exists()

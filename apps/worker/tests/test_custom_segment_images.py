"""Tests for per-segment custom images/charts (task-G1).

Covers the request API + validation, the ScriptSegment visual fields, the
``_apply_segment_images`` binding helper, material fetching that skips stock for
bound segments, the compose chart layout (``_fit_contain``, gentle motion,
hold-based spans, cover contain) and the subtitle band placement.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from pydantic import ValidationError

from src.core.ai_client import ScriptSegment
from src.core.subtitle_gen import Subtitle
from src.core.task_logger import TaskLogger
from src.routes.videos import SegmentImages, VideoGenerateRequest
from src.services import compose_service as cs
from src.services import translation_service as ts
from src.services import video_service as vs
from tests.test_compose_cover_unit import patch_moviepy

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _png(tmp_path: Path, name: str, size=(40, 30), color=(200, 0, 0)) -> Path:
    p = tmp_path / name
    Image.new("RGB", size, color).save(p)
    return p


def _logger(task_id, task_dir):
    return TaskLogger(task_id, task_dir)


def _segment(text="段落", images=None, **kwargs):
    return ScriptSegment(text=text, images=list(images or []), **kwargs)


def _script(*segments):
    return SimpleNamespace(segments=list(segments))


def _req(tmp_path=None, **overrides):
    base = dict(
        content_type="general",
        title="标题",
        text_content="内容",
        system_prompt="",
        rewrite_content=False,
        voice="zh-CN-XiaoxiaoNeural",
        voice_rate="+0%",
        resolution_width=1920,
        resolution_height=1080,
        background_source="both",
        generate_subtitle=True,
        generate_cover=True,
        fps=30,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# 1. Request validation
# --------------------------------------------------------------------------- #


def test_request_accepts_valid_segment_images(tmp_path):
    img = _png(tmp_path, "chart.png")
    req = VideoGenerateRequest(
        title="t",
        content="c",
        segment_images=[{"segment": 0, "images": [str(img)], "fit": "contain"}],
        cover_image=str(img),
    )
    assert req.segment_images[0].images == [str(img)]
    assert req.cover_image == str(img)


def test_request_rejects_missing_image(tmp_path):
    missing = tmp_path / "nope.png"
    with pytest.raises(ValidationError) as exc:
        VideoGenerateRequest(
            title="t",
            content="c",
            segment_images=[{"segment": 0, "images": [str(missing)]}],
        )
    assert "不存在" in str(exc.value)


def test_request_rejects_bad_extension(tmp_path):
    bad = tmp_path / "chart.gif"
    bad.write_bytes(b"x")
    with pytest.raises(ValidationError) as exc:
        VideoGenerateRequest(
            title="t",
            content="c",
            segment_images=[{"images": [str(bad)]}],
        )
    assert "扩展名" in str(exc.value)


def test_request_rejects_bad_cover_image(tmp_path):
    bad = tmp_path / "cover.txt"
    bad.write_bytes(b"x")
    with pytest.raises(ValidationError):
        VideoGenerateRequest(title="t", content="c", cover_image=str(bad))


def test_segment_images_defaults():
    spec = SegmentImages(images=[])
    assert spec.segment is None
    assert spec.fit == "contain"
    assert spec.motion == "none"
    assert spec.hold_seconds is None


def test_request_aliases_camel_case(tmp_path):
    img = _png(tmp_path, "chart.png")
    req = VideoGenerateRequest(
        title="t",
        content="c",
        segmentImages=[{"images": [str(img)], "fit": "cover", "motion": "gentle"}],
        coverImage=str(img),
    )
    assert req.segment_images[0].fit == "cover"
    assert req.segment_images[0].motion == "gentle"
    assert req.cover_image == str(img)


# --------------------------------------------------------------------------- #
# 2. ScriptSegment fields
# --------------------------------------------------------------------------- #


def test_script_segment_parses_without_keywords_or_duration():
    seg = ScriptSegment(text="only text")
    assert seg.keywords == []
    assert seg.duration_estimate == 0
    assert seg.images == []
    assert seg.fit == "contain"
    assert seg.motion == "none"


def test_script_segment_images_round_trip():
    seg = ScriptSegment(
        text="chart",
        images=["/tmp/a.png"],
        fit="cover",
        motion="gentle",
        hold_seconds=[1.5, 2.5],
        section="overview",
        chart="line",
        key_point="growth",
    )
    data = seg.model_dump()
    assert data["images"] == ["/tmp/a.png"]
    assert data["fit"] == "cover"
    assert data["motion"] == "gentle"
    assert data["hold_seconds"] == [1.5, 2.5]
    assert data["section"] == "overview"
    assert data["chart"] == "line"
    assert data["key_point"] == "growth"
    # Parsing the dump back keeps every field.
    restored = ScriptSegment.model_validate(data)
    assert restored == seg


def test_generate_script_parses_visual_fields(tmp_path):
    import asyncio

    from src.config import settings
    from src.core.ai_client import AIClient

    client = AIClient(base_url="http://x", api_key="k", model="gpt-test")
    payload = {
        "title": "T",
        "segments": [
            {
                "text": "seg",
                "images": ["/tmp/a.png"],
                "fit": "cover",
                "motion": "gentle",
                "section": "s1",
            }
        ],
        "total_duration_estimate": 10,
    }
    fake_choice = MagicMock()
    fake_choice.message.content = __import__("json").dumps(payload)
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    client._create_chat_with_retry = AsyncMock(return_value=fake_response)

    script = asyncio.run(client.generate_script(content="c", title="T"))
    seg = script.segments[0]
    assert seg.images == ["/tmp/a.png"]
    assert seg.fit == "cover"
    assert seg.motion == "gentle"
    assert seg.section == "s1"
    # cleanup no-op to keep settings import used
    assert settings is not None


@pytest.mark.asyncio
async def test_translate_script_preserves_visual_fields(tmp_path):
    from src.core.ai_client import GeneratedScript

    img = "/tmp/chart.png"
    source = GeneratedScript(
        title="中文",
        segments=[
            ScriptSegment(
                text="第一段",
                keywords=["k"],
                duration_estimate=10,
                images=[img],
                fit="contain",
                motion="gentle",
                hold_seconds=[2.0],
                section="s1",
                chart="bar",
                key_point="kp",
            )
        ],
        total_duration_estimate=10,
    )
    ai = MagicMock()
    ai.complete_json = AsyncMock(
        return_value={"title": "EN", "segments": [{"text": "First", "keywords": ["k"]}]}
    )
    out = await ts.translate_script(ai, source, target_lang="en")
    seg = out.segments[0]
    assert seg.text == "First"
    assert seg.images == [img]
    assert seg.fit == "contain"
    assert seg.motion == "gentle"
    assert seg.hold_seconds == [2.0]
    assert seg.section == "s1"
    assert seg.chart == "bar"
    assert seg.key_point == "kp"


# --------------------------------------------------------------------------- #
# 3. _apply_segment_images
# --------------------------------------------------------------------------- #


def test_apply_segment_images_by_explicit_index(tmp_path):
    tl = _logger("apply-idx", tmp_path)
    script = _script(_segment("a"), _segment("b"))
    req = SimpleNamespace(
        segment_images=[
            SegmentImages(segment=1, images=[str(_png(tmp_path, "x.png"))], fit="cover")
        ]
    )
    vs._apply_segment_images(script, req, tl)
    assert script.segments[1].images
    assert script.segments[1].fit == "cover"
    assert script.segments[0].images == []


def test_apply_segment_images_by_position(tmp_path):
    tl = _logger("apply-pos", tmp_path)
    script = _script(_segment("a"), _segment("b"))
    req = SimpleNamespace(
        segment_images=[
            SegmentImages(images=[str(_png(tmp_path, "0.png"))]),
            SegmentImages(images=[str(_png(tmp_path, "1.png"))]),
        ]
    )
    vs._apply_segment_images(script, req, tl)
    assert script.segments[0].images == [str(tmp_path / "0.png")]
    assert script.segments[1].images == [str(tmp_path / "1.png")]


def test_apply_segment_images_out_of_range_warns(tmp_path):
    tl = _logger("apply-oob", tmp_path)
    script = _script(_segment("a"))
    req = SimpleNamespace(
        segment_images=[SegmentImages(segment=5, images=[str(_png(tmp_path, "x.png"))])]
    )
    vs._apply_segment_images(script, req, tl)
    assert script.segments[0].images == []
    assert any("超出脚本段落数" in entry["message"] for entry in tl.logs)


def test_apply_segment_images_no_specs_is_noop(tmp_path):
    tl = _logger("apply-none", tmp_path)
    script = _script(_segment("a"))
    assert vs._apply_segment_images(script, SimpleNamespace(segment_images=None), tl) is script


def test_build_visual_specs_alignment(tmp_path):
    script = _script(
        _segment("a", images=["/tmp/a.png"], fit="cover", motion="gentle", hold_seconds=[1.0]),
        _segment("b"),
    )
    specs = vs._build_visual_specs(script)
    assert specs[0] == {"fit": "cover", "motion": "gentle", "hold_seconds": [1.0]}
    assert specs[1] is None


# --------------------------------------------------------------------------- #
# 4. Materials: bound segments skip Pexels
# --------------------------------------------------------------------------- #


def _mat_script(*specs):
    return _script(*[_segment(str(i), images=spec) for i, spec in enumerate(specs)])


@pytest.mark.asyncio
async def test_all_segments_bound_skips_material_fetcher(tmp_path):
    tl = _logger("mat-all", tmp_path)
    script = _mat_script(["/tmp/a.png"], ["/tmp/b.png"])
    req = _req()
    ctor = MagicMock()
    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", ctor
    ):
        result = await vs._fetch_materials(script, req, tl)

    ctor.assert_not_called()
    assert result == [Path("/tmp/a.png"), Path("/tmp/b.png")]
    assert req._materials_per_segment == [[Path("/tmp/a.png")], [Path("/tmp/b.png")]]
    assert req._segment_visual_specs[0]["fit"] == "contain"
    assert req._segment_visual_specs[0]["motion"] == "none"


@pytest.mark.asyncio
async def test_mixed_segments_fetch_only_unbound(tmp_path):
    tl = _logger("mat-mixed", tmp_path)
    script = _mat_script(["/tmp/a.png"], None)
    req = _req()
    fetcher = MagicMock()
    fetcher.fetch_videos = AsyncMock(return_value=[tmp_path / "v.mp4"])
    fetcher.fetch_images = AsyncMock()
    with patch.object(vs, "get_general_settings", AsyncMock(return_value={})), patch.object(
        vs, "MaterialFetcher", MagicMock(return_value=fetcher)
    ), patch.object(vs.settings, "assets_dir", tmp_path):
        result = await vs._fetch_materials(script, req, tl)

    # Only the unbound second segment hit the network.
    assert fetcher.fetch_videos.await_count == 1
    assert result[0] == Path("/tmp/a.png")
    assert req._materials_per_segment[0] == [Path("/tmp/a.png")]
    assert req._segment_visual_specs == [
        {"fit": "contain", "motion": "none", "hold_seconds": None},
        None,
    ]


# --------------------------------------------------------------------------- #
# 5. _fit_contain
# --------------------------------------------------------------------------- #


def test_fit_contain_preserves_aspect_and_fills_padding():
    clip = cs.ColorClip(size=(400, 300), color=(200, 0, 0), duration=1.0)
    fitted = cs._fit_contain(clip, (1920, 1080))
    frame = fitted.get_frame(0)
    assert frame.shape[:2] == (1080, 1920)
    # 400x300 scaled uniformly (1440x1080), centered -> side bars at x=100.
    assert tuple(frame[540, 960]) == (200, 0, 0)  # image centre
    assert tuple(frame[540, 100]) != (200, 0, 0)  # left background bar
    assert tuple(frame[540, 100]) == cs._chart_background_color()


def test_fit_contain_with_band_never_crops_landscape_image():
    # A 1920x1080 image into the band box stays fully visible (~1673x950).
    clip = cs.ColorClip(size=(1920, 1080), color=(10, 200, 10), duration=1.0)
    band = cs._subtitle_band_height((1920, 1080))
    assert band == 129
    box = (0, 0, 1920, 1080 - band)
    fitted = cs._fit_contain(clip, (1920, 1080), box=box)
    frame = fitted.get_frame(0)
    # Image area is centered in the box above the band; top row is image colour.
    assert tuple(frame[0, 960]) == (10, 200, 10)
    # Bottom band is the neutral background, not the image.
    assert tuple(frame[1080 - band // 2, 960]) == cs._chart_background_color()


def test_fit_contain_bad_source_returns_background():
    clip = SimpleNamespace(w=0, h=0)
    fitted = cs._fit_contain(clip, (64, 36))
    assert fitted.get_frame(0).shape[:2] == (36, 64)


def test_parse_hex_color_variants():
    assert cs._parse_hex_color("#16181c") == (22, 24, 28)
    assert cs._parse_hex_color("fff") == (255, 255, 255)
    assert cs._parse_hex_color(None) == (22, 24, 28)
    assert cs._parse_hex_color("nothex") == (22, 24, 28)


# --------------------------------------------------------------------------- #
# 6. Gentle motion
# --------------------------------------------------------------------------- #


def test_fit_contain_motion_keeps_full_image_visible():
    # A chart with a distinctive corner colour so cropping would show the bg.
    clip = cs.ColorClip(size=(1920, 1080), color=(180, 40, 0), duration=2.0)
    band = cs._subtitle_band_height((1920, 1080))
    box = (0, 0, 1920, 1080 - band)
    bg = cs._chart_background_color()
    # Base contain scale = min(box/src)/1.03 -> at max zoom the image is still
    # fully inside the box, so its top-left corner pixel stays image-coloured.
    scale0 = min(box[2] / 1920, box[3] / 1080) / 1.03
    img_w = 1920 * scale0
    img_h = 1080 * scale0
    left = (box[2] - img_w) / 2
    top = (box[3] - img_h) / 2

    moving = cs._fit_contain_motion(clip, (1920, 1080), 2.0, box=box)
    for t in (0.0, 1.999):
        frame = moving.get_frame(t)
        # A pixel just inside the image's corner stays image-coloured at both ends.
        px = int(left + 5)
        py = int(top + 5)
        assert tuple(frame[py, px]) != bg
        assert tuple(frame[py, px]) == (180, 40, 0)
        # The band stays neutral background.
        assert tuple(frame[1080 - band // 2, 960]) == bg


def test_fit_contain_motion_bad_source_returns_background():
    clip = SimpleNamespace(w=0, h=0)
    fitted = cs._fit_contain_motion(clip, (64, 36), 1.0)
    assert fitted.get_frame(0).shape[:2] == (36, 64)


# --------------------------------------------------------------------------- #
# 7. _create_video_track: hold spans + cover contain
# --------------------------------------------------------------------------- #


def test_create_video_track_hold_seconds_covers_span():
    logger = _logger("hold", Path("/tmp"))
    a = Path("/tmp/a.png")
    b = Path("/tmp/b.png")
    with patch_moviepy():
        clips = cs._create_video_track(
            [],
            (1920, 1080),
            10.0,
            logger,
            segment_audios=[{"index": 0, "duration": 8.0, "offset": 0.0, "pause_after": 2.0}],
            materials_per_segment=[[a, b]],
            segment_visual_specs=[
                {"fit": "contain", "motion": "none", "hold_seconds": [1.0, 3.0]}
            ],
        )
    # span = 10s, holds scaled proportionally (1:3) -> 2.5s and 7.5s.
    assert clips[0].duration == pytest.approx(2.5)
    assert clips[1].duration == pytest.approx(7.5)
    assert clips[1].start == pytest.approx(2.5)
    assert clips[0].start == 0.0


def test_create_video_track_even_split_without_holds():
    logger = _logger("split", Path("/tmp"))
    a = Path("/tmp/a.png")
    b = Path("/tmp/b.png")
    with patch_moviepy():
        clips = cs._create_video_track(
            [],
            (1920, 1080),
            9.0,
            logger,
            segment_audios=[{"index": 0, "duration": 9.0, "offset": 0.0}],
            materials_per_segment=[[a, b]],
            segment_visual_specs=[{"fit": "contain", "motion": "none", "hold_seconds": None}],
        )
    assert clips[0].duration == pytest.approx(4.5)
    assert clips[1].duration == pytest.approx(4.5)


def test_create_video_track_cover_spec_uses_fit_cover():
    logger = _logger("cover-spec", Path("/tmp"))
    a = Path("/tmp/a.png")
    with patch_moviepy() as mocks:
        cs._create_video_track(
            [],
            (1920, 1080),
            5.0,
            logger,
            segment_audios=[{"index": 0, "duration": 5.0, "offset": 0.0}],
            materials_per_segment=[[a]],
            segment_visual_specs=[{"fit": "cover", "motion": "none", "hold_seconds": None}],
        )
    # Cover layout does not build a CompositeVideoClip (no contain bg).
    assert mocks["CompositeVideoClip"].call_count == 0


def test_create_video_track_cover_is_contain(tmp_path):
    logger = _logger("cover-contain", tmp_path)
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")
    still = tmp_path / "s.png"
    with patch_moviepy() as mocks:
        clips = cs._create_video_track(
            [still],
            (1920, 1080),
            5.0,
            logger,
            cover_path=cover,
            cover_hold_seconds=2.0,
            cover_is_contain=True,
        )
    # Cover gets its own background+image composite, inserted first at t=0.
    assert clips[0].start == 0.0
    assert clips[0].duration == 2.0
    # Contain cover builds a neutral background clip (fake clips lack w/h so the
    # image itself degrades to the background inside _fit_contain).
    assert mocks["ColorClip"].call_count >= 1


# --------------------------------------------------------------------------- #
# 8. Subtitle band placement
# --------------------------------------------------------------------------- #


def test_subtitle_band_placement_inside_and_outside_window(tmp_path, monkeypatch):
    logger = _logger("subs-band", tmp_path)
    monkeypatch.setattr(cs, "FONT_PATHS", ["/no/such/font.ttf"])
    subtitles = [
        Subtitle(1, 1.0, 2.0, "图表字幕"),
        Subtitle(2, 30.0, 31.0, "普通字幕"),
    ]
    with patch_moviepy() as mocks:
        clips = cs._create_subtitle_track(
            subtitles,
            (1920, 1080),
            logger,
            chart_windows=[(0.0, 10.0)],
        )
    band = cs._subtitle_band_height((1920, 1080))
    # First sits in the band with the smaller chart font.
    assert clips[0].position == ("center", 1080 - band / 2 - cs._subtitle_font_size((1920, 1080), True) / 2)
    # Second keeps the default placement.
    assert clips[1].position == ("center", 1080 - 200)
    # Two different font sizes were requested (band vs default).
    sizes = [call.kwargs.get("font_size") for call in mocks["TextClip"].call_args_list]
    assert cs._subtitle_font_size((1920, 1080), True) in sizes
    assert int(1080 * 0.04) in sizes


def test_chart_narration_windows_only_contain_specs():
    segment_audios = [
        {"index": 0, "duration": 5.0, "offset": 0.0, "pause_after": 0.5},
        {"index": 1, "duration": 4.0, "offset": 5.5, "pause_after": 0.0},
    ]
    specs = [
        {"fit": "contain", "motion": "none", "hold_seconds": None},
        None,
    ]
    windows = cs._chart_narration_windows(segment_audios, specs)
    assert windows == [(0.0, 5.5)]
    assert cs._chart_narration_windows(segment_audios, None) == []


# --------------------------------------------------------------------------- #
# 9. Gentle pacing
# --------------------------------------------------------------------------- #


def test_uses_gentle_pacing():
    assert vs._uses_gentle_pacing(_req(content_type="book")) is True
    assert vs._uses_gentle_pacing(_req(content_type="indicator")) is True
    assert vs._uses_gentle_pacing(_req(segment_images=[SegmentImages(images=[])])) is True
    assert vs._uses_gentle_pacing(_req()) is False


@pytest.mark.asyncio
async def test_segment_images_request_uses_gentle_rate_and_pauses(tmp_path):
    tl = TaskLogger("gentle-custom", tmp_path)
    engine = MagicMock(return_value=_Provider())
    script = _script(_segment("a"), _segment("b"))

    with patch.object(vs, "EdgeTTSEngine", engine), patch.object(vs, "_ensure_not_cancelled"):
        segs, total = await vs._synthesize_audio(
            script,
            _req(segment_images=[SegmentImages(images=[])]),
            tmp_path,
            tl,
        )

    assert engine.call_args.kwargs["rate"] == "-8%"
    assert [s["pause_after"] for s in segs] == [0.5, 0.0]
    assert total == 20.5


class _Provider:
    def __init__(self, **kwargs):
        self.rate = kwargs.get("rate")

    async def synthesize(self, text, output_path=None, voice=None, boundaries=None):
        if boundaries is not None:
            boundaries.append({"offset": 0.0, "duration": 1.0, "text": text})
        Path(output_path).write_bytes(b"x")
        return output_path

    async def get_duration(self, audio_path):
        return 10.0


# --------------------------------------------------------------------------- #
# 10. _generate_cover custom image + compose wiring
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_cover_uses_custom_image(tmp_path):
    tl = _logger("cover-custom", tmp_path)
    img = _png(tmp_path, "mycover.png")
    with patch.object(vs, "get_general_settings", AsyncMock()) as gen:
        result = await vs._generate_cover(_req(cover_image=str(img)), tmp_path, tl)
    assert result == img
    gen.assert_not_called()
    assert tl.status["files"]["cover"] == str(img)


@pytest.mark.asyncio
async def test_compose_final_video_passes_specs_and_cover_contain(tmp_path):
    tl = _logger("compose-specs", tmp_path)
    out = tmp_path / "output.mp4"
    req = _req(fps=25, cover_image=str(tmp_path / "cover.png"))
    req._materials_per_segment = [[tmp_path / "a.png"]]
    req._segment_visual_specs = [{"fit": "contain", "motion": "gentle", "hold_seconds": None}]

    with patch.object(vs, "_resolve_bg_music_path", MagicMock(return_value=None)), patch.object(
        vs, "compose_video", AsyncMock(return_value=out)
    ) as comp:
        result = await vs._compose_final_video(
            req, tmp_path, tl, [tmp_path / "a.png"], [{"index": 0}], [], 5.0,
            cover_path=tmp_path / "cover.png",
        )

    assert result == out
    kwargs = comp.await_args.kwargs
    assert kwargs["segment_visual_specs"] == req._segment_visual_specs
    assert kwargs["cover_is_contain"] is True

"""Tests for video generator."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.video_generator import VideoGenerator, VideoOptions, SegmentAudio
from src.core.ai_client import GeneratedScript, ScriptSegment


class TestVideoOptions:
    """Tests for VideoOptions dataclass."""

    def test_default_options(self):
        """Test default video options."""
        options = VideoOptions()
        assert options.voice == "zh-CN-XiaoxiaoNeural"
        assert options.voice_rate == "+0%"
        assert options.resolution == (1080, 1920)
        assert options.fps == 30
        assert options.material_source == "both"

    def test_custom_options(self):
        """Test custom video options."""
        options = VideoOptions(
            voice="zh-CN-YunxiNeural",
            resolution=(720, 1280),
            fps=24,
            material_source="online",
        )
        assert options.voice == "zh-CN-YunxiNeural"
        assert options.resolution == (720, 1280)
        assert options.fps == 24
        assert options.material_source == "online"


class TestSegmentAudio:
    """Tests for SegmentAudio dataclass."""

    def test_create_segment_audio(self):
        """Test creating segment audio info."""
        audio = SegmentAudio(
            segment_index=0,
            text="测试文本",
            audio_path=Path("/tmp/audio.mp3"),
            duration=15.5,
        )
        assert audio.segment_index == 0
        assert audio.text == "测试文本"
        assert audio.audio_path == Path("/tmp/audio.mp3")
        assert audio.duration == 15.5


class TestVideoGenerator:
    """Tests for VideoGenerator class."""

    def test_init_with_defaults(self):
        """Test generator initialization with defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.core.video_generator.settings") as mock_settings:
                mock_settings.output_dir = Path(tmpdir)
                mock_settings.openai_api_key = "test-key"
                
                generator = VideoGenerator()
                assert generator.ai_client is not None
                assert generator.tts_engine is not None

    def test_init_with_custom_components(self):
        """Test generator initialization with custom components."""
        mock_ai = MagicMock()
        mock_tts = MagicMock()
        mock_fetcher = MagicMock()
        mock_subtitle = MagicMock()
        
        generator = VideoGenerator(
            ai_client=mock_ai,
            tts_engine=mock_tts,
            material_fetcher=mock_fetcher,
            subtitle_gen=mock_subtitle,
        )
        
        assert generator.ai_client is mock_ai
        assert generator.tts_engine is mock_tts
        assert generator.material_fetcher is mock_fetcher
        assert generator.subtitle_gen is mock_subtitle

    @pytest.mark.asyncio
    async def test_synthesize_segment(self):
        """Test synthesizing a single segment."""
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=Path("/tmp/segment_0.mp3"))
        mock_tts.get_duration = AsyncMock(return_value=30.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.core.video_generator.settings") as mock_settings:
                mock_settings.output_dir = Path(tmpdir)
                
                generator = VideoGenerator(tts_engine=mock_tts)
                segment = ScriptSegment(
                    text="测试段落内容",
                    keywords=["测试"],
                    duration_estimate=30,
                )
                
                result = await generator._synthesize_segment(segment, 0, "zh-CN-XiaoxiaoNeural")
                
                assert isinstance(result, SegmentAudio)
                assert result.segment_index == 0
                assert result.text == "测试段落内容"
                assert result.duration == 30.0

    @pytest.mark.asyncio
    async def test_generate_progress_callback(self):
        """Test that progress callback is called during generation."""
        progress_calls = []
        
        async def progress_callback(step: str, progress: float):
            progress_calls.append((step, progress))

        mock_ai = MagicMock()
        mock_ai.generate_script = AsyncMock(return_value=GeneratedScript(
            title="测试",
            segments=[ScriptSegment(text="内容", keywords=["a"], duration_estimate=30)],
            total_duration_estimate=30,
        ))

        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=Path("/tmp/audio.mp3"))
        mock_tts.get_duration = AsyncMock(return_value=10.0)

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_videos = AsyncMock(return_value=[])
        mock_fetcher.fetch_images = AsyncMock(return_value=[])

        mock_subtitle = MagicMock()
        mock_subtitle.generate = AsyncMock(return_value=[])
        mock_subtitle.save_ass = AsyncMock(return_value=Path("/tmp/sub.ass"))

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.core.video_generator.settings") as mock_settings:
                mock_settings.output_dir = Path(tmpdir)
                
                generator = VideoGenerator(
                    ai_client=mock_ai,
                    tts_engine=mock_tts,
                    material_fetcher=mock_fetcher,
                    subtitle_gen=mock_subtitle,
                )

                with patch.object(generator, '_compose_video', new_callable=AsyncMock) as mock_compose:
                    mock_compose.return_value = Path(tmpdir) / "output.mp4"
                    
                    await generator.generate(
                        content="测试内容",
                        title="测试标题",
                        options=VideoOptions(),
                        progress_callback=progress_callback,
                    )

        assert len(progress_calls) > 0
        assert any("script" in call[0].lower() for call in progress_calls)

    @pytest.mark.asyncio
    async def test_generate_collects_all_keywords(self):
        """Test that generation collects keywords from all segments."""
        mock_ai = MagicMock()
        mock_ai.generate_script = AsyncMock(return_value=GeneratedScript(
            title="测试",
            segments=[
                ScriptSegment(text="第一段", keywords=["科技", "创新"], duration_estimate=30),
                ScriptSegment(text="第二段", keywords=["科技", "发展"], duration_estimate=30),
                ScriptSegment(text="第三段", keywords=["未来", "趋势"], duration_estimate=30),
            ],
            total_duration_estimate=90,
        ))

        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=Path("/tmp/audio.mp3"))
        mock_tts.get_duration = AsyncMock(return_value=10.0)

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_videos = AsyncMock(return_value=[])
        mock_fetcher.fetch_images = AsyncMock(return_value=[])

        mock_subtitle = MagicMock()
        mock_subtitle.generate = AsyncMock(return_value=[])
        mock_subtitle.save_ass = AsyncMock(return_value=Path("/tmp/sub.ass"))

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.core.video_generator.settings") as mock_settings:
                mock_settings.output_dir = Path(tmpdir)
                
                generator = VideoGenerator(
                    ai_client=mock_ai,
                    tts_engine=mock_tts,
                    material_fetcher=mock_fetcher,
                    subtitle_gen=mock_subtitle,
                )

                with patch.object(generator, '_compose_video', new_callable=AsyncMock) as mock_compose:
                    mock_compose.return_value = Path(tmpdir) / "output.mp4"
                    
                    await generator.generate(
                        content="测试内容",
                        title="测试标题",
                        options=VideoOptions(),
                    )

        call_args = mock_fetcher.fetch_videos.call_args
        keywords = call_args.kwargs["keywords"]
        
        assert "科技" in keywords
        assert "创新" in keywords
        assert "发展" in keywords
        assert "未来" in keywords
        assert "趋势" in keywords


class TestComposeVideo:
    """Tests for video composition."""

    @pytest.mark.asyncio
    async def test_compose_video_without_materials(self):
        """Test video composition when no materials are available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            generator = VideoGenerator(output_dir=Path(tmpdir))
            
            with patch("src.core.video_generator.AudioFileClip") as mock_audio:
                with patch("src.core.video_generator.CompositeAudioClip") as mock_composite_audio:
                    with patch("src.core.video_generator.CompositeVideoClip") as mock_composite_video:
                        with patch("moviepy.video.VideoClip.ColorClip") as mock_color_clip:
                            mock_audio_instance = MagicMock()
                            mock_audio_instance.duration = 5.0
                            mock_audio.return_value = mock_audio_instance
                            
                            mock_video = MagicMock()
                            mock_video.write_videofile = MagicMock()
                            mock_composite_video.return_value = mock_video
                            
                            mock_bg = MagicMock()
                            mock_bg.write_videofile = MagicMock()
                            mock_color_clip.return_value = mock_bg
                            
                            result = await generator._compose_video(
                                materials=[],
                                segment_audios=[
                                    SegmentAudio(0, "text", Path(tmpdir) / "a.mp3", 5.0),
                                ],
                                subtitle_path=Path(tmpdir) / "sub.ass",
                                background_music_path=None,
                                duration=5.0,
                                resolution=(1080, 1920),
                                fps=30,
                            )
            
            assert result.suffix == ".mp4"

    @pytest.mark.asyncio
    async def test_compose_video_with_background_music(self):
        """Test video composition with background music."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bg_music = Path(tmpdir) / "bg.mp3"
            bg_music.touch()
            
            generator = VideoGenerator(output_dir=Path(tmpdir))
            
            with patch("src.core.video_generator.AudioFileClip") as mock_audio_clip:
                with patch("src.core.video_generator.CompositeAudioClip") as mock_composite_audio:
                    with patch("src.core.video_generator.CompositeVideoClip") as mock_composite_video:
                        with patch("moviepy.video.VideoClip.ColorClip"):
                            mock_narration = MagicMock()
                            mock_narration.duration = 30.0
                            
                            mock_bg_music = MagicMock()
                            mock_bg_music.duration = 10.0
                            mock_bg_music.with_effects.return_value = mock_bg_music
                            mock_bg_music.with_volume_scaled.return_value = mock_bg_music
                            
                            mock_audio_clip.side_effect = [mock_narration, mock_bg_music]
                            
                            mock_video = MagicMock()
                            mock_video.write_videofile = MagicMock()
                            mock_composite_video.return_value = mock_video
                            
                            await generator._compose_video(
                                materials=[],
                                segment_audios=[
                                    SegmentAudio(0, "text", Path(tmpdir) / "a.mp3", 30.0),
                                ],
                                subtitle_path=Path(tmpdir) / "sub.ass",
                                background_music_path=bg_music,
                                duration=30.0,
                                resolution=(1080, 1920),
                                fps=30,
                            )
                            
                            mock_bg_music.with_volume_scaled.assert_called_with(0.2)
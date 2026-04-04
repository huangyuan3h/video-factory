"""Tests for core modules coverage."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import tempfile


class TestMaterialFetcherCoverage:
    """Tests for MaterialFetcher coverage."""

    def test_material_fetcher_import(self):
        """Test MaterialFetcher import."""
        from src.core.material_fetcher import MaterialFetcher
        assert MaterialFetcher is not None

    def test_material_fetcher_init(self):
        """Test MaterialFetcher initialization."""
        from src.core.material_fetcher import MaterialFetcher
        
        fetcher = MaterialFetcher()
        assert fetcher.pexels_api_key is None
        assert fetcher.pixabay_api_key is None

    def test_material_fetcher_with_keys(self):
        """Test MaterialFetcher with API keys."""
        from src.core.material_fetcher import MaterialFetcher
        
        fetcher = MaterialFetcher(
            pexels_api_key="test-pexels",
            pixabay_api_key="test-pixabay"
        )
        assert fetcher.pexels_api_key == "test-pexels"
        assert fetcher.pixabay_api_key == "test-pixabay"

    def test_keyword_translations(self):
        """Test KEYWORD_TRANSLATIONS."""
        from src.core.material_fetcher import KEYWORD_TRANSLATIONS
        
        assert isinstance(KEYWORD_TRANSLATIONS, dict)
        assert len(KEYWORD_TRANSLATIONS) > 0

    @pytest.mark.asyncio
    async def test_fetch_videos_no_keys(self):
        """Test fetch_videos without API keys."""
        from src.core.material_fetcher import MaterialFetcher
        
        fetcher = MaterialFetcher()
        videos = await fetcher.fetch_videos(keywords=["test"], count=5)
        assert videos == []

    @pytest.mark.asyncio
    async def test_fetch_images_no_keys(self):
        """Test fetch_images without API keys."""
        from src.core.material_fetcher import MaterialFetcher
        
        fetcher = MaterialFetcher()
        images = await fetcher.fetch_images(keywords=["test"], count=5)
        assert images == []


class TestTaskLoggerCoverage:
    """Tests for TaskLogger coverage."""

    def test_task_logger_import(self):
        """Test TaskLogger import."""
        from src.core.task_logger import TaskLogger
        assert TaskLogger is not None

    def test_task_logger_init(self):
        """Test TaskLogger initialization."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            assert logger.task_id == "test-id"
            assert logger.task_dir == Path(tmpdir)

    def test_task_logger_info(self):
        """Test TaskLogger info method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.info("Test message")

    def test_task_logger_step(self):
        """Test TaskLogger step method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.step(1, "Test step")

    def test_task_logger_warning(self):
        """Test TaskLogger warning method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.warning("Test warning")

    def test_task_logger_set_progress(self):
        """Test TaskLogger set_progress method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.set_progress(0.5)

    def test_task_logger_set_file(self):
        """Test TaskLogger set_file method."""
        from src.core.task_logger import TaskLogger
        
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TaskLogger("test-id", Path(tmpdir))
            logger.set_file("test_file", Path(tmpdir) / "test.txt")


class TestSubtitleGeneratorCoverage:
    """Tests for SubtitleGenerator coverage."""

    def test_subtitle_generator_import(self):
        """Test SubtitleGenerator import."""
        from src.core.subtitle_gen import SubtitleGenerator
        assert SubtitleGenerator is not None

    def test_subtitle_generator_init(self):
        """Test SubtitleGenerator initialization."""
        from src.core.subtitle_gen import SubtitleGenerator
        
        gen = SubtitleGenerator()
        assert gen is not None

    @pytest.mark.asyncio
    async def test_subtitle_generate(self):
        """Test SubtitleGenerator generate method."""
        from src.core.subtitle_gen import SubtitleGenerator
        
        gen = SubtitleGenerator()
        subtitles = await gen.generate(
            text="Hello world this is a test",
            audio_duration=10.0
        )
        assert len(subtitles) > 0


class TestTTSEngineCoverage:
    """Tests for TTSEngine coverage."""

    def test_tts_engine_import(self):
        """Test EdgeTTSEngine import."""
        from src.core.tts_engine import EdgeTTSEngine
        assert EdgeTTSEngine is not None

    def test_tts_engine_init(self):
        """Test EdgeTTSEngine initialization."""
        from src.core.tts_engine import EdgeTTSEngine
        
        tts = EdgeTTSEngine(voice="zh-CN-XiaoxiaoNeural", rate="+0%")
        assert tts.voice == "zh-CN-XiaoxiaoNeural"
        assert tts.rate == "+0%"

    def test_tts_list_voices(self):
        """Test EdgeTTSEngine list_voices."""
        from src.core.tts_engine import EdgeTTSEngine
        
        voices = EdgeTTSEngine.list_voices()
        assert isinstance(voices, dict)
        assert len(voices) > 0


class TestVideoGeneratorCoverage:
    """Tests for VideoGenerator coverage."""

    def test_video_generator_import(self):
        """Test VideoGenerator import."""
        from src.core.video_generator import VideoGenerator
        assert VideoGenerator is not None

    def test_video_generator_init(self):
        """Test VideoGenerator initialization."""
        from src.core.video_generator import VideoGenerator
        
        gen = VideoGenerator()
        assert gen is not None
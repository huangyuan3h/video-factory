"""Video generator using MoviePy."""

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from moviepy.audio.AudioClip import AudioFileClip
from moviepy.video.VideoClip import ImageClip, TextClip, VideoClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.fx.all import resize
from moviepy.video.io.VideoFileClip import VideoFileClip

from ..config import settings
from .ai_client import AIClient, GeneratedScript
from .material_fetcher import MaterialFetcher
from .subtitle_gen import SubtitleGenerator
from .tts_engine import EdgeTTSEngine

logger = logging.getLogger(__name__)


@dataclass
class VideoOptions:
    """Video generation options."""

    voice: str = "zh-CN-XiaoxiaoNeural"
    resolution: tuple[int, int] = (1080, 1920)  # width, height (vertical video)
    fps: int = 30
    material_source: str = "both"  # online, local, both
    subtitle_style: str = "ass"  # srt, ass


class VideoGenerator:
    """Generate videos from content."""

    def __init__(
        self,
        ai_client: Optional[AIClient] = None,
        tts_engine: Optional[EdgeTTSEngine] = None,
        material_fetcher: Optional[MaterialFetcher] = None,
        subtitle_gen: Optional[SubtitleGenerator] = None,
        output_dir: Optional[Path] = None,
    ):
        self.ai_client = ai_client or AIClient()
        self.tts_engine = tts_engine or EdgeTTSEngine()
        self.material_fetcher = material_fetcher or MaterialFetcher()
        self.subtitle_gen = subtitle_gen or SubtitleGenerator()
        self.output_dir = output_dir or settings.output_dir

    async def generate(
        self,
        content: str,
        options: Optional[VideoOptions] = None,
        keywords: Optional[list[str]] = None,
    ) -> Path:
        """Generate a video from content.

        Args:
            content: Source content to generate video from
            options: Video generation options
            keywords: Keywords for material search

        Returns:
            Path to the generated video
        """
        options = options or VideoOptions()

        # Step 1: Generate script with AI
        logger.info("Generating script with AI...")
        script = await self.ai_client.generate_script(content)
        logger.info(f"Generated script: {script.title}")

        # Step 2: Generate TTS audio
        logger.info("Synthesizing speech...")
        audio_path = await self.tts_engine.synthesize(
            text=script.content,
            voice=options.voice,
        )
        audio_duration = await self.tts_engine.get_duration(audio_path)
        logger.info(f"Audio duration: {audio_duration:.1f}s")

        # Step 3: Fetch materials
        logger.info("Fetching materials...")
        search_keywords = keywords or script.keywords
        materials = await self.material_fetcher.fetch_videos(
            keywords=search_keywords,
            count=10,
            source=options.material_source,
        )

        if not materials:
            # Fallback to images
            materials = await self.material_fetcher.fetch_images(
                keywords=search_keywords,
                count=15,
                source=options.material_source,
            )

        logger.info(f"Fetched {len(materials)} materials")

        # Step 4: Generate subtitles
        logger.info("Generating subtitles...")
        subtitles = await self.subtitle_gen.generate(
            text=script.content,
            audio_duration=audio_duration,
        )

        subtitle_path = self.output_dir / "temp_subtitles.ass"
        await self.subtitle_gen.save_ass(subtitles, subtitle_path)

        # Step 5: Compose video
        logger.info("Composing video...")
        video_path = await self._compose_video(
            materials=materials,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            duration=audio_duration,
            resolution=options.resolution,
            fps=options.fps,
        )

        logger.info(f"Video generated: {video_path}")
        return video_path

    async def _compose_video(
        self,
        materials: list[Path],
        audio_path: Path,
        subtitle_path: Path,
        duration: float,
        resolution: tuple[int, int],
        fps: int,
    ) -> Path:
        """Compose final video from materials, audio, and subtitles."""

        def _sync_compose():
            # Load audio
            audio = AudioFileClip(str(audio_path))

            # Create background from materials
            clips = []
            clip_duration = duration / len(materials) if materials else duration

            for i, material in enumerate(materials):
                if material.suffix.lower() in (".mp4", ".mov"):
                    clip = VideoFileClip(str(material))
                else:
                    clip = ImageClip(str(material))

                # Resize to resolution
                clip = clip.resize(newsize=resolution)

                # Set duration
                clip = clip.set_duration(clip_duration)
                clip = clip.set_start(i * clip_duration)

                clips.append(clip)

            if not clips:
                # Create a blank black background
                from moviepy.video.VideoClip import ColorClip
                bg = ColorClip(size=resolution, color=(0, 0, 0), duration=duration)
                clips = [bg]

            # Concatenate all clips
            video = CompositeVideoClip(clips, size=resolution)
            video = video.set_duration(duration)
            video = video.set_audio(audio)

            # Add subtitles using ffmpeg
            output_path = self.output_dir / f"video_{asyncio.get_event_loop().time():.0f}.mp4"

            # Write video with subtitles
            video.write_videofile(
                str(output_path),
                fps=fps,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=tempfile.mktemp(suffix=".m4a"),
                remove_temp=True,
                logger=None,
            )

            return output_path

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_compose)

    async def generate_simple(
        self,
        script: str,
        background_video: Optional[Path] = None,
        voice: str = "zh-CN-XiaoxiaoNeural",
    ) -> Path:
        """Generate a simple video with text and background.

        Simpler alternative to full generation.
        """
        # Generate audio
        audio_path = await self.tts_engine.synthesize(script, voice=voice)
        audio_duration = await self.tts_engine.get_duration(audio_path)

        # Use default background if not provided
        if background_video is None:
            # Create a simple gradient background
            background_video = await self._create_default_background(audio_duration)

        # Compose
        output_path = self.output_dir / f"simple_{asyncio.get_event_loop().time():.0f}.mp4"

        def _compose():
            audio = AudioFileClip(str(audio_path))
            video = VideoFileClip(str(background_video))

            # Loop video if needed
            if video.duration < audio_duration:
                video = video.loop(duration=audio_duration)
            else:
                video = video.subclip(0, audio_duration)

            video = video.set_audio(audio)
            video.write_videofile(
                str(output_path),
                fps=30,
                codec="libx264",
                audio_codec="aac",
                logger=None,
            )

        await asyncio.get_event_loop().run_in_executor(None, _compose)
        return output_path

    async def _create_default_background(self, duration: float) -> Path:
        """Create a default gradient background video."""
        output_path = self.output_dir / "default_bg.mp4"

        def _create():
            from moviepy.video.VideoClip import ColorClip

            # Create a simple dark gradient
            clip = ColorClip(size=(1080, 1920), color=(30, 30, 50), duration=duration)
            clip.write_videofile(
                str(output_path),
                fps=30,
                codec="libx264",
                logger=None,
            )

        await asyncio.get_event_loop().run_in_executor(None, _create)
        return output_path
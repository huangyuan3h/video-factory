"""Video generator using MoviePy."""

import asyncio
import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip
from moviepy.audio.fx import AudioLoop

from ..config import settings
from .ai_client import AIClient, GeneratedScript, ScriptSegment
from .subtitle_gen import SubtitleGenerator
from .tts_engine import EdgeTTSEngine
from ..services.material import MaterialFetcher

logger = logging.getLogger(__name__)


@dataclass
class VideoOptions:
    """Video generation options."""

    voice: str = "zh-CN-XiaoxiaoNeural"
    voice_rate: str = "+0%"
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    material_source: str = "both"
    subtitle_style: dict = field(default_factory=lambda: {
        "font_name": "Microsoft YaHei",
        "font_size": 48,
        "color": "&H00FFFFFF",
        "outline_color": "&H00000000",
    })


@dataclass
class SegmentAudio:
    """Audio info for a segment."""

    segment_index: int
    text: str
    audio_path: Path
    duration: float


class VideoGenerator:
    """Generate videos from content."""

    def __init__(
        self,
        ai_client: AIClient | None = None,
        tts_engine: EdgeTTSEngine | None = None,
        material_fetcher: MaterialFetcher | None = None,
        subtitle_gen: SubtitleGenerator | None = None,
        output_dir: Path | None = None,
    ):
        self.ai_client = ai_client or AIClient()
        self.tts_engine = tts_engine or EdgeTTSEngine()
        self.material_fetcher = material_fetcher or MaterialFetcher()
        self.subtitle_gen = subtitle_gen or SubtitleGenerator()
        self.output_dir = output_dir or settings.output_dir

    async def generate(
        self,
        content: str,
        title: str = "",
        system_prompt: str = "",
        background_music_path: Path | None = None,
        options: VideoOptions | None = None,
        progress_callback: Callable | None = None,
    ) -> Path:
        """Generate a video from content.

        Args:
            content: Source content to generate video from
            title: Video title
            system_prompt: Custom system prompt for LLM
            background_music_path: Path to background music file
            options: Video generation options
            progress_callback: Callback for progress updates

        Returns:
            Path to the generated video
        """
        options = options or VideoOptions()

        async def report_progress(step: str, progress: float):
            logger.info(f"Progress: {step} - {progress * 100:.0f}%")
            if progress_callback:
                await progress_callback(step, progress)

        await report_progress("Generating script with AI", 0.0)
        script = await self.ai_client.generate_script(
            content=content,
            title=title,
            system_prompt=system_prompt,
        )
        await report_progress("Script generated", 0.1)

        segment_audios = []
        total_segments = len(script.segments)

        for i, segment in enumerate(script.segments):
            await report_progress(f"Synthesizing segment {i + 1}/{total_segments}", 0.1 + (i / total_segments) * 0.3)
            audio_info = await self._synthesize_segment(segment, i, options.voice)
            segment_audios.append(audio_info)

        total_audio_duration = sum(sa.duration for sa in segment_audios)
        await report_progress("TTS complete", 0.4)

        all_keywords = []
        for seg in script.segments:
            all_keywords.extend(seg.keywords)
        unique_keywords = list(set(all_keywords))[:10]

        await report_progress("Fetching materials", 0.4)
        materials = await self.material_fetcher.fetch_videos(
            keywords=unique_keywords,
            count=15,
            source=options.material_source,
        )

        if not materials:
            materials = await self.material_fetcher.fetch_images(
                keywords=unique_keywords,
                count=20,
                source=options.material_source,
            )

        await report_progress("Materials fetched", 0.5)

        await report_progress("Generating subtitles", 0.5)
        all_text = " ".join(sa.text for sa in segment_audios)
        subtitles = await self.subtitle_gen.generate(
            text=all_text,
            audio_duration=total_audio_duration,
        )

        subtitle_path = self.output_dir / f"subtitles_{asyncio.get_event_loop().time():.0f}.ass"
        await self.subtitle_gen.save_ass(
            subtitles,
            subtitle_path,
            font_name=options.subtitle_style.get("font_name", "Microsoft YaHei"),
            font_size=options.subtitle_style.get("font_size", 48),
            primary_color=options.subtitle_style.get("color", "&H00FFFFFF"),
            outline_color=options.subtitle_style.get("outline_color", "&H00000000"),
        )
        await report_progress("Subtitles ready", 0.6)

        await report_progress("Composing video", 0.6)
        video_path = await self._compose_video(
            materials=materials,
            segment_audios=segment_audios,
            subtitle_path=subtitle_path,
            background_music_path=background_music_path,
            duration=total_audio_duration,
            resolution=options.resolution,
            fps=options.fps,
        )

        await report_progress("Video complete", 1.0)
        logger.info(f"Video generated: {video_path}")
        return video_path

    async def _synthesize_segment(
        self,
        segment: ScriptSegment,
        index: int,
        voice: str,
    ) -> SegmentAudio:
        """Synthesize audio for a segment."""
        audio_path = await self.tts_engine.synthesize(
            text=segment.text,
            output_path=self.output_dir / f"segment_{index}.mp3",
            voice=voice,
        )
        duration = await self.tts_engine.get_duration(audio_path)

        return SegmentAudio(
            segment_index=index,
            text=segment.text,
            audio_path=audio_path,
            duration=duration,
        )

    async def _compose_video(
        self,
        materials: list[Path],
        segment_audios: list[SegmentAudio],
        subtitle_path: Path,
        background_music_path: Path | None,
        duration: float,
        resolution: tuple[int, int],
        fps: int,
    ) -> Path:
        """Compose final video from materials, audio, and subtitles."""
        
        import time
        timestamp = int(time.time())
        output_dir = self.output_dir

        def _sync_compose():
            audio_clips = []
            for sa in sorted(segment_audios, key=lambda x: x.segment_index):
                clip = AudioFileClip(str(sa.audio_path))
                audio_clips.append(clip)

            combined_audio = CompositeAudioClip(audio_clips)

            if background_music_path and background_music_path.exists():
                bg_music = AudioFileClip(str(background_music_path))
                if bg_music.duration < duration:
                    bg_music = bg_music.with_effects([AudioLoop(duration=duration)])
                else:
                    bg_music = bg_music.subclipped(0, duration)
                bg_music = bg_music.with_volume_scaled(0.2)
                combined_audio = CompositeAudioClip([combined_audio, bg_music])

            video_clips = []
            if materials:
                clip_duration = duration / len(materials)
                for i, material in enumerate(materials):
                    try:
                        if material.suffix.lower() in (".mp4", ".mov", ".webm"):
                            clip = VideoFileClip(str(material))
                        else:
                            clip = ImageClip(str(material))

                        clip = clip.resized(new_size=resolution)
                        clip = clip.with_duration(clip_duration)
                        clip = clip.with_start(i * clip_duration)
                        video_clips.append(clip)
                    except Exception as e:
                        logger.warning(f"Failed to load material {material}: {e}")
                        continue

            if not video_clips:
                from moviepy.video.VideoClip import ColorClip
                bg = ColorClip(size=resolution, color=(30, 30, 50), duration=duration)
                video_clips = [bg]

            video = CompositeVideoClip(video_clips, size=resolution)
            video = video.with_duration(duration)
            video = video.with_audio(combined_audio)

            output_path = output_dir / f"video_{timestamp}.mp4"

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

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_compose)

    async def generate_from_script(
        self,
        script: GeneratedScript,
        background_music_path: Path | None = None,
        options: VideoOptions | None = None,
        progress_callback: Callable | None = None,
    ) -> Path:
        """Generate video from a pre-generated script."""
        options = options or VideoOptions()

        all_content = "\n\n".join(seg.text for seg in script.segments)
        return await self.generate(
            content=all_content,
            title=script.title,
            background_music_path=background_music_path,
            options=options,
            progress_callback=progress_callback,
        )

"""Video composition service."""

import asyncio
import logging
import tempfile
from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip
from moviepy.audio.fx import AudioLoop
from moviepy.video.VideoClip import TextClip, ColorClip

from ..core.task_logger import TaskLogger

logger = logging.getLogger(__name__)

FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _find_font_path() -> str | None:
    """Find an available Chinese font path."""
    for fp in FONT_PATHS:
        if Path(fp).exists():
            return fp
    return None


def _create_audio_track(
    segment_audios: list[dict],
    bg_music_path: Path | None,
    duration: float,
    task_logger: TaskLogger,
) -> CompositeAudioClip:
    """Create composite audio track."""
    task_logger.info("合并音频片段...")
    audio_clips = []
    current_time = 0.0
    
    for sa in sorted(segment_audios, key=lambda x: x["index"]):
        clip = AudioFileClip(str(sa["audio_path"]))
        clip = clip.with_start(current_time)
        audio_clips.append(clip)
        current_time += sa["duration"]
        task_logger.info(f"音频片段 {sa['index']}: 开始={clip.start:.1f}s, 时长={sa['duration']:.1f}s")
    
    task_logger.info(f"总音频时长: {current_time:.1f}s")
    combined_audio = CompositeAudioClip(audio_clips)
    
    if bg_music_path and bg_music_path.exists():
        task_logger.info("添加背景音乐...")
        bg_music = AudioFileClip(str(bg_music_path))
        task_logger.info(f"背景音乐时长: {bg_music.duration:.1f}s")
        
        if bg_music.duration < duration:
            bg_music = bg_music.with_effects([AudioLoop(duration=duration)])
        else:
            bg_music = bg_music.subclipped(0, duration)
        
        bg_music = bg_music.with_volume_scaled(0.2)
        combined_audio = CompositeAudioClip([combined_audio, bg_music])
    
    return combined_audio


def _create_video_track(
    materials: list[Path],
    resolution: tuple[int, int],
    duration: float,
    task_logger: TaskLogger,
) -> list:
    """Create video track from materials."""
    task_logger.info("创建视频轨道...")
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
                task_logger.warning(f"加载素材失败 {material}: {e}")
                continue
    
    if not video_clips:
        task_logger.info("无素材，创建纯色背景")
        bg = ColorClip(size=resolution, color=(30, 30, 50), duration=duration)
        video_clips = [bg]
    
    return video_clips


def _create_subtitle_track(
    subtitles: list,
    resolution: tuple[int, int],
    task_logger: TaskLogger,
) -> list:
    """Create subtitle track."""
    task_logger.info("创建字幕轨道...")
    subtitle_clips = []
    width, height = resolution
    
    try:
        font_size = int(height * 0.04)
        font_path = _find_font_path()
        
        if font_path:
            task_logger.info(f"字幕字体: {font_path}")
        
        for sub in subtitles:
            try:
                txt_clip = TextClip(
                    text=sub.text,
                    font_size=font_size,
                    color="white",
                    stroke_color="black",
                    stroke_width=2,
                    method="caption",
                    size=(width - 100, None),
                    text_align="center",
                    font=font_path,
                )
                txt_clip = txt_clip.with_position(("center", height - 200))
                txt_clip = txt_clip.with_start(sub.start_time)
                txt_clip = txt_clip.with_duration(sub.end_time - sub.start_time)
                subtitle_clips.append(txt_clip)
            except Exception as e:
                task_logger.warning(f"创建字幕失败: {e}")
                continue
        
        if subtitle_clips:
            task_logger.info(f"创建了 {len(subtitle_clips)} 个字幕片段")
    except Exception as e:
        task_logger.warning(f"字幕轨道创建失败: {e}")
    
    return subtitle_clips


def _compose_video_sync(
    task_dir: Path,
    task_logger: TaskLogger,
    materials: list[Path],
    segment_audios: list[dict],
    subtitles: list,
    bg_music_path: Path | None,
    duration: float,
    resolution: tuple[int, int],
    fps: int,
) -> Path:
    """Compose video synchronously."""
    combined_audio = _create_audio_track(
        segment_audios, bg_music_path, duration, task_logger
    )
    
    video_clips = _create_video_track(
        materials, resolution, duration, task_logger
    )
    
    subtitle_clips = _create_subtitle_track(
        subtitles, resolution, task_logger
    )
    
    task_logger.info("合成最终视频...")
    all_clips = video_clips + subtitle_clips
    video = CompositeVideoClip(all_clips, size=resolution)
    video = video.with_duration(duration)
    video = video.with_audio(combined_audio)
    
    output_path = task_dir / "output.mp4"
    
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


async def compose_video(
    task_dir: Path,
    task_logger: TaskLogger,
    materials: list[Path],
    segment_audios: list[dict],
    subtitles: list,
    bg_music_path: Path | None,
    duration: float,
    resolution: tuple[int, int],
    fps: int = 30,
) -> Path:
    """Compose final video."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _compose_video_sync,
        task_dir,
        task_logger,
        materials,
        segment_audios,
        subtitles,
        bg_music_path,
        duration,
        resolution,
        fps,
    )
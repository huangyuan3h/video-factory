"""Video composition service."""

import asyncio
import logging
import tempfile
from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip
from moviepy.audio.fx import AudioLoop
from moviepy.video.fx import CrossFadeIn, CrossFadeOut
from moviepy.video.VideoClip import ColorClip, TextClip

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


def _fit_cover(clip, resolution: tuple[int, int]):
    """Scale + center-crop ``clip`` to fully cover ``resolution`` (no stretch).

    Off-ratio material (a 4:3 photo or a vertical video in a landscape episode)
    is scaled uniformly by ``max(W/w, H/h)`` so it fills the frame, then
    center-cropped to exactly ``resolution``. When the source size is missing or
    zero we fall back to a plain resize (old behaviour) so composition never
    crashes on odd clips.
    """
    try:
        out_w, out_h = int(resolution[0]), int(resolution[1])
        src_w = float(getattr(clip, "w", 0) or 0)
        src_h = float(getattr(clip, "h", 0) or 0)
        if src_w <= 0 or src_h <= 0 or out_w <= 0 or out_h <= 0:
            return clip.resized(new_size=resolution)
        scale = max(out_w / src_w, out_h / src_h)
        resized = clip.resized(scale)
        return resized.cropped(
            x_center=resized.w / 2,
            y_center=resized.h / 2,
            width=out_w,
            height=out_h,
        )
    except Exception:
        return clip.resized(new_size=resolution)


def _create_audio_track(
    segment_audios: list[dict],
    bg_music_path: Path | None,
    duration: float,
    task_logger: TaskLogger,
    start_offset: float = 0.0,
) -> CompositeAudioClip:
    """Create composite audio track.

    ``start_offset`` delays narration (e.g. to play under a cover title card)
    while background music still spans the whole video from t=0.
    """
    task_logger.info("合并音频片段...")
    audio_clips = []
    current_time = start_offset
    
    for sa in sorted(segment_audios, key=lambda x: x["index"]):
        clip = AudioFileClip(str(sa["audio_path"]))
        # Each segment sits at its own narration offset (speech + inter-segment
        # pauses). Fall back to the running sum of durations for old callers.
        seg_start = start_offset + float(sa.get("offset", current_time - start_offset))
        clip = clip.with_start(seg_start)
        audio_clips.append(clip)
        current_time = seg_start + sa["duration"]
        task_logger.info(f"音频片段 {sa['index']}: 开始={clip.start:.1f}s, 时长={sa['duration']:.1f}s")
    
    task_logger.info(f"总音频时长: {current_time:.1f}s")
    if not audio_clips:
        raise ValueError(
            "没有可用的音频片段（segment_audios 为空），无法合成音频轨道；"
            "请检查脚本是否成功生成了段落"
        )
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


def _apply_slide_transitions(built: list, transition_seconds: float, task_logger: TaskLogger) -> list:
    """Crossfade consecutive stills by overlapping each with the next one.

    ``built`` is an ordered ``[(clip, is_image), ...]`` list. Each still is
    extended by the transition so it overlaps the following clip (borrowing from
    the adjacent hold rather than stretching the total timeline; the final
    overlap is capped by ``with_duration`` on the composite). ``CrossFadeIn`` /
    ``CrossFadeOut`` provide the dissolve. The first still does not fade in so
    the video never opens on visible background. Returns the (mutated) list.
    """
    if transition_seconds <= 0:
        return built
    still_positions = [i for i, (_, is_image) in enumerate(built) if is_image]
    if len(still_positions) < 2:
        return built
    for order, i in enumerate(still_positions):
        clip, _ = built[i]
        dur = float(getattr(clip, "duration", 0.0) or 0.0)
        if dur <= 0:
            continue
        overlap = min(transition_seconds, dur / 2)
        if overlap <= 0:
            continue
        is_last = order == len(still_positions) - 1
        effects = []
        if order > 0:
            effects.append(CrossFadeIn(overlap))
        if not is_last:
            effects.append(CrossFadeOut(overlap))
            clip = clip.with_duration(dur + overlap)
        if effects:
            clip = clip.with_effects(effects)
            built[i] = (clip, True)
    task_logger.info(
        f"静图过渡: {len(still_positions)} 张，交叉淡入淡出 {transition_seconds:.2f}s"
    )
    return built


def _create_video_track(
    materials: list[Path],
    resolution: tuple[int, int],
    duration: float,
    task_logger: TaskLogger,
    segment_audios: list[dict] | None = None,
    materials_per_segment: list[list[Path]] | None = None,
    cover_path: Path | None = None,
    cover_hold_seconds: float = 3.0,
    start_offset: float = 0.0,
    transition_seconds: float = 0.0,
) -> list:
    """Create video track from materials — timeline-aware per segment if possible.

    When ``cover_path`` is given the cover is inserted as the first clip at t=0
    (a still title card) and the remaining timeline starts at
    ``start_offset`` (normally ``cover_hold_seconds``). ``transition_seconds``
    adds a dissolve between consecutive stills.
    """
    task_logger.info("创建视频轨道...")
    # Ordered [(clip, is_image)] so the transition pass can tell stills apart.
    built: list[tuple] = []

    # Per-segment timeline-aware path
    if materials_per_segment and segment_audios:
        task_logger.info(f"按段拼视频：{len(segment_audios)} 段，{sum(len(m) for m in materials_per_segment)} 素材")
        seg_sorted = sorted(segment_audios, key=lambda x: x["index"])
        current_start = start_offset
        for seg in seg_sorted:
            idx = seg["index"]
            seg_dur = seg["duration"]
            seg_pause = float(seg.get("pause_after", 0.0) or 0.0)
            # Visual span covers speech + trailing pause so the picture keeps
            # filling the frame during the silence (no black gap).
            span = seg_dur + seg_pause
            seg_start = start_offset + float(seg.get("offset", current_start - start_offset))
            seg_mats = materials_per_segment[idx] if idx < len(materials_per_segment) else []
            if not seg_mats:
                # No material for this segment — keep background for its duration
                task_logger.info(f"段 {idx} 无素材，保留背景 {span:.1f}s")
                current_start = seg_start + span
                continue
            sub_dur = span / len(seg_mats)
            for j, material in enumerate(seg_mats):
                try:
                    is_video = material.suffix.lower() in (".mp4", ".mov", ".webm")
                    clip = VideoFileClip(str(material)) if is_video else ImageClip(str(material))
                    clip = _fit_cover(clip, resolution)
                    clip = clip.with_duration(sub_dur)
                    clip = clip.with_start(seg_start + j * sub_dur)
                    built.append((clip, not is_video))
                except Exception as e:
                    task_logger.warning(f"加载素材失败 {material}: {e}")
                    continue
            current_start = seg_start + span
    elif materials:
        usable_duration = max(0.0, duration - start_offset)
        clip_duration = usable_duration / len(materials)
        for i, material in enumerate(materials):
            try:
                is_video = material.suffix.lower() in (".mp4", ".mov", ".webm")
                clip = VideoFileClip(str(material)) if is_video else ImageClip(str(material))
                clip = _fit_cover(clip, resolution)
                clip = clip.with_duration(clip_duration)
                clip = clip.with_start(start_offset + i * clip_duration)
                built.append((clip, not is_video))
            except Exception as e:
                task_logger.warning(f"加载素材失败 {material}: {e}")
                continue

    if not built:
        task_logger.info("无素材，创建纯色背景")
        bg_duration = max(0.01, duration - start_offset)
        bg = ColorClip(size=resolution, color=(30, 30, 50), duration=bg_duration)
        bg = bg.with_start(start_offset)
        built = [(bg, False)]

    built = _apply_slide_transitions(built, transition_seconds, task_logger)
    video_clips = [clip for clip, _ in built]

    if cover_path:
        try:
            cover = ImageClip(str(cover_path))
            cover = _fit_cover(cover, resolution)
            cover = cover.with_duration(cover_hold_seconds)
            cover = cover.with_start(0.0)
            video_clips.insert(0, cover)
            task_logger.info(f"封面片头: {cover_hold_seconds:.1f}s")
        except Exception as e:
            task_logger.warning(f"封面片头创建失败: {e}")
    
    return video_clips


def _create_subtitle_track(
    subtitles: list,
    resolution: tuple[int, int],
    task_logger: TaskLogger,
    start_offset: float = 0.0,
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
                txt_clip = txt_clip.with_start(sub.start_time + start_offset)
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
    materials_per_segment: list[list[Path]] | None = None,
    cover_path: Path | None = None,
    cover_hold_seconds: float = 3.0,
    transition_seconds: float = 0.0,
) -> Path:
    """Compose video synchronously.

    When ``cover_path`` is set, the cover is shown as the first frame for
    ``cover_hold_seconds`` and the narration/subtitles/video timeline is shifted
    by that amount (so the cover reads as a title card and the total video grows
    by ``cover_hold_seconds``). ``transition_seconds`` crossfades consecutive
    stills without extending the total duration.
    """
    has_cover = bool(cover_path and Path(cover_path).exists())
    start_offset = cover_hold_seconds if has_cover else 0.0
    total_duration = duration + start_offset

    combined_audio = _create_audio_track(
        segment_audios, bg_music_path, total_duration, task_logger,
        start_offset=start_offset,
    )
    
    video_clips = _create_video_track(
        materials, resolution, total_duration, task_logger,
        segment_audios=segment_audios,
        materials_per_segment=materials_per_segment,
        cover_path=cover_path if has_cover else None,
        cover_hold_seconds=cover_hold_seconds,
        start_offset=start_offset,
        transition_seconds=transition_seconds,
    )
    
    subtitle_clips = _create_subtitle_track(
        subtitles, resolution, task_logger, start_offset=start_offset
    )
    
    task_logger.info("合成最终视频...")
    all_clips = video_clips + subtitle_clips
    video = CompositeVideoClip(all_clips, size=resolution)
    video = video.with_duration(total_duration)
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
    materials_per_segment: list[list[Path]] | None = None,
    cover_path: Path | None = None,
    cover_hold_seconds: float = 3.0,
    transition_seconds: float = 0.0,
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
        materials_per_segment,
        cover_path,
        cover_hold_seconds,
        transition_seconds,
    )
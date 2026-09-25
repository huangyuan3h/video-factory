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


def _parse_hex_color(value: str | None, default: tuple[int, int, int] = (22, 24, 28)) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` (or ``RRGGBB``) into an RGB tuple, falling back on error."""
    if not value:
        return default
    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return default
    try:
        return (
            int(text[0:2], 16),
            int(text[2:4], 16),
            int(text[4:6], 16),
        )
    except ValueError:
        return default


def _chart_background_color() -> tuple[int, int, int]:
    from ..config import settings

    return _parse_hex_color(getattr(settings, "chart_background_color", "#16181c"))


def _fit_contain(clip, resolution: tuple[int, int], box: tuple[int, int, int, int] | None = None,
                 bg_color: tuple[int, int, int] | None = None):
    """Scale ``clip`` uniformly to fit INSIDE ``box`` and center it (never crops).

    The whole image stays visible, letterboxed into a clip of exactly
    ``resolution``; the surrounding area is filled with ``bg_color`` (default the
    configured neutral chart background). ``box`` is ``(x, y, w, h)`` in output
    pixels and defaults to the whole frame.
    """
    out_w, out_h = int(resolution[0]), int(resolution[1])
    if box is None:
        bx, by, bw, bh = 0, 0, out_w, out_h
    else:
        bx, by, bw, bh = (int(v) for v in box)
    color = bg_color if bg_color is not None else _chart_background_color()
    bg = ColorClip(size=(out_w, out_h), color=color)
    try:
        src_w = float(getattr(clip, "w", 0) or 0)
        src_h = float(getattr(clip, "h", 0) or 0)
    except Exception:
        src_w = src_h = 0.0
    if src_w <= 0 or src_h <= 0 or bw <= 0 or bh <= 0:
        return bg
    scale = min(bw / src_w, bh / src_h)
    try:
        fitted = clip.resized(scale)
        fitted = fitted.with_position((bx + (bw - src_w * scale) / 2, by + (bh - src_h * scale) / 2))
    except Exception:
        return bg
    return CompositeVideoClip([bg, fitted], size=(out_w, out_h))


def _fit_contain_motion(clip, resolution: tuple[int, int], duration: float,
                        box: tuple[int, int, int, int] | None = None,
                        max_zoom: float = 1.03,
                        bg_color: tuple[int, int, int] | None = None):
    """``_fit_contain`` plus a very slow linear zoom of 1.00 -> ``max_zoom``.

    The base contain size is scaled by ``1 / max_zoom`` so that at maximum zoom
    the full image is still inside the box (no chart content is ever cropped).
    """
    out_w, out_h = int(resolution[0]), int(resolution[1])
    if box is None:
        bx, by, bw, bh = 0, 0, out_w, out_h
    else:
        bx, by, bw, bh = (int(v) for v in box)
    color = bg_color if bg_color is not None else _chart_background_color()
    bg = ColorClip(size=(out_w, out_h), color=color)
    try:
        src_w = float(getattr(clip, "w", 0) or 0)
        src_h = float(getattr(clip, "h", 0) or 0)
    except Exception:
        src_w = src_h = 0.0
    if src_w <= 0 or src_h <= 0 or bw <= 0 or bh <= 0:
        return bg
    base = min(bw / src_w, bh / src_h) / float(max_zoom)
    dur = float(duration) if duration and duration > 0 else 1.0

    def _scale(t: float) -> float:
        progress = max(0.0, min(1.0, float(t) / dur))
        return base * (1.0 + (max_zoom - 1.0) * progress)

    def _position(t: float):
        scale = _scale(t)
        return (bx + (bw - src_w * scale) / 2, by + (bh - src_h * scale) / 2)

    try:
        fitted = clip.resized(_scale)
        fitted = fitted.with_position(_position)
    except Exception:
        return bg
    return CompositeVideoClip([bg, fitted], size=(out_w, out_h))


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


def _hold_durations(spec: dict, count: int, span: float) -> list[float]:
    """Per-image hold seconds covering ``span`` exactly.

    Uses ``spec['hold_seconds']`` when provided, scaling the list proportionally
    so the images still cover the whole segment span; otherwise the span is split
    evenly.
    """
    if span <= 0 or count <= 0:
        return [span / count if count else span] * count
    holds = spec.get("hold_seconds")
    if holds and len(holds) == count:
        total = sum(float(h) for h in holds)
        if total > 0:
            return [float(h) * span / total for h in holds]
    return [span / count] * count


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
    segment_visual_specs: list[dict | None] | None = None,
    cover_is_contain: bool = False,
) -> list:
    """Create video track from materials — timeline-aware per segment if possible.

    When ``cover_path`` is given the cover is inserted as the first clip at t=0
    (a still title card) and the remaining timeline starts at
    ``start_offset`` (normally ``cover_hold_seconds``). ``transition_seconds``
    adds a dissolve between consecutive stills.

    ``segment_visual_specs`` (aligned with ``materials_per_segment``) selects the
    chart layout per segment: ``contain`` keeps the whole image visible (with a
    subtitle band and optional gentle zoom), ``cover`` keeps the old crop-to-fill.
    """
    task_logger.info("创建视频轨道...")
    # Ordered [(clip, is_image)] so the transition pass can tell stills apart.
    built: list[tuple] = []
    band = _subtitle_band_height(resolution)

    def _layout(clip, spec: dict, box_height: int):
        """Apply contain chart layout + motion, or crop-to-fill for 'cover'."""
        fit = str(spec.get("fit") or "contain")
        if fit != "contain":
            return _fit_cover(clip, resolution)
        box = (0, 0, int(resolution[0]), int(box_height))
        if str(spec.get("motion") or "none") == "gentle":
            return _fit_contain_motion(clip, resolution, clip.duration, box=box)
        return _fit_contain(clip, resolution, box=box)

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
            spec = (
                segment_visual_specs[idx]
                if segment_visual_specs and idx < len(segment_visual_specs)
                else None
            )
            if spec:
                holds = _hold_durations(spec, len(seg_mats), span)
            else:
                holds = [span / len(seg_mats)] * len(seg_mats)
            offset_in_seg = 0.0
            for j, material in enumerate(seg_mats):
                sub_dur = holds[j]
                try:
                    is_video = material.suffix.lower() in (".mp4", ".mov", ".webm")
                    clip = VideoFileClip(str(material)) if is_video else ImageClip(str(material))
                    if spec:
                        clip = _layout(clip, spec, resolution[1] - band)
                    else:
                        clip = _fit_cover(clip, resolution)
                    clip = clip.with_duration(sub_dur)
                    clip = clip.with_start(seg_start + offset_in_seg)
                    built.append((clip, not is_video))
                except Exception as e:
                    task_logger.warning(f"加载素材失败 {material}: {e}")
                offset_in_seg += sub_dur
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
            if cover_is_contain:
                # Cover supplied as a local "contain" image: whole image visible
                # over the full frame, no subtitle band.
                cover = _fit_contain(cover, resolution)
            else:
                cover = _fit_cover(cover, resolution)
            cover = cover.with_duration(cover_hold_seconds)
            cover = cover.with_start(0.0)
            video_clips.insert(0, cover)
            task_logger.info(f"封面片头: {cover_hold_seconds:.1f}s")
        except Exception as e:
            task_logger.warning(f"封面片头创建失败: {e}")
    
    return video_clips


def _subtitle_band_height(resolution: tuple[int, int]) -> int:
    """Subtitles band height in pixels for the chart layout (part of the frame)."""
    from ..config import settings

    ratio = float(getattr(settings, "chart_subtitle_band_ratio", 0.12) or 0.12)
    return max(0, int(resolution[1] * ratio))


def _subtitle_font_size(resolution: tuple[int, int], in_band: bool) -> int:
    from ..config import settings

    height = resolution[1]
    if in_band:
        ratio = float(getattr(settings, "chart_subtitle_font_ratio", 0.036) or 0.036)
        return max(1, int(height * ratio))
    return int(height * 0.04)


def _create_subtitle_track(
    subtitles: list,
    resolution: tuple[int, int],
    task_logger: TaskLogger,
    start_offset: float = 0.0,
    chart_windows: list[tuple[float, float]] | None = None,
) -> list:
    """Create subtitle track.

    ``chart_windows`` are narration-time ``(start, end)`` windows belonging to
    "contain" chart segments: a subtitle starting inside one is rendered in the
    bottom subtitle band with the smaller chart font. Other subtitles keep the
    current placement at ``y = height - 200``.
    """
    task_logger.info("创建字幕轨道...")
    subtitle_clips = []
    width, height = resolution
    band = _subtitle_band_height(resolution)
    windows = list(chart_windows or [])
    
    try:
        font_path = _find_font_path()
        
        if font_path:
            task_logger.info(f"字幕字体: {font_path}")
        
        for sub in subtitles:
            try:
                in_band = any(start <= sub.start_time < end for start, end in windows)
                font_size = _subtitle_font_size(resolution, in_band)
                txt_clip = TextClip(
                    text=sub.text,
                    font_size=font_size,
                    color="white",
                    stroke_color="black",
                    stroke_width=3,
                    method="caption",
                    size=(width - 100, None),
                    text_align="center",
                    font=font_path,
                )
                if in_band and band > 0:
                    txt_y = height - band / 2 - font_size / 2
                else:
                    txt_y = height - 200
                txt_clip = txt_clip.with_position(("center", txt_y))
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


def _chart_narration_windows(
    segment_audios: list[dict],
    segment_visual_specs: list[dict | None] | None,
) -> list[tuple[float, float]]:
    """Narration-time windows of "contain" (chart) segments.

    Each window is the segment's on-screen span (``offset`` .. ``offset`` +
    ``duration`` + ``pause_after``) and is used to place subtitles in the band.
    """
    if not segment_audios or not segment_visual_specs:
        return []
    windows: list[tuple[float, float]] = []
    for seg in segment_audios:
        idx = seg.get("index", 0)
        if idx >= len(segment_visual_specs):
            continue
        spec = segment_visual_specs[idx]
        if not spec or str(spec.get("fit") or "contain") != "contain":
            continue
        start = float(seg.get("offset", 0.0) or 0.0)
        span = float(seg.get("duration", 0.0) or 0.0) + float(seg.get("pause_after", 0.0) or 0.0)
        windows.append((start, start + span))
    return windows


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
    segment_visual_specs: list[dict | None] | None = None,
    cover_is_contain: bool = False,
) -> Path:
    """Compose video synchronously.

    When ``cover_path`` is set, the cover is shown as the first frame for
    ``cover_hold_seconds`` and the narration/subtitles/video timeline is shifted
    by that amount (so the cover reads as a title card and the total video grows
    by ``cover_hold_seconds``). ``transition_seconds`` crossfades consecutive
    stills without extending the total duration. ``segment_visual_specs`` drive
    the per-segment chart layout and the subtitle band windows.
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
        segment_visual_specs=segment_visual_specs,
        cover_is_contain=cover_is_contain,
    )
    
    subtitle_clips = _create_subtitle_track(
        subtitles, resolution, task_logger, start_offset=start_offset,
        chart_windows=_chart_narration_windows(segment_audios, segment_visual_specs),
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
    segment_visual_specs: list[dict | None] | None = None,
    cover_is_contain: bool = False,
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
        segment_visual_specs,
        cover_is_contain,
    )
"""Video generation service."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..core.ai_client import AIClient
from ..core.task_logger import TaskLogger
from ..core.tts_engine import EdgeTTSEngine
from ..core.subtitle_gen import SubtitleGenerator
from .settings_service import get_active_ai_client, get_general_settings
from .cover_service import generate_cover_image
from .compose_service import compose_video
from .material import MaterialFetcher

logger = logging.getLogger(__name__)

video_tasks: dict[str, dict] = {}


def run_video_generation(
    task_id: str,
    request,
    task_dir: Path,
):
    """Run video generation in background."""

    async def _generate():
        task_logger = TaskLogger(task_id, task_dir)
        
        try:
            video_tasks[task_id]["task_dir"] = str(task_dir)
            video_tasks[task_id]["log_file"] = str(task_dir / "task.log")
            
            await _init_task(task_logger, request)
            
            ai_client = await _get_ai_client(task_logger)
            script = await _generate_script(ai_client, request, task_logger)
            segment_audios, total_duration = await _synthesize_audio(
                script, request, task_dir, task_logger
            )
            materials = await _fetch_materials(script, request, task_logger)
            subtitles = await _generate_subtitles(segment_audios, total_duration, request, task_dir, task_logger)
            cover_path = await _generate_cover(request, task_dir, task_logger)
            video_path = await _compose_final_video(
                request, task_dir, task_logger, materials, segment_audios, subtitles, total_duration
            )
            
            _mark_completed(task_id, task_logger, video_path)
            
        except Exception as e:
            _handle_error(task_id, task_logger, e)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_generate())
    finally:
        loop.close()


async def _init_task(task_logger: TaskLogger, request):
    """Initialize task configuration."""
    task_logger.step(1, "初始化任务配置")
    task_logger.info(f"标题: {request.title}")
    task_logger.info(f"语音: {request.voice}")
    task_logger.info(f"分辨率: {request.resolution_width}x{request.resolution_height}")


async def _get_ai_client(task_logger: TaskLogger) -> AIClient:
    """Get AI client and validate configuration."""
    ai_client = await get_active_ai_client()
    if not ai_client:
        raise ValueError("未配置 AI 设置，请先在设置页面配置 AI 参数")
    
    task_logger.info(f"使用 AI 模型: {ai_client.model}")
    return ai_client


async def _generate_script(ai_client: AIClient, request, task_logger: TaskLogger):
    """Generate script using AI."""
    task_logger.step(2, "调用 AI 生成脚本")
    
    script = await ai_client.generate_script(
        content=request.text_content,
        title=request.title,
        system_prompt=request.system_prompt or "",
    )
    
    task_logger.save_script(script.model_dump())
    task_logger.info(f"生成 {len(script.segments)} 个段落")
    
    for i, seg in enumerate(script.segments):
        task_logger.info(f"段落 {i+1}: {seg.text[:50]}... (关键词: {', '.join(seg.keywords)})")
    
    return script


async def _synthesize_audio(script, request, task_dir: Path, task_logger: TaskLogger):
    """Synthesize audio for each segment."""
    task_logger.step(3, "合成语音")
    
    tts = EdgeTTSEngine(voice=request.voice, rate=request.voice_rate)
    segment_audios = []
    total_segments = len(script.segments)
    
    for i, segment in enumerate(script.segments):
        audio_path = task_dir / f"segment_{i}.mp3"
        task_logger.info(f"合成段落 {i+1}/{total_segments}")
        
        await tts.synthesize(
            text=segment.text,
            output_path=audio_path,
            voice=request.voice,
        )
        duration = await tts.get_duration(audio_path)
        
        segment_audios.append({
            "index": i,
            "text": segment.text,
            "audio_path": audio_path,
            "duration": duration,
        })
        task_logger.set_file(f"audio_{i}", audio_path)
        
        progress = 0.2 + (i / total_segments) * 0.2
        task_logger.set_progress(progress)
    
    total_duration = sum(sa["duration"] for sa in segment_audios)
    task_logger.info(f"总音频时长: {total_duration:.1f} 秒")
    
    return segment_audios, total_duration


async def _fetch_materials(script, request, task_logger: TaskLogger):
    """Fetch video/image materials."""
    task_logger.step(4, "获取视频素材")
    
    all_keywords = []
    for seg in script.segments:
        all_keywords.extend(seg.keywords)
    unique_keywords = list(set(all_keywords))[:10]
    task_logger.info(f"关键词: {', '.join(unique_keywords)}")
    
    gen_settings = await get_general_settings()
    material_fetcher = MaterialFetcher(
        pexels_api_key=gen_settings.get("pexels_api_key"),
        pixabay_api_key=gen_settings.get("pixabay_api_key"),
    )
    task_logger.info(f"Pexels API Key: {'已配置' if gen_settings.get('pexels_api_key') else '未配置'}")
    
    materials = await material_fetcher.fetch_videos(
        keywords=unique_keywords,
        count=15,
        source=request.background_source,
    )
    
    if not materials:
        task_logger.warning("未找到视频素材，尝试获取图片")
        materials = await material_fetcher.fetch_images(
            keywords=unique_keywords,
            count=20,
            source=request.background_source,
        )
    
    task_logger.info(f"获取 {len(materials)} 个素材")
    for i, m in enumerate(materials[:5]):
        task_logger.info(f"素材 {i+1}: {m.name}")
    
    return materials


async def _generate_subtitles(segment_audios, total_duration, request, task_dir: Path, task_logger: TaskLogger):
    """Generate subtitles."""
    task_logger.step(5, "生成字幕")
    
    subtitle_gen = SubtitleGenerator()
    all_text = " ".join(sa["text"] for sa in segment_audios)
    
    subtitles = await subtitle_gen.generate(
        text=all_text,
        audio_duration=total_duration,
    )
    
    subtitle_path = task_dir / "subtitles.ass"
    await subtitle_gen.save_ass(
        subtitles,
        subtitle_path,
        font_name=request.subtitle_font,
        font_size=48,
        primary_color=request.subtitle_color,
        outline_color="&H00000000",
    )
    task_logger.set_file("subtitles", subtitle_path)
    task_logger.info(f"生成 {len(subtitles)} 条字幕")
    
    return subtitles


async def _generate_cover(request, task_dir: Path, task_logger: TaskLogger):
    """Generate cover image."""
    task_logger.step(6, "生成封面图")
    
    gen_settings = await get_general_settings()
    
    cover_path = await generate_cover_image(
        task_dir=task_dir,
        task_logger=task_logger,
        title=request.title,
        keywords=[],
        pexels_api_key=gen_settings.get("pexels_api_key"),
        resolution=(request.resolution_width, request.resolution_height),
    )
    task_logger.set_file("cover", cover_path)
    
    return cover_path


async def _compose_final_video(
    request, task_dir: Path, task_logger: TaskLogger, materials, segment_audios, subtitles, total_duration
):
    """Compose final video."""
    task_logger.step(7, "合成视频")
    
    bg_music_path = _resolve_bg_music_path(request, task_logger)
    
    video_path = await compose_video(
        task_dir=task_dir,
        task_logger=task_logger,
        materials=materials,
        segment_audios=segment_audios,
        subtitles=subtitles,
        bg_music_path=bg_music_path,
        duration=total_duration,
        resolution=(request.resolution_width, request.resolution_height),
        fps=30,
    )
    
    return video_path


def _resolve_bg_music_path(request, task_logger: TaskLogger):
    """Resolve background music path."""
    if not request.background_music:
        return None
    
    music_path = Path(request.background_music)
    if music_path.exists():
        return music_path
    
    assets_music_path = settings.assets_dir / "music" / request.background_music
    if assets_music_path.exists():
        return assets_music_path
    
    task_logger.info(f"背景音乐: {request.background_music} 未找到")
    return None


def _mark_completed(task_id: str, task_logger: TaskLogger, video_path: Path):
    """Mark task as completed."""
    task_logger.step(8, "完成")
    task_logger.complete(video_path)
    
    video_tasks[task_id]["status"] = "completed"
    video_tasks[task_id]["progress"] = 1.0
    video_tasks[task_id]["message"] = "视频生成完成"
    video_tasks[task_id]["video_path"] = str(video_path)
    video_tasks[task_id]["completed_at"] = datetime.now().isoformat()


def _handle_error(task_id: str, task_logger: TaskLogger, error: Exception):
    """Handle task error."""
    logger.error(f"Video generation failed for task {task_id}: {error}", exc_info=True)
    task_logger.fail(str(error))
    
    video_tasks[task_id]["status"] = "failed"
    video_tasks[task_id]["message"] = str(error)
    video_tasks[task_id]["error"] = str(error)
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
            # LLM rewrite if requested
            await _maybe_rewrite_content(ai_client, request, task_logger)
            script = await _generate_script(ai_client, request, task_logger)
            segment_audios, total_duration = await _synthesize_audio(
                script, request, task_dir, task_logger
            )
            materials = await _fetch_materials(script, request, task_logger, segment_audios)
            subtitles = await _generate_subtitles(segment_audios, total_duration, request, task_dir, task_logger)
            cover_path = await _generate_cover(request, task_dir, task_logger)
            video_path = await _compose_final_video(
                request, task_dir, task_logger, materials, segment_audios, subtitles, total_duration
            )
            
            _mark_completed(task_id, task_logger, video_path)
            # Auto-publish if requested — extensible, per-platform folder support
            await _auto_publish_if_requested(request, video_path, task_logger, task_id)
            
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


async def _maybe_rewrite_content(ai_client: AIClient, request, task_logger: TaskLogger):
    """Handle LLM rewrite if requested — respects boolean and prompt provision."""
    should_rewrite = bool(
        getattr(request, "rewrite_content", False)
        or getattr(request, "optimize", False)
        or getattr(request, "rewriteContent", False)
        or getattr(request, "optimize_content", False)
    )
    if not should_rewrite:
        return
    task_logger.step(1, "LLM 优化内容")
    original = request.content if hasattr(request, "content") else request.text_content
    rewrite_prompt = getattr(request, "rewrite_prompt", None) or getattr(request, "rewritePrompt", None)
    # If prompt explicitly provided, use it; else fallback to system_prompt or default
    effective_prompt = rewrite_prompt or getattr(request, "system_prompt", "") or None
    # If still no prompt, try fallback provider (vercel/deepseek) for default rewrite
    client = ai_client
    if not effective_prompt:
        # Use fallback client if configured, otherwise same client with default prompt
        try:
            fallback = ai_client.get_fallback_client()
            if fallback is not ai_client:
                task_logger.info(f"重写使用 fallback 模型: {fallback.model} ({fallback.base_url})")
                client = fallback
        except Exception:
            pass
    task_logger.info(f"原文 {len(original)} 字符，开始重写...")
    rewritten = await client.optimize_content(original, system_prompt=effective_prompt or "")
    # Update request in place (both content and text_content alias)
    try:
        request.content = rewritten
        # Also keep compatibility for any direct attribute access
        if hasattr(request, "text_content"):
            # text_content is property, cannot set; but content is source
            pass
    except Exception:
        # If frozen, set via object.__setattr__
        object.__setattr__(request, "content", rewritten)
    task_logger.info(f"重写完成 {len(rewritten)} 字符")
    task_logger.set_file("rewritten_content", Path(task_logger.task_dir) / "rewritten.txt")
    # Persist rewritten for debug
    try:
        (task_logger.task_dir / "rewritten.txt").write_text(rewritten, encoding="utf-8")
    except Exception:
        pass


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


async def _fetch_materials(script, request, task_logger: TaskLogger, segment_audios: list[dict] | None = None):
    """Fetch video/image materials per segment for timeline relevance (10s per theme)."""
    task_logger.step(4, "获取视频素材（按段主题）")
    
    gen_settings = await get_general_settings()
    material_fetcher = MaterialFetcher(
        pexels_api_key=gen_settings.get("pexels_api_key") or settings.pexels_api_key,
        pixabay_api_key=gen_settings.get("pixabay_api_key") or settings.pixabay_api_key,
        local_assets_dir=settings.assets_dir,
    )
    task_logger.info(f"Pexels API Key: {'已配置' if gen_settings.get('pexels_api_key') or settings.pexels_api_key else '未配置'}")
    
    # Orientation derived from resolution
    rw, rh = getattr(request, "resolution_width", 1920), getattr(request, "resolution_height", 1080)
    orientation = "landscape" if rw >= rh else "portrait" if rh > rw else "square"
    
    # Build segment-wise fetching — each segment's keywords map to its duration
    # Use actual TTS durations if available, else estimate
    materials_per_segment: list[list[Path]] = []
    flat_materials: list[Path] = []
    
    # Map segment index -> duration (from segment_audios if given)
    seg_durations: dict[int, float] = {}
    if segment_audios:
        for sa in segment_audios:
            seg_durations[sa["index"]] = sa["duration"]
    
    for idx, seg in enumerate(script.segments):
        seg_duration = seg_durations.get(idx, float(seg.duration_estimate))
        # Aim for one clip per ~10s, at least 1, at most 5 per segment
        count = max(1, min(5, round(seg_duration / 10)))
        if count < 1:
            count = 1
        task_logger.info(f"段落 {idx+1} 关键词: {', '.join(seg.keywords)} 时长≈{seg_duration:.1f}s 拉取 {count} 个")
        vids = await material_fetcher.fetch_videos(
            keywords=seg.keywords[:3],
            count=count,
            source=getattr(request, "background_source", "both"),
            orientation=orientation,
        )
        if not vids:
            vids = await material_fetcher.fetch_images(
                keywords=seg.keywords[:3],
                count=count,
                source=getattr(request, "background_source", "both"),
                orientation=orientation,
            )
        if not vids:
            # Fallback placeholder per segment
            try:
                from .cover_service import _create_gradient_background
                res = (request.resolution_width, request.resolution_height)
                placeholder = _create_gradient_background(res[0], res[1])
                p = settings.assets_dir / "images" / f"placeholder_seg{idx}.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    placeholder.save(p)
                vids = [p]
            except Exception as e:
                task_logger.warning(f"段 {idx} 占位图失败: {e}")
                vids = []
        materials_per_segment.append(vids)
        flat_materials.extend(vids)
    
    # Ensure total count cap 20 to avoid overload
    flat_materials = flat_materials[:20]
    
    task_logger.info(f"按段共获取 {len(flat_materials)} 个素材 ({len(materials_per_segment)} 段)")
    for i, seg_mats in enumerate(materials_per_segment):
        task_logger.info(f"  段 {i+1}: {len(seg_mats)} 个 — {[m.name for m in seg_mats[:2]]}")
    
    # Attach per-segment mapping to request for compose
    try:
        object.__setattr__(request, "_materials_per_segment", materials_per_segment)
        object.__setattr__(request, "_flat_materials", flat_materials)
    except Exception:
        request._materials_per_segment = materials_per_segment  # type: ignore
        request._flat_materials = flat_materials  # type: ignore
    
    return flat_materials


async def _generate_subtitles(segment_audios, total_duration, request, task_dir: Path, task_logger: TaskLogger):
    """Generate subtitles — respects generate_subtitle flag."""
    if not getattr(request, "generate_subtitle", True):
        task_logger.step(5, "跳过字幕生成")
        return []
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
        font_name=getattr(request, "subtitle_font", "Microsoft YaHei"),
        font_size=48,
        primary_color=getattr(request, "subtitle_color", "&H00FFFFFF"),
        outline_color="&H00000000",
    )
    task_logger.set_file("subtitles", subtitle_path)
    task_logger.info(f"生成 {len(subtitles)} 条字幕")
    
    return subtitles


async def _generate_cover(request, task_dir: Path, task_logger: TaskLogger):
    """Generate cover image — respects generate_cover flag."""
    if not getattr(request, "generate_cover", True):
        task_logger.step(6, "跳过封面生成")
        return None
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
    if cover_path:
        task_logger.set_file("cover", cover_path)
    
    return cover_path


async def _compose_final_video(
    request, task_dir: Path, task_logger: TaskLogger, materials, segment_audios, subtitles, total_duration
):
    """Compose final video — timeline-aware."""
    task_logger.step(7, "合成视频")
    
    bg_music_path = _resolve_bg_music_path(request, task_logger)
    
    # Retrieve per-segment materials if available
    materials_per_segment = getattr(request, "_materials_per_segment", None)
    fps = int(getattr(request, "fps", 30))
    
    video_path = await compose_video(
        task_dir=task_dir,
        task_logger=task_logger,
        materials=materials,
        segment_audios=segment_audios,
        subtitles=subtitles,
        bg_music_path=bg_music_path,
        duration=total_duration,
        resolution=(request.resolution_width, request.resolution_height),
        fps=fps,
        materials_per_segment=materials_per_segment,
    )
    
    return video_path


def _resolve_bg_music_path(request, task_logger: TaskLogger):
    """Resolve background music path — now with default fallback."""
    # Explicit request
    candidate = getattr(request, "background_music", None)
    if candidate:
        music_path = Path(candidate)
        if music_path.exists():
            task_logger.info(f"背景音乐: 使用 {music_path}")
            return music_path
        assets_music_path = settings.assets_dir / "music" / candidate
        if assets_music_path.exists():
            task_logger.info(f"背景音乐: 使用 {assets_music_path}")
            return assets_music_path
        # Try data/assets alias
        alt = Path("data/assets/music") / candidate
        if alt.exists():
            return alt
        task_logger.info(f"背景音乐: {candidate} 未找到，尝试默认")
    
    # Fallback 1: GeneralSetting default_background_music
    try:
        # get_general_settings is async, but we are sync — try sync heuristic: check DB file already loaded elsewhere
        # So we just scan filesystem for any music file
        pass
    except Exception:
        pass

    # Fallback 2: any file under settings.assets_dir/music or known web assets
    for base in [
        settings.assets_dir / "music",
        Path("data/assets/music"),
        Path("data/assets/background-music"),
        Path("apps/web/assets"),
        Path("../web/assets"),
        Path("/Users/huangyuan/Projects/video-factory/apps/web/assets"),
        Path("/Users/huangyuan/Projects/video-factory/apps/worker/data/assets/music"),
    ]:
        if base.exists():
            for pat in ("*.mp3", "*.wav", "*.m4a", "*.flac"):
                files = list(base.glob(pat))
                if files:
                    chosen = sorted(files)[0]
                    task_logger.info(f"背景音乐: 默认使用 {chosen}")
                    return chosen

    task_logger.info("背景音乐: 无可用文件，跳过")
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


async def _auto_publish_if_requested(request, video_path: Path, task_logger: TaskLogger, task_id: str):
    """Auto-publish to platforms if publish_to requested — folder-aware."""
    publish_to = getattr(request, "publish_to", None)
    if not publish_to:
        return
    # Normalize to list
    if isinstance(publish_to, str):
        publish_to = [p.strip() for p in publish_to.split(",") if p.strip()]
    if not isinstance(publish_to, (list, tuple)):
        return
    if not publish_to:
        return
    task_logger.step(8, "自动发布")
    task_logger.info(f"请求发布到: {', '.join(publish_to)}")
    # Lazy imports to avoid circular
    try:
        from ..database import async_session_maker
        from ..models import PublisherAccount
        from ..publishers import get_publisher
        from sqlalchemy import select
    except Exception as e:
        task_logger.warning(f"发布模块加载失败: {e}")
        return
    published = []
    for platform in publish_to:
        platform = platform.lower().strip()
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    select(PublisherAccount).where(PublisherAccount.platform == platform, PublisherAccount.enabled == True).limit(1)
                )
                acc = result.scalars().first()
                if not acc:
                    task_logger.warning(f"平台 {platform} 未配置账号，跳过")
                    continue
                # Resolve folder from request or account
                folder = getattr(request, "folder_id", None) or getattr(acc, "folder_id", None)
                cred = getattr(acc, "credentials", None) or getattr(acc, "cookies", None)
                pub = get_publisher(platform, credentials=cred, folder_id=folder, cookies=cred)
                title = getattr(request, "title", "Video")
                # Use same title as description fallback
                res = await pub.upload(
                    video_path=video_path,
                    title=title,
                    description=getattr(request, "content", "")[:200],
                    tags=[],
                    folder_id=folder,
                    playlist_id=folder,
                    privacy=getattr(request, "publish_privacy", None) or "private",
                )
                if res.success:
                    task_logger.info(f"发布到 {platform} 成功: {res.post_url or res.post_id}")
                    published.append({"platform": platform, "post_url": res.post_url, "post_id": res.post_id})
                else:
                    task_logger.warning(f"发布到 {platform} 失败: {res.error}")
                    published.append({"platform": platform, "error": res.error})
        except Exception as e:
            task_logger.warning(f"发布到 {platform} 异常: {e}")
            published.append({"platform": platform, "error": str(e)})
    # Update task
    video_tasks[task_id]["published_to"] = published
    video_tasks[task_id]["message"] = f"视频生成完成，已发布到 {len([p for p in published if 'post_url' in p or 'post_id' in p])} 个平台" if published else video_tasks[task_id]["message"]


def _handle_error(task_id: str, task_logger: TaskLogger, error: Exception):
    """Handle task error."""
    logger.error(f"Video generation failed for task {task_id}: {error}", exc_info=True)
    task_logger.fail(str(error))
    
    video_tasks[task_id]["status"] = "failed"
    video_tasks[task_id]["message"] = str(error)
    video_tasks[task_id]["error"] = str(error)
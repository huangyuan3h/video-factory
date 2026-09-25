"""Video generation service."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..core.ai_client import AIClient
from ..core.subtitle_gen import SubtitleGenerator
from ..core.task_logger import TaskLogger
from ..core.tts.voices import normalize_language, resolve_voice
from ..core.tts_engine import EdgeTTSEngine
from .book_script import (
    BOOK_DENSE_REWRITE_PROMPT,
    BOOK_DENSE_SCRIPT_PROMPT,
    book_char_range,
    book_segment_range,
)
from .compose_service import compose_video
from .cover_service import generate_cover_image
from .material import (
    MaterialFetcher,
    book_fallback_keywords,
    build_book_segment_query,
    chapter_anchor_terms,
    derive_book_search_terms,
    derive_search_terms,
    normalize_sources,
    to_visual_search_terms,
)
from .settings_service import get_active_ai_client, get_general_settings
from .translation_service import generate_youtube_metadata, translate_script

logger = logging.getLogger(__name__)

video_tasks: dict[str, dict] = {}

# Backward-compatible default: the high end of the configured friendly rewrite
# char range (default 800-1000 -> 1000). The live threshold is re-derived from
# config per call via ``book_char_range`` so pacing changes are honoured.
_BOOK_REWRITE_MAX_CHARS = book_char_range()[1]


class GenerationCancelled(Exception):
    """Raised when a cancel flag is detected at a step boundary."""


def _ensure_not_cancelled(task_logger: TaskLogger):
    if task_logger.is_cancel_requested():
        raise GenerationCancelled("任务已取消")


def _is_news_request(request) -> bool:
    return str(getattr(request, "content_type", "") or "").strip().lower() == "news"


def _is_book_request(request) -> bool:
    return str(getattr(request, "content_type", "") or "").strip().lower() == "book"


def _request_language(request) -> str:
    """Normalized spoken language for a request (defaults to Chinese)."""
    language = getattr(request, "language", None) or getattr(request, "lang", None)
    return normalize_language(language)


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
            _ensure_not_cancelled(task_logger)

            # News pipeline: fetch GNews articles + images, fill title/content
            # before the script step. Leaves the general path untouched.
            if _is_news_request(request):
                await _prepare_news(request, task_dir, task_logger)
                _ensure_not_cancelled(task_logger)

            ai_client = await _get_ai_client(task_logger)
            # LLM rewrite if requested
            await _maybe_rewrite_content(ai_client, request, task_logger)
            _ensure_not_cancelled(task_logger)
            script = await _generate_script(ai_client, request, task_logger)
            _ensure_not_cancelled(task_logger)
            script = await _localize_script(ai_client, request, script, task_logger)
            _ensure_not_cancelled(task_logger)
            segment_audios, total_duration = await _synthesize_audio(
                script, request, task_dir, task_logger
            )
            _ensure_not_cancelled(task_logger)
            materials = await _fetch_materials(script, request, task_logger, segment_audios)
            _ensure_not_cancelled(task_logger)
            subtitles = await _generate_subtitles(segment_audios, total_duration, request, task_dir, task_logger)
            _ensure_not_cancelled(task_logger)
            cover_path = await _generate_cover(request, task_dir, task_logger)
            _ensure_not_cancelled(task_logger)
            video_path = await _compose_final_video(
                request, task_dir, task_logger, materials, segment_audios, subtitles, total_duration, cover_path
            )
            _ensure_not_cancelled(task_logger)
            
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
    series_id = getattr(request, "series_id", None)
    if series_id:
        task_logger.set_meta("series_id", series_id)
    content_type = getattr(request, "content_type", None)
    if content_type:
        # Persist the pipeline type so task status/enrichment can surface it.
        task_logger.set_meta("content_type", content_type)
        if str(content_type).strip().lower() == "book":
            task_logger.set_meta("type", "book")
            # Book episodes always run the dense key-point path (see
            # book_script.BOOK_DENSE_*): record it on the task status.
            task_logger.set_meta("book_dense", True)
            task_logger.info("书籍要点压缩模式（book dense）已启用")
    task_logger.info(f"标题: {request.title}")
    # Spoken language drives the TTS voice: an ``en`` request must not be read by
    # a Chinese neural voice (and vice versa). Persist it so publish can read it.
    language = _request_language(request)
    resolved_voice = resolve_voice(language, getattr(request, "voice", None))
    try:
        object.__setattr__(request, "voice", resolved_voice)
    except Exception:
        request.voice = resolved_voice  # type: ignore[attr-defined]
    task_logger.set_meta("language", language)
    task_logger.set_meta("voice", resolved_voice)
    task_logger.info(f"语言: {language} | 语音: {resolved_voice}")
    task_logger.info(f"分辨率: {request.resolution_width}x{request.resolution_height}")


async def _prepare_news(request, task_dir: Path, task_logger: TaskLogger) -> dict:
    """Fetch GNews articles + article images and seed title/content.

    Never falls back to synthetic generation — only article images, then online
    stock imagery if downloads failed.
    """
    from .news_service import resolve_news_content

    task_logger.step(1, "获取新闻文章与配图（GNews）")
    meta = await resolve_news_content(request, task_dir, task_logger)
    task_logger.info(
        f"新闻来源: {meta.get('source_name')} | 文章数: {len(meta.get('articles', []))} "
        f"| 配图数: {meta.get('image_count', 0)}"
    )
    return meta


async def _get_ai_client(task_logger: TaskLogger) -> AIClient:
    """Get AI client and validate configuration."""
    ai_client = await get_active_ai_client()
    if not ai_client:
        raise ValueError("未配置 AI 设置，请先在设置页面配置 AI 参数")
    
    task_logger.info(f"使用 AI 模型: {ai_client.model}")
    return ai_client


async def _maybe_rewrite_content(ai_client: AIClient, request, task_logger: TaskLogger):
    """Handle LLM rewrite if requested — respects boolean and prompt provision.

    Book episodes (``type=book``) always take the dense "要点压缩" path, even
    when the caller did not set ``rewrite_content`` and the episode text is
    already short/outline-like.
    """
    is_book = _is_book_request(request)
    should_rewrite = is_book or bool(
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
    if is_book:
        # Forced gentle compression; an explicit user prompt still wins.
        effective_prompt = rewrite_prompt or BOOK_DENSE_REWRITE_PROMPT
        user_prompt = f"请用温和、像和朋友聊天的口吻，把《{request.title}》这一章讲清楚：\n\n{original}"
        task_logger.info("书籍讲书重写（book friendly rewrite）")
        task_logger.set_meta("book_dense", True)
    else:
        effective_prompt = rewrite_prompt or getattr(request, "system_prompt", "") or None
        user_prompt = None
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
    # For book rewrites the token budget must scale with the chapter target:
    # a reasoning model otherwise returns an empty reply and the rewrite
    # silently no-ops (returning the original 3000+ char chapter).
    low_chars, max_chars = book_char_range()
    optimize_kwargs: dict = {}
    if is_book:
        optimize_kwargs["target_length"] = max_chars
    task_logger.info(f"原文 {len(original)} 字符，开始重写...")
    rewritten = await client.optimize_content(
        original,
        system_prompt=effective_prompt or "",
        user_prompt=user_prompt,
        **optimize_kwargs,
    )
    # Book models can silently no-op (returning the input verbatim). If the
    # result is still well above the configured 讲书 char range, force one
    # stronger compression pass rather than feeding a padded chapter to the
    # script step. Threshold derived from config (range high * 1.2).
    threshold = max_chars * 1.2
    if is_book and len((rewritten or "").strip()) > threshold:
        task_logger.info(
            f"重写后仍 {len(rewritten)} 字符（目标 {low_chars}-{max_chars}），进行第二次强制压缩..."
        )
        strict_prompt = (
            f"{BOOK_DENSE_REWRITE_PROMPT}\n"
            f"重要：必须把全文压缩到 {low_chars}-{max_chars} 字，当前 {len(rewritten)} 字，超出即不合格，"
            "同时保持温和、像和朋友聊天的口吻。"
        )
        compressed = await client.optimize_content(
            rewritten,
            system_prompt=strict_prompt,
            user_prompt=(
                f"请务必把以下内容压到 {low_chars}-{max_chars} 字，保留温和的口吻和口语化短句，"
                f"不要保留原文结构：\n\n{rewritten}"
            ),
            **optimize_kwargs,
        )
        if compressed and len(compressed.strip()) < len(rewritten.strip()):
            rewritten = compressed
            task_logger.info(f"二次压缩完成 {len(rewritten)} 字符")
        else:
            task_logger.warning("二次压缩未缩短内容，保留首次重写结果")
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


def _script_char_count(script) -> int:
    """Total visible characters across a generated script's segments."""
    return sum(len((getattr(seg, "text", "") or "")) for seg in script.segments)


def _script_range_distance(total: int, low: int, high: int) -> int:
    """Distance of ``total`` from the ``[low, high]`` target (0 when inside)."""
    if total < low:
        return low - total
    if total > high:
        return total - high
    return 0


async def _guard_book_script_length(
    ai_client: AIClient, request, script, system_prompt: str, task_logger: TaskLogger
):
    """Regenerate an over-long book script once and keep the closer result.

    The sample script came out 1203 chars vs the 800-1000 target, stretching the
    episode past 240 s. When the total exceeds ``high * 1.15`` ask for a shorter
    version with the segment count spelled out, then keep whichever script is
    nearer the target range (the original on a tie or when the retry is empty).
    """
    low, high = book_char_range()
    seg_low, seg_high = book_segment_range()
    total = _script_char_count(script)
    count = len(script.segments)
    if total <= high * 1.15:
        return script

    task_logger.info(
        f"书籍脚本 {total} 字 / {count} 段超过目标 {low}-{high} 字，尝试精简一次..."
    )
    directive = (
        f"重要：上一版共 {total} 字、{count} 段，没在目标范围内。"
        f"请调整到 {low}-{high} 字（不要少于 {low} 字，也不要超过 {high} 字）、"
        f"{seg_low}-{seg_high} 段，每段只讲一个意思，保持温和的口吻。"
    )
    try:
        shortened = await ai_client.generate_script(
            content=request.text_content,
            title=request.title,
            system_prompt=f"{system_prompt}\n{directive}",
        )
    except Exception as e:  # noqa: BLE001 - keep the original script on failure
        task_logger.warning(f"精简脚本生成失败，保留原脚本: {e}")
        return script

    new_total = _script_char_count(shortened)
    task_logger.info(
        f"精简后脚本 {new_total} 字 / {len(shortened.segments)} 段"
        f"（原 {total} 字 / {count} 段）"
    )
    if not shortened.segments:
        return script
    if _script_range_distance(new_total, low, high) < _script_range_distance(
        total, low, high
    ):
        return shortened
    return script


async def _generate_script(ai_client: AIClient, request, task_logger: TaskLogger):
    """Generate script using AI — gentle 讲书 mode for book episodes."""
    task_logger.step(2, "调用 AI 生成脚本")

    is_book = _is_book_request(request)
    system_prompt = request.system_prompt or ""
    if is_book:
        # Keep an explicit user prompt, otherwise use the friendly book prompt.
        system_prompt = system_prompt or BOOK_DENSE_SCRIPT_PROMPT
        task_logger.info("书籍讲书脚本模式（book friendly script）")
        task_logger.set_meta("book_dense", True)

    script = await ai_client.generate_script(
        content=request.text_content,
        title=request.title,
        system_prompt=system_prompt,
    )

    # Empty segments make TTS produce zero clips and later crash ``max()`` in
    # compose. Retry once, then fail fast with a clear message so the pipeline
    # never reaches TTS/compose.
    if not script.segments:
        task_logger.warning("AI 未生成任何段落（segments=[]），重试脚本生成一次...")
        script = await ai_client.generate_script(
            content=request.text_content,
            title=request.title,
            system_prompt=system_prompt,
        )

    if not script.segments:
        task_logger.save_script(script.model_dump())
        raise ValueError(
            "AI 脚本生成失败：两次生成均返回 0 个段落（segments=[]），"
            "请检查 AI 模型配置或输入内容后重试"
        )

    if is_book:
        script = await _guard_book_script_length(
            ai_client, request, script, system_prompt, task_logger
        )

    task_logger.save_script(script.model_dump())
    task_logger.info(f"生成 {len(script.segments)} 个段落")
    
    for i, seg in enumerate(script.segments):
        task_logger.info(f"段落 {i+1}: {seg.text[:50]}... (关键词: {', '.join(seg.keywords)})")
    
    return script


async def _localize_script(ai_client: AIClient, request, script, task_logger: TaskLogger):
    """Localize the Chinese master script for ``language=en`` (YouTube growth).

    Keeps the master Chinese script intact for Bilibili; only the spoken/video
    language changes. Structure (segment count/order) is preserved so the visual
    timeline and durations do not shift.
    """
    language = _request_language(request)
    if language == "zh":
        return script

    task_logger.step(2, f"本地化脚本为 {language}（翻译）")
    localized = await translate_script(
        ai_client,
        script,
        target_lang=language,
        source_lang="zh",
        task_logger=task_logger,
    )
    task_logger.save_script(localized.model_dump())

    # English hook title / description / tags for YouTube discoverability.
    if language == "en":
        try:
            meta = await generate_youtube_metadata(
                ai_client,
                title=getattr(request, "title", "") or "",
                script=localized,
                target_lang="en",
                task_logger=task_logger,
            )
            task_logger.set_meta("youtube_title", meta["title"])
            task_logger.set_meta("youtube_description", meta["description"])
            task_logger.set_meta("youtube_tags", meta["tags"])
        except Exception as e:  # noqa: BLE001 - packaging must not break the video
            task_logger.warning(f"YouTube 元数据生成失败，回退到脚本标题: {e}")
            task_logger.set_meta("youtube_title", localized.title)

    return localized


async def _synthesize_audio(script, request, task_dir: Path, task_logger: TaskLogger):
    """Synthesize audio for each segment.

    Book episodes narrate more slowly (``settings.book_tts_rate``) and leave a
    short pause between segments to keep the pacing calm. An explicit
    non-default ``voice_rate`` on the request still wins.
    """
    task_logger.step(3, "合成语音")

    is_book = _is_book_request(request)
    voice = resolve_voice(_request_language(request), getattr(request, "voice", None))
    default_rate = getattr(settings, "tts_rate", "+0%") or "+0%"
    request_rate = getattr(request, "voice_rate", None)
    if is_book and (not request_rate or str(request_rate) == default_rate):
        rate = getattr(settings, "book_tts_rate", "+0%") or default_rate
        task_logger.info(f"书籍语速: {rate}（默认 {default_rate}）")
    else:
        rate = request_rate if request_rate is not None else default_rate
    tts = EdgeTTSEngine(voice=voice, rate=rate)
    segment_audios = []
    total_segments = len(script.segments)
    running_offset = 0.0
    pause_after = float(getattr(settings, "book_segment_pause_seconds", 0.0) or 0.0) if is_book else 0.0

    for i, segment in enumerate(script.segments):
        _ensure_not_cancelled(task_logger)
        audio_path = task_dir / f"segment_{i}.mp3"
        task_logger.info(f"合成段落 {i+1}/{total_segments}")

        boundaries: list[dict] = []
        try:
            # Real provider captures per-sentence boundaries; a plain/mock TTS
            # that lacks the keyword is retried without it.
            await tts.synthesize(
                text=segment.text,
                output_path=audio_path,
                voice=voice,
                boundaries=boundaries,
            )
        except TypeError:
            boundaries = []
            await tts.synthesize(
                text=segment.text,
                output_path=audio_path,
                voice=voice,
            )
        duration = await tts.get_duration(audio_path)

        # The last segment carries no trailing pause so the video does not end
        # on silence; ``duration`` stays the speech duration (subtitles must not
        # extend into the pause).
        seg_pause = pause_after if i < total_segments - 1 else 0.0
        segment_audios.append({
            "index": i,
            "text": segment.text,
            "audio_path": audio_path,
            "duration": duration,
            "offset": running_offset,
            "pause_after": seg_pause,
            "boundaries": boundaries,
        })
        running_offset += duration + seg_pause
        task_logger.set_file(f"audio_{i}", audio_path)
        
        progress = 0.2 + (i / total_segments) * 0.2
        task_logger.set_progress(progress)
    
    total_duration = sum(sa["duration"] + sa.get("pause_after", 0.0) for sa in segment_audios)
    task_logger.info(f"总音频时长: {total_duration:.1f} 秒")
    
    return segment_audios, total_duration


async def _fetch_materials(script, request, task_logger: TaskLogger, segment_audios: list[dict] | None = None):
    """Fetch video/image materials per segment for timeline relevance (10s per theme)."""
    if _is_news_request(request):
        return await _fetch_news_materials(script, request, task_logger, segment_audios)
    if _is_book_request(request):
        return await _fetch_book_materials(script, request, task_logger, segment_audios)

    task_logger.step(4, "获取视频素材（按段主题）")
    
    gen_settings = await get_general_settings()
    material_fetcher = MaterialFetcher(
        pexels_api_key=gen_settings.get("pexels_api_key") or settings.pexels_api_key,
        pixabay_api_key=gen_settings.get("pixabay_api_key") or settings.pixabay_api_key,
        local_assets_dir=settings.assets_dir,
    )
    task_logger.info(f"Pexels API Key: {'已配置' if gen_settings.get('pexels_api_key') or settings.pexels_api_key else '未配置'}")
    background_source = getattr(request, "background_source", "both")
    task_logger.info(f"素材来源 background_source={background_source} -> {sorted(normalize_sources(background_source))}")
    
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
        seg_keywords = seg.keywords[:3]
        task_logger.info(
            f"段落 {idx+1} 关键词: {', '.join(seg.keywords)} 时长≈{seg_duration:.1f}s 拉取 {count} 个"
            f" | 英文检索词: {derive_search_terms(seg_keywords)}"
        )
        vids = await material_fetcher.fetch_videos(
            keywords=seg_keywords,
            count=count,
            source=background_source,
            orientation=orientation,
        )
        if not vids:
            vids = await material_fetcher.fetch_images(
                keywords=seg_keywords,
                count=count,
                source=background_source,
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


async def _fetch_book_materials(script, request, task_logger: TaskLogger, segment_audios: list[dict] | None = None):
    """Book path materials: chapter-relevant stock, high-quality videos first.

    Search terms are derived from the chapter title plus the segment keywords
    (see ``derive_book_search_terms``); when nothing translates the fetcher uses
    book-specific fallbacks instead of the global finance/news
    ``FALLBACK_KEYWORDS``. Videos are tried first, with still images as a
    fallback. Synthetic/ComfyUI is never used.
    """
    task_logger.step(4, "获取图书素材（章节相关视频优先，图片兜底）")

    gen_settings = await get_general_settings()
    fetcher = MaterialFetcher(
        pexels_api_key=gen_settings.get("pexels_api_key") or settings.pexels_api_key,
        pixabay_api_key=gen_settings.get("pixabay_api_key") or settings.pixabay_api_key,
        local_assets_dir=settings.assets_dir,
        book_mode=True,
        book_title=getattr(request, "title", "") or "",
    )
    task_logger.info(
        f"Pexels API Key: {'已配置' if gen_settings.get('pexels_api_key') or settings.pexels_api_key else '未配置'}"
    )

    background_source = getattr(request, "background_source", "online")
    sources = normalize_sources(background_source)
    unsupported = sources - {"online", "local"}
    real = sources & {"online", "local"}
    if unsupported:
        task_logger.warning(f"书籍类型仅使用在线/本地素材，忽略来源 {sorted(unsupported)}")
    background_source = ",".join(sorted(real)) if real else "online"
    task_logger.info(
        f"书籍素材来源 background_source={background_source} -> {sorted(normalize_sources(background_source))}"
    )

    rw, rh = getattr(request, "resolution_width", 1920), getattr(request, "resolution_height", 1080)
    orientation = "portrait" if rh > rw else "landscape"

    seg_durations: dict[int, float] = {}
    seg_pauses: dict[int, float] = {}
    if segment_audios:
        for sa in segment_audios:
            seg_durations[sa["index"]] = sa["duration"]
            seg_pauses[sa["index"]] = float(sa.get("pause_after", 0.0) or 0.0)

    materials_per_segment: list[list[Path]] = []
    flat_materials: list[Path] = []
    # Chapter anchor: derived once and prepended to every segment query so the
    # stills stay on one coherent theme instead of drifting segment to segment.
    chapter_title = getattr(request, "title", "") or ""
    anchor = chapter_anchor_terms(chapter_title)
    if anchor:
        task_logger.info(f"章节锚点检索词（全片稳定）: {anchor}")

    hold = float(getattr(settings, "book_image_hold_seconds", 4.0) or 4.0)
    if hold <= 0:
        hold = 4.0

    # Safety net on top of the fetcher's own seen sets: guarantees no still is
    # reused across the whole episode even if a source returns duplicates.
    seen_media: set[str] = set()

    def _take_unique(paths: list[Path]) -> list[Path]:
        unique: list[Path] = []
        for path in paths:
            key = Path(path).stem
            if key in seen_media:
                task_logger.info(f"跳过重复素材: {key}")
                continue
            seen_media.add(key)
            unique.append(path)
        return unique

    for idx, seg in enumerate(script.segments):
        seg_duration = seg_durations.get(idx, float(seg.duration_estimate))
        # Count stills for the full on-screen span (speech + trailing pause) so
        # the picture keeps covering the pause without a black gap.
        seg_span = float(seg_duration) + float(seg_pauses.get(idx, 0.0))
        count = max(1, min(25, round(seg_span / hold)))
        seg_keywords = list(seg.keywords[:3])
        query = build_book_segment_query(chapter_title, seg_keywords, anchor=anchor)
        if not query:
            query = book_fallback_keywords(chapter_title, seg_keywords)
        task_logger.info(
            f"段落 {idx+1} 关键词: {', '.join(seg.keywords)} 时长≈{seg_duration:.1f}s 拉取 {count} 个视频"
            f" | 英文检索词: {query}"
        )
        media = _take_unique(
            await fetcher.fetch_videos(
                keywords=query,
                count=count,
                source=background_source,
                orientation=orientation,
            )
        )
        if not media:
            task_logger.info("未获取到视频，回退到章节图片")
            media = _take_unique(
                await fetcher.fetch_book_images(
                    query=query,
                    count=count,
                    source=background_source,
                    orientation=orientation,
                )
            )
        if not media:
            media = _placeholder_for_segment(idx, request, task_logger)
        materials_per_segment.append(media)
        flat_materials.extend(media)

    flat_materials = flat_materials[:120]
    task_logger.info(f"图书素材共 {len(flat_materials)} 个 ({len(materials_per_segment)} 段)")
    _attach_news_materials(request, materials_per_segment, flat_materials)
    return flat_materials


async def _fetch_news_materials(script, request, task_logger: TaskLogger, segment_audios: list[dict] | None = None):
    """News path materials: article images, then online stock. Never synthetic."""
    task_logger.step(4, "使用新闻配图作为素材")

    images = list(getattr(request, "_news_images", None) or [])
    n_segments = len(script.segments)
    materials_per_segment: list[list[Path]] = [[] for _ in range(max(1, n_segments))]

    if images and n_segments:
        # Spread all images across segments (round-robin). When there are fewer
        # images than segments, images repeat rather than leaving blank segments.
        for i, img in enumerate(images):
            materials_per_segment[i % n_segments].append(img)
        task_logger.info(f"使用 {len(images)} 张新闻配图分配到 {n_segments} 段")
    else:
        task_logger.info("无新闻配图，回退到在线图库（Pexels/online），不使用合成")
        flat, materials_per_segment = await _fetch_news_fallback_images(
            script, request, task_logger, segment_audios
        )
        _attach_news_materials(request, materials_per_segment, flat)
        return flat[:20]

    flat = [m for seg in materials_per_segment for m in seg]
    _attach_news_materials(request, materials_per_segment, flat)
    return flat[:20]


async def _fetch_news_fallback_images(script, request, task_logger: TaskLogger, segment_audios):
    """Online-only stock fallback for the news path (synthetic explicitly excluded)."""
    gen_settings = await get_general_settings()
    fetcher = MaterialFetcher(
        pexels_api_key=gen_settings.get("pexels_api_key") or settings.pexels_api_key,
        pixabay_api_key=gen_settings.get("pixabay_api_key") or settings.pixabay_api_key,
        local_assets_dir=settings.assets_dir,
    )
    rw, rh = getattr(request, "resolution_width", 1920), getattr(request, "resolution_height", 1080)
    orientation = "landscape" if rw >= rh else "portrait" if rh > rw else "square"

    seg_durations: dict[int, float] = {}
    if segment_audios:
        for sa in segment_audios:
            seg_durations[sa["index"]] = sa["duration"]

    materials_per_segment: list[list[Path]] = []
    for idx, seg in enumerate(script.segments):
        seg_duration = seg_durations.get(idx, float(seg.duration_estimate))
        count = max(1, min(3, round(seg_duration / 10)))
        # source="online" maps to Pexels/Pixabay only — no synthetic opt-in here.
        imgs = await fetcher.fetch_images(
            keywords=seg.keywords[:3],
            count=count,
            source="online",
            orientation=orientation,
        )
        if not imgs:
            imgs = _placeholder_for_segment(idx, request, task_logger)
        materials_per_segment.append(imgs)

    flat = [m for seg in materials_per_segment for m in seg]
    task_logger.info(f"在线图库回退获取 {len(flat)} 个素材")
    return flat, materials_per_segment


def _placeholder_for_segment(idx: int, request, task_logger: TaskLogger) -> list[Path]:
    """Last-resort gradient placeholder (no synthetic generation)."""
    try:
        from .cover_service import _create_gradient_background

        res = (request.resolution_width, request.resolution_height)
        placeholder = _create_gradient_background(res[0], res[1])
        p = settings.assets_dir / "images" / f"placeholder_seg{idx}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            placeholder.save(p)
        return [p]
    except Exception as e:
        task_logger.warning(f"段 {idx} 占位图失败: {e}")
        return []


def _attach_news_materials(request, materials_per_segment, flat_materials) -> None:
    try:
        object.__setattr__(request, "_materials_per_segment", materials_per_segment)
        object.__setattr__(request, "_flat_materials", flat_materials)
    except Exception:
        request._materials_per_segment = materials_per_segment  # type: ignore
        request._flat_materials = flat_materials  # type: ignore


async def _generate_subtitles(segment_audios, total_duration, request, task_dir: Path, task_logger: TaskLogger):
    """Generate subtitles — respects generate_subtitle flag."""
    if not getattr(request, "generate_subtitle", True):
        task_logger.step(5, "跳过字幕生成")
        return []
    task_logger.step(5, "生成字幕")

    # Landscape frames are wider, so a line can hold more characters; portrait
    # and square use the narrower value. Fall back to landscape when the request
    # carries no explicit dimensions.
    rw = getattr(request, "resolution_width", None)
    rh = getattr(request, "resolution_height", None)
    if rw is None or rh is None:
        resolved = getattr(request, "resolved_resolution", None)
        if callable(resolved):
            try:
                rw, rh = resolved()
            except Exception:
                rw, rh = 1920, 1080
        else:
            rw, rh = 1920, 1080
    rw = rw or 1920
    rh = rh or 1080
    if rw > rh:
        max_chars = settings.subtitle_max_chars_landscape
    else:
        max_chars = settings.subtitle_max_chars_portrait

    subtitle_gen = SubtitleGenerator(max_chars_per_line=max_chars)
    subtitles = subtitle_gen.generate_for_segments(segment_audios)

    if subtitles:
        last_end = max(sub.end_time for sub in subtitles)
        task_logger.info(
            f"字幕结束: {last_end:.1f}s / 音频时长: {total_duration:.1f}s"
        )
    
    subtitle_path = task_dir / "subtitles.ass"
    # Subtitle text follows the spoken language (English segments -> English
    # subtitles). The Latin default font renders the CJK default poorly, so swap
    # in a neutral sans font unless the caller picked one explicitly.
    font_name = getattr(request, "subtitle_font", "Microsoft YaHei")
    if _request_language(request) == "en" and font_name in (None, "", "Microsoft YaHei"):
        font_name = "Arial"
    await subtitle_gen.save_ass(
        subtitles,
        subtitle_path,
        font_name=font_name,
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

    # Book covers should reflect the chapter theme, not the generic "abstract"
    # fallback. Derive chapter-title keywords (and book fallbacks when the title
    # yields no domain tokens) so the cover is not an abstract placeholder.
    keywords: list[str] = []
    if _is_book_request(request):
        keywords = derive_book_search_terms([], request.title) or book_fallback_keywords(
            request.title, []
        )
        # Cover uses the same visual-safe language as the episode stills.
        keywords = to_visual_search_terms(keywords)
        task_logger.info(f"封面检索关键词: {keywords}")
    
    # English episodes use the localized hook title so the first frame / thumbnail
    # is readable for a global audience; Chinese keeps the master chapter title.
    cover_title = request.title
    if _request_language(request) == "en" and task_logger.status.get("youtube_title"):
        cover_title = str(task_logger.status["youtube_title"])

    cover_path = await generate_cover_image(
        task_dir=task_dir,
        task_logger=task_logger,
        title=cover_title,
        keywords=keywords,
        pexels_api_key=gen_settings.get("pexels_api_key"),
        resolution=(request.resolution_width, request.resolution_height),
    )
    if cover_path:
        task_logger.set_file("cover", cover_path)
    
    return cover_path


async def _compose_final_video(
    request, task_dir: Path, task_logger: TaskLogger, materials, segment_audios, subtitles, total_duration,
    cover_path: Path | None = None,
):
    """Compose final video — timeline-aware, cover-first when available."""
    task_logger.step(7, "合成视频")
    
    bg_music_path = _resolve_bg_music_path(request, task_logger)
    
    # Retrieve per-segment materials if available
    materials_per_segment = getattr(request, "_materials_per_segment", None)
    fps = int(getattr(request, "fps", 30))
    cover_hold = float(getattr(settings, "book_cover_hold_seconds", 3.0) or 3.0)
    transition = float(getattr(settings, "book_slide_transition_seconds", 0.5) or 0.0)
    
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
        cover_path=cover_path,
        cover_hold_seconds=cover_hold,
        transition_seconds=transition,
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


def _resolve_publish_metadata(platform: str, language: str, request, task_logger: TaskLogger):
    """Title/description/tags for a publish, using the localized YouTube pack.

    For ``en`` YouTube publishes the worker generated a hook title, a
    keyword-rich description and tags during generation; reuse them instead of
    leaking the raw Chinese chapter title/content.
    """
    title = getattr(request, "title", "Video") or "Video"
    description = getattr(request, "content", "")[:200]
    tags: list[str] = []
    if platform in ("youtube", "yt") and language != "zh":
        status = getattr(task_logger, "status", {}) or {}
        title = status.get("youtube_title") or title
        description = status.get("youtube_description") or description
        tags = list(status.get("youtube_tags") or [])
    return title, description, tags


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
        from sqlalchemy import select

        from ..database import async_session_maker
        from ..models import PublisherAccount
        from ..publishers import get_publisher
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
                language = _request_language(request)
                title, description, tags = _resolve_publish_metadata(
                    platform, language, request, task_logger
                )
                privacy = getattr(request, "publish_privacy", None) or (
                    settings.youtube_default_privacy if platform in ("youtube", "yt") else "private"
                )
                res = await pub.upload(
                    video_path=video_path,
                    title=title,
                    description=description,
                    tags=tags,
                    folder_id=folder,
                    playlist_id=folder,
                    privacy=privacy,
                    default_language=language,
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
    if isinstance(error, GenerationCancelled):
        logger.info(f"Video generation cancelled for task {task_id}")
        task_logger.cancelled(str(error))
        video_tasks[task_id]["status"] = "cancelled"
        video_tasks[task_id]["message"] = "任务已取消"
        return
    logger.error(f"Video generation failed for task {task_id}: {error}", exc_info=True)
    task_logger.fail(str(error))
    
    video_tasks[task_id]["status"] = "failed"
    video_tasks[task_id]["message"] = str(error)
    video_tasks[task_id]["error"] = str(error)
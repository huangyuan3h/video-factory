"""Video generation routes."""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..core.ai_client import AIClient, GeneratedScript
from ..core.task_logger import TaskLogger
from ..core.tts_engine import EdgeTTSEngine
from ..core.material_fetcher import MaterialFetcher
from ..core.subtitle_gen import SubtitleGenerator
from ..database import async_session_maker
from ..models import AISetting

logger = logging.getLogger(__name__)

router = APIRouter()

video_tasks: dict[str, dict] = {}


class VideoGenerateRequest(BaseModel):
    """Request model for video generation."""

    title: str
    system_prompt: str = ""
    text_content: str
    background_music: str | None = None
    generate_subtitle: bool = True
    subtitle_color: str = "&H00FFFFFF"
    subtitle_font: str = "Microsoft YaHei"
    voice: str = "zh-CN-XiaoxiaoNeural"
    voice_rate: str = "+0%"
    background_source: str = "both"
    resolution_width: int = 1080
    resolution_height: int = 1920


async def get_active_ai_client() -> AIClient | None:
    """Get AI client from active database settings."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(AISetting).where(AISetting.is_active == True)
        )
        ai_setting = result.scalar_one_or_none()
        
        if ai_setting:
            return AIClient(
                base_url=ai_setting.base_url,
                api_key=ai_setting.api_key,
                model=ai_setting.model_id,
            )
        return None


async def get_general_settings() -> dict:
    """Get general settings from database."""
    from ..models import GeneralSetting
    async with async_session_maker() as session:
        result = await session.execute(select(GeneralSetting))
        setting = result.scalar_one_or_none()
        if setting:
            return {
                "pexels_api_key": setting.pexels_api_key,
                "pixabay_api_key": setting.pixabay_api_key,
            }
        return {}


def run_video_generation(
    task_id: str,
    request: VideoGenerateRequest,
    task_dir: Path,
):
    """Run video generation in background."""

    async def _generate():
        task_logger = TaskLogger(task_id, task_dir)
        
        try:
            video_tasks[task_id]["task_dir"] = str(task_dir)
            video_tasks[task_id]["log_file"] = str(task_dir / "task.log")
            
            task_logger.step(1, "初始化任务配置")
            task_logger.info(f"标题: {request.title}")
            task_logger.info(f"语音: {request.voice}")
            task_logger.info(f"分辨率: {request.resolution_width}x{request.resolution_height}")

            ai_client = await get_active_ai_client()
            if not ai_client:
                raise ValueError("未配置 AI 设置，请先在设置页面配置 AI 参数")
            
            task_logger.info(f"使用 AI 模型: {ai_client.model}")

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

            task_logger.step(6, "合成视频")
            bg_music_path = None
            if request.background_music:
                music_path = Path(request.background_music)
                if music_path.exists():
                    bg_music_path = music_path
                elif (settings.assets_dir / "music" / request.background_music).exists():
                    bg_music_path = settings.assets_dir / "music" / request.background_music
                task_logger.info(f"背景音乐: {bg_music_path}")

            video_path = await _compose_video(
                task_dir=task_dir,
                task_logger=task_logger,
                materials=materials,
                segment_audios=segment_audios,
                subtitle_path=subtitle_path,
                bg_music_path=bg_music_path,
                duration=total_duration,
                resolution=(request.resolution_width, request.resolution_height),
                fps=30,
            )

            task_logger.step(7, "完成")
            task_logger.complete(video_path)
            
            video_tasks[task_id]["status"] = "completed"
            video_tasks[task_id]["progress"] = 1.0
            video_tasks[task_id]["message"] = "视频生成完成"
            video_tasks[task_id]["video_path"] = str(video_path)
            video_tasks[task_id]["completed_at"] = datetime.now().isoformat()

        except Exception as e:
            logger.error(f"Video generation failed for task {task_id}: {e}", exc_info=True)
            task_logger.fail(str(e))
            video_tasks[task_id]["status"] = "failed"
            video_tasks[task_id]["message"] = str(e)
            video_tasks[task_id]["error"] = str(e)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_generate())
    finally:
        loop.close()


async def _compose_video(
    task_dir: Path,
    task_logger: TaskLogger,
    materials: list[Path],
    segment_audios: list[dict],
    subtitle_path: Path,
    bg_music_path: Path | None,
    duration: float,
    resolution: tuple[int, int],
    fps: int,
) -> Path:
    """Compose final video."""
    import tempfile
    import time
    
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoFileClip
    from moviepy.audio.fx import AudioLoop

    timestamp = int(time.time())

    def _sync_compose():
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
            from moviepy.video.VideoClip import ColorClip
            bg = ColorClip(size=resolution, color=(30, 30, 50), duration=duration)
            video_clips = [bg]

        task_logger.info("合成最终视频...")
        video = CompositeVideoClip(video_clips, size=resolution)
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

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_compose)


@router.post("/generate")
async def generate_video(
    request: VideoGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """Start video generation task."""
    task_uuid = uuid.uuid4().hex
    task_id = f"video-{task_uuid[:8]}"
    
    task_dir = settings.output_dir / task_uuid

    video_tasks[task_id] = {
        "id": task_id,
        "task_uuid": task_uuid,
        "task_dir": str(task_dir),
        "status": "pending",
        "progress": 0.0,
        "current_step": 0,
        "message": "任务已创建，等待开始...",
        "created_at": datetime.now().isoformat(),
        "request": {
            "title": request.title,
            "has_background_music": bool(request.background_music),
            "voice": request.voice,
        },
    }

    background_tasks.add_task(
        run_video_generation,
        task_id,
        request,
        task_dir,
    )

    return {
        "success": True,
        "data": {
            "id": task_id,
            "task_uuid": task_uuid,
            "task_dir": str(task_dir),
            "status": "pending",
            "message": "视频生成任务已启动",
        },
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get video generation task status."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = video_tasks[task_id]
    
    task_dir = Path(task.get("task_dir", ""))
    status_file = task_dir / "status.json"
    
    if status_file.exists():
        import json
        with open(status_file, "r", encoding="utf-8") as f:
            file_status = json.load(f)
            task["current_step"] = file_status.get("current_step", 0)
            task["step_name"] = file_status.get("step_name", "")
            task["files"] = file_status.get("files", {})
    
    return {
        "success": True,
        "data": task,
    }


@router.get("/tasks/{task_id}/log")
async def get_task_log(task_id: str):
    """Get task log content."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = video_tasks[task_id]
    log_file = Path(task.get("task_dir", "")) / "task.log"
    
    if not log_file.exists():
        return {"success": True, "data": {"log": ""}}
    
    with open(log_file, "r", encoding="utf-8") as f:
        log_content = f.read()
    
    return {
        "success": True,
        "data": {"log": log_content},
    }


@router.get("/tasks")
async def list_tasks():
    """List all video generation tasks."""
    return {
        "success": True,
        "data": list(video_tasks.values()),
    }


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a video generation task."""
    if task_id not in video_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    del video_tasks[task_id]
    return {
        "success": True,
        "message": "Task deleted",
    }
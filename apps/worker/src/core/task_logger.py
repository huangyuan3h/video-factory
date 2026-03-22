"""Task logger for video generation."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


class TaskLogger:
    """Logger for video generation tasks."""

    STEPS = [
        {"id": 1, "name": "init", "description": "初始化任务"},
        {"id": 2, "name": "script", "description": "生成脚本内容"},
        {"id": 3, "name": "tts", "description": "合成语音"},
        {"id": 4, "name": "materials", "description": "获取素材"},
        {"id": 5, "name": "subtitles", "description": "生成字幕"},
        {"id": 6, "name": "compose", "description": "合成视频"},
        {"id": 7, "name": "complete", "description": "完成"},
    ]

    def __init__(self, task_id: str, task_dir: Path):
        self.task_id = task_id
        self.task_dir = task_dir
        self.log_file = task_dir / "task.log"
        self.status_file = task_dir / "status.json"
        self.current_step = 0
        self.logs: list[dict[str, Any]] = []
        self.status = {
            "task_id": task_id,
            "status": "pending",
            "current_step": 0,
            "step_name": "",
            "progress": 0.0,
            "message": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "files": {},
            "error": None,
        }
        self._init_files()

    def _init_files(self):
        """Initialize task directory and files."""
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self._save_status()

    def _save_status(self):
        """Save status to JSON file."""
        self.status["updated_at"] = datetime.now().isoformat()
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump(self.status, f, ensure_ascii=False, indent=2)

    def _append_log(self, level: str, message: str, step: int | None = None):
        """Append a log entry."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "step": step or self.current_step,
            "message": message,
        }
        self.logs.append(entry)
        
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"[{entry['timestamp']}] [Step {entry['step']}] [{level}] {message}\n")

    def step(self, step_id: int, message: str = ""):
        """Set current step."""
        if step_id < 1 or step_id > len(self.STEPS):
            return
        
        step_info = self.STEPS[step_id - 1]
        self.current_step = step_id
        self.status["current_step"] = step_id
        self.status["step_name"] = step_info["name"]
        
        step_message = f"Step {step_id}: {step_info['description']}"
        if message:
            step_message += f" - {message}"
        
        self.status["message"] = step_message
        self._append_log("INFO", step_message)
        self._save_status()

    def info(self, message: str):
        """Log info message."""
        self._append_log("INFO", message)
        self.status["message"] = message
        self._save_status()

    def error(self, message: str):
        """Log error message."""
        self._append_log("ERROR", message)
        self.status["status"] = "failed"
        self.status["error"] = message
        self._save_status()

    def warning(self, message: str):
        """Log warning message."""
        self._append_log("WARNING", message)

    def set_progress(self, progress: float):
        """Set progress (0.0 to 1.0)."""
        self.status["progress"] = min(1.0, max(0.0, progress))
        self._save_status()

    def set_file(self, file_type: str, path: Path):
        """Record a generated file."""
        self.status["files"][file_type] = str(path)
        self._append_log("INFO", f"Generated {file_type}: {path.name}")
        self._save_status()

    def complete(self, video_path: Path):
        """Mark task as completed."""
        self.current_step = len(self.STEPS)
        self.status["status"] = "completed"
        self.status["progress"] = 1.0
        self.status["current_step"] = self.current_step
        self.status["step_name"] = "complete"
        self.status["message"] = "视频生成完成"
        self.status["completed_at"] = datetime.now().isoformat()
        self.set_file("video", video_path)
        self._append_log("INFO", "Task completed successfully")
        self._save_status()

    def fail(self, error: str):
        """Mark task as failed."""
        self.status["status"] = "failed"
        self.status["error"] = error
        self._append_log("ERROR", f"Task failed: {error}")
        self._save_status()

    def get_status(self) -> dict:
        """Get current status."""
        return self.status.copy()

    def save_script(self, script_data: dict):
        """Save generated script to file."""
        script_file = self.task_dir / "script.json"
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)
        self.set_file("script", script_file)

    def save_thumbnail(self, image_path: Path):
        """Save thumbnail path."""
        self.set_file("thumbnail", image_path)
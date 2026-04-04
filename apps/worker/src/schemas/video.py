"""Video Options schema."""

from pydantic import BaseModel


class VideoOptions(BaseModel):
    voice: str = "zh-CN-XiaoxiaoNeural"
    resolution: str = "1080p"
    fps: int = 30
    material_source: str = "both"
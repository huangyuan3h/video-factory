"""Pydantic schemas for API validation."""

from .ai_setting import AISettingBase, AISettingCreate, AISettingResponse, AISettingUpdate
from .common import ApiResponse, PaginatedResponse
from .general_setting import GeneralSettingBase, GeneralSettingResponse, GeneralSettingUpdate
from .publisher import PublisherAccountBase, PublisherAccountCreate, PublisherAccountResponse
from .run import RunBase, RunCreate, RunResponse
from .series import SeriesBase, SeriesCreate, SeriesResponse, SeriesUpdate
from .source import SourceBase, SourceCreate, SourceResponse, SourceUpdate
from .system_prompt import (
    SystemPromptBase,
    SystemPromptCreate,
    SystemPromptResponse,
    SystemPromptUpdate,
)
from .task import TaskBase, TaskCreate, TaskResponse, TaskUpdate
from .tts_setting import TTSSettingBase, TTSSettingResponse, TTSSettingTestRequest, TTSSettingUpdate
from .video import VideoOptions

__all__ = [
    "ApiResponse",
    "PaginatedResponse",
    "SourceBase",
    "SourceCreate",
    "SourceUpdate",
    "SourceResponse",
    "TaskBase",
    "TaskCreate",
    "TaskUpdate",
    "TaskResponse",
    "RunBase",
    "RunCreate",
    "RunResponse",
    "AISettingBase",
    "AISettingCreate",
    "AISettingUpdate",
    "AISettingResponse",
    "TTSSettingBase",
    "TTSSettingUpdate",
    "TTSSettingTestRequest",
    "TTSSettingResponse",
    "GeneralSettingBase",
    "GeneralSettingUpdate",
    "GeneralSettingResponse",
    "SystemPromptBase",
    "SystemPromptCreate",
    "SystemPromptUpdate",
    "SystemPromptResponse",
    "PublisherAccountBase",
    "PublisherAccountCreate",
    "PublisherAccountResponse",
    "SeriesBase",
    "SeriesCreate",
    "SeriesUpdate",
    "SeriesResponse",
    "VideoOptions",
]

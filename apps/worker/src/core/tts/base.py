"""TTS provider abstraction."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        output_path: Path | None = None,
        voice: str | None = None,
    ) -> Path:
        ...

    async def get_duration(self, audio_path: Path) -> float:
        ...

    @classmethod
    def list_voices(cls) -> dict[str, str]:
        ...

"""OpenAI-compatible AI client for content generation."""

import logging

from openai import AsyncOpenAI
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


class ScriptSegment(BaseModel):
    """A segment of the video script."""

    text: str
    keywords: list[str]
    duration_estimate: int  # seconds


class GeneratedScript(BaseModel):
    """Generated video script."""

    title: str
    segments: list[ScriptSegment]
    total_duration_estimate: int  # seconds


class AIClient:
    """OpenAI-compatible AI client."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.base_url = base_url or settings.openai_base_url or "https://api.openai.com/v1"
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def generate_script(
        self,
        content: str,
        title: str = "",
        system_prompt: str = "",
        max_duration: int = 600,
    ) -> GeneratedScript:
        """Generate a video script from content.

        Args:
            content: Source content to generate script from
            title: Video title
            system_prompt: Custom system prompt
            max_duration: Maximum duration in seconds (default 10 minutes)

        Returns:
            GeneratedScript with title, segments, and total duration estimate
        """
        default_system_prompt = """You are a professional short video script writer for Chinese social media platforms.
Your task is to create engaging, concise scripts optimized for short videos (5-10 minutes).

Rules:
1. Write in conversational, spoken Chinese suitable for narration
2. Include a catchy opening hook in the first sentence
3. Keep sentences short and easy to read aloud
4. Split the content into 3-8 segments based on logical breaks
5. For each segment, provide 2-3 keywords for video material matching
6. Each segment should be 30-90 seconds when spoken

Output format (JSON):
{
    "title": "Short engaging title",
    "segments": [
        {
            "text": "The script content for this segment",
            "keywords": ["keyword1", "keyword2"],
            "duration_estimate": 60
        }
    ],
    "total_duration_estimate": 300
}
"""
        final_system_prompt = system_prompt if system_prompt else default_system_prompt
        user_prompt = f"Generate a video script based on this content:\n\nTitle: {title}\n\nContent: {content}"

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": final_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=4000,
                response_format={"type": "json_object"},
            )

            import json
            content = response.choices[0].message.content or "{}"
            result = json.loads(content)

            segments = [
                ScriptSegment(
                    text=seg.get("text", ""),
                    keywords=seg.get("keywords", []),
                    duration_estimate=seg.get("duration_estimate", 30),
                )
                for seg in result.get("segments", [])
            ]

            return GeneratedScript(
                title=result.get("title", title),
                segments=segments,
                total_duration_estimate=result.get("total_duration_estimate", 180),
            )

        except Exception as e:
            logger.error(f"Failed to generate script: {e}")
            raise

    async def summarize(self, content: str, max_length: int = 500) -> str:
        """Summarize content for video description."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a content summarizer. Create concise, engaging summaries in Chinese.",
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this content in {max_length} characters or less:\n\n{content}",
                    },
                ],
                temperature=0.5,
                max_tokens=500,
            )
            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"Failed to summarize: {e}")
            raise

    async def extract_keywords(self, content: str, count: int = 5) -> list[str]:
        """Extract keywords from content."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"Extract {count} most relevant keywords from the content. Return as JSON array.",
                    },
                    {
                        "role": "user",
                        "content": content,
                    },
                ],
                temperature=0.3,
                max_tokens=100,
                response_format={"type": "json_object"},
            )

            import json
            content = response.choices[0].message.content or "{}"
            result = json.loads(content)
            return result.get("keywords", [])

        except Exception as e:
            logger.error(f"Failed to extract keywords: {e}")
            return []

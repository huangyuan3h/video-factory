"""OpenAI-compatible AI client for content generation."""

import logging
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


class GeneratedScript(BaseModel):
    """Generated video script."""

    title: str
    content: str
    keywords: list[str]
    duration_estimate: int  # seconds


class AIClient:
    """OpenAI-compatible AI client."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
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
        style: str = "informative",
        max_duration: int = 60,
    ) -> GeneratedScript:
        """Generate a video script from content.

        Args:
            content: Source content to generate script from
            style: Script style (informative, entertaining, news)
            max_duration: Maximum duration in seconds

        Returns:
            GeneratedScript with title, content, keywords, and duration estimate
        """
        system_prompt = f"""You are a professional short video script writer for Chinese social media platforms.
Your task is to create engaging, concise scripts optimized for {max_duration}-second videos.

Rules:
1. Write in conversational, spoken Chinese suitable for narration
2. Include a catchy opening hook in the first sentence
3. Keep sentences short and easy to read aloud
4. Total length should be speakable in under {max_duration} seconds
5. Extract 3-5 relevant keywords for video material matching

Output format (JSON):
{{
    "title": "Short engaging title",
    "content": "The script content with natural speech patterns",
    "keywords": ["keyword1", "keyword2", ...],
    "duration_estimate": estimated_seconds
}}
"""

        user_prompt = f"Generate a {style} video script based on this content:\n\n{content}"

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            import json
            result = json.loads(response.choices[0].message.content)

            return GeneratedScript(
                title=result.get("title", ""),
                content=result.get("content", ""),
                keywords=result.get("keywords", []),
                duration_estimate=result.get("duration_estimate", 30),
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
            return response.choices[0].message.content.strip()

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
            result = json.loads(response.choices[0].message.content)
            return result.get("keywords", [])

        except Exception as e:
            logger.error(f"Failed to extract keywords: {e}")
            return []
"""OpenAI-compatible AI client for content generation."""

import logging

from openai import AsyncOpenAI
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


def _strip_json_fences(raw: str) -> str:
    """Drop ```json fences some models wrap around JSON output."""
    import re

    text = raw or ""
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1)
    return text.strip()


def parse_json_lenient(raw: str) -> dict:
    """Parse model JSON, tolerating the usual small breakages.

    Shared by :meth:`AIClient.generate_script` and :meth:`AIClient.complete_json`
    so translation/metadata calls survive the same quirks as script generation.
    """
    import json
    import re

    text = _strip_json_fences(raw)
    try:
        return json.loads(text)
    except Exception as strict_error:  # noqa: BLE001
        fixed = re.sub(r",\s*}", "}", text)
        fixed = re.sub(r",\s*]", "]", fixed)
        fixed = re.sub(r'"\s*\n\s*"duration_estimate"', '",\n"duration_estimate"', fixed)
        fixed = re.sub(r']\s*\n\s*"', '],\n"', fixed)
        fixed = re.sub(r'}\s*\n\s*"', '},\n"', fixed)
        fixed = re.sub(r'"\s*\n\s*\{', '",\n{', fixed)
        try:
            return json.loads(fixed, strict=False)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", fixed)
            if match:
                return json.loads(match.group(0), strict=False)
            raise strict_error


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
            # ling via novita doesn't support json_object (400), omit for ling
            use_json_format = "ling" not in self.model.lower()
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": final_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=4000,
            )
            # ling-3 spec: temperature false -> omit
            if "ling" not in self.model.lower():
                kwargs["temperature"] = 0.7
                kwargs["response_format"] = {"type": "json_object"}
            response = await self.client.chat.completions.create(**kwargs)

            import json, re
            raw = response.choices[0].message.content or "{}"
            # strip ```json fences for ling
            if "```" in raw:
                m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
                if m:
                    raw = m.group(1)
            raw = raw.strip()
            # try strict then lenient
            try:
                result = json.loads(raw)
            except Exception as je:
                logger.warning(f"JSON strict failed {je}, trying lenient fix")
                # common fixes: trailing commas, missing commas via regex, save raw for debug
                try:
                    import pathlib
                    pathlib.Path("/tmp/ling_last_raw.json").write_text(raw, encoding="utf-8")
                except: pass
                fixed = re.sub(r",\s*}", "}", raw)
                fixed = re.sub(r",\s*]", "]", fixed)
                # fix missing commas between fields (common ling slip: "keywords": [...] "duration_estimate")
                fixed = re.sub(r'"\s*\n\s*"duration_estimate"', '",\n"duration_estimate"', fixed)
                fixed = re.sub(r']\s*\n\s*"', '],\n"', fixed)
                fixed = re.sub(r'}\s*\n\s*"', '},\n"', fixed)
                fixed = re.sub(r'"\s*\n\s*\{', '",\n{', fixed)
                try:
                    result = json.loads(fixed, strict=False)
                except Exception:
                    # extract outermost {...} and retry
                    m2 = re.search(r"\{[\s\S]*\}", fixed)
                    if m2:
                        result = json.loads(m2.group(0), strict=False)
                    else:
                        raise je

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

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
    ) -> dict:
        """Run a chat completion expected to return a JSON object.

        Generic entry point used by the translation / YouTube-metadata services
        so they do not have to re-implement the fence-stripping and lenient
        parsing logic. Returns ``{}`` when the model returns unusable output.
        """
        use_json_format = "ling" not in self.model.lower()
        kwargs: dict = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        if use_json_format:
            kwargs["temperature"] = 0.4
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = await self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or "{}"
            return parse_json_lenient(raw)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to complete JSON: {e}")
            return {}

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

    async def optimize_content(
        self,
        content: str,
        system_prompt: str | None = None,
        target_length: int = 500,
        user_prompt: str | None = None,
    ) -> str:
        """Rewrite/optimize content for narration — preserves facts, improves spoken flow.

        If system_prompt provided, used as rewrite instruction. Otherwise uses default.
        ``user_prompt`` overrides the generic "请重写以下内容" instruction (e.g. the
        book "要点压缩" path).
        """
        default_rewrite_prompt = (
            "You are an expert Chinese editor for short video narration. "
            "Rewrite the input to be concise, engaging, spoken-style Chinese, "
            "preserve all factual points, keep numbers and names, "
            f"target {target_length} characters, no markdown, no extra explanation."
        )
        prompt = system_prompt.strip() if system_prompt and system_prompt.strip() else default_rewrite_prompt
        instruction = user_prompt if user_prompt else f"请重写以下内容：\n\n{content}"
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": instruction},
                ],
                temperature=0.7,
                max_tokens=min(4000, max(500, target_length * 3)),
            )
            rewritten = (response.choices[0].message.content or "").strip()
            if rewritten:
                logger.info(f"Optimized content {len(content)} -> {len(rewritten)} chars")
                return rewritten
            return content
        except Exception as e:
            logger.error(f"Failed to optimize content: {e}")
            return content

    def get_fallback_client(self) -> "AIClient":
        """Return fallback client for rewrite when primary LLM not suitable.

        Priority: Vercel Gateway (VERCEL_API_KEY or vercel_gateway_api_key) > DeepSeek > self
        """
        vercel_key = settings.vercel_gateway_api_key or settings.vercel_api_key
        if vercel_key:
            return AIClient(
                base_url=settings.vercel_gateway_url,
                api_key=vercel_key,
                model="openai/gpt-4o-mini",
            )
        if settings.deepseek_api_key:
            return AIClient(
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
            )
        return self

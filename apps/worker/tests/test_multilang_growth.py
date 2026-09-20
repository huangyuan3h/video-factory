"""Multi-language pipeline tests: zh master script, en YouTube growth variant.

Covers:
* language -> TTS voice mapping (en must not use a Chinese voice; zh unchanged)
* the translation layer preserving segment structure
* English YouTube title/description/tags generation + graceful fallback
* language plumbing through the generate request and publish packaging
* no-regression: the default zh path stays byte-for-byte the Chinese pipeline
"""

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src import models  # noqa: F401  (register tables)
from src.config import settings
from src.core.ai_client import GeneratedScript, ScriptSegment
from src.core.task_logger import TaskLogger
from src.core.tts import voices
from src.database import Base
from src.routes import videos as videos_route
from src.services import translation_service as ts
from src.services import video_service as vs

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _script() -> GeneratedScript:
    return GeneratedScript(
        title="失去的三十年：泡沫的开端",
        segments=[
            ScriptSegment(text="日本经济在八十年代高速增长。", keywords=["泡沫经济"], duration_estimate=25),
            ScriptSegment(text="日元升值冲击了出口。", keywords=["日元升值"], duration_estimate=20),
        ],
        total_duration_estimate=45,
    )


def _ai(complete_json_result=None, side_effect=None) -> MagicMock:
    ai = MagicMock()
    if side_effect is not None:
        ai.complete_json = AsyncMock(side_effect=side_effect)
    else:
        ai.complete_json = AsyncMock(return_value=complete_json_result or {})
    return ai


# --------------------------------------------------------------------------- #
# Voice mapping
# --------------------------------------------------------------------------- #


def test_normalize_language_variants():
    assert voices.normalize_language(None) == "zh"
    assert voices.normalize_language("") == "zh"
    assert voices.normalize_language("EN") == "en"
    assert voices.normalize_language("en-US") == "en"
    assert voices.normalize_language("zh_CN") == "zh"


def test_voice_language_prefix():
    assert voices.voice_language("en-US-AriaNeural") == "en"
    assert voices.voice_language("zh-CN-XiaoxiaoNeural") == "zh"
    assert voices.voice_language("customvoice") is None
    assert voices.voice_language(None) is None


def test_default_voice_en_is_aria():
    assert voices.default_voice("en") == "en-US-AriaNeural"
    assert voices.default_voice("zh") == "zh-CN-XiaoxiaoNeural"


def test_resolve_voice_zh_keeps_chinese_voice():
    # Backward compatible: the default zh request keeps the historical voice.
    assert voices.resolve_voice("zh", "zh-CN-XiaoxiaoNeural") == "zh-CN-XiaoxiaoNeural"
    assert voices.resolve_voice("zh", "zh-CN-YunxiNeural") == "zh-CN-YunxiNeural"
    assert voices.resolve_voice(None, "zh-CN-XiaoxiaoNeural") == "zh-CN-XiaoxiaoNeural"


def test_resolve_voice_en_swaps_chinese_default():
    assert voices.resolve_voice("en", "zh-CN-XiaoxiaoNeural") == "en-US-AriaNeural"
    assert voices.resolve_voice("en", None) == "en-US-AriaNeural"


def test_resolve_voice_en_keeps_matching_english_voice():
    assert voices.resolve_voice("en", "en-GB-RyanNeural") == "en-GB-RyanNeural"


def test_resolve_voice_unknown_custom_voice_respected():
    assert voices.resolve_voice("en", "my-narrator") == "my-narrator"


def test_resolve_voice_japanese():
    assert voices.resolve_voice("ja", "zh-CN-XiaoxiaoNeural") == "ja-JP-NanamiNeural"


# --------------------------------------------------------------------------- #
# Translation layer
# --------------------------------------------------------------------------- #


def test_translation_prompt_targets_natural_spoken_english():
    assert "same number of segments" in ts.BOOK_TRANSLATE_SCRIPT_PROMPT.lower()
    assert "spoken english" in ts.BOOK_TRANSLATE_SCRIPT_PROMPT.lower()
    assert "JSON" in ts.BOOK_TRANSLATE_SCRIPT_PROMPT


@pytest.mark.asyncio
async def test_translate_script_preserves_structure():
    source = _script()
    ai = _ai(
        {
            "title": "The Lost Three Decades",
            "segments": [
                {"text": "Japan grew fast in the 1980s.", "keywords": ["japan economy"], "duration_estimate": 25},
                {"text": "The rising yen hit exports.", "keywords": ["yen appreciation"], "duration_estimate": 20},
            ],
            "total_duration_estimate": 45,
        }
    )

    out = await ts.translate_script(ai, source, target_lang="en")

    assert len(out.segments) == len(source.segments)
    assert out.title == "The Lost Three Decades"
    assert out.segments[0].text == "Japan grew fast in the 1980s."
    assert out.segments[0].keywords == ["japan economy"]
    assert out.segments[1].keywords == ["yen appreciation"]
    # The prompt asked for the target language and carried the source JSON.
    system, user = ai.complete_json.await_args.args
    assert "Target language: en" in user
    assert ts.BOOK_TRANSLATE_SCRIPT_PROMPT == system


@pytest.mark.asyncio
async def test_translate_script_falls_back_when_model_returns_nothing():
    source = _script()
    ai = _ai({})

    out = await ts.translate_script(ai, source, target_lang="en")

    assert out is source  # unchanged, pipeline keeps the Chinese master


@pytest.mark.asyncio
async def test_translate_script_maps_partial_output():
    source = _script()
    ai = _ai({"segments": [{"text": "Only first", "keywords": ["one"]}]})

    out = await ts.translate_script(ai, source, target_lang="en")

    assert len(out.segments) == 2
    assert out.segments[0].text == "Only first"
    # Missing segment keeps the source narration so no segment is ever empty.
    assert out.segments[1].text == source.segments[1].text
    assert out.segments[1].keywords == source.segments[1].keywords


@pytest.mark.asyncio
async def test_generate_youtube_metadata_normalizes_and_dedupes():
    ai = _ai(
        {
            "title": "Japan's Lost Decades: How the Bubble Broke an Economy",
            "description": "Why did Japan stall for 30 years? #japan #economy",
            "tags": ["#Japan", "Bubble Economy", "japan", "Heisei"],
        }
    )

    meta = await ts.generate_youtube_metadata(ai, title="失去的三十年", script=_script())

    assert meta["title"].startswith("Japan's Lost Decades")
    assert "japan" in meta["description"].lower()
    assert meta["tags"] == ["japan", "bubble economy", "heisei"]


@pytest.mark.asyncio
async def test_generate_youtube_metadata_fallback_when_empty():
    ai = _ai({})

    meta = await ts.generate_youtube_metadata(ai, title="失去的三十年", script=_script())

    assert meta["title"] == "失去的三十年"
    # Derived from the (translated/segment) keywords instead of an empty list.
    assert "泡沫经济" in meta["tags"]
    assert meta["description"]


# --------------------------------------------------------------------------- #
# video_service language wiring
# --------------------------------------------------------------------------- #


def _request(**overrides) -> SimpleNamespace:
    base = dict(
        content_type="book",
        title="第一章 泡沫经济",
        language="zh",
        voice="zh-CN-XiaoxiaoNeural",
        voice_rate="+0%",
        resolution_width=1080,
        resolution_height=1920,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_init_task_en_sets_language_and_english_voice(tmp_path):
    tl = TaskLogger("lang-en-init", tmp_path)
    req = _request(language="en")

    await vs._init_task(tl, req)

    assert tl.status["language"] == "en"
    assert tl.status["voice"] == "en-US-AriaNeural"
    assert req.voice == "en-US-AriaNeural"


@pytest.mark.asyncio
async def test_init_task_zh_keeps_chinese_voice(tmp_path):
    tl = TaskLogger("lang-zh-init", tmp_path)
    req = _request()

    await vs._init_task(tl, req)

    assert tl.status["language"] == "zh"
    assert tl.status["voice"] == "zh-CN-XiaoxiaoNeural"
    assert req.voice == "zh-CN-XiaoxiaoNeural"


@pytest.mark.asyncio
async def test_localize_script_zh_is_noop(tmp_path):
    tl = TaskLogger("localize-zh", tmp_path)
    source = _script()
    ai = _ai({})

    out = await vs._localize_script(ai, _request(), source, tl)

    assert out is source
    ai.complete_json.assert_not_called()


@pytest.mark.asyncio
async def test_localize_script_en_translates_and_builds_metadata(tmp_path):
    tl = TaskLogger("localize-en", tmp_path)
    source = _script()
    ai = _ai(
        side_effect=[
            {
                "title": "The Lost Three Decades",
                "segments": [
                    {"text": "Japan boomed in the 1980s.", "keywords": ["japan economy"]},
                    {"text": "Then the yen soared.", "keywords": ["yen appreciation"]},
                ],
                "total_duration_estimate": 45,
            },
            {
                "title": "Japan's Lost Decades Explained",
                "description": "The bubble and the long stagnation.",
                "tags": ["japan", "lost decades"],
            },
        ]
    )

    out = await vs._localize_script(ai, _request(language="en"), source, tl)

    assert out.segments[0].text == "Japan boomed in the 1980s."
    assert ai.complete_json.await_count == 2
    assert tl.status["youtube_title"] == "Japan's Lost Decades Explained"
    assert tl.status["youtube_description"].startswith("The bubble")
    assert tl.status["youtube_tags"] == ["japan", "lost decades"]
    # Localized script persisted for debugging / download.
    assert (tmp_path / "script.json").exists()


@pytest.mark.asyncio
async def test_synthesize_audio_en_uses_english_voice(tmp_path):
    tl = TaskLogger("tts-en", tmp_path)
    req = _request(language="en")
    script = SimpleNamespace(segments=[SimpleNamespace(text="Hello world.", keywords=["x"], duration_estimate=10)])

    tts = MagicMock()
    tts.synthesize = AsyncMock(return_value=tmp_path / "a.mp3")
    tts.get_duration = AsyncMock(return_value=3.0)
    engine = MagicMock(return_value=tts)

    with patch.object(vs, "EdgeTTSEngine", engine):
        await vs._synthesize_audio(script, req, tmp_path, tl)

    assert engine.call_args.kwargs["voice"] == "en-US-AriaNeural"
    assert tts.synthesize.await_args.kwargs["voice"] == "en-US-AriaNeural"


def test_resolve_publish_metadata_en_youtube_uses_generated_pack(tmp_path):
    tl = TaskLogger("pub-meta-en", tmp_path)
    tl.set_meta("youtube_title", "Japan's Lost Decades")
    tl.set_meta("youtube_description", "A keyword-rich description.")
    tl.set_meta("youtube_tags", ["japan", "bubble"])
    req = SimpleNamespace(title="失去的三十年", content="中文正文")

    title, description, tags = vs._resolve_publish_metadata("youtube", "en", req, tl)

    assert title == "Japan's Lost Decades"
    assert description == "A keyword-rich description."
    assert tags == ["japan", "bubble"]


def test_resolve_publish_metadata_zh_keeps_master(tmp_path):
    tl = TaskLogger("pub-meta-zh", tmp_path)
    req = SimpleNamespace(title="失去的三十年", content="中文正文")

    title, description, tags = vs._resolve_publish_metadata("youtube", "zh", req, tl)

    assert title == "失去的三十年"
    assert tags == []


# --------------------------------------------------------------------------- #
# Request / publish schema plumbing
# --------------------------------------------------------------------------- #


def test_generate_request_language_aliases():
    assert videos_route.VideoGenerateRequest.model_validate(
        {"title": "t", "content": "c"}
    ).language == "zh"
    assert videos_route.VideoGenerateRequest.model_validate(
        {"title": "t", "content": "c", "language": "en"}
    ).language == "en"
    # `lang` is the short alias for narration language.
    assert videos_route.VideoGenerateRequest.model_validate(
        {"title": "t", "content": "c", "lang": "en"}
    ).language == "en"


def test_news_lang_alias_still_works():
    req = videos_route.VideoGenerateRequest.model_validate(
        {"type": "news", "news_query": "japan", "news_lang": "ja"}
    )
    assert req.news_lang == "ja"


def test_publish_request_accepts_publish_locale():
    data = videos_route.PublishTaskRequest.model_validate({"publish_locale": "en-US"})
    assert data.publish_locale == "en-US"


# --------------------------------------------------------------------------- #
# YouTube upload packaging (default language / locale)
# --------------------------------------------------------------------------- #


class _Exec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data

    def next_chunk(self):
        return (None, self._data)


def _fake_google_modules(captured: dict) -> dict:
    google = types.ModuleType("google")
    oauth2 = types.ModuleType("google.oauth2")
    credentials = types.ModuleType("google.oauth2.credentials")

    class _Creds:
        @classmethod
        def from_authorized_user_info(cls, info, scopes=None):
            return cls()

    credentials.Credentials = _Creds
    oauth2.credentials = credentials
    google.oauth2 = oauth2

    google_auth_httplib2 = types.ModuleType("google_auth_httplib2")

    class _AuthorizedHttp:
        def __init__(self, credentials, http=None):
            pass

    google_auth_httplib2.AuthorizedHttp = _AuthorizedHttp

    def _insert(**kwargs):
        captured["body"] = kwargs.get("body")
        return _Exec({"id": "vid1"})

    class _Service:
        def videos(self):
            return SimpleNamespace(insert=_insert)

        def playlistItems(self):  # noqa: N802 - mirrors the Google API method name
            return SimpleNamespace(insert=lambda **k: _Exec({}))

    apiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = lambda *a, **k: _Service()
    http = types.ModuleType("googleapiclient.http")

    class _Media:
        def __init__(self, *args, **kwargs):
            pass

    http.MediaFileUpload = _Media
    apiclient.discovery = discovery
    apiclient.http = http

    return {
        "google": google,
        "google.oauth2": oauth2,
        "google.oauth2.credentials": credentials,
        "google_auth_httplib2": google_auth_httplib2,
        "googleapiclient": apiclient,
        "googleapiclient.discovery": discovery,
        "googleapiclient.http": http,
    }


@pytest.mark.asyncio
async def test_youtube_upload_sets_default_language(tmp_path):
    from src.publishers.youtube import YoutubePublisher

    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    captured: dict = {}
    pub = YoutubePublisher(credentials=json.dumps({"refresh_token": "rt"}))

    with patch.dict(sys.modules, _fake_google_modules(captured)):
        result = await pub.upload(video, "Title", description="d", default_language="en")

    assert result.success is True
    assert captured["body"]["snippet"]["defaultLanguage"] == "en"
    assert captured["body"]["snippet"]["defaultAudioLanguage"] == "en"


@pytest.mark.asyncio
async def test_youtube_upload_publish_locale_overrides_language(tmp_path):
    from src.publishers.youtube import YoutubePublisher

    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    captured: dict = {}
    pub = YoutubePublisher(credentials=json.dumps({"refresh_token": "rt"}))

    with patch.dict(sys.modules, _fake_google_modules(captured)):
        await pub.upload(video, "Title", publish_locale="en-US", default_language="en")

    assert captured["body"]["snippet"]["defaultLanguage"] == "en-US"


def test_youtube_default_privacy_configurable():
    assert settings.youtube_default_privacy == "unlisted"


# --------------------------------------------------------------------------- #
# PublishJob language persistence
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_publish_job_persists_language():
    from src import queue as q

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    with patch("src.database.async_session_maker", maker):
        created = await q.enqueue_publish_jobs(
            [
                {
                    "id": "pj-lang",
                    "task_id": "t-lang",
                    "platform": "youtube",
                    "title": "Japan's Lost Decades",
                    "language": "en",
                }
            ]
        )
        claimed = await q.claim_next_publish_job()

    assert created == 1
    assert claimed["language"] == "en"
    await engine.dispose()

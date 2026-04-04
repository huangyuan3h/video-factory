"""Additional tests to increase coverage."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestPublisherBaseMethods:
    """Tests for publisher base methods."""

    def test_publisher_base_methods_exist(self):
        """Test publisher base methods exist."""
        from src.publishers.base import BasePublisher
        
        class TestPub(BasePublisher):
            @property
            def platform_name(self):
                return "Test"
            
            @property
            def login_url(self):
                return "http://test"
            
            @property
            def upload_url(self):
                return "http://test"
            
            async def check_login(self):
                return True
            
            async def upload(self, video_path, title, **kwargs):
                from src.publishers.base import PublishResult
                return PublishResult(success=True, platform="Test")
        
        pub = TestPub()
        
        assert hasattr(pub, 'init_browser')
        assert hasattr(pub, 'close_browser')
        assert hasattr(pub, 'login')

    def test_publisher_cookies_property(self):
        """Test publisher cookies property."""
        from src.publishers.base import BasePublisher
        
        class TestPub(BasePublisher):
            @property
            def platform_name(self):
                return "Test"
            
            @property
            def login_url(self):
                return "http://test"
            
            @property
            def upload_url(self):
                return "http://test"
            
            async def check_login(self):
                return True
            
            async def upload(self, video_path, title, **kwargs):
                from src.publishers.base import PublishResult
                return PublishResult(success=True, platform="Test")
        
        pub = TestPub(cookies="test-cookies")
        assert pub.cookies == "test-cookies"

    def test_publisher_headless_property(self):
        """Test publisher headless property."""
        from src.publishers.base import BasePublisher
        
        class TestPub(BasePublisher):
            @property
            def platform_name(self):
                return "Test"
            
            @property
            def login_url(self):
                return "http://test"
            
            @property
            def upload_url(self):
                return "http://test"
            
            async def check_login(self):
                return True
            
            async def upload(self, video_path, title, **kwargs):
                from src.publishers.base import PublishResult
                return PublishResult(success=True, platform="Test")
        
        pub = TestPub(headless=False)
        assert pub.headless is False


class TestHotTopicsParsers:
    """Tests for hot topics parsers."""

    @pytest.mark.asyncio
    async def test_parse_weibo_with_data(self):
        """Test parse_weibo with data."""
        from src.sources.hot_topics import HotTopicsSource
        
        source = HotTopicsSource(name="Test", platform="weibo")
        
        html = """
        <html><body><tbody>
            <tr><td><a href="/test">Test Topic</a></td></tr>
        </tbody></body></html>
        """
        
        items = await source._parse_weibo(html, 5)
        assert isinstance(items, list)


class TestRSSSourceMethods:
    """Tests for RSS source methods."""

    def test_clean_html(self):
        """Test _clean_html method."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(name="Test", url="http://test.com/rss")
        
        html = "<p>Hello <b>World</b></p>"
        cleaned = source._clean_html(html)
        assert "<p>" not in cleaned
        assert "<b>" not in cleaned

    def test_clean_html_with_entities(self):
        """Test _clean_html with entities."""
        from src.sources.rss import RSSSource
        
        source = RSSSource(name="Test", url="http://test.com/rss")
        
        html = "Hello &amp; World &lt;test&gt;"
        cleaned = source._clean_html(html)
        assert "&amp;" not in cleaned


class TestNewsAPISourceMethods:
    """Tests for NewsAPI source methods."""

    def test_news_api_init_with_category(self):
        """Test NewsAPISource with category."""
        from src.sources.news_api import NewsAPISource
        
        source = NewsAPISource(
            name="Test",
            api_key="key",
            category="technology"
        )
        assert source.category == "technology"

    def test_news_api_init_with_country(self):
        """Test NewsAPISource with country."""
        from src.sources.news_api import NewsAPISource
        
        source = NewsAPISource(
            name="Test",
            api_key="key",
            country="us"
        )
        assert source.country == "us"


class TestModelsTableNames:
    """Tests for model table names."""

    def test_all_models_have_table_names(self):
        """Test all models have table names."""
        from src.models import (
            AISetting,
            Task,
            Source,
            Run,
            SystemPrompt,
            TTSSetting,
            GeneralSetting,
            PublisherAccount
        )
        
        assert AISetting.__tablename__ == "ai_settings"
        assert Task.__tablename__ == "tasks"
        assert Source.__tablename__ == "sources"
        assert Run.__tablename__ == "runs"
        assert SystemPrompt.__tablename__ == "system_prompts"
        assert TTSSetting.__tablename__ == "tts_settings"
        assert GeneralSetting.__tablename__ == "general_settings"
        assert PublisherAccount.__tablename__ == "publisher_accounts"


class TestSchemasAll:
    """Tests for all schemas."""

    def test_all_response_schemas_exist(self):
        """Test all response schemas exist."""
        from src.schemas import (
            AISettingResponse,
            TaskResponse,
            SourceResponse,
            RunResponse,
            SystemPromptResponse,
            TTSSettingResponse,
            GeneralSettingResponse,
            PublisherAccountResponse
        )
        
        assert AISettingResponse is not None
        assert TaskResponse is not None
        assert SourceResponse is not None
        assert RunResponse is not None
        assert SystemPromptResponse is not None
        assert TTSSettingResponse is not None
        assert GeneralSettingResponse is not None
        assert PublisherAccountResponse is not None

    def test_all_create_schemas_exist(self):
        """Test all create schemas exist."""
        from src.schemas import (
            AISettingCreate,
            TaskCreate,
            SourceCreate,
            SystemPromptCreate
        )
        
        assert AISettingCreate is not None
        assert TaskCreate is not None
        assert SourceCreate is not None
        assert SystemPromptCreate is not None

    def test_all_update_schemas_exist(self):
        """Test all update schemas exist."""
        from src.schemas import (
            AISettingUpdate,
            TaskUpdate,
            SourceUpdate,
            SystemPromptUpdate,
            TTSSettingUpdate,
            GeneralSettingUpdate
        )
        
        assert AISettingUpdate is not None
        assert TaskUpdate is not None
        assert SourceUpdate is not None
        assert SystemPromptUpdate is not None
        assert TTSSettingUpdate is not None
        assert GeneralSettingUpdate is not None
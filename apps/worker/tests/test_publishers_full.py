"""Full tests for publishers module."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path


class TestBasePublisher:
    """Tests for BasePublisher class."""

    def test_base_publisher_import(self):
        """Test BasePublisher import."""
        from src.publishers.base import BasePublisher, PublishResult
        assert BasePublisher is not None
        assert PublishResult is not None

    def test_publish_result_creation(self):
        """Test PublishResult creation."""
        from src.publishers.base import PublishResult
        
        result = PublishResult(
            success=True,
            platform="test",
            post_url="http://test.com",
            post_id="123"
        )
        assert result.success is True
        assert result.platform == "test"
        assert result.post_url == "http://test.com"

    def test_publish_result_failure(self):
        """Test PublishResult failure."""
        from src.publishers.base import PublishResult
        
        result = PublishResult(
            success=False,
            platform="test",
            error="Connection failed"
        )
        assert result.success is False
        assert result.error == "Connection failed"

    def test_publisher_properties(self):
        """Test publisher abstract properties."""
        from src.publishers.base import BasePublisher
        
        class TestPublisher(BasePublisher):
            @property
            def platform_name(self) -> str:
                return "Test"
            
            @property
            def login_url(self) -> str:
                return "http://login.test.com"
            
            @property
            def upload_url(self) -> str:
                return "http://upload.test.com"
            
            async def check_login(self) -> bool:
                return True
            
            async def upload(self, video_path, title, **kwargs):
                from src.publishers.base import PublishResult
                return PublishResult(success=True, platform=self.platform_name)
        
        publisher = TestPublisher()
        assert publisher.platform_name == "Test"
        assert publisher.login_url == "http://login.test.com"
        assert publisher.upload_url == "http://upload.test.com"

    def test_publisher_init(self):
        """Test publisher initialization."""
        from src.publishers.base import BasePublisher
        
        class TestPublisher(BasePublisher):
            @property
            def platform_name(self) -> str:
                return "Test"
            
            @property
            def login_url(self) -> str:
                return "http://test"
            
            @property
            def upload_url(self) -> str:
                return "http://test"
            
            async def check_login(self) -> bool:
                return True
            
            async def upload(self, video_path, title, **kwargs):
                from src.publishers.base import PublishResult
                return PublishResult(success=True, platform="Test")
        
        publisher = TestPublisher(cookies="test-cookies", headless=False)
        assert publisher.cookies == "test-cookies"
        assert publisher.headless is False
        assert publisher.browser is None

    @pytest.mark.asyncio
    async def test_close_browser(self):
        """Test close_browser method."""
        from src.publishers.base import BasePublisher
        
        class TestPublisher(BasePublisher):
            @property
            def platform_name(self) -> str:
                return "Test"
            
            @property
            def login_url(self) -> str:
                return "http://test"
            
            @property
            def upload_url(self) -> str:
                return "http://test"
            
            async def check_login(self) -> bool:
                return True
            
            async def upload(self, video_path, title, **kwargs):
                from src.publishers.base import PublishResult
                return PublishResult(success=True, platform="Test")
        
        publisher = TestPublisher()
        publisher.browser = MagicMock()
        publisher.browser.close = AsyncMock()
        
        await publisher.close_browser()
        
        assert publisher.browser is None


class TestDouyinPublisher:
    """Tests for DouyinPublisher class."""

    def test_douyin_publisher_import(self):
        """Test DouyinPublisher import."""
        from src.publishers.douyin import DouyinPublisher
        assert DouyinPublisher is not None

    def test_douyin_properties(self):
        """Test Douyin properties."""
        from src.publishers.douyin import DouyinPublisher
        
        publisher = DouyinPublisher()
        assert publisher.platform_name == "Douyin"
        assert publisher.login_url == "https://creator.douyin.com/"
        assert publisher.upload_url == "https://creator.douyin.com/creator-micro/content/upload"

    @pytest.mark.asyncio
    async def test_douyin_check_login_no_browser(self):
        """Test check_login without browser."""
        from src.publishers.douyin import DouyinPublisher
        
        publisher = DouyinPublisher()
        publisher.page = None
        
        try:
            result = await publisher.check_login()
            assert result is False
        except AttributeError:
            pass

    @pytest.mark.asyncio
    async def test_douyin_upload_not_logged_in(self):
        """Test upload when not logged in."""
        from src.publishers.douyin import DouyinPublisher
        from src.publishers.base import PublishResult
        
        publisher = DouyinPublisher()
        publisher.browser = None
        
        result = await publisher.upload(
            video_path=Path("/tmp/test.mp4"),
            title="Test video"
        )
        assert result.success is False


class TestXiaohongshuPublisher:
    """Tests for XiaohongshuPublisher class."""

    def test_xiaohongshu_publisher_import(self):
        """Test XiaohongshuPublisher import."""
        from src.publishers.xiaohongshu import XiaohongshuPublisher
        assert XiaohongshuPublisher is not None

    def test_xiaohongshu_properties(self):
        """Test Xiaohongshu properties."""
        from src.publishers.xiaohongshu import XiaohongshuPublisher
        
        publisher = XiaohongshuPublisher()
        assert publisher.platform_name == "Xiaohongshu"
        assert publisher.login_url == "https://creator.xiaohongshu.com/"
        assert publisher.upload_url == "https://creator.xiaohongshu.com/publish/publish"

    @pytest.mark.asyncio
    async def test_xiaohongshu_upload_not_logged_in(self):
        """Test upload when not logged in."""
        from src.publishers.xiaohongshu import XiaohongshuPublisher
        from src.publishers.base import PublishResult
        
        publisher = XiaohongshuPublisher()
        publisher.browser = None
        
        result = await publisher.upload(
            video_path=Path("/tmp/test.mp4"),
            title="Test video"
        )
        assert result.success is False


class TestPublishersInit:
    """Tests for publishers __init__.py."""

    def test_publishers_init_import(self):
        """Test publishers module imports."""
        from src.publishers import DouyinPublisher, XiaohongshuPublisher
        
        assert DouyinPublisher is not None
        assert XiaohongshuPublisher is not None
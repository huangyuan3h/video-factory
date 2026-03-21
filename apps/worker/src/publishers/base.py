"""Base class for video publishers."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Result of a publish operation."""

    success: bool
    platform: str
    post_url: Optional[str] = None
    post_id: Optional[str] = None
    error: Optional[str] = None
    published_at: Optional[datetime] = None


class BasePublisher(ABC):
    """Abstract base class for video publishers."""

    def __init__(
        self,
        cookies: Optional[str] = None,
        headless: bool = True,
    ):
        self.cookies = cookies
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Platform name."""
        pass

    @property
    @abstractmethod
    def login_url(self) -> str:
        """Login page URL."""
        pass

    @property
    @abstractmethod
    def upload_url(self) -> str:
        """Upload page URL."""
        pass

    async def init_browser(self):
        """Initialize browser with Playwright."""
        playwright = await async_playwright().start()

        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
            ],
        )

        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        # Load cookies if provided
        if self.cookies:
            await self._load_cookies()

        self.page = await self.context.new_page()

    async def close_browser(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
            self.browser = None
            self.context = None
            self.page = None

    async def _load_cookies(self):
        """Load cookies from string."""
        import json

        try:
            cookies = json.loads(self.cookies)
            await self.context.add_cookies(cookies)
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")

    async def save_cookies(self) -> str:
        """Save cookies to string."""
        import json

        cookies = await self.context.cookies()
        return json.dumps(cookies)

    @abstractmethod
    async def check_login(self) -> bool:
        """Check if user is logged in."""
        pass

    @abstractmethod
    async def upload(
        self,
        video_path: Path,
        title: str,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        **kwargs,
    ) -> PublishResult:
        """Upload video to platform."""
        pass

    async def login(self, timeout: int = 120) -> bool:
        """Manual login via QR code or credentials.

        Args:
            timeout: Maximum time to wait for login in seconds

        Returns:
            True if login successful
        """
        await self.init_browser()
        await self.page.goto(self.login_url)

        logger.info(f"Please log in to {self.platform_name} manually...")
        logger.info(f"Waiting up to {timeout} seconds for login...")

        # Wait for login to complete
        start_time = datetime.now()
        while (datetime.now() - start_time).total_seconds() < timeout:
            if await self.check_login():
                logger.info(f"Login to {self.platform_name} successful!")
                # Save cookies for future use
                self.cookies = await self.save_cookies()
                return True
            await asyncio.sleep(2)

        logger.error("Login timeout")
        return False

    async def wait_for_selector(
        self,
        selector: str,
        timeout: int = 30000,
    ):
        """Wait for an element to appear."""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def click(self, selector: str):
        """Click an element."""
        await self.page.click(selector)

    async def fill(self, selector: str, text: str):
        """Fill a text input."""
        await self.page.fill(selector, text)

    async def upload_file(self, selector: str, file_path: Path):
        """Upload a file."""
        input_element = await self.page.query_selector(selector)
        await input_element.set_input_files(str(file_path))
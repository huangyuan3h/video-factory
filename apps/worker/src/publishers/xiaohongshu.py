"""Xiaohongshu (Little Red Book) publisher."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from .base import BasePublisher, PublishResult

logger = logging.getLogger(__name__)


class XiaohongshuPublisher(BasePublisher):
    """Publisher for Xiaohongshu (小红书)."""

    @property
    def platform_name(self) -> str:
        return "Xiaohongshu"

    @property
    def login_url(self) -> str:
        return "https://creator.xiaohongshu.com/"

    @property
    def upload_url(self) -> str:
        return "https://creator.xiaohongshu.com/publish/publish"

    async def check_login(self) -> bool:
        """Check if logged in to Xiaohongshu Creator Studio."""
        try:
            await self.page.goto(self.login_url)
            await asyncio.sleep(2)

            # Check for user avatar or login redirect
            user_avatar = await self.page.query_selector('[class*="avatar"], [class*="user-info"]')
            login_btn = await self.page.query_selector('[class*="login-btn"], button:has-text("登录")')

            return user_avatar is not None and login_btn is None

        except Exception as e:
            logger.error(f"Failed to check login status: {e}")
            return False

    async def upload(
        self,
        video_path: Path,
        title: str,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        cover_image: Optional[Path] = None,
        **kwargs,
    ) -> PublishResult:
        """Upload video to Xiaohongshu.

        Args:
            video_path: Path to video file
            title: Video title (used as first line of description)
            description: Video description
            tags: List of hashtags
            cover_image: Custom cover image (optional)

        Returns:
            PublishResult with upload status
        """
        try:
            if not self.browser:
                await self.init_browser()

            # Check login
            if not await self.check_login():
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    error="Not logged in. Please login first.",
                )

            # Navigate to upload page
            await self.page.goto(self.upload_url)
            await asyncio.sleep(2)

            # Click video upload tab if needed
            video_tab = await self.page.query_selector('[class*="video"], button:has-text("视频")')
            if video_tab:
                await video_tab.click()
                await asyncio.sleep(1)

            # Upload video file
            logger.info(f"Uploading video: {video_path}")
            await self.upload_file('input[type="file"]', video_path)

            # Wait for upload and processing
            await self._wait_for_upload_complete()

            # Fill in description
            await asyncio.sleep(2)

            full_description = f"{title}\n\n{description or ''}"
            if tags:
                full_description += "\n\n" + " ".join(f"#{tag}" for tag in tags)

            # Xiaohongshu title is the first line, rest is description
            title_input = await self.page.query_selector('input[placeholder*="标题"], input[placeholder*="title"]')
            if title_input:
                await title_input.fill(title[:20])  # Xiaohongshu title limit

            # Fill description
            desc_textarea = await self.page.query_selector('textarea, [contenteditable="true"]')
            if desc_textarea:
                await desc_textarea.fill(full_description[:1000])  # Xiaohongshu char limit

            # Upload cover image if provided
            if cover_image:
                await self._upload_cover(cover_image)

            # Click publish button
            await self._click_publish()

            # Wait for success
            await asyncio.sleep(3)

            return PublishResult(
                success=True,
                platform=self.platform_name,
            )

        except Exception as e:
            logger.error(f"Failed to upload to Xiaohongshu: {e}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error=str(e),
            )

    async def _wait_for_upload_complete(self, timeout: int = 600):
        """Wait for video upload and processing to complete."""
        logger.info("Waiting for upload to complete...")

        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                # Check for success indicator
                progress = await self.page.query_selector('[class*="progress"], [class*="uploading"]')

                if not progress:
                    # Check for cover selection interface (indicates upload done)
                    cover_select = await self.page.query_selector('[class*="cover"], [class*="thumbnail"]')
                    if cover_select:
                        logger.info("Upload complete, ready for cover selection")
                        return

                    # Also check for description form
                    desc_form = await self.page.query_selector('textarea, [contenteditable="true"]')
                    if desc_form:
                        logger.info("Upload complete, ready for description")
                        return

                await asyncio.sleep(2)

            except Exception as e:
                logger.debug(f"Upload check error: {e}")
                await asyncio.sleep(2)

        raise TimeoutError("Upload timed out")

    async def _upload_cover(self, cover_path: Path):
        """Upload custom cover image."""
        try:
            # Click to upload custom cover
            cover_btn = await self.page.query_selector('[class*="custom-cover"], [class*="upload-cover"]')
            if cover_btn:
                await cover_btn.click()
                await asyncio.sleep(1)

                # Upload cover file
                await self.upload_file('input[type="file"][accept*="image"]', cover_path)
                await asyncio.sleep(2)

                # Confirm cover selection
                confirm_btn = await self.page.query_selector('button:has-text("确定"), button:has-text("完成")')
                if confirm_btn:
                    await confirm_btn.click()

        except Exception as e:
            logger.warning(f"Failed to upload cover: {e}")

    async def _click_publish(self):
        """Click the publish button."""
        # Find and click publish button
        publish_btn = await self.page.query_selector(
            'button:has-text("发布"), button:has-text("发表"), [class*="publish-btn"]'
        )
        if publish_btn:
            await publish_btn.click()
            logger.info("Clicked publish button")

            # Wait for success dialog
            await asyncio.sleep(2)
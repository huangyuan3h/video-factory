"""Douyin (TikTok China) publisher."""

import asyncio
import logging
from pathlib import Path

from .base import BasePublisher, PublishResult

logger = logging.getLogger(__name__)


class DouyinPublisher(BasePublisher):
    """Publisher for Douyin (抖音)."""

    @property
    def platform_name(self) -> str:
        return "Douyin"

    @property
    def login_url(self) -> str:
        return "https://creator.douyin.com/"

    @property
    def upload_url(self) -> str:
        return "https://creator.douyin.com/creator-micro/content/upload"

    async def check_login(self) -> bool:
        """Check if logged in to Douyin Creator Studio."""
        try:
            await self.page.goto(self.login_url)
            await asyncio.sleep(2)

            # Check if we're redirected to login page or see user avatar
            current_url = self.page.url

            # If we see the upload button or user info, we're logged in
            user_info = await self.page.query_selector('[class*="user-info"], [class*="avatar"]')

            return user_info is not None and "login" not in current_url.lower()

        except Exception as e:
            logger.error(f"Failed to check login status: {e}")
            return False

    async def upload(
        self,
        video_path: Path,
        title: str,
        description: str | None = None,
        tags: list[str] | None = None,
        publish_time: str | None = None,  # Format: "YYYY-MM-DD HH:MM"
        **kwargs,
    ) -> PublishResult:
        """Upload video to Douyin.

        Args:
            video_path: Path to video file
            title: Video title
            description: Video description
            tags: List of hashtags
            publish_time: Scheduled publish time (optional)

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

            # Upload video file
            logger.info(f"Uploading video: {video_path}")
            await self.upload_file('input[type="file"]', video_path)

            # Wait for upload to complete
            await self._wait_for_upload_complete()

            # Fill in title and description
            full_description = f"{title}\n{description or ''}"
            if tags:
                full_description += "\n" + " ".join(f"#{tag}" for tag in tags)

            # Find and fill description textarea
            await asyncio.sleep(1)
            textarea = await self.page.query_selector('textarea, [contenteditable="true"]')
            if textarea:
                await textarea.fill(full_description[:2200])  # Douyin char limit

            # Set publish time if scheduled
            if publish_time:
                await self._set_publish_time(publish_time)

            # Click publish button
            await self._click_publish()

            # Wait for success
            await asyncio.sleep(3)

            # Get post URL (if available)
            post_url = None
            try:
                success_msg = await self.page.query_selector('[class*="success"], [class*="published"]')
                if success_msg:
                    link = await success_msg.query_selector('a')
                    if link:
                        post_url = await link.get_attribute('href')
            except Exception:
                pass

            return PublishResult(
                success=True,
                platform=self.platform_name,
                post_url=post_url,
            )

        except Exception as e:
            logger.error(f"Failed to upload to Douyin: {e}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error=str(e),
            )

    async def _wait_for_upload_complete(self, timeout: int = 600):
        """Wait for video upload to complete."""
        logger.info("Waiting for upload to complete...")

        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                # Check for success indicator
                progress = await self.page.query_selector('[class*="progress"], [class*="uploading"]')

                # If no progress element, check for completion
                if not progress:
                    complete = await self.page.query_selector('[class*="success"], [class*="complete"]')
                    if complete:
                        logger.info("Upload complete!")
                        return

                await asyncio.sleep(2)

            except Exception as e:
                logger.debug(f"Upload check error: {e}")
                await asyncio.sleep(2)

        raise TimeoutError("Upload timed out")

    async def _set_publish_time(self, publish_time: str):
        """Set scheduled publish time."""
        try:
            # Click schedule button
            schedule_btn = await self.page.query_selector('[class*="schedule"], [class*="timing"]')
            if schedule_btn:
                await schedule_btn.click()
                await asyncio.sleep(1)

                # Fill in time
                # Note: Actual selectors depend on Douyin's current UI
                date_input = await self.page.query_selector('input[type="date"]')
                if date_input:
                    await date_input.fill(publish_time.split()[0])

                time_input = await self.page.query_selector('input[type="time"]')
                if time_input:
                    await time_input.fill(publish_time.split()[1])

        except Exception as e:
            logger.warning(f"Failed to set publish time: {e}")

    async def _click_publish(self):
        """Click the publish button."""
        # Find and click publish button
        publish_btn = await self.page.query_selector(
            'button:has-text("发布"), button:has-text("发表"), [class*="publish-btn"]'
        )
        if publish_btn:
            await publish_btn.click()
            logger.info("Clicked publish button")

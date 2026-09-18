"""YouTube publisher via official Data API v3 — extensible folder = playlist."""

import json
import logging
from pathlib import Path
from datetime import datetime

from .base import BasePublisher, PublishResult

logger = logging.getLogger(__name__)


class YoutubePublisher(BasePublisher):
    """Publisher for YouTube — uses OAuth credentials, not Playwright."""

    def __init__(self, credentials: str | None = None, folder_id: str | None = None, **kwargs):
        # credentials is JSON string containing refresh_token or full token
        super().__init__(cookies=None, headless=True)
        self.credentials_json = credentials
        self.default_playlist_id = folder_id
        # Allow passing via kwargs for flexibility
        self.extra = kwargs

    @property
    def platform_name(self) -> str:
        return "YouTube"

    @property
    def login_url(self) -> str:
        return "https://accounts.google.com/o/oauth2/auth"

    @property
    def upload_url(self) -> str:
        return "https://www.youtube.com/upload"

    async def check_login(self) -> bool:
        # OAuth valid if credentials contain refresh_token or access_token
        if not self.credentials_json:
            return False
        try:
            data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
            return bool(data.get("refresh_token") or data.get("access_token") or data.get("credentials"))
        except Exception:
            return False

    def supports_folder(self) -> bool:
        return True

    async def list_folders(self) -> list[dict]:
        """List YouTube playlists as folders. Returns [{id, name, itemCount}]"""
        if not self.credentials_json:
            logger.info("YouTube list_folders: no credentials configured")
            return []
        try:
            return await self._list_playlists_real()
        except Exception as e:
            logger.warning(f"YouTube list_folders failed: {e}")
            return []

    async def _list_playlists_real(self) -> list[dict]:
        # Lazy import to keep optional
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
        creds = Credentials.from_authorized_user_info(creds_data, scopes=["https://www.googleapis.com/auth/youtube"])
        service = build("youtube", "v3", credentials=creds)
        # Synchronous call in thread
        import asyncio
        loop = asyncio.get_event_loop()
        def _fetch():
            resp = service.playlists().list(part="snippet,contentDetails", mine=True, maxResults=25).execute()
            return resp.get("items", [])
        items = await loop.run_in_executor(None, _fetch)
        return [{"id": it["id"], "name": it["snippet"]["title"], "itemCount": it["contentDetails"]["itemCount"]} for it in items]

    async def create_folder(self, name: str, **kwargs) -> dict | None:
        """Create a YouTube playlist as folder."""
        if not self.credentials_json:
            logger.info("YouTube create_folder: no credentials configured")
            return None
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            creds_data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
            creds = Credentials.from_authorized_user_info(creds_data, scopes=["https://www.googleapis.com/auth/youtube"])
            service = build("youtube", "v3", credentials=creds)
            import asyncio
            loop = asyncio.get_event_loop()
            def _create():
                body = {"snippet": {"title": name, "description": kwargs.get("description", "")}, "status": {"privacyStatus": kwargs.get("privacy", "private")}}
                resp = service.playlists().insert(part="snippet,status", body=body).execute()
                return resp
            resp = await loop.run_in_executor(None, _create)
            return {"id": resp["id"], "name": resp["snippet"]["title"]}
        except Exception as e:
            logger.error(f"YouTube create_folder failed: {e}")
            return None

    async def upload(
        self,
        video_path: Path,
        title: str,
        description: str | None = None,
        tags: list[str] | None = None,
        folder_id: str | None = None,
        playlist_id: str | None = None,
        privacy: str = "private",
        category_id: str = "22",
        publish_at: str | None = None,
        **kwargs,
    ) -> PublishResult:
        """Upload to YouTube.

        folder_id / playlist_id maps to YouTube playlist.
        privacy: public|unlisted|private
        """
        effective_playlist = folder_id or playlist_id or self.default_playlist_id
        # No credentials -> fail loudly instead of pretending to publish.
        if not await self.check_login():
            logger.warning(f"YouTube upload skipped: no valid credentials for {video_path.name}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error="YouTube 凭据未配置或无效（需要在 PublisherAccount.credentials 提供含 refresh_token 的 OAuth JSON）",
            )
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            creds_data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
            creds = Credentials.from_authorized_user_info(creds_data, scopes=["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.upload"])
            service = build("youtube", "v3", credentials=creds)
            import asyncio
            loop = asyncio.get_event_loop()

            body = {
                "snippet": {
                    "title": title[:100],
                    "description": (description or "")[:5000],
                    "tags": tags or [],
                    "categoryId": category_id,
                },
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }
            if publish_at:
                body["status"]["publishAt"] = publish_at

            media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/*")

            def _insert():
                req = service.videos().insert(part="snippet,status", body=body, media_body=media)
                resp = None
                while resp is None:
                    status, resp = req.next_chunk()
                return resp

            resp = await loop.run_in_executor(None, _insert)
            video_id = resp.get("id")
            post_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None

            # Add to playlist if requested
            if effective_playlist and video_id:
                def _add_to_playlist():
                    service.playlistItems().insert(
                        part="snippet",
                        body={"snippet": {"playlistId": effective_playlist, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
                    ).execute()
                try:
                    await loop.run_in_executor(None, _add_to_playlist)
                except Exception as e:
                    logger.warning(f"YouTube add to playlist failed: {e}")

            return PublishResult(success=True, platform=self.platform_name, post_id=video_id, post_url=post_url, published_at=datetime.now())
        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            return PublishResult(success=False, platform=self.platform_name, error=str(e))

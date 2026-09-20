"""YouTube publisher via official Data API v3 — extensible folder = playlist."""

import asyncio
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

from .base import BasePublisher, PublishResult

logger = logging.getLogger(__name__)


class GoogleAPITimeoutError(Exception):
    """Raised when Google API calls timeout (network unreachable, etc.)."""
    pass


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
        """List YouTube playlists as folders. Returns [{id, name, itemCount}]
        
        Raises:
            ImportError: If proxy is configured but PySocks is not installed
            GoogleAPITimeoutError: If API request times out
            Exception: Other API errors (network, auth, etc.)
        """
        if not self.credentials_json:
            logger.info("YouTube list_folders: no credentials configured")
            return []
        # Re-raise errors instead of silently returning empty list
        # This ensures proxy/build errors surface to caller
        return await self._list_playlists_real()

    async def _list_playlists_real(self) -> list[dict]:
        # Lazy import to keep optional
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
        creds = Credentials.from_authorized_user_info(creds_data, scopes=["https://www.googleapis.com/auth/youtube"])
        http = self._build_http_with_proxy()
        service = build("youtube", "v3", credentials=creds, http=http)
        
        loop = asyncio.get_event_loop()
        def _fetch():
            resp = service.playlists().list(part="snippet,contentDetails", mine=True, maxResults=25).execute()
            return resp.get("items", [])
        
        # Apply timeout to prevent hanging when Google APIs are unreachable
        timeout = self._get_api_timeout()
        try:
            items = await asyncio.wait_for(loop.run_in_executor(None, _fetch), timeout=timeout)
        except asyncio.TimeoutError as e:
            logger.error(f"YouTube list_playlists timed out after {timeout}s (network unreachable?)")
            raise GoogleAPITimeoutError(f"Google API request timed out after {timeout}s. Check network connectivity to googleapis.com") from e
        
        return [{"id": it["id"], "name": it["snippet"]["title"], "itemCount": it["contentDetails"]["itemCount"]} for it in items]
    
    def _get_api_timeout(self) -> float:
        """Get configured timeout for external API calls, with fallback."""
        try:
            from ..config import settings
            return settings.external_api_timeout_s
        except Exception:
            return 30.0  # default fallback

    def _build_http_with_proxy(self):
        """Build httplib2.Http with proxy support when HTTPS_PROXY is set.
        
        Uses PySocks for proxy support. If PySocks is not installed and proxy
        is required, raises ImportError with clear installation instructions.
        
        Returns:
            httplib2.Http configured with proxy settings if HTTPS_PROXY is set,
            otherwise returns None (googleapiclient will use default Http).
        """
        https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        proxy_url = https_proxy or http_proxy
        
        if not proxy_url:
            return None
        
        # Parse proxy URL
        parsed = urlparse(proxy_url)
        proxy_host = parsed.hostname
        proxy_port = parsed.port or (443 if parsed.scheme == "https" else 8080)
        
        # Import PySocks for proxy support
        try:
            import socks
        except ImportError as e:
            raise ImportError(
                "PySocks is required for proxy support but is not installed. "
                "Please install it with: pip install PySocks"
            ) from e
        
        # Import httplib2 and build Http with proxy
        try:
            import httplib2
        except ImportError as e:
            raise ImportError(
                "httplib2 is required but is not installed. "
                "This should be installed with google-api-python-client."
            ) from e
        
        # Determine proxy type from URL scheme
        if parsed.scheme in ("socks5", "socks5h"):
            proxy_type = socks.PROXY_TYPE_SOCKS5
        elif parsed.scheme == "socks4":
            proxy_type = socks.PROXY_TYPE_SOCKS4
        else:  # http, https
            proxy_type = socks.PROXY_TYPE_HTTP
        
        logger.info(f"Building Http client with proxy: {parsed.scheme}://{proxy_host}:{proxy_port}")
        
        # Build Http with proxy_info
        proxy_info = httplib2.ProxyInfo(
            proxy_type=proxy_type,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            proxy_user=parsed.username,
            proxy_pass=parsed.password,
        )
        
        return httplib2.Http(proxy_info=proxy_info)

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
            http = self._build_http_with_proxy()
            service = build("youtube", "v3", credentials=creds, http=http)
            
            loop = asyncio.get_event_loop()
            def _create():
                body = {"snippet": {"title": name, "description": kwargs.get("description", "")}, "status": {"privacyStatus": kwargs.get("privacy", "private")}}
                resp = service.playlists().insert(part="snippet,status", body=body).execute()
                return resp
            
            timeout = self._get_api_timeout()
            try:
                resp = await asyncio.wait_for(loop.run_in_executor(None, _create), timeout=timeout)
            except asyncio.TimeoutError as e:
                logger.error(f"YouTube create_folder timed out after {timeout}s (network unreachable?)")
                raise GoogleAPITimeoutError(f"Google API request timed out after {timeout}s. Check network connectivity to googleapis.com") from e
            
            return {"id": resp["id"], "name": resp["snippet"]["title"]}
        except GoogleAPITimeoutError:
            raise
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
            http = self._build_http_with_proxy()
            service = build("youtube", "v3", credentials=creds, http=http)
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

            # Upload with timeout - large videos may need more time, use 5x normal timeout
            timeout = self._get_api_timeout() * 5
            try:
                resp = await asyncio.wait_for(loop.run_in_executor(None, _insert), timeout=timeout)
            except asyncio.TimeoutError as e:
                logger.error(f"YouTube upload timed out after {timeout}s (network unreachable or slow?)")
                raise GoogleAPITimeoutError(f"Video upload timed out after {timeout}s. Check network connectivity to googleapis.com") from e
            
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
                    playlist_timeout = self._get_api_timeout()
                    await asyncio.wait_for(loop.run_in_executor(None, _add_to_playlist), timeout=playlist_timeout)
                except asyncio.TimeoutError:
                    logger.warning(f"YouTube add to playlist timed out after {playlist_timeout}s")
                except Exception as e:
                    logger.warning(f"YouTube add to playlist failed: {e}")

            return PublishResult(success=True, platform=self.platform_name, post_id=video_id, post_url=post_url, published_at=datetime.now())
        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            return PublishResult(success=False, platform=self.platform_name, error=str(e))

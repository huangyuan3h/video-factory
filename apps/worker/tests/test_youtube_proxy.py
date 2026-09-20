"""Tests for YouTube API proxy support."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, call

import pytest

from src.publishers.youtube import YoutubePublisher


@pytest.fixture
def youtube_publisher():
    """Create a YoutubePublisher instance with test credentials."""
    credentials = json.dumps({"refresh_token": "test_token"})
    return YoutubePublisher(credentials=credentials)


def test_build_http_without_proxy(youtube_publisher):
    """Test that HTTP is built without proxy when no env vars are set."""
    # Clear any proxy environment variables
    env_backup = {}
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        env_backup[key] = os.environ.pop(key, None)
    
    try:
        with patch("httplib2.Http") as mock_http_class:
            with patch("httplib2.ProxyInfo") as mock_proxy_info_class:
                http = youtube_publisher._build_http_with_proxy()
                
                # Should create Http without ProxyInfo
                mock_http_class.assert_called_once()
                call_kwargs = mock_http_class.call_args.kwargs
                assert "proxy_info" not in call_kwargs
                assert call_kwargs.get("timeout") == 30.0
                
                # ProxyInfo should not be created
                mock_proxy_info_class.assert_not_called()
    finally:
        # Restore environment
        for key, value in env_backup.items():
            if value is not None:
                os.environ[key] = value


def test_build_http_with_https_proxy(youtube_publisher):
    """Test that HTTP is built with proxy when HTTPS_PROXY is set."""
    env_backup = os.environ.copy()
    
    try:
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
        
        with patch("httplib2.socks") as mock_socks:
            mock_socks.PROXY_TYPE_HTTP = 3
            with patch("httplib2.Http") as mock_http_class:
                with patch("httplib2.ProxyInfo") as mock_proxy_info_class:
                    mock_proxy_info = MagicMock()
                    mock_proxy_info_class.return_value = mock_proxy_info
                    
                    http = youtube_publisher._build_http_with_proxy()
                    
                    # Should create ProxyInfo with correct parameters
                    mock_proxy_info_class.assert_called_once()
                    call_kwargs = mock_proxy_info_class.call_args.kwargs
                    assert call_kwargs["proxy_type"] == 3
                    assert call_kwargs["proxy_host"] == "127.0.0.1"
                    assert call_kwargs["proxy_port"] == 7890
                    
                    # Should create Http with ProxyInfo
                    mock_http_class.assert_called_once()
                    http_call_kwargs = mock_http_class.call_args.kwargs
                    assert http_call_kwargs["proxy_info"] is mock_proxy_info
                    assert http_call_kwargs["timeout"] == 30.0
    finally:
        # Restore environment
        os.environ.clear()
        os.environ.update(env_backup)


def test_build_http_with_http_proxy(youtube_publisher):
    """Test that HTTP_PROXY is used when HTTPS_PROXY is not set."""
    env_backup = os.environ.copy()
    
    try:
        # Clear HTTPS_PROXY, set HTTP_PROXY
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("https_proxy", None)
        os.environ["HTTP_PROXY"] = "http://proxy.example.com:8080"
        
        with patch("httplib2.socks") as mock_socks:
            mock_socks.PROXY_TYPE_HTTP = 3
            with patch("httplib2.Http"):
                with patch("httplib2.ProxyInfo") as mock_proxy_info_class:
                    http = youtube_publisher._build_http_with_proxy()
                    
                    # Should use HTTP_PROXY
                    mock_proxy_info_class.assert_called_once()
                    call_kwargs = mock_proxy_info_class.call_args.kwargs
                    assert call_kwargs["proxy_host"] == "proxy.example.com"
                    assert call_kwargs["proxy_port"] == 8080
    finally:
        # Restore environment
        os.environ.clear()
        os.environ.update(env_backup)


def test_build_http_with_socks5_proxy(youtube_publisher):
    """Test that SOCKS5 proxy is configured correctly."""
    env_backup = os.environ.copy()
    
    try:
        os.environ["HTTPS_PROXY"] = "socks5://127.0.0.1:7891"
        
        with patch("httplib2.socks") as mock_socks:
            mock_socks.PROXY_TYPE_SOCKS5 = 1
            with patch("httplib2.Http"):
                with patch("httplib2.ProxyInfo") as mock_proxy_info_class:
                    http = youtube_publisher._build_http_with_proxy()
                    
                    # Should create ProxyInfo with SOCKS5 type
                    mock_proxy_info_class.assert_called_once()
                    call_kwargs = mock_proxy_info_class.call_args.kwargs
                    assert call_kwargs["proxy_type"] == 1
                    assert call_kwargs["proxy_host"] == "127.0.0.1"
                    assert call_kwargs["proxy_port"] == 7891
    finally:
        # Restore environment
        os.environ.clear()
        os.environ.update(env_backup)


def test_build_http_prefers_https_proxy_over_http_proxy(youtube_publisher):
    """Test that HTTPS_PROXY is preferred over HTTP_PROXY."""
    env_backup = os.environ.copy()
    
    try:
        os.environ["HTTP_PROXY"] = "http://http-proxy:8080"
        os.environ["HTTPS_PROXY"] = "http://https-proxy:7890"
        
        with patch("httplib2.socks") as mock_socks:
            mock_socks.PROXY_TYPE_HTTP = 3
            with patch("httplib2.Http"):
                with patch("httplib2.ProxyInfo") as mock_proxy_info_class:
                    http = youtube_publisher._build_http_with_proxy()
                    
                    # Should use HTTPS_PROXY
                    mock_proxy_info_class.assert_called_once()
                    call_kwargs = mock_proxy_info_class.call_args.kwargs
                    assert call_kwargs["proxy_host"] == "https-proxy"
                    assert call_kwargs["proxy_port"] == 7890
    finally:
        # Restore environment
        os.environ.clear()
        os.environ.update(env_backup)


def test_build_http_handles_lowercase_env_vars(youtube_publisher):
    """Test that lowercase proxy env vars are recognized."""
    env_backup = os.environ.copy()
    
    try:
        # Clear uppercase, set lowercase
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("HTTP_PROXY", None)
        os.environ["https_proxy"] = "http://lowercase-proxy:9090"
        
        with patch("httplib2.socks") as mock_socks:
            mock_socks.PROXY_TYPE_HTTP = 3
            with patch("httplib2.Http"):
                with patch("httplib2.ProxyInfo") as mock_proxy_info_class:
                    http = youtube_publisher._build_http_with_proxy()
                    
                    # Should use lowercase env var
                    mock_proxy_info_class.assert_called_once()
                    call_kwargs = mock_proxy_info_class.call_args.kwargs
                    assert call_kwargs["proxy_host"] == "lowercase-proxy"
                    assert call_kwargs["proxy_port"] == 9090
    finally:
        # Restore environment
        os.environ.clear()
        os.environ.update(env_backup)


def test_build_http_with_proxy_no_port(youtube_publisher):
    """Test that default port is used when not specified."""
    env_backup = os.environ.copy()
    
    try:
        os.environ["HTTPS_PROXY"] = "http://proxy.example.com"
        
        with patch("httplib2.socks") as mock_socks:
            mock_socks.PROXY_TYPE_HTTP = 3
            with patch("httplib2.Http"):
                with patch("httplib2.ProxyInfo") as mock_proxy_info_class:
                    http = youtube_publisher._build_http_with_proxy()
                    
                    # Should use default port 3128 for HTTP proxy
                    mock_proxy_info_class.assert_called_once()
                    call_kwargs = mock_proxy_info_class.call_args.kwargs
                    assert call_kwargs["proxy_port"] == 3128
    finally:
        # Restore environment
        os.environ.clear()
        os.environ.update(env_backup)


@pytest.mark.asyncio
async def test_list_folders_uses_proxy():
    """Test that list_folders passes proxy-configured HTTP to build()."""
    credentials = json.dumps({"refresh_token": "test_token"})
    pub = YoutubePublisher(credentials=credentials)
    
    mock_http = MagicMock()
    mock_service = MagicMock()
    mock_playlists = MagicMock()
    mock_list = MagicMock()
    
    # Setup mock chain
    mock_list.execute.return_value = {"items": [
        {
            "id": "PL123",
            "snippet": {"title": "Test Playlist"},
            "contentDetails": {"itemCount": 5}
        }
    ]}
    mock_playlists.list.return_value = mock_list
    mock_service.playlists.return_value = mock_playlists
    
    with patch.object(pub, "_build_http_with_proxy", return_value=mock_http):
        with patch("google.oauth2.credentials.Credentials"):
            with patch("googleapiclient.discovery.build", return_value=mock_service) as mock_build:
                result = await pub._list_playlists_real()
    
    # Verify build was called with our HTTP instance
    mock_build.assert_called_once()
    call_kwargs = mock_build.call_args.kwargs
    assert call_kwargs["http"] is mock_http
    
    # Verify result
    assert len(result) == 1
    assert result[0]["id"] == "PL123"


@pytest.mark.asyncio
async def test_create_folder_uses_proxy():
    """Test that create_folder passes proxy-configured HTTP to build()."""
    credentials = json.dumps({"refresh_token": "test_token"})
    pub = YoutubePublisher(credentials=credentials)
    
    mock_http = MagicMock()
    mock_service = MagicMock()
    mock_playlists = MagicMock()
    mock_insert = MagicMock()
    
    # Setup mock chain
    mock_insert.execute.return_value = {
        "id": "PL456",
        "snippet": {"title": "New Playlist"}
    }
    mock_playlists.insert.return_value = mock_insert
    mock_service.playlists.return_value = mock_playlists
    
    with patch.object(pub, "_build_http_with_proxy", return_value=mock_http):
        with patch("google.oauth2.credentials.Credentials"):
            with patch("googleapiclient.discovery.build", return_value=mock_service) as mock_build:
                result = await pub.create_folder("New Playlist")
    
    # Verify build was called with our HTTP instance
    mock_build.assert_called_once()
    call_kwargs = mock_build.call_args.kwargs
    assert call_kwargs["http"] is mock_http
    
    # Verify result
    assert result["id"] == "PL456"
    assert result["name"] == "New Playlist"


@pytest.mark.asyncio
async def test_upload_uses_proxy(tmp_path):
    """Test that upload passes proxy-configured HTTP to build()."""
    credentials = json.dumps({"refresh_token": "test_token"})
    pub = YoutubePublisher(credentials=credentials)
    
    # Create a fake video file
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"fake video content")
    
    mock_http = MagicMock()
    mock_service = MagicMock()
    mock_videos = MagicMock()
    mock_insert = MagicMock()
    
    # Setup mock chain for upload
    mock_insert.next_chunk.return_value = (None, {"id": "VID789"})
    mock_videos.insert.return_value = mock_insert
    mock_service.videos.return_value = mock_videos
    
    with patch.object(pub, "_build_http_with_proxy", return_value=mock_http):
        with patch("google.oauth2.credentials.Credentials"):
            with patch("googleapiclient.discovery.build", return_value=mock_service) as mock_build:
                with patch("googleapiclient.http.MediaFileUpload"):
                    result = await pub.upload(
                        video_path=video_path,
                        title="Test Video",
                        description="Test Description"
                    )
    
    # Verify build was called with our HTTP instance
    mock_build.assert_called_once()
    call_kwargs = mock_build.call_args.kwargs
    assert call_kwargs["http"] is mock_http
    
    # Verify result
    assert result.success is True
    assert result.post_id == "VID789"


@pytest.mark.asyncio
async def test_proxy_respects_custom_timeout():
    """Test that proxy HTTP respects custom timeout settings."""
    credentials = json.dumps({"refresh_token": "test_token"})
    pub = YoutubePublisher(credentials=credentials)
    
    env_backup = os.environ.copy()
    
    try:
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
        
        # Mock config to return custom timeout
        with patch.object(pub, "_get_api_timeout", return_value=45.0):
            with patch("httplib2.socks") as mock_socks:
                mock_socks.PROXY_TYPE_HTTP = 3
                with patch("httplib2.Http") as mock_http_class:
                    with patch("httplib2.ProxyInfo"):
                        http = pub._build_http_with_proxy()
                        
                        # Verify timeout was passed
                        call_kwargs = mock_http_class.call_args.kwargs
                        assert call_kwargs["timeout"] == 45.0
    finally:
        os.environ.clear()
        os.environ.update(env_backup)

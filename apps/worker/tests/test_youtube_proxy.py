"""Tests for YouTube publisher proxy support."""

import json
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.publishers.youtube import YoutubePublisher


CREDS = json.dumps({"refresh_token": "rt"})


def _fake_google_modules():
    """Create fake google modules for testing without real dependencies."""
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

    apiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")
    
    # Mock build function that captures http argument
    def mock_build(name, version, credentials=None, http=None):
        service = MagicMock()
        service._http = http  # Store for inspection
        return service
    
    discovery.build = mock_build
    apiclient.discovery = discovery

    return {
        "google": google,
        "google.oauth2": oauth2,
        "google.oauth2.credentials": credentials,
        "googleapiclient": apiclient,
        "googleapiclient.discovery": discovery,
    }


def test_build_http_with_proxy_returns_none_when_no_proxy():
    """When no proxy is set, _build_http_with_proxy returns None."""
    pub = YoutubePublisher(credentials=CREDS)
    with patch.dict(os.environ, {}, clear=True):
        result = pub._build_http_with_proxy()
    assert result is None


def test_build_http_with_proxy_with_https_proxy():
    """When HTTPS_PROXY is set, _build_http_with_proxy returns configured Http."""
    pub = YoutubePublisher(credentials=CREDS)
    
    # Mock socks and httplib2
    mock_socks = MagicMock()
    mock_socks.PROXY_TYPE_HTTP = 3
    
    mock_httplib2 = MagicMock()
    mock_proxy_info = MagicMock()
    mock_httplib2.ProxyInfo.return_value = mock_proxy_info
    mock_http = MagicMock()
    mock_httplib2.Http.return_value = mock_http
    
    with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7890"}):
        with patch.dict(sys.modules, {"socks": mock_socks, "httplib2": mock_httplib2}):
            result = pub._build_http_with_proxy()
    
    # Verify ProxyInfo was called with correct arguments
    mock_httplib2.ProxyInfo.assert_called_once()
    call_kwargs = mock_httplib2.ProxyInfo.call_args[1]
    assert call_kwargs["proxy_type"] == 3  # PROXY_TYPE_HTTP
    assert call_kwargs["proxy_host"] == "127.0.0.1"
    assert call_kwargs["proxy_port"] == 7890
    
    # Verify Http was created with proxy_info
    mock_httplib2.Http.assert_called_once_with(proxy_info=mock_proxy_info)
    assert result == mock_http


def test_build_http_with_proxy_raises_clear_error_when_pysocks_missing():
    """When proxy is set but PySocks is missing, raise ImportError with clear message."""
    pub = YoutubePublisher(credentials=CREDS)
    
    with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7890"}):
        # Simulate PySocks not installed
        with patch.dict(sys.modules, {"socks": None}):
            with pytest.raises(ImportError) as exc_info:
                # Force reload to trigger import
                import importlib
                # Make import socks fail
                def mock_import(name, *args, **kwargs):
                    if name == "socks":
                        raise ImportError("No module named 'socks'")
                    return importlib.__import__(name, *args, **kwargs)
                
                with patch("builtins.__import__", side_effect=mock_import):
                    pub._build_http_with_proxy()
    
    assert "PySocks is required for proxy support" in str(exc_info.value)
    assert "pip install PySocks" in str(exc_info.value)


def test_build_http_with_proxy_handles_httplib2_socks_none():
    """Regression: when httplib2.socks is None, still build proxy Http using PySocks.
    
    This simulates the original bug where httplib2.socks was None (PySocks not
    wired properly) and code tried to access httplib2.socks.PROXY_TYPE_HTTP,
    causing AttributeError.
    """
    pub = YoutubePublisher(credentials=CREDS)
    
    # Mock socks from PySocks (the correct way)
    mock_socks = MagicMock()
    mock_socks.PROXY_TYPE_HTTP = 3
    
    # Mock httplib2 with socks = None (simulating the bug scenario)
    mock_httplib2 = MagicMock()
    mock_httplib2.socks = None  # This was the bug!
    mock_proxy_info = MagicMock()
    mock_httplib2.ProxyInfo.return_value = mock_proxy_info
    mock_http = MagicMock()
    mock_httplib2.Http.return_value = mock_http
    
    with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7890"}):
        with patch.dict(sys.modules, {"socks": mock_socks, "httplib2": mock_httplib2}):
            result = pub._build_http_with_proxy()
    
    # Should succeed by using socks.PROXY_TYPE_HTTP, not httplib2.socks.PROXY_TYPE_HTTP
    assert result == mock_http
    mock_httplib2.ProxyInfo.assert_called_once()


def test_build_http_with_proxy_supports_different_proxy_types():
    """Verify different proxy URL schemes map to correct proxy types."""
    pub = YoutubePublisher(credentials=CREDS)
    
    test_cases = [
        ("http://proxy:8080", "PROXY_TYPE_HTTP"),
        ("https://proxy:443", "PROXY_TYPE_HTTP"),
        ("socks5://proxy:1080", "PROXY_TYPE_SOCKS5"),
        ("socks4://proxy:1080", "PROXY_TYPE_SOCKS4"),
    ]
    
    for proxy_url, expected_type in test_cases:
        mock_socks = MagicMock()
        mock_socks.PROXY_TYPE_HTTP = 3
        mock_socks.PROXY_TYPE_SOCKS4 = 1
        mock_socks.PROXY_TYPE_SOCKS5 = 2
        
        mock_httplib2 = MagicMock()
        
        with patch.dict(os.environ, {"HTTPS_PROXY": proxy_url}):
            with patch.dict(sys.modules, {"socks": mock_socks, "httplib2": mock_httplib2}):
                pub._build_http_with_proxy()
        
        call_kwargs = mock_httplib2.ProxyInfo.call_args[1]
        expected_value = getattr(mock_socks, expected_type)
        assert call_kwargs["proxy_type"] == expected_value, f"Failed for {proxy_url}"


@pytest.mark.asyncio
async def test_list_folders_uses_proxy_http():
    """Verify list_folders passes proxy Http to googleapiclient.build()."""
    pub = YoutubePublisher(credentials=CREDS)
    
    mock_http = MagicMock()
    mock_build_calls = []
    
    def capture_build(name, version, credentials=None, http=None):
        mock_build_calls.append({'name': name, 'version': version, 'http': http})
        service = MagicMock()
        return service
    
    fake_mods = _fake_google_modules()
    fake_mods["googleapiclient.discovery"].build = capture_build
    
    # Mock _build_http_with_proxy to return our mock
    with patch.object(pub, "_build_http_with_proxy", return_value=mock_http):
        with patch.dict(sys.modules, fake_mods):
            # Mock the service response
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_future = MagicMock()
                mock_future.result.return_value = []
                mock_loop.return_value.run_in_executor.return_value = mock_future
                
                try:
                    await pub._list_playlists_real()
                except Exception:
                    pass  # We just care that build was called with http
    
    # Verify build was called with our mock http
    assert len(mock_build_calls) > 0, "build() should have been called"
    assert mock_build_calls[0]['http'] == mock_http, "build() should receive custom Http"


@pytest.mark.asyncio
async def test_list_folders_raises_on_proxy_error():
    """Verify list_folders raises ImportError when proxy configured but PySocks missing.
    
    Previously list_folders silently returned [] on any error, hiding proxy issues.
    """
    pub = YoutubePublisher(credentials=CREDS)
    
    # Make _build_http_with_proxy raise ImportError
    with patch.object(pub, "_build_http_with_proxy", side_effect=ImportError("PySocks required")):
        with patch.dict(sys.modules, _fake_google_modules()):
            with pytest.raises(ImportError) as exc_info:
                await pub.list_folders()
    
    assert "PySocks required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_list_folders_no_longer_silently_returns_empty_on_error():
    """Regression: list_folders should not return [] when build/proxy fails with credentials present."""
    pub = YoutubePublisher(credentials=CREDS)
    
    # Simulate a proxy build error
    with patch.object(pub, "_list_playlists_real", side_effect=RuntimeError("proxy build failed")):
        with pytest.raises(RuntimeError) as exc_info:
            await pub.list_folders()
    
    assert "proxy build failed" in str(exc_info.value)

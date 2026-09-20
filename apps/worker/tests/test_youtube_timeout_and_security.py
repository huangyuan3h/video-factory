"""Tests for YouTube API timeout handling and credential security."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import get_session
from src.models import PublisherAccount
from src.publishers.youtube import GoogleAPITimeoutError, YoutubePublisher
from src.routes import publishers as pub_route


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def execute(self, stmt):
        return _Result(self.rows)

    def add(self, obj):
        self.rows.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(pub_route.router, prefix="/api/publishers")
    holder = {"session": _FakeSession()}

    async def override():
        yield holder["session"]

    app.dependency_overrides[get_session] = override
    test_client = TestClient(app)
    test_client.holder = holder
    return test_client


# ========== TIMEOUT TESTS ==========


@pytest.mark.asyncio
async def test_list_folders_timeout():
    """Test that list_folders times out instead of hanging when Google API is unreachable."""
    pub = YoutubePublisher(credentials=json.dumps({"refresh_token": "test_token"}))
    
    # Mock to raise GoogleAPITimeoutError which list_folders catches
    with patch.object(pub, "_list_playlists_real", side_effect=GoogleAPITimeoutError("timeout")):
        folders = await pub.list_folders()
    
    # Should return empty list when underlying call times out
    assert folders == []


@pytest.mark.asyncio
async def test_list_folders_raises_timeout_error():
    """Test that _list_playlists_real raises GoogleAPITimeoutError on timeout."""
    pub = YoutubePublisher(credentials=json.dumps({"refresh_token": "test_token"}))
    
    # Mock asyncio.wait_for to raise TimeoutError immediately
    async def fake_wait_for(coro, timeout):
        raise asyncio.TimeoutError()
    
    with patch("googleapiclient.discovery.build"):
        with patch("google.oauth2.credentials.Credentials"):
            with patch("asyncio.wait_for", side_effect=fake_wait_for):
                with patch.object(pub, "_get_api_timeout", return_value=0.1):
                    with pytest.raises(GoogleAPITimeoutError) as exc_info:
                        await pub._list_playlists_real()
    
    assert "timed out" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_create_folder_timeout():
    """Test that create_folder times out instead of hanging."""
    pub = YoutubePublisher(credentials=json.dumps({"refresh_token": "test_token"}))
    
    # Mock asyncio.wait_for to raise TimeoutError
    async def fake_wait_for(coro, timeout):
        raise asyncio.TimeoutError()
    
    with patch("googleapiclient.discovery.build"):
        with patch("google.oauth2.credentials.Credentials"):
            with patch("asyncio.wait_for", side_effect=fake_wait_for):
                with patch.object(pub, "_get_api_timeout", return_value=0.1):
                    with pytest.raises(GoogleAPITimeoutError):
                        await pub.create_folder("Test Playlist")


@pytest.mark.asyncio
async def test_upload_timeout(tmp_path):
    """Test that upload wrapper catches timeout and returns error result."""
    pub = YoutubePublisher(credentials=json.dumps({"refresh_token": "test_token"}))
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake video data")
    
    # Mock the build to return a service, then mock wait_for to timeout
    mock_service = MagicMock()
    
    async def fake_wait_for(coro, timeout):
        # Timeout on the actual upload operation
        raise asyncio.TimeoutError()
    
    with patch("googleapiclient.discovery.build", return_value=mock_service):
        with patch("google.oauth2.credentials.Credentials"):
            with patch("googleapiclient.http.MediaFileUpload"):
                with patch("asyncio.wait_for", side_effect=fake_wait_for):
                    with patch.object(pub, "_get_api_timeout", return_value=0.1):
                        result = await pub.upload(video, "Test Title", description="Test")
    
    # Should return a failed PublishResult with timeout error
    assert result.success is False
    assert ("timeout" in result.error.lower() or "timed out" in result.error.lower())


def test_list_folders_endpoint_timeout_returns_504(client):
    """Test that the /folders endpoint returns 504 on timeout instead of hanging."""
    acc = PublisherAccount(
        id="timeout1",
        platform="youtube",
        name="YT Timeout",
        credentials=json.dumps({"refresh_token": "test"})
    )
    client.holder["session"].rows.append(acc)
    
    fake_pub = AsyncMock()
    fake_pub.list_folders = AsyncMock(side_effect=GoogleAPITimeoutError("Request timed out after 30s"))
    
    with patch.object(pub_route, "get_publisher", return_value=fake_pub):
        resp = client.get("/api/publishers/timeout1/folders")
    
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()


def test_create_folder_endpoint_timeout_returns_504(client):
    """Test that the /folders POST endpoint returns 504 on timeout."""
    acc = PublisherAccount(
        id="timeout2",
        platform="youtube",
        name="YT Timeout",
        credentials=json.dumps({"refresh_token": "test"})
    )
    client.holder["session"].rows.append(acc)
    
    fake_pub = AsyncMock()
    fake_pub.create_folder = AsyncMock(side_effect=GoogleAPITimeoutError("Request timed out after 30s"))
    
    with patch.object(pub_route, "get_publisher", return_value=fake_pub):
        resp = client.post("/api/publishers/timeout2/folders", json={"name": "Test Playlist"})
    
    assert resp.status_code == 504
    assert "timed out" in resp.json()["detail"].lower()


# ========== CREDENTIAL REDACTION TESTS ==========


def test_list_publishers_redacts_credentials(client):
    """Test that GET /publishers does not expose raw credentials/cookies."""
    acc = PublisherAccount(
        id="sec1",
        platform="youtube",
        name="YT Secret",
        credentials=json.dumps({"refresh_token": "SUPER_SECRET_TOKEN", "client_secret": "CLIENT_SECRET"}),
        cookies="[{'name':'sid','value':'SECRET_COOKIE'}]"
    )
    client.holder["session"].rows.append(acc)
    
    resp = client.get("/api/publishers")
    assert resp.status_code == 200
    
    data = resp.json()["data"]
    assert len(data) == 1
    pub_data = data[0]
    
    # Should NOT contain raw credentials
    assert "credentials" not in pub_data
    assert "cookies" not in pub_data
    assert "SUPER_SECRET_TOKEN" not in json.dumps(pub_data)
    assert "SECRET_COOKIE" not in json.dumps(pub_data)
    
    # Should contain presence indicators
    assert pub_data["has_credentials"] is True
    assert pub_data["has_cookies"] is True


def test_get_publisher_redacts_credentials(client):
    """Test that GET /publishers/{id} does not expose raw credentials/cookies."""
    acc = PublisherAccount(
        id="sec2",
        platform="youtube",
        name="YT Secret",
        credentials=json.dumps({"access_token": "ACCESS_TOKEN_SECRET"}),
        cookies=None
    )
    client.holder["session"].rows.append(acc)
    
    resp = client.get("/api/publishers/sec2")
    assert resp.status_code == 200
    
    pub_data = resp.json()["data"]
    
    # Should NOT contain raw credentials
    assert "credentials" not in pub_data
    assert "cookies" not in pub_data
    assert "ACCESS_TOKEN_SECRET" not in json.dumps(pub_data)
    
    # Should contain presence indicators
    assert pub_data["has_credentials"] is True
    assert pub_data["has_cookies"] is False


def test_create_publisher_accepts_credentials(client):
    """Test that POST /publishers still accepts credentials for creation."""
    resp = client.post(
        "/api/publishers",
        json={
            "platform": "youtube",
            "name": "New YT",
            "credentials": json.dumps({"refresh_token": "NEW_TOKEN"}),
        }
    )
    assert resp.status_code == 200
    
    # Response should be redacted
    pub_data = resp.json()["data"]
    assert "credentials" not in pub_data
    assert pub_data["has_credentials"] is True
    assert "NEW_TOKEN" not in json.dumps(pub_data)


def test_update_publisher_accepts_credentials(client):
    """Test that PUT /publishers/{id} still accepts credentials for update."""
    acc = PublisherAccount(id="sec3", platform="youtube", name="YT")
    client.holder["session"].rows.append(acc)
    
    resp = client.put(
        "/api/publishers/sec3",
        json={"credentials": json.dumps({"refresh_token": "UPDATED_TOKEN"})}
    )
    assert resp.status_code == 200
    
    # Response should be redacted
    pub_data = resp.json()["data"]
    assert "credentials" not in pub_data
    assert pub_data["has_credentials"] is True
    assert "UPDATED_TOKEN" not in json.dumps(pub_data)
    
    # DB should have the actual credentials
    assert acc.credentials == json.dumps({"refresh_token": "UPDATED_TOKEN"})


def test_empty_credentials_shows_false(client):
    """Test that missing credentials show as has_credentials=False."""
    acc = PublisherAccount(
        id="sec4",
        platform="douyin",
        name="DY No Creds",
        credentials=None,
        cookies=None
    )
    client.holder["session"].rows.append(acc)
    
    resp = client.get("/api/publishers/sec4")
    assert resp.status_code == 200
    
    pub_data = resp.json()["data"]
    assert pub_data["has_credentials"] is False
    assert pub_data["has_cookies"] is False

"""Tests for YouTube publisher real-API code paths with mocked Google libs."""

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.publishers.youtube import YoutubePublisher


class _Exec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data

    def next_chunk(self):
        return (None, self._data)


class _Service:
    def playlists(self):
        return SimpleNamespace(
            list=lambda **k: _Exec(
                {
                    "items": [
                        {"id": "p1", "snippet": {"title": "PL"}, "contentDetails": {"itemCount": 3}}
                    ]
                }
            ),
            insert=lambda **k: _Exec({"id": "newp", "snippet": {"title": "New PL"}}),
        )

    def videos(self):
        return SimpleNamespace(insert=lambda **k: _Exec({"id": "vid1"}))

    def playlistItems(self):
        return SimpleNamespace(insert=lambda **k: _Exec({}))


def _fake_modules():
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
    discovery.build = lambda name, version, credentials=None, http=None, **kwargs: _Service()
    http = types.ModuleType("googleapiclient.http")

    class _Media:
        def __init__(self, *args, **kwargs):
            pass

    http.MediaFileUpload = _Media
    apiclient.discovery = discovery
    apiclient.http = http

    return {
        "google": google,
        "google.oauth2": oauth2,
        "google.oauth2.credentials": credentials,
        "googleapiclient": apiclient,
        "googleapiclient.discovery": discovery,
        "googleapiclient.http": http,
    }


CREDS = json.dumps({"refresh_token": "rt"})


@pytest.mark.asyncio
async def test_list_playlists_real():
    pub = YoutubePublisher(credentials=CREDS)
    with patch.dict(sys.modules, _fake_modules()):
        folders = await pub.list_folders()
    assert folders == [{"id": "p1", "name": "PL", "itemCount": 3}]


@pytest.mark.asyncio
async def test_create_folder_real():
    pub = YoutubePublisher(credentials=CREDS)
    with patch.dict(sys.modules, _fake_modules()):
        result = await pub.create_folder("New PL")
    assert result == {"id": "newp", "name": "New PL"}


@pytest.mark.asyncio
async def test_upload_real(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    pub = YoutubePublisher(credentials=CREDS)
    with patch.dict(sys.modules, _fake_modules()):
        result = await pub.upload(video, "Title", description="d", folder_id="p1")
    assert result.success is True
    assert result.post_id == "vid1"
    assert result.post_url.endswith("vid1")


@pytest.mark.asyncio
async def test_upload_real_failure(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"data")
    pub = YoutubePublisher(credentials=CREDS)

    def raiser(name, version, credentials=None, http=None, **kwargs):
        raise RuntimeError("api down")

    mods = _fake_modules()
    mods["googleapiclient.discovery"].build = raiser
    with patch.dict(sys.modules, mods):
        result = await pub.upload(video, "Title")
    assert result.success is False
    assert "api down" in (result.error or "")

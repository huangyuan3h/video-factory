"""Upload the daily-news MVP sample as UNLISTED into a new unlisted playlist.

Never prints credentials. Privacy is forced to unlisted; never public.
Usage (proxy required for YouTube API):
    cd apps/worker
    HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 \
      .venv/bin/python scripts/upload_news_mvp.py \
        --task-dir ../../data/output/daily_news/mvp-2026-09-25 [--playlist]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from sqlalchemy import select  # noqa: E402

from src import database  # noqa: E402
from src.models import PublisherAccount  # noqa: E402
from src.publishers import get_publisher  # noqa: E402

PUB_ID = "e58dcc1f7a1c8c8b"
PLAYLIST = "每日财经"
PL_DESC = "每天一只财经新闻视频：只讲有出处的数据，配Karios早报快照解读。主讲：躺平的老黄。个人解读，不构成投资建议。"


async def publisher():
    async with database.async_session_maker() as s:
        acc = (await s.execute(select(PublisherAccount).where(PublisherAccount.id == PUB_ID))).scalar_one()
    assert acc.name == "Yuan YouTube", acc.name
    return get_publisher(acc.platform, credentials=acc.credentials or acc.cookies, folder_id=acc.folder_id)


async def ensure_playlist(pub):
    for f in await pub.list_folders():
        if f.get("name") == PLAYLIST:
            print("REUSE playlist", f.get("id"), flush=True)
            return f.get("id")
    f = await pub.create_folder(PLAYLIST, description=PL_DESC, privacy="unlisted")
    print("CREATED playlist", json.dumps(f, ensure_ascii=False), flush=True)
    return (f or {}).get("id")


async def main(args) -> int:
    task = Path(args.task_dir)
    pub = await publisher()
    if args.playlist:
        await ensure_playlist(pub)
        return 0
    meta = json.loads((task / "upload_meta.json").read_text(encoding="utf-8"))
    video = task / "render" / "output.mp4"
    playlist_id = await ensure_playlist(pub)
    res = await pub.upload(
        video_path=video, title=meta["title"], description=meta["description"],
        tags=meta["tags"], folder_id=playlist_id, playlist_id=playlist_id,
        privacy="unlisted", category_id=meta.get("category_id", "25"),
        default_language="zh-CN",
    )
    print("UPLOAD", json.dumps(
        {"success": res.success, "post_url": res.post_url, "post_id": res.post_id,
         "error": res.error}, ensure_ascii=False), flush=True)
    (task / "upload.json").write_text(json.dumps(
        {"success": res.success, "post_url": res.post_url, "post_id": res.post_id,
         "error": res.error, "playlist": PLAYLIST, "playlist_id": playlist_id,
         "privacy": "unlisted"}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if res.success else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--playlist", action="store_true")
    asyncio.run(main(ap.parse_args()))

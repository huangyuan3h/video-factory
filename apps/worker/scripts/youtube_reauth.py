#!/usr/bin/env python
"""YouTube OAuth re-auth for Video Factory (installed-app flow).

Reads the existing client_id/client_secret from the current token stores,
runs the installed-app OAuth flow with the SAME scopes the uploader needs,
opens the consent page in the user's default browser automatically, goes
through the proxy, and writes the new token to EVERY place the uploaders
read, keeping a timestamped backup of the old one.

Never prints secrets or tokens to logs (only presence/lengths/paths).

Usage (run from apps/worker):
    cd apps/worker
    HTTPS_PROXY=http://127.0.0.1:7890 uv run python scripts/youtube_reauth.py [--pub-id ID]

Writes to:
  1. DB PublisherAccount.credentials (id = PUB_ID, default Yuan YouTube)
  2. File data/secrets/youtube-oauth-token.json (legacy copy, same JSON)
Backups (timestamped, alongside the token file):
  - youtube-oauth-token.backup-YYYYMMDD-HHMMSS.json (old file copy)
  - youtube-oauth-db.backup-YYYYMMDD-HHMMSS.json (old DB credentials copy)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

# Make `src` importable when run as `python scripts/youtube_reauth.py`
# from apps/worker. Also work when invoked via repo-root shim.
_THIS = Path(__file__).resolve()
_CANDIDATES = [
    _THIS.parent.parent,  # apps/worker/scripts/ -> apps/worker/
    _THIS.parent.parent / "apps" / "worker",  # repo/scripts/ -> repo/apps/worker
]
WORKER_DIR = next((p for p in _CANDIDATES if (p / "src" / "database.py").exists()), None)
if WORKER_DIR is None:
    print("REAUTH_FAIL cannot locate apps/worker/src", file=sys.stderr)
    raise SystemExit(1)
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))
os.chdir(WORKER_DIR)

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
]
DEFAULT_PUB_ID = "e58dcc1f7a1c8c8b"
DEFAULT_TOKEN_FILE = Path("data/secrets/youtube-oauth-token.json")
PROXY_URL = "http://127.0.0.1:7890"


def ensure_proxy() -> None:
    os.environ.setdefault("HTTPS_PROXY", PROXY_URL)
    os.environ.setdefault("HTTP_PROXY", PROXY_URL)
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = {p.strip() for p in no_proxy.split(",") if p.strip()}
    parts.update({"127.0.0.1", "localhost"})
    os.environ["NO_PROXY"] = ",".join(sorted(parts))
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    print(f"REAUTH proxy configured (HTTPS_PROXY set={bool(os.environ.get('HTTPS_PROXY'))})")


def load_file_token(path: Path) -> dict | None:
    try:
        if not path.exists():
            print(f"REAUTH file token: missing at {path}")
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        print(f"REAUTH file token: present len={len(path.read_text(encoding='utf-8'))} keys={len(data)} has_refresh={bool(data.get('refresh_token'))}")
        return data
    except Exception as e:
        print(f"REAUTH file token: unreadable ({type(e).__name__})")
        return None


async def load_db_token(pub_id: str) -> tuple[dict | None, str | None]:
    from sqlalchemy import select

    from src import database
    from src.models import PublisherAccount

    async with database.async_session_maker() as session:
        acc = (await session.execute(select(PublisherAccount).where(PublisherAccount.id == pub_id))).scalar_one_or_none()
        if acc is None:
            print(f"REAUTH db token: no PublisherAccount id={pub_id}")
            return None, None
        raw = acc.credentials or acc.cookies
        if not raw:
            print(f"REAUTH db token: empty credentials for id={pub_id} name={acc.name}")
            return None, acc.name
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            print(f"REAUTH db token: present name={acc.name} cred_len={len(raw)} has_refresh={bool(data.get('refresh_token'))}")
            return data, acc.name
        except Exception:
            print(f"REAUTH db token: unparsable for id={pub_id}")
            return None, acc.name


async def write_db_token(pub_id: str, new_json: str) -> None:
    from sqlalchemy import select

    from src import database
    from src.models import PublisherAccount

    async with database.async_session_maker() as session:
        acc = (await session.execute(select(PublisherAccount).where(PublisherAccount.id == pub_id))).scalar_one()
        acc.credentials = new_json
        await session.commit()
    print(f"REAUTH db token: updated id={pub_id} new_len={len(new_json)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="YouTube re-auth (installed-app flow)")
    ap.add_argument("--pub-id", default=DEFAULT_PUB_ID)
    ap.add_argument("--token-file", default=str(DEFAULT_TOKEN_FILE))
    ap.add_argument("--port", type=int, default=0, help="local callback port (0=ephemeral)")
    ap.add_argument("--timeout", type=int, default=1800, help="wait up to N seconds for consent")
    args = ap.parse_args()

    ensure_proxy()

    import asyncio

    token_path = Path(args.token_file)
    if not token_path.is_absolute():
        token_path = WORKER_DIR / token_path

    file_data = load_file_token(token_path)
    db_data, acc_name = asyncio.run(load_db_token(args.pub_id))

    src = db_data or file_data
    if src is None:
        # last resort: env (names only in logs)
        if os.environ.get("YOUTUBE_CLIENT_ID") and os.environ.get("YOUTUBE_CLIENT_SECRET"):
            client_id = os.environ["YOUTUBE_CLIENT_ID"]
            client_secret = os.environ["YOUTUBE_CLIENT_SECRET"]
            print("REAUTH client: from env YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET")
        else:
            print("REAUTH_FAIL no client_id/client_secret found (checked DB, token file, env).", file=sys.stderr)
            print("REAUTH_FAIL Ask the owner for the Google Cloud OAuth client (Desktop type) and set YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET, then re-run.", file=sys.stderr)
            return 1
    else:
        client_id = src.get("client_id") or ""
        client_secret = src.get("client_secret") or ""
        where = "DB" if db_data else "file"
        print(f"REAUTH client: from {where} (client_id_len={len(client_id)} has_secret={bool(client_secret)})")
        if not client_id or not client_secret:
            print("REAUTH_FAIL stored token has no client_id/client_secret; set YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET env and re-run.", file=sys.stderr)
            return 1

    # Timestamped backups of the OLD token (never log contents).
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        if token_path.exists():
            bak = token_path.parent / f"youtube-oauth-token.backup-{ts}.json"
            bak.write_text(token_path.read_text(encoding="utf-8"), encoding="utf-8")
            try:
                os.chmod(bak, 0o600)
            except Exception:
                pass
            print(f"REAUTH backup: file -> {bak}")
        if db_data is not None:
            db_bak = token_path.parent / f"youtube-oauth-db.backup-{ts}.json"
            db_bak.write_text(json.dumps(db_data), encoding="utf-8")
            try:
                os.chmod(db_bak, 0o600)
            except Exception:
                pass
            print(f"REAUTH backup: db -> {db_bak}")
    except Exception as e:
        print(f"REAUTH_FAIL backup failed ({type(e).__name__})", file=sys.stderr)
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    print("REAUTH opening browser for consent (choose the channel account and Allow)...")
    try:
        # open_browser=True uses the default browser (`open <url>` on macOS).
        # access_type=offline + prompt=consent forces a refresh_token.
        flow.run_local_server(
            port=args.port,
            open_browser=True,
            timeout_seconds=args.timeout,
            access_type="offline",
            prompt="consent",
            authorization_prompt_message="REAUTH open this URL in your browser:\n{url}\n",
            success_message="YouTube 授权成功，可以关闭此页面回到终端。",
        )
    except Exception as e:
        print(f"REAUTH_FAIL consent flow failed ({type(e).__name__}: {e})", file=sys.stderr)
        return 1

    creds = flow.credentials
    try:
        new_json = creds.to_json()
        new_data = json.loads(new_json)
    except Exception:
        print("REAUTH_FAIL could not serialize new credentials", file=sys.stderr)
        return 1
    if not new_data.get("refresh_token"):
        print("REAUTH_FAIL new credentials have no refresh_token (need access_type=offline + consent). Re-run and accept all scopes.", file=sys.stderr)
        return 1
    print(f"REAUTH consent: received new token (has_refresh=True scopes_n={len(new_data.get('scopes', []))})")

    # Write to EVERY place the uploaders read.
    try:
        token_path.write_text(new_json, encoding="utf-8")
        try:
            os.chmod(token_path, 0o600)
        except Exception:
            pass
        print(f"REAUTH wrote file {token_path} new_len={len(new_json)}")
    except Exception as e:
        print(f"REAUTH_FAIL writing token file ({type(e).__name__})", file=sys.stderr)
        return 1

    try:
        asyncio.run(write_db_token(args.pub_id, new_json))
    except Exception as e:
        print(f"REAUTH_FAIL writing DB ({type(e).__name__})", file=sys.stderr)
        return 1

    # Light verify: credentials parse + (optional) channel check goes in step 4.
    print("REAUTH_OK re-auth complete (file + DB updated, backups kept). Next: verify channel/playlist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

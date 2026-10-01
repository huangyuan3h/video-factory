#!/usr/bin/env python
"""CLI: publish one Bilibili video from a ``publish_payload.json``.

Headless-by-default reusable tool (persistent profile). Examples::

    cd apps/worker
    uv run python -m src.publishers.bili_publish --payload /path/to/publish_payload.json --draft-only
    uv run python -m src.publishers.bili_publish --payload /path/to/publish_payload.json --mode publish
    uv run python -m src.publishers.bili_publish --payload <path> --mode publish --headed --force --no-open
    scripts/bili_publish.sh <payload> [--draft-only] [--headed]

Modes:
  draft   — upload, fill form, screenshot filled form. Never publishes.
  publish — same as draft, then click publish only if verification passes.

Headless:
  Default is headless=True with the persistent profile. A cheap
  member-page login check runs first; only when login/QR/captcha/risk
  control is needed does the tool close headless, relaunch the SAME profile
  headed (visible), notify the owner (``B站需要扫码登录``), wait up to
  10 min, then continue automatically.

Idempotency:
  In publish mode, refuses when ``published.json`` already holds a URL/BV
  unless ``--force`` is given.

On publish success: prints the URL/BV, saves ``published.json`` (url +
bvid + status + timestamp + screenshots) next to the payload, and
``open <url>`` in the default browser unless ``--no-open``.

Exit code 0 on draft/published, 2 on BLOCKED (login/verification), 1 on error.
Final line printed is ``PUBLISH DONE`` or ``DRAFT DONE`` or ``BLOCKED: <reason>``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.publishers.bili import (  # noqa: E402
    DEFAULT_PROFILE_DIR,
    DEFAULT_SMOKE_DIR,
    BiliPublisher,
    cleanup_own_chrome_processes,
    is_already_published,
    open_url_in_browser,
    verify_public_logged_out,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bili_publish",
        description="Publish one Bilibili video (headless-by-default, official web only). Exactly one video per run.",
    )
    p.add_argument("--payload", type=Path, required=True, help="Path to publish_payload.json")
    p.add_argument("--mode", choices=("draft", "publish"), default="draft")
    p.add_argument(
        "--draft-only",
        action="store_true",
        help="Draft only: fill + verify, never publish (overrides --mode).",
    )
    p.add_argument(
        "--headed",
        action="store_true",
        help="Run with a visible Chrome window (default is headless=True).",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Force headless (default is already headless; overrides --headed).",
    )
    p.add_argument(
        "--no-open",
        action="store_true",
        help="Do not `open <url>` in the default browser after publish.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Publish even when published.json already holds a URL/BV.",
    )
    p.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_DIR)
    p.add_argument("--smoke-dir", type=Path, default=DEFAULT_SMOKE_DIR)
    p.add_argument("--smoke-label", default="ep1")
    p.add_argument("--login-timeout-s", type=int, default=10 * 60)
    p.add_argument("--skip-logged-out-check", action="store_true")
    return p


def resolve_mode(args) -> str:
    if getattr(args, "draft_only", False):
        return "draft"
    return args.mode


def resolve_headless(args) -> bool:
    if getattr(args, "headless", False):
        return True
    if getattr(args, "headed", False):
        return False
    return True


async def _run(args) -> int:
    mode = resolve_mode(args)
    headless = resolve_headless(args)
    if mode == "publish" and not args.force:
        already, rec = is_already_published(args.payload)
        if already:
            print(
                f"ERROR: already published: {rec.get('url')} "
                f"(at {rec.get('published_at', '?')}); pass --force to republish",
                file=sys.stderr,
                flush=True,
            )
            print(json.dumps({"status": "error", "public_url": rec.get("url")}, ensure_ascii=False, indent=2))
            return 1
    pub = BiliPublisher(
        profile_dir=args.profile,
        headless=headless,
        smoke_dir=args.smoke_dir,
        login_timeout_s=args.login_timeout_s,
    )
    try:
        res = await pub.publish_video_from_payload(
            args.payload,
            mode=mode,
            smoke_label=args.smoke_label,
            force=args.force,
            no_open=args.no_open,
        )
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        try:
            cleanup_own_chrome_processes(args.profile)
        except Exception:  # noqa: BLE001
            pass
        return 1
    # BLOCKED keeps the window visible (publisher left it open); do not sweep.
    status = res.get("status")
    if status == "blocked":
        print(f"BLOCKED: {res.get('reason', 'unknown')}", flush=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 2
    try:
        cleanup_own_chrome_processes(args.profile)
    except Exception:  # noqa: BLE001
        pass
    if status == "error":
        print(f"ERROR: {res.get('error', 'unknown')}", file=sys.stderr, flush=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 1
    if status == "published" and not args.skip_logged_out_check and res.get("public_url"):
        url = res["public_url"]
        if url.startswith("http") and "BV" in (res.get("bvid") or url):
            out = Path(args.smoke_dir) / f"{args.smoke_label}_logged_out.png"
            check = await verify_public_logged_out(url, out)
            res["logged_out_check"] = check
            if not check.get("ok"):
                print(f"NOTE: logged-out check inconclusive: {check.get('reason')}", flush=True)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if status == "published":
        url = res.get("public_url")
        if url:
            print(f"PUBLISHED URL: {url}", flush=True)
        bvid = res.get("bvid")
        if bvid:
            print(f"BVID: {bvid}", flush=True)
        if url and url.startswith("http") and not args.no_open:
            open_url_in_browser(url)
        print("PUBLISH DONE", flush=True)
    else:
        print("DRAFT DONE", flush=True)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.payload.exists():
        print(f"ERROR: payload not found: {args.payload}", file=sys.stderr)
        return 1
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("BLOCKED: interrupted", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

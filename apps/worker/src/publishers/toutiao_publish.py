#!/usr/bin/env python
"""CLI: publish one Toutiao article from a ``toutiao_payload.json``.

Headless-by-default reusable tool (persistent profile). Examples::

    cd apps/worker
    uv run python -m src.publishers.toutiao_publish --payload /path/to/toutiao_payload.json --mode draft
    uv run python -m src.publishers.toutiao_publish --payload /path/to/toutiao_payload.json --mode publish
    scripts/toutiao_publish.sh <payload> --mode draft
    scripts/toutiao_publish.sh <payload> --mode publish --no-open

Modes:
  draft   — write, save as draft, reload + verify, screenshot. Never publishes.
  publish — same as draft, then click publish only if verification passes.
            (Implemented but NOT exercised in the smoke test; smoke runs draft.)

Headless:
  Default is headless=True with the persistent profile. A cheap MP-page
  login check runs first; only when login/QR/captcha/verification is needed
  does the tool close headless, relaunch the SAME profile headed (visible),
  notify the owner (头条冒烟：请用今日头条或抖音App扫码登录), wait up to
  20 min, then continue automatically.

Contract:
  - NEVER ticks 首发 (ensures unchecked; refuses publish otherwise).
  - Ticks 原创 if available; sets AI declaration if the panel has one.
  - Cover is ensured to 1024x678 before upload.

Exit code 0 on draft/published, 2 on BLOCKED (login/verification/onboarding), 1 on error.
Final line printed is ``PUBLISH DONE`` or ``DRAFT DONE`` or ``BLOCKED: <reason>``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.publishers.toutiao import (  # noqa: E402
    DEFAULT_PROFILE_DIR,
    DEFAULT_SMOKE_DIR,
    ToutiaoPublisher,
    cleanup_own_chrome_processes,
    is_already_published,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="toutiao_publish",
        description="Publish one Toutiao article (headless-by-default). Exactly one article per run.",
    )
    p.add_argument("--payload", type=Path, required=True, help="Path to toutiao_payload.json")
    p.add_argument("--mode", choices=("draft", "publish"), default="draft")
    p.add_argument("--draft-only", action="store_true", help="Draft only (overrides --mode).")
    p.add_argument("--headed", action="store_true", help="Run visible (default headless=True).")
    p.add_argument("--headless", action="store_true", default=False, help="Force headless.")
    p.add_argument("--no-open", action="store_true", help="Do not open URL after publish.")
    p.add_argument("--force", action="store_true", help="Publish even when published.json has URL.")
    p.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_DIR)
    p.add_argument("--smoke-dir", type=Path, default=DEFAULT_SMOKE_DIR)
    p.add_argument("--smoke-label", default="toutiao_smoke")
    p.add_argument("--login-timeout-s", type=int, default=20 * 60)
    p.add_argument("--draft-url", default=None, help="Reuse existing draft URL (not used for Toutiao v1).")
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
            print(f"ERROR: already published: {rec.get('url')} (at {rec.get('published_at','?')}); pass --force to republish",
                  file=sys.stderr, flush=True)
            print(json.dumps({"status": "error", "public_url": rec.get("url")}, ensure_ascii=False, indent=2))
            return 1
    pub = ToutiaoPublisher(profile_dir=args.profile, headless=headless,
                           smoke_dir=args.smoke_dir, login_timeout_s=args.login_timeout_s)
    try:
        res = await pub.publish_article_from_payload(args.payload, mode=mode,
                                                     smoke_label=args.smoke_label,
                                                     draft_url=args.draft_url, force=args.force)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        try:
            cleanup_own_chrome_processes(args.profile)
        except Exception:
            pass
        return 1
    try:
        cleanup_own_chrome_processes(args.profile)
    except Exception:
        pass
    status = res.get("status")
    if status == "blocked":
        print(f"BLOCKED: {res.get('reason','unknown')}", flush=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 2
    if status == "error":
        print(f"ERROR: {res.get('error','unknown')}", file=sys.stderr, flush=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if status == "published":
        url = res.get("public_url")
        if url:
            print(f"PUBLISHED URL: {url}", flush=True)
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

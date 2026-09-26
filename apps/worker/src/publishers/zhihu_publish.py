#!/usr/bin/env python
"""CLI: publish one Zhihu 专栏 article from a ``publish_payload.json``.

Examples::

    cd apps/worker
    uv run python -m src.publishers.zhihu_publish --payload /path/to/publish_payload.json --mode draft
    uv run python -m src.publishers.zhihu_publish --payload /path/to/publish_payload.json --mode publish
    uv run python scripts/zhihu_publish.py --payload <path> --mode publish

Modes:
  draft   — write, save as draft, reload + verify, screenshot. Never publishes.
  publish — same as draft, then click publish only if verification passes.

Exit code 0 on draft/published, 2 on BLOCKED (login/verification), 1 on error.
Final line printed is ``PUBLISH DONE`` or ``BLOCKED: <reason>``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.publishers.zhihu import (  # noqa: E402
    DEFAULT_PROFILE_DIR,
    DEFAULT_SMOKE_DIR,
    ZhihuPublisher,
    verify_public_logged_out,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zhihu_publish",
        description="Publish one Zhihu 专栏 article (ep9 smoke test). Exactly one article per run.",
    )
    p.add_argument("--payload", type=Path, required=True, help="Path to publish_payload.json")
    p.add_argument("--mode", choices=("draft", "publish"), default="draft")
    p.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_DIR)
    p.add_argument("--smoke-dir", type=Path, default=DEFAULT_SMOKE_DIR)
    p.add_argument("--smoke-label", default="ep9")
    p.add_argument("--login-timeout-s", type=int, default=20 * 60)
    p.add_argument("--skip-logged-out-check", action="store_true")
    return p


async def _run(args) -> int:
    pub = ZhihuPublisher(
        profile_dir=args.profile,
        headless=False,
        smoke_dir=args.smoke_dir,
        login_timeout_s=args.login_timeout_s,
    )
    res = await pub.publish_article_from_payload(args.payload, mode=args.mode, smoke_label=args.smoke_label)
    status = res.get("status")
    if status == "blocked":
        print(f"BLOCKED: {res.get('reason', 'unknown')}", flush=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 2
    if status == "error":
        print(f"ERROR: {res.get('error', 'unknown')}", file=sys.stderr, flush=True)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 1
    # draft or published — optionally verify the public URL logged-out.
    if status == "published" and not args.skip_logged_out_check and res.get("public_url"):
        out = Path(args.smoke_dir) / f"{args.smoke_label}_logged_out.png"
        check = await verify_public_logged_out(res["public_url"], out)
        res["logged_out_check"] = check
        if not check.get("ok"):
            print(f"NOTE: logged-out check inconclusive: {check.get('reason')}", flush=True)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print("PUBLISH DONE" if status == "published" else "DRAFT DONE", flush=True)
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

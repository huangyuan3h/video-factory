"""Upload description funnel template + checker (Phase 4).

Every upload needs a funnel link + playlist CTA + disclaimer, but shipped
descriptions historically contain zero http links (see ``ep/yt/ep21.json`` in
the daily-routine checkout). ``vf publish --check-funnel`` checks a description
against this template without publishing anything.

The canonical Karios funnel URL defaults to ``https://zhibiao.it-t.xyz/request``
(owner-approved tentative; swap when the paid page lands). Set ``VF_FUNNEL_URL``
or pass ``funnel_url=`` explicitly to override.
"""

from __future__ import annotations

import os

PLAYLIST_ID = "PLJ8z9DDMq_Yg"
PLAYLIST_NAME = "什么指标不赚钱"
PRESENTER = "躺平的老黄"
DISCLAIMER = "本内容为投资者教育，不构成投资建议，过往业绩不代表未来表现。投资有风险，入市需谨慎。"
FUNNEL_ENV_VAR = "VF_FUNNEL_URL"
# Owner-approved tentative Karios funnel (2026-10-02 polish). Replace when paid page lands.
DEFAULT_FUNNEL_URL = "https://zhibiao.it-t.xyz/request"

REQUIRED_PARTS = ("funnel-link", "playlist", "disclaimer", "presenter")


def funnel_url(explicit: str | None = None) -> str | None:
    """Canonical funnel URL (explicit arg wins, else env, else tentative default)."""
    if explicit and explicit.strip():
        return explicit.strip()
    env = os.environ.get(FUNNEL_ENV_VAR, "").strip()
    if env:
        return env
    return DEFAULT_FUNNEL_URL


def build_description(
    title: str,
    episode_label: str = "",
    funnel: str | None = None,
    extra_lines: tuple[str, ...] = (),
    music_credit: str | None = None,
) -> str:
    """Build a funnel-complete description (pure, no network).

    ``music_credit`` (e.g. a Kevin MacLeod CC BY line for the calm track
    used) is appended automatically when provided, so YouTube uploads carry
    the required attribution.
    """
    url = funnel_url(explicit=funnel)
    lines = [title.strip()]
    if episode_label.strip():
        lines.append(episode_label.strip())
    lines.append("")
    lines.extend(extra_lines)
    if extra_lines:
        lines.append("")
    if url:
        lines.append(f"更多实测复盘：{url}")
    lines.append(f"播放列表：https://www.youtube.com/playlist?list={PLAYLIST_ID}（{PLAYLIST_NAME}）")
    lines.append(f"主讲：{PRESENTER}")
    lines.append(DISCLAIMER)
    credit = (music_credit or "").strip()
    if credit and credit not in "\n".join(lines):
        lines.append("")
        lines.append(credit)
    return "\n".join(lines).strip() + "\n"


def check_description(text: str, funnel: str | None = None) -> dict:
    """Check a description. Returns {ok, missing, present, detail} (pure)."""
    body = text or ""
    url = funnel_url(explicit=funnel)
    missing: list[str] = []
    present: list[str] = []
    if url and url in body:
        present.append("funnel-link")
    else:
        missing.append("funnel-link")
    if PLAYLIST_ID in body or PLAYLIST_NAME in body:
        present.append("playlist")
    else:
        missing.append("playlist")
    if "不构成投资建议" in body:
        present.append("disclaimer")
    else:
        missing.append("disclaimer")
    if PRESENTER in body:
        present.append("presenter")
    else:
        missing.append("presenter")
    detail = ""
    if "funnel-link" in missing and not url:
        detail = (
            f"No funnel URL available (env {FUNNEL_ENV_VAR} empty and no default). "
            f"Re-run with {FUNNEL_ENV_VAR}=<url>."
        )
    return {"ok": not missing, "missing": missing, "present": present, "detail": detail}

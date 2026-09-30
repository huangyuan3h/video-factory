"""Visual-beats check for indicator segments (ep21 seed fix).

Root cause (ep21): seg08 narrates three distinct groups (0/12, 1/12, 3/12)
but the screen shows ONE static image the whole time. Viewers hear three
results while the picture never changes.

Rule:
- When a segment's narration presents >=2 distinct results/groups/numbers
  (e.g. three groups, several stocks, multiple N/M fractions), it must have
  a matching number of visual beats (image switches or highlight steps).
  A single static image for a multi-result narration fails QA.
- Any single image must not stay on screen longer than ~12s unless it is
  an animated chart (motion != "none"). Long static holds fail QA.

Detection (deterministic, no LLM):
- ``count_group_beats`` counts distinct result beats in narration text:
  distinct N/M fractions (0/12, 1/12, 3/12), 第X组 markers, and legacy
  种子/seed markers (for old scripts). Returns >=1.
- ``check_visual_beats`` compares beats vs bound images per segment and
  per-image hold durations. Returns offender strings; ``assert_visual_beats``
  raises to fail the build.
"""

from __future__ import annotations

import re

MAX_SINGLE_HOLD_SECONDS = 12.0

_FRACTION_RE = re.compile(r"(\d+\s*/\s*\d+)")
_GROUP_RE = re.compile(r"第[一二三四五六七八九十\d]+组")
_SEED_RE = re.compile(r"种子|seed", re.IGNORECASE)


def _normalise_fraction(token: str) -> str:
    return re.sub(r"\s+", "", token)


def count_group_beats(text: str) -> int:
    """Distinct result beats in narration ``text`` (>=1).

    - Distinct N/M fractions (0/12, 1/12, 3/12) each count one beat.
    - 第X组 markers each count one beat (capped by fractions when both exist).
    - Legacy 种子/seed markers count when no fractions are present (old scripts
      like "种子20260925那组…换种子1…种子2那组" -> 3 beats).
    Returns 1 for ordinary single-result narration.
    """
    text = text or ""
    fractions = {_normalise_fraction(m) for m in _FRACTION_RE.findall(text)}
    # Only N/M fractions with a small denominator look like group results
    # (12 in this series). A lone date like 2024/07 is not a group beat, but
    # counting it is harmless: it only raises the bar when >=2 distinct exist.
    groups = set(_GROUP_RE.findall(text))
    seeds = _SEED_RE.findall(text)
    if len(fractions) >= 2:
        return max(len(fractions), len(groups) or 0)
    if len(groups) >= 2:
        return len(groups)
    if len(seeds) >= 2:
        # Old seed-wording scripts: each seed mention is a group.
        # Count distinct seed tokens (20260925 / 1 / 2) when discernible.
        seed_nums = set(re.findall(r"seed\s*(\S+)", text, re.IGNORECASE))
        seed_cn = set(re.findall(r"种子\s*(\S+)", text))
        n = max(len(seed_nums), len(seed_cn), len(seeds))
        # "种子20260925那组，…换种子1，…种子2那组" has 3 mentions.
        mentions = len(re.findall(r"(?:种子|seed)", text, re.IGNORECASE))
        return max(2, min(mentions, 6))
    return 1


def check_visual_beats(
    segments: list[str],
    images_per_segment: list[list[str]],
    durations: list[float] | None = None,
    motions: list[str] | None = None,
    max_single_hold: float = MAX_SINGLE_HOLD_SECONDS,
) -> list[str]:
    """Return offender descriptions (empty when PASS).

    - Multi-beat narration (beats>=2) needs >=beats images (switches or
      highlight-step variants). A single image for multi-beat narration fails.
      Each image in a multi-beat segment must hold <= ``max_single_hold``
      (~12s) unless animated.
    - Single-result narration (beats==1) may hold one detailed chart up to
      ~36s (series norm ep4-7: 15-36s per chart); only multi-beat static
      holds are gated by the 12s rule.
    """
    offenders: list[str] = []
    n = len(segments)
    for i in range(n):
        text = segments[i] if i < len(segments) else ""
        beats = count_group_beats(text)
        images = images_per_segment[i] if i < len(images_per_segment) else []
        nimg = len(images)
        dur = float(durations[i]) if durations and i < len(durations) else 0.0
        motion = str(motions[i]) if motions and i < len(motions) else "none"
        if beats >= 2 and nimg < beats:
            offenders.append(
                f"seg{i+1}: narration has {beats} result beats "
                f"but only {nimg} image(s) (need >=beats switches/highlights)"
            )
        # 12s hold gate applies to multi-beat segments only (the ep21 bug:
        # static image while narration moves through distinct results).
        if beats >= 2 and nimg >= 1 and dur > 0 and motion == "none":
            hold = dur / max(1, nimg)
            if hold > max_single_hold:
                offenders.append(
                    f"seg{i+1}: each image holds {hold:.1f}s "
                    f"> {max_single_hold:.0f}s (add beats or animate)"
                )
    return offenders


def assert_visual_beats(
    segments: list[str],
    images_per_segment: list[list[str]],
    durations: list[float] | None = None,
    motions: list[str] | None = None,
    max_single_hold: float = MAX_SINGLE_HOLD_SECONDS,
) -> None:
    """Fail the build when visual beats do not match multi-result narration."""
    offenders = check_visual_beats(
        segments, images_per_segment, durations, motions, max_single_hold
    )
    if offenders:
        raise ValueError(
            "画面与口播不匹配 (visual beats): " + "; ".join(offenders[:5])
        )

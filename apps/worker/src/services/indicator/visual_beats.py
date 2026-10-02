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
  (Note: the 12s gate uses the average hold dur/nimg; cue-based highlight
  steps may have a longer first hold because it covers the lead-in
  你可能会问… + 第一组 — the sync gate below is the binding check.)

Beat sync (ep21 beat-sync fix, 2026-09-30):
- Highlight-step switch times must come from the subtitle cue / TTS word
  timing of the phrase introducing each beat (the cue containing 第二组
  starts → switch to g2), not an even split. Even-split timing desyncs by
  ~1.5s (ep21 seg08b at 179.5s showed g2 while the subtitle still said
  第一组0只跑赢) because phrases have unequal spoken lengths.
- ``compute_cue_based_holds`` derives per-image holds from cue starts;
  ``check_beat_sync`` verifies at each switch the active subtitle mentions
  the highlighted marker (or the next cue does within 0.3s).

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


def beat_markers_in_order(text: str) -> list[str]:
    """Group markers (第一组/第二组/…) in order of appearance.

    Used to align highlight-step images to narration: image k shows when
    marker k is spoken. Returns [] when no markers are present.
    """
    return _GROUP_RE.findall(text or "")


def compute_cue_based_holds(
    segment_text: str,
    span: float,
    cues: list[dict],
    num_images: int,
    seg_start: float = 0.0,
) -> list[float]:
    """Per-image holds covering ``span`` from subtitle cue timings.

    ``cues`` are narration-absolute ``{"start","end","text"}`` dicts (ASS or
    subtitle objects). For image k>=2 the switch time is the start of the first
    cue containing marker k (e.g. the cue containing 第二组 starts → switch to
    g2). Image 1 starts at ``seg_start``; the last image runs to
    ``seg_start + span``. Falls back to an even split when markers/cues do not
    line up (wrong count, marker missing, non-increasing switches, tiny holds).

    Pure function; never raises (fallback is always valid).
    """
    try:
        span = float(span)
        if span <= 0 or num_images <= 0:
            return [span / num_images] * num_images if num_images else []
        markers = beat_markers_in_order(segment_text)
        if len(markers) != num_images or num_images < 2:
            return [span / num_images] * num_images
        switches: list[float] = []
        for marker in markers[1:]:
            found: float | None = None
            for cue in cues or []:
                try:
                    text = str(cue.get("text") or "")
                    start = float(cue.get("start", cue.get("start_time", 0.0)) or 0.0)
                except Exception:
                    continue
                if marker and marker in text and start >= seg_start - 1e-6:
                    # First cue mentioning this beat (in segment order; cues are
                    # time-ordered so the first hit is the introduction).
                    if start < seg_start + span - 1e-6:
                        found = start
                        break
            if found is None:
                return [span / num_images] * num_images
            switches.append(found)
        # Strictly increasing and inside (seg_start, seg_start+span)?
        prev = seg_start
        for sw in switches:
            if not (sw > prev + 1e-6 and sw < seg_start + span - 1e-6):
                return [span / num_images] * num_images
            prev = sw
        holds = [switches[0] - seg_start]
        for a, b in zip(switches, switches[1:]):
            holds.append(b - a)
        holds.append(seg_start + span - switches[-1])
        # Sanity: every hold must be >=0.8s (a beat flashed shorter is a bug;
        # fall back so QA flags the even split instead of a sliver).
        if any(h < 0.8 - 1e-6 for h in holds):
            return [span / num_images] * num_images
        total = sum(holds)
        if total <= 0:
            return [span / num_images] * num_images
        # Normalise exactly onto span (float hygiene).
        return [h * span / total for h in holds]
    except Exception:
        try:
            return [float(span) / num_images] * num_images
        except Exception:
            return []


def compute_holds_from_boundaries(
    segment_text: str,
    span: float,
    boundaries: list[dict],
    num_images: int,
) -> list[float]:
    """Fallback variant using TTS sentence boundaries (offsets relative to seg).

    Same contract as :func:`compute_cue_based_holds` but ``boundaries`` carry
    ``{"offset","duration","text"}`` relative to the segment start. Used when
    subtitles are not available yet (pre-subtitle path); subtitles remain the
    primary source because they are snapped to measured speech runs.
    """
    try:
        cues = [
            {
                "start": float(b.get("offset", 0.0) or 0.0),
                "end": float(b.get("offset", 0.0) or 0.0)
                + float(b.get("duration", 0.0) or 0.0),
                "text": str(b.get("text") or ""),
            }
            for b in (boundaries or [])
            if isinstance(b, dict)
        ]
        return compute_cue_based_holds(segment_text, span, cues, num_images, 0.0)
    except Exception:
        return [float(span) / num_images] * num_images if num_images else []


def check_beat_sync(
    segment_text: str,
    images: list[str],
    seg_start: float,
    holds: list[float] | None,
    cues: list[dict],
    span: float | None = None,
    tolerance_next_cue_s: float = 0.3,
) -> list[str]:
    """Verify each highlight switch lands on its narration beat.

    For image k>=2 with marker M (e.g. 第二组), the switch time
    ``seg_start + sum(holds[:k-1])`` must have an active subtitle cue
    containing M, or the next cue must start within ``tolerance_next_cue_s``
    (0.3s) and contain M. Returns offender strings (empty when in sync).

    ``holds`` is the actual per-image timing used for the render (cue-based or
    even split); ``cues`` are narration-absolute ``{"start","end","text"}``.
    When markers/images do not align (no markers or count mismatch) there is
    nothing beat-specific to check → [].
    """
    try:
        markers = beat_markers_in_order(segment_text)
        nimg = len(images or [])
        if nimg < 2 or len(markers) != nimg:
            return []
        if not holds or len(holds) != nimg:
            return []
        offenders: list[str] = []
        switch = float(seg_start)
        for k in range(1, nimg):
            switch += float(holds[k - 1])
            expected = markers[k]
            active_text: str | None = None
            for cue in cues or []:
                try:
                    s = float(cue.get("start", cue.get("start_time", 0.0)) or 0.0)
                    e = float(cue.get("end", cue.get("end_time", s)) or s)
                    t = str(cue.get("text") or "")
                except Exception:
                    continue
                if s <= switch < e:
                    active_text = t
                    break
            if active_text is not None and expected in active_text:
                continue
            # Next cue within tolerance?
            nxt = None
            nxt_gap = None
            for cue in cues or []:
                try:
                    s = float(cue.get("start", cue.get("start_time", 0.0)) or 0.0)
                    t = str(cue.get("text") or "")
                except Exception:
                    continue
                if s >= switch and (nxt is None or s < float(nxt.get("start", 1e18))):
                    nxt = {"start": s, "text": t}
            if nxt is not None:
                nxt_gap = float(nxt["start"]) - switch
                if nxt_gap <= tolerance_next_cue_s + 1e-9 and expected in str(nxt["text"]):
                    continue
            offenders.append(
                f"beat k={k+1} ({expected}) switch at {switch:.2f}s "
                f"active subtitle {active_text!r} does not mention {expected} "
                f"(next cue in {nxt_gap:.2f}s)" if nxt_gap is not None else
                f"beat k={k+1} ({expected}) switch at {switch:.2f}s "
                f"active subtitle {active_text!r} does not mention {expected} (no next cue)"
            )
        return offenders
    except Exception as exc:  # noqa: BLE001 - QA reports, never crashes
        return [f"beat-sync check error: {exc}"]


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


def assert_beat_sync(
    segment_text: str,
    images: list[str],
    seg_start: float,
    holds: list[float] | None,
    cues: list[dict],
    span: float | None = None,
) -> None:
    """Fail the build when a highlight switch does not land on its beat."""
    offenders = check_beat_sync(segment_text, images, seg_start, holds, cues, span)
    if offenders:
        raise ValueError("画面节拍不同步 (beat sync): " + "; ".join(offenders[:5]))

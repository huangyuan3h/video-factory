"""Card overflow QA for ``13_myth_vs_data.png`` (and any card frame).

Root cause (ep12): the research chart renderer
(``kseries/charts.py::_chart_13``) had no pixel-measured fit: it wrapped by
character count, shrank to a shared font without re-validating each container,
kept <24px vertical padding, never grew the box, and the render-time guard
(``check_text_bounds``) only checked the figure edges -- never the box
containers. A margin helper that shifted axes containers without moving
figure-coordinate text made the right (green) column run past its box edges.

This module is the Video Factory side of the fix:
- :func:`check_card_image_no_overflow` pixel-checks a rendered card PNG: every
  dark text blob inside a card box must keep >=24px padding from all four box
  edges, and no text ink may touch/cross a box border.
- :func:`assert_card_image_fits` fails the build (raises) when the above finds
  offenders, so a bad card can never reach upload.
- :func:`shorten_card_fact` is the script-stage shortening: when a fact would
  need more than two short lines in its box, it is shortened (numbers kept,
  prose trimmed) to at most two short lines.

The renderer fix itself lives in ``kseries/charts.py`` (measure by pixel
width, wrap, shrink to a readable minimum, >=24px padding, grow the box,
container assertion). This QA gate runs on the PNGs/frames before upload so a
regression fails loudly on either side.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

CARD_MIN_PADDING_PX = 24

# Figure-fraction geometry of ``_chart_13`` (fallback when detection fails).
# Old (buggy): top 0.775, card_h 0.205, gap 0.035. Fixed: top 0.78, card_h
# 0.23, gap 0.025. Detection below handles both; fallback uses the fixed one.
_CARD_GEO_FIXED = (0.025, 0.47, 0.53, 0.975, 0.78, 0.23, 0.025)
_CARD_GEO_OLD = (0.025, 0.47, 0.53, 0.975, 0.775, 0.205, 0.035)


def _box_pixels_fallback(
    width: int, height: int
) -> list[tuple[int, int, int, int]]:
    """Pixel boxes for the fixed geometry (fallback)."""
    _, _, rx0, rx1, top, card_h, gap = _CARD_GEO_FIXED
    boxes: list[tuple[int, int, int, int]] = []
    for k in range(3):
        y1_fig = top - k * (card_h + gap)
        y0_fig = y1_fig - card_h
        x0, x1 = int(rx0 * width), int(rx1 * width)
        y_top = int((1.0 - y1_fig) * height)
        y_bottom = int((1.0 - y0_fig) * height)
        boxes.append((x0, y_top, x1, y_bottom))
    return boxes


def _detect_right_boxes(
    rgb: np.ndarray,
) -> list[tuple[int, int, int, int]] | None:
    """Detect the 3 right-hand green boxes by border colour.

    Returns ``[(x0, y_top, x1, y_bottom)]`` in image pixels (origin top-left),
    or ``None`` when detection fails (caller falls back to geometry).
    """
    try:
        green = (
            (rgb[:, :, 0] < 80)
            & (rgb[:, :, 1] > 120)
            & (rgb[:, :, 2] < 80)
        )
        height, width = green.shape
        # Horizontal borders: rows with a long green run (box width ~800px).
        row_counts = green.sum(axis=1)
        # Threshold: at least half a box width of green in the row.
        cand_y = [y for y in range(height) if row_counts[y] > 400]
        if len(cand_y) < 6:
            return None
        # Cluster consecutive rows (border is 1-2px thick).
        clusters: list[list[int]] = []
        for y in sorted(cand_y):
            if clusters and y - clusters[-1][-1] <= 3:
                clusters[-1].append(y)
            else:
                clusters.append([y])
        # Take the 6 strongest clusters (by count) as the 6 horizontal edges.
        clusters.sort(key=lambda c: sum(row_counts[y] for y in c), reverse=True)
        edges = sorted(int(sum(c) / len(c)) for c in clusters[:6])
        if len(edges) < 6:
            return None
        # Pair top/bottom: sorted edges should be [t0,b0,t1,b1,t2,b2] top-down
        # (y grows downward in image coords).
        boxes: list[tuple[int, int, int, int]] = []
        for k in range(3):
            y_top, y_bottom = edges[2 * k], edges[2 * k + 1]
            if y_bottom - y_top < 50:
                return None
            # Vertical borders: columns with green inside this y-band.
            band = green[max(0, y_top - 2) : min(height, y_bottom + 3), :]
            col_counts = band.sum(axis=0)
            cand_x = [x for x in range(width) if col_counts[x] > (y_bottom - y_top) * 0.5]
            if len(cand_x) < 2:
                return None
            # Cluster columns.
            xclusters: list[list[int]] = []
            for x in sorted(cand_x):
                if xclusters and x - xclusters[-1][-1] <= 3:
                    xclusters[-1].append(x)
                else:
                    xclusters.append([x])
            # Right boxes: left and right vertical edges (2 clusters).
            # Keep the two outermost strong clusters in the right half.
            xclusters.sort(key=lambda c: len(c), reverse=True)
            # Filter to right half (x > width*0.5) for the green column.
            right = [c for c in xclusters if sum(c) / len(c) > width * 0.5]
            if len(right) < 2:
                # Fall back to the two strongest overall.
                right = xclusters[:2]
            xs = sorted(int(sum(c) / len(c)) for c in right[:2])
            if len(xs) < 2 or xs[1] - xs[0] < 400:
                return None
            boxes.append((xs[0], y_top, xs[1], y_bottom))
        if len(boxes) != 3:
            return None
        return boxes
    except Exception:
        return None


def _dark_mask(rgb: np.ndarray) -> np.ndarray:
    """Dark text ink (the card text colour ``#222222``)."""
    return (
        (rgb[:, :, 0] < 100)
        & (rgb[:, :, 1] < 100)
        & (rgb[:, :, 2] < 100)
    )


def check_card_image_no_overflow(
    image_path: str | Path, padding: int = CARD_MIN_PADDING_PX
) -> list[str]:
    """Return offender descriptions when card text violates its container.

    Checks the three right-hand (green) boxes of a ``13_myth_vs_data`` card:
    text must sit at least ``padding`` px inside every edge, and no dark ink
    may sit on the box border itself (1px tolerance for anti-aliasing).
    """
    path = Path(image_path)
    offenders: list[str] = []
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            width, height = img.size
            rgb = np.asarray(img)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the gate
        return [f"{path.name}: cannot read image ({exc})"]
    dark = _dark_mask(rgb)
    boxes = _detect_right_boxes(rgb)
    if boxes is None:
        boxes = _box_pixels_fallback(width, height)
    for idx, (x0, y_top, x1, y_bottom) in enumerate(boxes):
        # Clip to the image (a box extending past the figure is itself an
        # overflow, e.g. the old right column at x1>width).
        if x1 > width or x0 < 0 or y_top < 0 or y_bottom > height:
            offenders.append(
                f"box{idx}: container outside figure "
                f"(x0={x0},x1={x1},w={width})"
            )
            continue
        inner = dark[y_top:y_bottom, x0:x1]
        ys, xs = np.where(inner)
        if len(xs) == 0:
            offenders.append(f"box{idx}: no text ink found")
            continue
        xmin, xmax = int(xs.min()), int(xs.max())
        ymin, ymax = int(ys.min()), int(ys.max())
        pad_l, pad_r = xmin, (x1 - x0 - 1) - xmax
        pad_t, pad_b = ymin, (y_bottom - y_top - 1) - ymax
        if min(pad_l, pad_r, pad_t, pad_b) < padding:
            offenders.append(
                f"box{idx}: padding L={pad_l} R={pad_r} T={pad_t} B={pad_b} "
                f"< {padding}px"
            )
        # Border touch: 2px ring just inside the box must contain no text ink
        # except where the border line itself is (green, not dark, so any dark
        # there is text crossing the border).
        ring = np.zeros_like(inner, dtype=bool)
        ring[:2, :] = True
        ring[-2:, :] = True
        ring[:, :2] = True
        ring[:, -2:] = True
        if bool((inner & ring).any()):
            offenders.append(f"box{idx}: text touches box border")
    return offenders


def assert_card_image_fits(
    image_path: str | Path, padding: int = CARD_MIN_PADDING_PX
) -> None:
    """Render-time assertion: fail the build when text exceeds its container."""
    offenders = check_card_image_no_overflow(image_path, padding=padding)
    if offenders:
        raise AssertionError(
            f"card overflow in {Path(image_path).name}: "
            + "; ".join(offenders)
        )


def shorten_card_fact(fact: str, max_lines: int = 2) -> str:
    """Script-stage shortening: keep at most two short lines per box.

    Numbers are never dropped (every number token is preserved verbatim);
    only prose is trimmed: whitespace around ``/`` is collapsed, the era tail
    ``N 个时代全部跑输两大指数`` is compacted to ``N时代全输``, and clauses
    beyond the first two (split on ``；``) are dropped.
    """
    import re

    text = (fact or "").strip()
    # Preserve numbers: record them so we can assert none were lost.
    numbers = re.findall(r"[+\-]?\d+(?:\.\d+)?%?", text)
    # Collapse `` / `` and full-width spaces around slashes.
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", " ", text)
    # Compact the era tail (keeps the leading count ``4``).
    text = re.sub(
        r"(\d+)\s*个时代全部跑输两大指数", r"\1时代全输", text
    )
    text = re.sub(r"(\d+)\s*个时代里\s*(\d+)\s*个跑输两大指数", r"\1时代里\2个跑输", text)
    clauses = [c.strip() for c in text.split("；") if c.strip()]
    if len(clauses) > max_lines:
        clauses = clauses[:max_lines]
    short = "；".join(clauses)
    # Never drop a number while shortening.
    for token in numbers:
        if token and token not in short:
            return fact.strip()
    return short

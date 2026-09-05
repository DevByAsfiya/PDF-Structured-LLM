"""geometry.py - Spatial analysis for product-grid pages.

Infers column boundaries from image x-positions and binds each product image
to its caption block using bounding-box proximity in the same column.

No LLMs.  Pure geometry + deterministic heuristics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from pdfscraper.catalogue_spec import (
    COLUMN_X_TOLERANCE_PT,
    GRID_COLUMNS_MAX,
    GRID_COLUMNS_MIN,
    MAX_CAPTION_OFFSET_PT,
    MAX_HORIZONTAL_DRIFT_PT,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    SECTION_HEADER_MIN_FONT_SIZE_PT,
    MIN_IMAGE_AREA_PX,
)
from pdfscraper.schemas import BoundingBox, RawBlock


# ---------------------------------------------------------------------------
# Data classes for geometry results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ColumnBoundary:
    """A single inferred column on a product-grid page."""
    index: int
    x_left: float
    x_right: float
    x_centre: float


@dataclass
class ImageCaptionBinding:
    """Binding of a product image block to the text blocks beneath it."""
    image_block: RawBlock
    caption_blocks: list[RawBlock] = field(default_factory=list)
    column_index: int = -1
    confidence: float = 1.0
    binding_method: str = "spatial_column_nearest_below"


# ---------------------------------------------------------------------------
# Column inference
# ---------------------------------------------------------------------------

def _cluster_x_positions(
    x_centres: list[float],
    tolerance: float = COLUMN_X_TOLERANCE_PT,
) -> list[list[float]]:
    """Cluster a sorted list of x-centre positions into groups.

    Simple greedy 1-D clustering: walk the sorted list and merge
    consecutive positions that are within *tolerance* of the running
    cluster mean.  Returns the raw cluster lists (not centroids) so
    callers can merge further.
    """
    if not x_centres:
        return []

    sorted_xs = sorted(x_centres)
    clusters: list[list[float]] = [[sorted_xs[0]]]

    for x in sorted_xs[1:]:
        cluster_mean = sum(clusters[-1]) / len(clusters[-1])
        if abs(x - cluster_mean) <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    return clusters


def _merge_to_max_columns(
    clusters: list[list[float]],
    max_cols: int = GRID_COLUMNS_MAX,
) -> list[list[float]]:
    """Iteratively merge the two closest adjacent clusters until we have
    at most *max_cols* clusters.

    This handles wide images (e.g. Arctic spout x=317–520, cx=419) whose
    centres fall between two real columns: the 419 cluster is merged into
    its nearest neighbour.
    """
    while len(clusters) > max_cols:
        # Find the adjacent pair with the smallest centroid gap
        min_gap = float("inf")
        merge_idx = 0
        for i in range(len(clusters) - 1):
            mean_i = sum(clusters[i]) / len(clusters[i])
            mean_j = sum(clusters[i + 1]) / len(clusters[i + 1])
            gap = mean_j - mean_i
            if gap < min_gap:
                min_gap = gap
                merge_idx = i

        # Merge the pair
        merged = clusters[merge_idx] + clusters[merge_idx + 1]
        clusters = clusters[:merge_idx] + [merged] + clusters[merge_idx + 2:]

    return clusters


def infer_columns(image_blocks: list[RawBlock]) -> list[ColumnBoundary]:
    """Infer column boundaries from the x-centre positions of product images.

    Steps:
    1.  Initial fine-grained clustering with COLUMN_X_TOLERANCE_PT.
    2.  Merge closest pair of clusters until ≤ GRID_COLUMNS_MAX.
    3.  Build column boundary objects with midpoints between neighbours.

    Returns an ordered list of ColumnBoundary objects (left to right).
    """
    if not image_blocks:
        return []

    x_centres = [
        (b.bbox.x0 + b.bbox.x1) / 2.0
        for b in image_blocks
    ]

    # Step 1: fine-grained clustering
    clusters = _cluster_x_positions(x_centres, COLUMN_X_TOLERANCE_PT)
    if not clusters:
        return []

    # Step 2: merge until ≤ max columns
    clusters = _merge_to_max_columns(clusters, GRID_COLUMNS_MAX)

    # Compute centroids
    centroids = [sum(c) / len(c) for c in clusters]

    # Step 3: build column objects with boundaries halfway between neighbours
    cols: list[ColumnBoundary] = []
    for i, cx in enumerate(centroids):
        if i == 0:
            x_left = 0.0
        else:
            x_left = (centroids[i - 1] + cx) / 2.0

        if i == len(centroids) - 1:
            x_right = PAGE_WIDTH_PT
        else:
            x_right = (cx + centroids[i + 1]) / 2.0

        cols.append(ColumnBoundary(index=i, x_left=x_left, x_right=x_right, x_centre=cx))

    logger.debug(
        "Inferred {} columns: {}",
        len(cols),
        [(c.index, f"x=[{c.x_left:.0f},{c.x_right:.0f}] cx={c.x_centre:.0f}") for c in cols],
    )

    return cols


def _assign_column(bbox: BoundingBox, columns: list[ColumnBoundary]) -> int:
    """Return the column index whose range contains the bbox centre-x."""
    cx = (bbox.x0 + bbox.x1) / 2.0
    best_idx = 0
    best_dist = float("inf")
    for col in columns:
        dist = abs(cx - col.x_centre)
        if dist < best_dist:
            best_dist = dist
            best_idx = col.index
    return best_idx


# ---------------------------------------------------------------------------
# Series header detection
# ---------------------------------------------------------------------------

def detect_series_header(
    text_blocks: list[RawBlock],
    known_series: list[str],
) -> Optional[str]:
    """Detect a series/collection name from large-font header text blocks.

    Handles letter-spaced renderings (e.g. ``T A N S A`` → ``TANSA``) by
    stripping all whitespace before matching.

    Sorts known_series by descending length to prefer longer matches
    (e.g. 'Nalini Pro' before 'Nalini').
    """
    # Sort by length descending so compound names match first
    sorted_series = sorted(known_series, key=lambda s: len(s), reverse=True)

    # Collect candidate blocks: top region OR large font
    candidates = [
        b for b in text_blocks
        if b.text and (
            b.bbox.y0 < 150.0
            or (b.font_size or 0.0) >= SECTION_HEADER_MIN_FONT_SIZE_PT
        )
    ]
    # Sort by vertical position (topmost first), then by font size descending
    candidates.sort(key=lambda b: (b.bbox.y0, -(b.font_size or 0.0)))

    for block in candidates:
        text = block.text or ""
        # Normalise: strip ALL whitespace to handle letter-spacing
        cleaned = re.sub(r"\s+", "", text).upper()
        if len(cleaned) < 3:
            continue

        for series in sorted_series:
            series_clean = re.sub(r"\s+", "", series).upper()
            if len(series_clean) >= 3 and series_clean in cleaned:
                return series

    return None


# ---------------------------------------------------------------------------
# Image → caption binding
# ---------------------------------------------------------------------------

def _is_product_image(block: RawBlock) -> bool:
    """Filter out tiny decorative images (masks, logos, bullets)."""
    area = block.bbox.area
    # Use a rough pt² threshold — MIN_IMAGE_AREA_PX is in pixel² at 300 DPI.
    # At 300 DPI on A4, 1 pt ≈ 300/72 ≈ 4.17 px, so 1 pt² ≈ 17.36 px².
    # MIN_IMAGE_AREA_PX = 5000 px² ≈ 288 pt².  Use a generous 200 pt².
    return area >= 200.0


def bind_images_to_captions(
    blocks: list[RawBlock],
    columns: list[ColumnBoundary],
) -> list[ImageCaptionBinding]:
    """For each product image, find the caption text blocks directly below
    it in the same column, within MAX_CAPTION_OFFSET_PT.

    Deduplicates images by xref so the same raster produces only one binding.

    Returns one ImageCaptionBinding per unique product image, ordered
    top-to-bottom, left-to-right.
    """
    image_blocks = [
        b for b in blocks
        if b.block_type == "image" and _is_product_image(b)
    ]
    text_blocks = [b for b in blocks if b.block_type == "text"]

    if not columns:
        # Fall back: treat entire page as one column
        columns = [ColumnBoundary(index=0, x_left=0, x_right=PAGE_WIDTH_PT, x_centre=PAGE_WIDTH_PT / 2)]

    # --- Deduplicate images by xref ---
    seen_xrefs: set[int] = set()
    unique_images: list[RawBlock] = []
    for img in image_blocks:
        xref = img.xref
        if xref is not None and xref in seen_xrefs:
            continue
        if xref is not None:
            seen_xrefs.add(xref)
        unique_images.append(img)

    # Sort images top-to-bottom then left-to-right for deterministic ordering
    unique_images.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))

    bindings: list[ImageCaptionBinding] = []

    for img in unique_images:
        col_idx = _assign_column(img.bbox, columns)
        col = columns[col_idx]

        # Caption search zone:
        # - Vertically: from image bottom to image bottom + MAX_CAPTION_OFFSET_PT
        # - Horizontally: within the column boundaries (strict — no extra drift)
        caption_y_start = img.bbox.y1
        caption_y_end = img.bbox.y1 + MAX_CAPTION_OFFSET_PT
        caption_x_left = col.x_left
        caption_x_right = col.x_right

        # Gather caption text blocks in the zone, sorted top-to-bottom
        caption_candidates = []
        for tb in text_blocks:
            tb_cx = (tb.bbox.x0 + tb.bbox.x1) / 2.0

            in_column = caption_x_left <= tb_cx <= caption_x_right
            in_vertical_zone = caption_y_start - 5.0 <= tb.bbox.y0 <= caption_y_end

            if in_column and in_vertical_zone:
                caption_candidates.append(tb)

        caption_candidates.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))

        # Confidence heuristics
        confidence = 1.0
        if not caption_candidates:
            confidence = 0.3  # No caption found — very suspicious
        elif len(caption_candidates) > 12:
            confidence = 0.5  # Too many spans — might be grabbing from neighbours

        binding = ImageCaptionBinding(
            image_block=img,
            caption_blocks=caption_candidates,
            column_index=col_idx,
            confidence=confidence,
        )
        bindings.append(binding)

    return bindings

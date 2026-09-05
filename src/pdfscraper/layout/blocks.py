"""blocks.py - Deterministic extraction of text spans and image rects in a shared coordinate space."""

from typing import Optional
import pymupdf
from loguru import logger

from pdfscraper.schemas import BoundingBox, RawBlock


def extract_page_blocks(page: pymupdf.Page, page_number: int) -> list[RawBlock]:
    """Extract all text spans and raster image rects from a page into shared coordinate space (points).

    Args:
        page: PyMuPDF Page object.
        page_number: 1-indexed page number.

    Returns:
        List of RawBlock instances (both text spans and image rects).
    """
    raw_blocks: list[RawBlock] = []

    # 1. Extract text spans with typography
    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text or not text.strip():
                    continue

                bbox = span.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue

                x0, y0, x1, y1 = bbox
                if x1 <= x0 or y1 <= y0:
                    continue

                raw_blocks.append(
                    RawBlock(
                        page_number=page_number,
                        block_type="text",
                        bbox=BoundingBox(
                            x0=float(x0),
                            y0=float(y0),
                            x1=float(x1),
                            y1=float(y1),
                        ),
                        text=text.strip(),
                        font_size=float(span.get("size", 0.0)),
                        font_name=span.get("font"),
                        confidence=1.0,
                        extraction_method="pymupdf_span_extraction",
                    )
                )

    # 2. Extract raster image rects with xref
    image_list = page.get_images()
    seen_rects = set()

    for img_idx, img_info in enumerate(image_list):
        xref = img_info[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception as e:
            logger.debug("Failed getting image rects for xref {} on page {}: {}", xref, page_number, e)
            continue

        for rect in rects:
            x0 = min(rect.x0, rect.x1)
            x1 = max(rect.x0, rect.x1)
            y0 = min(rect.y0, rect.y1)
            y1 = max(rect.y0, rect.y1)

            # Deduplicate identical rects on the same page
            rect_key = (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))
            if rect_key in seen_rects:
                continue
            seen_rects.add(rect_key)

            if x1 > x0 and y1 > y0:
                raw_blocks.append(
                    RawBlock(
                        page_number=page_number,
                        block_type="image",
                        bbox=BoundingBox(x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1)),
                        image_index=img_idx,
                        xref=xref,
                        confidence=1.0,
                        extraction_method="pymupdf_image_stream",
                    )
                )

    return raw_blocks

"""classifier.py - Heuristic classification of catalogue page archetypes with multi-tier confidence."""

import re
from pathlib import Path
from typing import Any, Optional
from loguru import logger
import pandas as pd
import pymupdf

from pdfscraper.catalogue_spec import (
    ALL_ARCHETYPES,
    ARCHETYPE_COVER,
    ARCHETYPE_EDITORIAL,
    ARCHETYPE_HERO,
    ARCHETYPE_INDEX,
    ARCHETYPE_LIFESTYLE,
    ARCHETYPE_PARTS_TABLE,
    ARCHETYPE_PRODUCT_GRID,
    ARCHETYPE_TECH_SPEC,
    INDEX_PAGE_INDEX,
    MRP_PATTERN,
    PDF_FILENAME,
    TABLE_PRICE_PATTERN,
    TOTAL_PAGES,
)
from pdfscraper.config import settings
from pdfscraper.layout.blocks import extract_page_blocks
from pdfscraper.schemas import Page, RawBlock


def _find_series_in_spans(
    text_blocks: list[RawBlock],
    known_series: list[str],
) -> Optional[str]:
    """Find a series name from known series in top header text blocks."""
    # Sort by length descending so compound names match first
    sorted_series = sorted(known_series, key=lambda s: len(s), reverse=True)

    header_blocks = [b for b in text_blocks if b.bbox.y0 < 150.0]
    header_blocks.sort(key=lambda b: (b.bbox.y0, -(b.font_size or 0.0)))

    for b in header_blocks:
        if not b.text:
            continue
        cleaned = re.sub(r"\s+", "", b.text.upper())
        for series in sorted_series:
            series_clean = re.sub(r"\s+", "", series.upper())
            if len(series_clean) >= 3 and series_clean in cleaned:
                return series

    large_blocks = [b for b in text_blocks if (b.font_size or 0.0) >= 18.0]
    for b in large_blocks:
        if not b.text:
            continue
        cleaned = re.sub(r"\s+", "", b.text.upper())
        for series in sorted_series:
            series_clean = re.sub(r"\s+", "", series.upper())
            if len(series_clean) >= 3 and series_clean in cleaned:
                return series

    return None


def classify_page(
    page: pymupdf.Page,
    page_number: int,
    raw_blocks: list[RawBlock],
    known_series: list[str],
    current_series: Optional[str] = None,
    section_name: Optional[str] = None,
    section_start: Optional[int] = None,
) -> Page:
    """Classify a single catalogue page into an archetype using deterministic heuristics and 3 confidence tiers.

    Confidence Tiers:
    - Tier 1 (High: 0.90 - 0.99): Strong structural agreement with catalogue templates.
    - Tier 2 (Moderate: 0.75 - 0.89): Standard classification with minor ambiguity.
    - Tier 3 (Low / Flagged: 0.40 - 0.65): High ambiguity, missing text layer, or vector-rendered text (routes to review queue).
    """
    text_blocks = [b for b in raw_blocks if b.block_type == "text"]
    image_blocks = [b for b in raw_blocks if b.block_type == "image"]
    all_text = " ".join(b.text for b in text_blocks if b.text)
    all_text_upper = all_text.upper()

    drawings = page.get_drawings()
    drawings_count = len(drawings)
    image_count = len(image_blocks)

    mrp_matches = list(MRP_PATTERN.finditer(all_text))
    mrp_count = len(mrp_matches)

    # Detected series header
    detected_series = _find_series_in_spans(text_blocks, known_series)
    effective_series = detected_series or current_series

    # Printed page footer check
    printed_page_num = None
    footer_blocks = [b for b in text_blocks if b.bbox.y1 > page.rect.height - 60.0]
    for b in footer_blocks:
        if b.text and re.fullmatch(r"[0-9]{1,3}", b.text.strip()):
            printed_page_num = int(b.text.strip())
            break

    # HEURISTIC 1: Cover pages (Page 1, 2, 3 and 202)
    if page_number == 1 or page_number == TOTAL_PAGES:
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_COVER,
            series_header=detected_series,
            section_name="Cover",
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=0.99,
            extraction_method="heuristic_classifier",
        )

    if page_number in (2, 3) and mrp_count == 0:
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_COVER,
            series_header=detected_series,
            section_name="Front Matter",
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=0.95,
            extraction_method="heuristic_classifier",
        )

    # HEURISTIC 2: Index pages (Pages 6 and 7)
    if page_number in (INDEX_PAGE_INDEX, INDEX_PAGE_INDEX + 1) or "I N D E X" in all_text_upper:
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_INDEX,
            series_header=None,
            section_name="Index",
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=0.99,
            extraction_method="heuristic_classifier",
        )

    # HEURISTIC 3: Technical Specifications & Guidelines (Page 199 or explicit installation guides)
    if page_number == 199 or "INSTALLATION" in all_text_upper or "WATER SAVING CHART" in all_text_upper:
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_TECH_SPEC,
            series_header=effective_series,
            section_name=section_name or "Technical Specification",
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=0.95,
            extraction_method="heuristic_classifier",
        )

    # HEURISTIC 4: Ruled Parts & Sinks Tables (Kitchen Sinks p.188-193 and Spindles p.197-198)
    is_spindles_table = (
        page_number in (197, 198)
        or ("CAT NO" in all_text_upper and "USED IN" in all_text_upper)
        or ("SPINDLES & CARTRIDGES" in all_text_upper and page_number >= 195)
    )
    is_sinks_table = (188 <= page_number <= 193) and ("SINK" in all_text_upper or "BOWL" in all_text_upper)

    if is_spindles_table or is_sinks_table:
        table_sec = "Kitchen Sinks" if is_sinks_table else "Parts & Accessories"
        conf = 0.98 if (drawings_count >= 10 or mrp_count >= 1) else 0.90
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_PARTS_TABLE,
            series_header=effective_series,
            section_name=section_name or table_sec,
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=conf,
            extraction_method="heuristic_classifier",
        )

    # HEURISTIC 5: Vector-Text / Outline Anomaly Detection (Page 143 pattern)
    # Inside a section range, high drawing count (> 20), images present, but 0 text-layer MRPs
    # and not matching expected hero or editorial text
    is_vector_text_candidate = (
        section_name is not None
        and mrp_count == 0
        and drawings_count > 50
        and image_count >= 1
        and len(all_text) < 100
        and page_number not in (134,)  # p.134 is water savings chart
    )
    if is_vector_text_candidate or page_number == 143:
        logger.warning("Flagging Page {} as vector-text product anomaly for review queue", page_number)
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_PRODUCT_GRID,
            series_header=effective_series,
            section_name=section_name or effective_series,
            blocks_count=len(raw_blocks),
            has_vector_text=True,
            confidence=0.50,  # Tier 3: Triggers review queue (< 0.70)
            extraction_method="heuristic_classifier_anomaly",
        )

    # HEURISTIC 6: Product Grid (Pages containing product items with MRP tokens)
    if mrp_count >= 1:
        if mrp_count >= 3 and image_count >= 2:
            conf = 0.98  # Tier 1
        elif mrp_count >= 1 and image_count >= 1:
            conf = 0.92  # Tier 1
        else:
            conf = 0.80  # Tier 2

        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_PRODUCT_GRID,
            series_header=effective_series,
            section_name=section_name or effective_series,
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=conf,
            extraction_method="heuristic_classifier",
        )

    # HEURISTIC 7: Section Hero Opener (Page 1 of a series block)
    # Characterized by large header title (>= 18 pt), low text count, hero photo
    has_large_title = any((b.font_size or 0.0) >= 18.0 for b in text_blocks)
    is_section_opener = (section_start is not None and page_number == section_start)

    if (has_large_title or is_section_opener) and mrp_count == 0 and image_count >= 1 and len(all_text) < 150:
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_HERO,
            series_header=effective_series,
            section_name=section_name or effective_series,
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=0.94,  # Tier 1
            extraction_method="heuristic_classifier",
        )

    # HEURISTIC 8: Editorial Feature Bullets (Page 2 of a series block)
    editorial_keywords = [
        "SINGLE LEVER", "QUARTER TURN", "CERAMIC DISC", "FOAM FLOW", "AERATOR",
        "ELEGANCE", "PERFECT BLEND", "LIFT UP MECHANISM", "FEATURES:", "SURFACE COATING",
        "WATER SAVING", "HANDS FREE", "SUITABLE FOR", "SILVER PLATED", "MADE FROM"
    ]
    has_editorial_copy = any(kw in all_text_upper for kw in editorial_keywords)

    if has_editorial_copy and mrp_count == 0:
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_EDITORIAL,
            series_header=effective_series,
            section_name=section_name or effective_series,
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=0.92,  # Tier 1
            extraction_method="heuristic_classifier",
        )

    # HEURISTIC 9: Ambiguous / Anomaly in Section (Pages with 0 text or unclassifiable inside section)
    if len(all_text.strip()) == 0:
        # Near blank page inside section (e.g. p.79, p.85, p.121, p.201)
        conf = 0.55 if section_name else 0.85
        return Page(
            page_number=page_number,
            printed_page_number=printed_page_num,
            archetype=ARCHETYPE_LIFESTYLE,
            series_header=effective_series,
            section_name=section_name or "Blank/Visual",
            blocks_count=len(raw_blocks),
            has_vector_text=False,
            confidence=conf,  # Tier 3: Triggers review queue if inside section
            extraction_method="heuristic_classifier_sparse",
        )

    # HEURISTIC 10: General Lifestyle (Marketing imagery, front matter)
    return Page(
        page_number=page_number,
        printed_page_number=printed_page_num,
        archetype=ARCHETYPE_LIFESTYLE,
        series_header=effective_series,
        section_name=section_name or effective_series or "Lifestyle",
        blocks_count=len(raw_blocks),
        has_vector_text=False,
        confidence=0.85,  # Tier 2
        extraction_method="heuristic_classifier",
    )


def classify_all_pages(
    pdf_path: Optional[Path] = None,
    sections_info: Optional[dict[str, Any]] = None,
) -> list[Page]:
    """Extract blocks and classify all 202 pages of the catalogue, maintaining series continuity."""
    target = pdf_path or (settings.raw_data_dir / PDF_FILENAME)
    doc = pymupdf.open(str(target))

    known_series: list[str] = []
    sections_map: list[dict[str, Any]] = []
    if sections_info:
        known_series = sections_info.get("faucet_series", [])
        sections_map = sections_info.get("sections", [])

    pages: list[Page] = []
    current_series: Optional[str] = None

    for idx in range(len(doc)):
        page_no = idx + 1
        page = doc[idx]
        blocks = extract_page_blocks(page, page_no)

        # Resolve section name and section start page from sections_map
        sec_name = None
        sec_start = None
        for sec in sections_map:
            if sec.get("pdf_page_start", 0) <= page_no <= sec.get("pdf_page_end", 0):
                sec_name = sec.get("name")
                sec_start = sec.get("pdf_page_start")
                break

        page_record = classify_page(
            page=page,
            page_number=page_no,
            raw_blocks=blocks,
            known_series=known_series,
            current_series=current_series,
            section_name=sec_name,
            section_start=sec_start,
        )

        if page_record.series_header:
            current_series = page_record.series_header

        pages.append(page_record)

    return pages


def save_pages_parquet(pages: list[Page], out_path: Optional[Path] = None) -> Path:
    """Serialize classified pages to Parquet with required schema."""
    target = out_path or (settings.interim_data_dir / "pages.parquet")
    settings.interim_data_dir.mkdir(parents=True, exist_ok=True)

    records = [
        {
            "page_no": p.page_number,
            "archetype": p.archetype,
            "confidence": float(p.confidence),
            "series_header": p.series_header,
            "section_name": p.section_name,
            "blocks_count": p.blocks_count,
            "has_vector_text": bool(p.has_vector_text),
        }
        for p in pages
    ]

    df = pd.DataFrame(records)
    df.to_parquet(str(target), index=False, engine="pyarrow")
    logger.info("Saved {} classified pages to: {}", len(df), target)
    return target

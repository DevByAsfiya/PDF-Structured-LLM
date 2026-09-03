"""catalogue_spec.py - JAL Faucets 2025 catalogue-specific constants.

This file houses all JAL-specific constants in one place: exact PDF filename,
SKU and MRP regexes, series list, page offsets, page ranges, archetypes,
and grid geometry tolerances.

Hard rule: Nothing that is not a constant belongs in this file.
"""

from typing import Final, Pattern
import re

# Document identity and metadata
MANUFACTURER: Final[str] = "JAL"
PDF_FILENAME: Final[str] = "JAL FAUCETS 2025.pdf"
TOTAL_PAGES: Final[int] = 202
PAGE_WIDTH_PT: Final[float] = 595.276
PAGE_HEIGHT_PT: Final[float] = 841.89
PDF_PRODUCER: Final[str] = "PDFium"
PDF_VERSION: Final[str] = "1.7"
PRICE_EFFECTIVE_DATE: Final[str] = "23.11.2024"
CURRENCY: Final[str] = "INR"

# Printed page number to 1-indexed PDF page index offset default (~7)
# Phase 1 must derive this empirically from the INDEX page (PDF page 6)
# and log a warning if the derived offset differs.
PRINTED_TO_PDF_PAGE_OFFSET: Final[int] = 7

# Ground-truth known page indices (1-indexed PDF page numbers)
# NOTE: Page ranges (front matter, product grids, parts tables) are not hardcoded;
# the Phase 1 classifier determines the archetype per page dynamically.
COVER_PAGE_INDEX: Final[int] = 1
INDEX_PAGE_INDEX: Final[int] = 6

# Standard development loop page sample (fast verification)
FAST_DEV_LOOP_PAGE_RANGE: Final[tuple[int, int]] = (38, 45)

# Golden evaluation benchmark pages (1-indexed PDF page indices)
# PDF indices 40, 90, 150 correspond to printed pages 33, 83, 143; page 198 is parts table.
GOLDEN_EVAL_PAGES: Final[tuple[int, ...]] = (40, 90, 150, 198)

# Page Archetypes
ARCHETYPE_COVER: Final[str] = "cover"
ARCHETYPE_INDEX: Final[str] = "index"
ARCHETYPE_LIFESTYLE: Final[str] = "lifestyle"
ARCHETYPE_PRODUCT_GRID: Final[str] = "product_grid"
ARCHETYPE_PARTS_TABLE: Final[str] = "parts_table"
ARCHETYPE_TECH_SPEC: Final[str] = "tech_spec"

ALL_ARCHETYPES: Final[tuple[str, ...]] = (
    ARCHETYPE_COVER,
    ARCHETYPE_INDEX,
    ARCHETYPE_LIFESTYLE,
    ARCHETYPE_PRODUCT_GRID,
    ARCHETYPE_PARTS_TABLE,
    ARCHETYPE_TECH_SPEC,
)

# Extraction Regular Expressions (Deterministic)
# JAL SKU / Cat No: matches numeric and alphanumeric SKUs
# Grid codes: e.g. 82456, 82470, 40120N
# Parts-table codes: e.g. 76510S01, 73390S01, 75730S103
SKU_PATTERN: Final[Pattern[str]] = re.compile(r"\b([0-9]{4,6}(?:[A-Z][0-9]*)?)\b")

# MRP pattern for product grid captions: e.g. "MRP 1992/-", "MRP 2066/-", "M.R.P. 1,594/-"
MRP_PATTERN: Final[Pattern[str]] = re.compile(
    r"(?:M\.?R\.?P\.?|MRP)\s*(?:\(Rs\.?\s*Each\))?\s*:?\s*([0-9,]+(?:\.[0-9]{2})?)\s*(?:/\-|/-)?",
    re.IGNORECASE,
)

# Parts-table price pattern: bare numbers in table cells with no MRP prefix (e.g. "1424.00", "1,424.00")
TABLE_PRICE_PATTERN: Final[Pattern[str]] = re.compile(
    r"^\s*(?:Rs\.?\s*)?([0-9,]+(?:\.[0-9]{2})?)\s*$",
    re.IGNORECASE,
)

# Price effective date on page 1
PRICE_EFFECTIVE_DATE_PATTERN: Final[Pattern[str]] = re.compile(
    r"M\.?R\.?P\.?\s*w\.?e\.?f\.?\s*([0-9]{1,2}[\.\-\/][0-9]{1,2}[\.\-\/][0-9]{4})",
    re.IGNORECASE,
)

# Dimension/size specification (e.g. "15 mm", "20 mm")
SIZE_PATTERN: Final[Pattern[str]] = re.compile(
    r"\b([0-9]+(?:\.[0-9]+)?\s*(?:mm|inch|cm|g|kg|l|ltr|mtr|m))\b",
    re.IGNORECASE,
)

# NOTE: The series list is NOT hardcoded here.
# Series names (e.g. TANSA, WARNA PRO, NALINI PRO, DRAS PRO, NALINI, WARNA, etc.)
# and parts-table series (e.g. NIRA, NEUR, NUBRA, TITAS, INDUS) must be parsed at runtime
# from the INDEX page in Phase 1 and written to data/interim/sections.json.

# Grid Geometry Tolerances (Points & Pixels)
GRID_COLUMNS_MIN: Final[int] = 3
GRID_COLUMNS_MAX: Final[int] = 4
COLUMN_X_TOLERANCE_PT: Final[float] = 12.0
IMAGE_CAPTION_MAX_VERTICAL_GAP_PT: Final[float] = 25.0
MAX_CAPTION_OFFSET_PT: Final[float] = 90.0
MAX_HORIZONTAL_DRIFT_PT: Final[float] = 15.0
SECTION_HEADER_MIN_FONT_SIZE_PT: Final[float] = 20.0
MIN_INTERIOR_BOUNDING_BOX_INTERSECTION_RATIO: Final[float] = 0.50

# Image Extraction Specifications
SOURCE_IMAGE_COLORSPACE: Final[str] = "CMYK"
TARGET_IMAGE_COLORSPACE: Final[str] = "sRGB"
SOURCE_IMAGE_DPI: Final[int] = 300
MIN_IMAGE_AREA_PX: Final[int] = 5000
MAX_IMAGE_AREA_RATIO: Final[float] = 0.85

"""active_profile.py - Shim for JAL catalogue profile migration.

This file loads the default profile and re-exports the names,
to keep everything working during migration.
"""

from typing import Final, Pattern
from pdfscraper.config import settings
from pdfscraper.profile import CatalogueProfile

# Load the default profile
_profile = CatalogueProfile.load_yaml(settings.profile_path)

MANUFACTURER: Final[str] = _profile.manufacturer
PDF_FILENAME: Final[str] = _profile.pdf_filename
TOTAL_PAGES: Final[int] = _profile.total_pages
PAGE_WIDTH_PT: Final[float] = _profile.page_width_pt
PAGE_HEIGHT_PT: Final[float] = _profile.page_height_pt
PDF_PRODUCER: Final[str] = _profile.pdf_producer
PDF_VERSION: Final[str] = _profile.pdf_version
PRICE_EFFECTIVE_DATE: Final[str] = _profile.price_effective_date
CURRENCY: Final[str] = _profile.currency

PRINTED_TO_PDF_PAGE_OFFSET: Final[int] = _profile.printed_to_pdf_page_offset
COVER_PAGE_INDEX: Final[int] = _profile.cover_page_index
INDEX_PAGE_INDEX: Final[int] = _profile.index_page_index
FAST_DEV_LOOP_PAGE_RANGE: Final[tuple[int, int]] = tuple(_profile.fast_dev_loop_page_range)
GOLDEN_EVAL_PAGES: Final[tuple[int, ...]] = tuple(_profile.golden_eval_pages)

ARCHETYPE_COVER: Final[str] = _profile.archetypes.cover
ARCHETYPE_INDEX: Final[str] = _profile.archetypes.index
ARCHETYPE_HERO: Final[str] = _profile.archetypes.hero
ARCHETYPE_EDITORIAL: Final[str] = _profile.archetypes.editorial
ARCHETYPE_LIFESTYLE: Final[str] = _profile.archetypes.lifestyle
ARCHETYPE_PRODUCT_GRID: Final[str] = _profile.archetypes.product_grid
ARCHETYPE_PARTS_TABLE: Final[str] = _profile.archetypes.parts_table
ARCHETYPE_TECH_SPEC: Final[str] = _profile.archetypes.tech_spec

ALL_ARCHETYPES: Final[tuple[str, ...]] = tuple(_profile.archetypes.all)

SKU_PATTERN: Final[Pattern[str]] = _profile.regex_patterns.sku
MRP_PATTERN: Final[Pattern[str]] = _profile.regex_patterns.mrp
TABLE_PRICE_PATTERN: Final[Pattern[str]] = _profile.regex_patterns.table_price
PRICE_EFFECTIVE_DATE_PATTERN: Final[Pattern[str]] = _profile.regex_patterns.price_effective_date
SIZE_PATTERN: Final[Pattern[str]] = _profile.regex_patterns.size

GRID_COLUMNS_MIN: Final[int] = _profile.grid_geometry.grid_columns_min
GRID_COLUMNS_MAX: Final[int] = _profile.grid_geometry.grid_columns_max
COLUMN_X_TOLERANCE_PT: Final[float] = _profile.grid_geometry.column_x_tolerance_pt
IMAGE_CAPTION_MAX_VERTICAL_GAP_PT: Final[float] = _profile.grid_geometry.image_caption_max_vertical_gap_pt
MAX_CAPTION_OFFSET_PT: Final[float] = _profile.grid_geometry.max_caption_offset_pt
MAX_HORIZONTAL_DRIFT_PT: Final[float] = _profile.grid_geometry.max_horizontal_drift_pt
SECTION_HEADER_MIN_FONT_SIZE_PT: Final[float] = _profile.grid_geometry.section_header_min_font_size_pt
MIN_INTERIOR_BOUNDING_BOX_INTERSECTION_RATIO: Final[float] = _profile.grid_geometry.min_interior_bounding_box_intersection_ratio

SOURCE_IMAGE_COLORSPACE: Final[str] = _profile.image_extraction.source_image_colorspace
TARGET_IMAGE_COLORSPACE: Final[str] = _profile.image_extraction.target_image_colorspace
SOURCE_IMAGE_DPI: Final[int] = _profile.image_extraction.source_image_dpi
MIN_IMAGE_AREA_PX: Final[int] = _profile.image_extraction.min_image_area_px
MAX_IMAGE_AREA_RATIO: Final[float] = _profile.image_extraction.max_image_area_ratio

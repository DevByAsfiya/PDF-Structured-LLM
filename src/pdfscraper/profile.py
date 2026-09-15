"""profile.py - Catalogue profile management using pydantic and YAML."""

import re
from pathlib import Path
from typing import Pattern, Any, List, Tuple
import yaml
from pydantic import BaseModel, Field

class Archetypes(BaseModel):
    cover: str
    index: str
    hero: str
    editorial: str
    lifestyle: str
    product_grid: str
    parts_table: str
    tech_spec: str

    @property
    def all(self) -> tuple[str, ...]:
        return (
            self.cover, self.index, self.hero, self.editorial, 
            self.lifestyle, self.product_grid, self.parts_table, self.tech_spec
        )

class RegexPatterns(BaseModel):
    sku: Pattern[str]
    mrp: Pattern[str]
    table_price: Pattern[str]
    price_effective_date: Pattern[str]
    size: Pattern[str]

    def __init__(self, **data):
        super().__init__(**data)
        if isinstance(data.get('sku'), str):
            self.sku = re.compile(data['sku'])
        if isinstance(data.get('mrp'), str):
            self.mrp = re.compile(data['mrp'], re.IGNORECASE)
        if isinstance(data.get('table_price'), str):
            self.table_price = re.compile(data['table_price'], re.IGNORECASE)
        if isinstance(data.get('price_effective_date'), str):
            self.price_effective_date = re.compile(data['price_effective_date'], re.IGNORECASE)
        if isinstance(data.get('size'), str):
            self.size = re.compile(data['size'], re.IGNORECASE)

class GridGeometry(BaseModel):
    grid_columns_min: int
    grid_columns_max: int
    column_x_tolerance_pt: float
    image_caption_max_vertical_gap_pt: float
    max_caption_offset_pt: float
    max_horizontal_drift_pt: float
    section_header_min_font_size_pt: float
    min_interior_bounding_box_intersection_ratio: float

class ImageExtraction(BaseModel):
    source_image_colorspace: str
    target_image_colorspace: str
    source_image_dpi: int
    min_image_area_px: int
    max_image_area_ratio: float

class CatalogueProfile(BaseModel):
    manufacturer: str
    pdf_filename: str
    total_pages: int
    page_width_pt: float
    page_height_pt: float
    pdf_producer: str
    pdf_version: str
    price_effective_date: str
    currency: str

    printed_to_pdf_page_offset: int
    cover_page_index: int
    index_page_index: int
    fast_dev_loop_page_range: Tuple[int, int]
    golden_eval_pages: Tuple[int, ...]

    archetypes: Archetypes
    regex_patterns: RegexPatterns
    grid_geometry: GridGeometry
    image_extraction: ImageExtraction

    @classmethod
    def load_yaml(cls, path: str | Path) -> "CatalogueProfile":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

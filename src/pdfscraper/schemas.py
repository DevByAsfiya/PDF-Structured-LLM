"""schemas.py - Pydantic v2 data models for the JAL Catalogue Scraper pipeline.

Hard Rules:
- Every extracted model carries `confidence: float` and `extraction_method: str`.
- One-to-many image-to-SKU relationship is explicitly modeled:
  One `Product` owns multiple `Variant` instances, each having its own SKU and MRP.
"""

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    """Bounding box coordinates in PDF points (top-left origin)."""
    model_config = ConfigDict(frozen=True)

    x0: float = Field(..., description="Left coordinate (pt)")
    y0: float = Field(..., description="Top coordinate (pt)")
    x1: float = Field(..., description="Right coordinate (pt)")
    y1: float = Field(..., description="Bottom coordinate (pt)")

    @property
    def width(self) -> float:
        """Width of bounding box in points."""
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        """Height of bounding box in points."""
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        """Area of bounding box in square points."""
        return self.width * self.height


class Attribute(BaseModel):
    """Normalized technical attribute (e.g. size_mm, finish, mounting_type, cartridge)."""
    name: str = Field(..., description="Attribute name (e.g. 'size_mm', 'finish')")
    value: Any = Field(..., description="Extracted or normalized attribute value")
    unit: Optional[str] = Field(None, description="Measurement unit, if applicable (e.g. 'mm')")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score (0.0 to 1.0)",
    )
    extraction_method: str = Field(
        ...,
        description="Extraction method (e.g. 'regex_size', 'llm_normalized')",
    )


class Variant(BaseModel):
    """A specific SKU variant of a product (e.g. 15mm vs 20mm stop cock)."""
    sku: str = Field(..., description="JAL SKU / Cat No (e.g. '82456', '82470')")
    mrp: float = Field(..., ge=0.0, description="Maximum Retail Price in INR")
    raw_caption_line: str = Field(..., description="Exact verbatim line from the PDF caption")
    dimensions_or_size: Optional[str] = Field(
        None,
        description="Extracted dimensional spec (e.g. '15 mm', '20 mm')",
    )
    description_suffix: Optional[str] = Field(
        None,
        description="Variant-specific description text if distinct from product base description",
    )
    attributes: list[Attribute] = Field(
        default_factory=list,
        description="Structured variant-specific attributes",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score (0.0 to 1.0)",
    )
    extraction_method: str = Field(
        ...,
        description="Deterministic method used (e.g. 'regex_grammar', 'caption_tokenizer')",
    )


class Asset(BaseModel):
    """Extracted raster image asset from the catalogue."""
    asset_id: str = Field(..., description="Unique asset identifier / hash")
    page_number: int = Field(..., ge=1, description="1-indexed PDF page where asset appears")
    bbox: BoundingBox = Field(..., description="Asset bounding box on page")
    file_path: str = Field(..., description="Relative path in data/assets/")
    width_px: int = Field(..., ge=1, description="Image pixel width")
    height_px: int = Field(..., ge=1, description="Image pixel height")
    colorspace: str = Field(default="sRGB", description="Target colorspace (CMYK converted to sRGB)")
    perceptual_hash: Optional[str] = Field(None, description="pHash string for visual deduplication")
    role: str = Field(default="product_image", description="Asset role ('product_image', 'lifestyle', 'drawing')")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Asset extraction confidence",
    )
    extraction_method: str = Field(
        default="pymupdf_image_stream",
        description="Method used for raster extraction",
    )


class RawBlock(BaseModel):
    """Raw extracted block from PDF page (text span or raster image rect)."""
    page_number: int = Field(..., ge=1, description="1-indexed PDF page number")
    block_type: Literal["text", "image"] = Field(..., description="Block type: 'text' or 'image'")
    bbox: BoundingBox = Field(..., description="Bounding box on the page")
    text: Optional[str] = Field(None, description="Extracted raw text content for text blocks")
    image_index: Optional[int] = Field(None, description="Index of image in page stream")
    font_size: Optional[float] = Field(None, description="Font size in points for text spans")
    font_name: Optional[str] = Field(None, description="Font family/name for text spans")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence",
    )
    extraction_method: str = Field(
        default="pymupdf_span_extraction",
        description="Extraction method identifier",
    )


class Product(BaseModel):
    """Master product entity representing one visual fixture with one or more SKU variants.

    Explicitly models the 1-to-many relationship: One Product visual owns 1+ Variants.
    """
    product_id: str = Field(..., description="Deterministic product ID (e.g. 'PROD_P040_01')")
    series_name: str = Field(..., description="Manufacturer collection/series (e.g. 'WARNA PRO')")
    title: str = Field(..., description="Base product title/description")
    category: Optional[str] = Field(None, description="Assigned category (e.g. 'Stop Cock', 'Basin Mixer')")
    subcategory: Optional[str] = Field(None, description="Assigned subcategory")
    price_tier: Optional[str] = Field(
        None,
        description="Statistical within-category price tier ('value', 'mid', 'premium', 'luxury')",
    )
    page_number: int = Field(..., ge=1, description="1-indexed PDF page number")
    printed_page_number: Optional[int] = Field(None, description="Printed page number from footer")
    bbox: BoundingBox = Field(..., description="Total envelope bounding box for product + caption")
    image_asset_id: Optional[str] = Field(None, description="Foreign key to Asset.asset_id")
    asset: Optional[Asset] = Field(None, description="Associated image asset instance")
    variants: list[Variant] = Field(
        ...,
        min_length=1,
        description="List of SKU variants under this product visual (1-to-many)",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate extraction confidence score (0.0 to 1.0)",
    )
    extraction_method: str = Field(
        ...,
        description="Method used for product binding (e.g. 'spatial_grid_join')",
    )


class Page(BaseModel):
    """A classified page of the catalogue with structural metadata."""
    page_number: int = Field(..., ge=1, description="1-indexed PDF page number")
    printed_page_number: Optional[int] = Field(None, description="Printed page number on footer")
    archetype: str = Field(
        ...,
        description="Classified archetype ('cover', 'index', 'lifestyle', 'product_grid', 'parts_table', 'tech_spec')",
    )
    series_header: Optional[str] = Field(None, description="Detected series name in page header")
    blocks_count: int = Field(default=0, ge=0, description="Total raw blocks extracted on page")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Page classification confidence score",
    )
    extraction_method: str = Field(
        ...,
        description="Classification method (e.g. 'heuristic_classifier', 'vlm_fallback')",
    )


class Catalogue(BaseModel):
    """Top-level catalogue metadata and ingestion summary."""
    catalogue_id: str = Field(default="jal_faucets_2025", description="Unique catalogue identifier")
    filename: str = Field(..., description="Source PDF filename")
    manufacturer: str = Field(default="JAL", description="Manufacturer name")
    edition: str = Field(default="2025", description="Catalogue edition")
    total_pages: int = Field(..., ge=1, description="Total page count")
    price_effective_date: str = Field(..., description="Effective price date (e.g. '23.11.2024')")
    currency: str = Field(default="INR", description="Price currency code")
    sha256: Optional[str] = Field(None, description="SHA-256 checksum of source PDF file")
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Ingestion timestamp (UTC)")
    series_found: list[str] = Field(default_factory=list, description="List of all detected series")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Catalogue metadata confidence")
    extraction_method: str = Field(default="deterministic_pdf_metadata", description="Method used")


class ExtractionResult(BaseModel):
    """Summary outcome of a pipeline stage or end-to-end execution."""
    stage: str = Field(..., description="Pipeline stage identifier (e.g. '03_extract', '05_parse')")
    pages_processed: list[int] = Field(default_factory=list, description="List of page indices processed")
    products_count: int = Field(default=0, ge=0, description="Count of products extracted")
    variants_count: int = Field(default=0, ge=0, description="Count of SKU variants extracted")
    review_queue_count: int = Field(default=0, ge=0, description="Entities routed to human review queue")
    artifacts_written: list[str] = Field(default_factory=list, description="Paths of saved artifacts")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Stage execution confidence")
    extraction_method: str = Field(default="pipeline_stage_runner", description="Execution method")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of execution (UTC)")

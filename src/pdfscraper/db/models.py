"""models.py - SQLAlchemy ORM models for the JAL Catalogue Scraper database.

Maps the pydantic data model to SQLite tables:
catalogue, page, product, variant, asset, attribute (EAV),
taxonomy_node, review_item.

Note: SKU deduplication is currently per-page, so the same SKU can appear
on two different pages as two distinct products. There is no UNIQUE constraint
on SKU alone — the unique key is (product_id).
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session


class Base(DeclarativeBase):
    pass


class CatalogueRow(Base):
    """Top-level catalogue metadata."""

    __tablename__ = "catalogue"

    catalogue_id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    manufacturer = Column(String, nullable=False, default="JAL")
    edition = Column(String, default="2025")
    total_pages = Column(Integer, nullable=False)
    price_effective_date = Column(String)
    currency = Column(String, default="INR")
    sha256 = Column(String)
    ingested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    pages = relationship("PageRow", back_populates="catalogue", cascade="all, delete-orphan")
    products = relationship("ProductRow", back_populates="catalogue", cascade="all, delete-orphan")


class PageRow(Base):
    """Classified catalogue page."""

    __tablename__ = "page"

    id = Column(Integer, primary_key=True, autoincrement=True)
    catalogue_id = Column(String, ForeignKey("catalogue.catalogue_id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    printed_page_number = Column(Integer)
    archetype = Column(String, nullable=False)
    series_header = Column(String)
    section_name = Column(String)
    blocks_count = Column(Integer, default=0)
    has_vector_text = Column(Boolean, default=False)
    confidence = Column(Float, nullable=False)
    extraction_method = Column(String, nullable=False)

    catalogue = relationship("CatalogueRow", back_populates="pages")

    __table_args__ = (
        UniqueConstraint("catalogue_id", "page_number", name="uq_page_catalogue_page"),
    )


class AssetRow(Base):
    """Extracted raster image asset."""

    __tablename__ = "asset"

    asset_id = Column(String, primary_key=True)
    page_number = Column(Integer, nullable=False)
    bbox_x0 = Column(Float)
    bbox_y0 = Column(Float)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    file_path = Column(String)
    width_px = Column(Integer)
    height_px = Column(Integer)
    colorspace = Column(String, default="sRGB")
    perceptual_hash = Column(String)
    role = Column(String, default="product_image")
    confidence = Column(Float, default=1.0)
    extraction_method = Column(String, default="pymupdf_image_stream")


class ProductRow(Base):
    """Master product entity with one or more SKU variants."""

    __tablename__ = "product"

    product_id = Column(String, primary_key=True)
    catalogue_id = Column(String, ForeignKey("catalogue.catalogue_id"), nullable=False)
    series_name = Column(String, nullable=False)
    title = Column(String, nullable=False)
    category = Column(String, ForeignKey("taxonomy_node.name"), nullable=True)
    subcategory = Column(String)
    price_tier = Column(String)
    page_number = Column(Integer, nullable=False)
    printed_page_number = Column(Integer)
    bbox_x0 = Column(Float)
    bbox_y0 = Column(Float)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    image_asset_id = Column(String, ForeignKey("asset.asset_id"))
    confidence = Column(Float, nullable=False)
    extraction_method = Column(String, nullable=False)

    catalogue = relationship("CatalogueRow", back_populates="products")
    asset = relationship("AssetRow", foreign_keys=[image_asset_id])
    taxonomy_node = relationship("TaxonomyNodeRow", foreign_keys=[category])
    variants = relationship("VariantRow", back_populates="product", cascade="all, delete-orphan")


class VariantRow(Base):
    """A specific SKU variant of a product."""

    __tablename__ = "variant"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, ForeignKey("product.product_id"), nullable=False)
    sku = Column(String, nullable=False, index=True)
    mrp = Column(Float)  # nullable: Rule 11 — null price is never zero
    raw_caption_line = Column(Text)
    dimensions_or_size = Column(String)
    description_suffix = Column(String)
    confidence = Column(Float, nullable=False)
    extraction_method = Column(String, nullable=False)

    product = relationship("ProductRow", back_populates="variants")
    attributes = relationship("AttributeRow", back_populates="variant", cascade="all, delete-orphan")


class AttributeRow(Base):
    """EAV attribute row for a variant."""

    __tablename__ = "attribute"

    id = Column(Integer, primary_key=True, autoincrement=True)
    variant_id = Column(Integer, ForeignKey("variant.id"), nullable=False)
    name = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    unit = Column(String)
    confidence = Column(Float, nullable=False)
    extraction_method = Column(String, nullable=False)

    variant = relationship("VariantRow", back_populates="attributes")


class TaxonomyNodeRow(Base):
    """Hierarchical taxonomy node for product categorization."""

    __tablename__ = "taxonomy_node"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    parent_id = Column(Integer, ForeignKey("taxonomy_node.id"))
    level = Column(Integer, nullable=False, default=0)
    description = Column(Text)

    parent = relationship("TaxonomyNodeRow", remote_side=[id])
    children = relationship("TaxonomyNodeRow", back_populates="parent")


class ReviewItemRow(Base):
    """Items flagged for human review (low confidence, missing data, etc.)."""

    __tablename__ = "review_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, ForeignKey("product.product_id"))
    variant_id = Column(Integer, ForeignKey("variant.id"))
    page_number = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    product = relationship("ProductRow")
    variant = relationship("VariantRow")


def init_db(db_path: str) -> "Engine":
    """Create engine, create all tables, return engine."""
    from sqlalchemy import create_engine as _create_engine

    engine = _create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine

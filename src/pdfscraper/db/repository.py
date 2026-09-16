"""repository.py - The only query surface for the catalogue database.

Nothing else in the project writes SQL. All database reads and writes
go through this module.
"""

import json
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session, sessionmaker

from pdfscraper.config import settings
from pdfscraper.db.models import (
    AssetRow,
    AttributeRow,
    Base,
    CatalogueRow,
    PageRow,
    ProductRow,
    ReviewItemRow,
    TaxonomyNodeRow,
    VariantRow,
    init_db,
)


class CatalogueRepository:
    """Single entry point for all database operations."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or settings.sqlite_db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = init_db(str(self._db_path))
        self._session_factory = sessionmaker(bind=self._engine)

    def session(self) -> Session:
        """Return a new session."""
        return self._session_factory()

    # ── Load from parquet ─────────────────────────────────────────────

    def load_products_from_parquet(
        self,
        parquet_path: Optional[Path] = None,
        catalogue_id: str = "jal_faucets_2025",
    ) -> int:
        """Load products.parquet into the database. Idempotent — replaces on re-run.

        Returns the number of product rows inserted.
        """
        path = parquet_path or (settings.processed_data_dir / "products.parquet")
        if not path.exists():
            raise FileNotFoundError(f"Parquet file not found: {path}")

        df = pd.read_parquet(path)
        logger.info("Loading {} product rows from {}", len(df), path)

        with self.session() as session:
            # Ensure catalogue row exists
            cat = session.get(CatalogueRow, catalogue_id)
            if not cat:
                cat = CatalogueRow(
                    catalogue_id=catalogue_id,
                    filename="JAL FAUCETS 2025.pdf",
                    manufacturer="JAL",
                    edition="2025",
                    total_pages=202,
                    price_effective_date="23.11.2024",
                    currency="INR",
                )
                session.add(cat)
            else:
                # Idempotent: delete existing data for this catalogue.
                # Bulk delete() bypasses ORM cascade, so delete children first.
                product_ids = [
                    pid
                    for (pid,) in session.query(ProductRow.product_id)
                    .filter(ProductRow.catalogue_id == catalogue_id)
                    .all()
                ]
                if product_ids:
                    # Delete review items referencing these products
                    session.query(ReviewItemRow).filter(
                        ReviewItemRow.product_id.in_(product_ids)
                    ).delete(synchronize_session="fetch")
                    # Delete attributes → variants → products
                    variant_ids = [
                        vid
                        for (vid,) in session.query(VariantRow.id)
                        .filter(VariantRow.product_id.in_(product_ids))
                        .all()
                    ]
                    if variant_ids:
                        session.query(AttributeRow).filter(
                            AttributeRow.variant_id.in_(variant_ids)
                        ).delete(synchronize_session="fetch")
                    session.query(VariantRow).filter(
                        VariantRow.product_id.in_(product_ids)
                    ).delete(synchronize_session="fetch")
                    session.query(ProductRow).filter(
                        ProductRow.catalogue_id == catalogue_id
                    ).delete(synchronize_session="fetch")

            session.flush()

            product_count = 0
            for _, row in df.iterrows():
                product_id = row["product_id"]

                # Parse bbox
                bbox = _parse_json_field(row.get("bbox"))

                # Build product row
                product = ProductRow(
                    product_id=product_id,
                    catalogue_id=catalogue_id,
                    series_name=row.get("series_name", "UNKNOWN"),
                    title=row.get("title", ""),
                    category=row.get("category"),
                    subcategory=row.get("subcategory"),
                    price_tier=row.get("price_tier"),
                    page_number=int(row.get("page_number", 0)),
                    printed_page_number=_safe_int(row.get("printed_page_number")),
                    bbox_x0=bbox.get("x0") if bbox else None,
                    bbox_y0=bbox.get("y0") if bbox else None,
                    bbox_x1=bbox.get("x1") if bbox else None,
                    bbox_y1=bbox.get("y1") if bbox else None,
                    image_asset_id=row.get("image_asset_id"),
                    confidence=float(row.get("confidence", 0.0)),
                    extraction_method=row.get("extraction_method", "unknown"),
                )

                # Parse and attach asset
                asset_data = _parse_json_field(row.get("asset"))
                if asset_data and asset_data.get("asset_id"):
                    existing_asset = session.get(AssetRow, asset_data["asset_id"])
                    if not existing_asset:
                        asset_bbox = asset_data.get("bbox", {})
                        asset_row = AssetRow(
                            asset_id=asset_data["asset_id"],
                            page_number=int(asset_data.get("page_number", 0)),
                            bbox_x0=asset_bbox.get("x0"),
                            bbox_y0=asset_bbox.get("y0"),
                            bbox_x1=asset_bbox.get("x1"),
                            bbox_y1=asset_bbox.get("y1"),
                            file_path=asset_data.get("file_path"),
                            width_px=_safe_int(asset_data.get("width_px")),
                            height_px=_safe_int(asset_data.get("height_px")),
                            colorspace=asset_data.get("colorspace", "sRGB"),
                            perceptual_hash=asset_data.get("perceptual_hash"),
                            role=asset_data.get("role", "product_image"),
                            confidence=float(asset_data.get("confidence", 1.0)),
                            extraction_method=asset_data.get(
                                "extraction_method", "pymupdf_image_stream"
                            ),
                        )
                        session.add(asset_row)
                        session.flush()

                # Parse and attach variants
                variants_data = _parse_json_field(row.get("variants"))
                if isinstance(variants_data, list):
                    for v in variants_data:
                        variant = VariantRow(
                            product_id=product_id,
                            sku=v.get("sku", ""),
                            mrp=v.get("mrp"),  # None is correct — Rule 11
                            raw_caption_line=v.get("raw_caption_line", ""),
                            dimensions_or_size=v.get("dimensions_or_size"),
                            description_suffix=v.get("description_suffix"),
                            confidence=float(v.get("confidence", 0.0)),
                            extraction_method=v.get("extraction_method", "unknown"),
                        )
                        product.variants.append(variant)

                        # Parse and attach attributes
                        for attr in v.get("attributes", []):
                            attr_val = attr.get("value")
                            if isinstance(attr_val, (list, dict)):
                                attr_val = json.dumps(attr_val)
                            else:
                                attr_val = str(attr_val) if attr_val is not None else ""
                            attribute = AttributeRow(
                                name=attr.get("name", ""),
                                value=attr_val,
                                unit=attr.get("unit"),
                                confidence=float(attr.get("confidence", 0.0)),
                                extraction_method=attr.get(
                                    "extraction_method", "unknown"
                                ),
                            )
                            variant.attributes.append(attribute)

                session.add(product)
                product_count += 1

            # Flag low-confidence products for review
            review_count = 0
            for product in (
                session.query(ProductRow)
                .filter(ProductRow.catalogue_id == catalogue_id)
                .all()
            ):
                if product.confidence < settings.confidence_threshold:
                    review = ReviewItemRow(
                        product_id=product.product_id,
                        page_number=product.page_number,
                        reason=f"Product confidence {product.confidence:.2f} below threshold {settings.confidence_threshold}",
                        confidence=product.confidence,
                    )
                    session.add(review)
                    review_count += 1

            session.commit()

        logger.info(
            "Loaded {} products, {} flagged for review into {}",
            product_count,
            review_count,
            self._db_path,
        )
        return product_count

    # ── Load pages from parquet ────────────────────────────────────────

    def load_pages_from_parquet(
        self,
        parquet_path: Optional[Path] = None,
        catalogue_id: str = "jal_faucets_2025",
    ) -> int:
        """Load pages.parquet into the database. Idempotent."""
        path = parquet_path or (settings.interim_data_dir / "pages.parquet")
        if not path.exists():
            raise FileNotFoundError(f"Parquet file not found: {path}")

        df = pd.read_parquet(path)
        logger.info("Loading {} page rows from {}", len(df), path)

        with self.session() as session:
            # Delete existing pages for this catalogue
            session.query(PageRow).filter(
                PageRow.catalogue_id == catalogue_id
            ).delete()
            session.flush()

            page_count = 0
            for _, row in df.iterrows():
                page = PageRow(
                    catalogue_id=catalogue_id,
                    page_number=int(row.get("page_no", 0)),
                    printed_page_number=_safe_int(row.get("printed_page_no")),
                    archetype=row.get("archetype", "unknown"),
                    series_header=row.get("series_header"),
                    section_name=row.get("section_name"),
                    blocks_count=int(row.get("blocks_count", 0)),
                    has_vector_text=bool(row.get("has_vector_text", False)),
                    confidence=float(row.get("confidence", 0.0)),
                    extraction_method=row.get(
                        "extraction_method", "heuristic_classifier"
                    ),
                )
                session.add(page)
                page_count += 1

            session.commit()

        logger.info("Loaded {} pages into {}", page_count, self._db_path)
        return page_count

    # ── Query helpers ─────────────────────────────────────────────────

    def get_cross_page_sku_collisions(self) -> pd.DataFrame:
        """Find SKUs that appear on more than one page.

        Returns a DataFrame with columns: sku, page_count, pages, product_ids.
        """
        with self.session() as session:
            results = (
                session.query(
                    VariantRow.sku,
                    func.count(func.distinct(ProductRow.page_number)).label("page_count"),
                    func.group_concat(func.distinct(ProductRow.page_number)).label("pages"),
                    func.group_concat(func.distinct(ProductRow.product_id)).label("product_ids"),
                )
                .join(ProductRow, VariantRow.product_id == ProductRow.product_id)
                .group_by(VariantRow.sku)
                .having(func.count(func.distinct(ProductRow.page_number)) > 1)
                .all()
            )

        if not results:
            return pd.DataFrame(columns=["sku", "page_count", "pages", "product_ids"])

        return pd.DataFrame(
            [
                {
                    "sku": r.sku,
                    "page_count": r.page_count,
                    "pages": r.pages,
                    "product_ids": r.product_ids,
                }
                for r in results
            ]
        )

    def get_product_count(self) -> int:
        """Total products in the database."""
        with self.session() as session:
            return session.query(func.count(ProductRow.product_id)).scalar() or 0

    def get_variant_count(self) -> int:
        """Total variants (SKUs) in the database."""
        with self.session() as session:
            return session.query(func.count(VariantRow.id)).scalar() or 0

    def get_review_queue(self) -> pd.DataFrame:
        """Return all unresolved review items."""
        with self.session() as session:
            results = (
                session.query(ReviewItemRow)
                .filter(ReviewItemRow.resolved == False)
                .all()
            )
        if not results:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "id": r.id,
                    "product_id": r.product_id,
                    "page_number": r.page_number,
                    "reason": r.reason,
                    "confidence": r.confidence,
                }
                for r in results
            ]
        )


# ── Private helpers ───────────────────────────────────────────────────


def _parse_json_field(val) -> Optional[dict | list]:
    """Parse a JSON string field from parquet. Returns None if empty/invalid."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _safe_int(val) -> Optional[int]:
    """Safely convert a value to int, returning None on failure."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None

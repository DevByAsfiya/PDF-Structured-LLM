"""grid_parser.py - Concrete parser for product_grid page archetype.

Assembles Product and Variant objects from spatial bindings and parsed
captions.  Inherits the series from the page header and attaches image
bbox + xref.

Hard rules:
- No LLM.  Deterministic extraction only.
- Every field carries confidence and extraction_method.
- Multi-SKU images produce one Product with multiple Variants.
"""

from __future__ import annotations

from typing import Optional

import pymupdf
from loguru import logger

from pdfscraper.catalogue_spec import (
    ARCHETYPE_PRODUCT_GRID,
    PRINTED_TO_PDF_PAGE_OFFSET,
)
from pdfscraper.extract.base import PageParser
from pdfscraper.extract.caption_grammar import tokenise_caption
from pdfscraper.layout.blocks import extract_page_blocks
from pdfscraper.layout.geometry import (
    bind_images_to_captions,
    detect_series_header,
    infer_columns,
    _is_product_image,
)
from pdfscraper.schemas import (
    BoundingBox,
    Product,
    RawBlock,
    Variant,
)


class GridParser(PageParser):
    """Parser for ``product_grid`` pages.

    Pipeline:
    1. Filter product images (exclude decorative masks).
    2. Infer column boundaries from image x-positions.
    3. Bind each image to its caption block (same column, nearest below).
    4. Tokenise each caption into (sku, description, mrp) tuples.
    5. Assemble Product + Variant objects with inherited series.
    """

    def parse(
        self,
        page: pymupdf.Page,
        blocks: list[RawBlock],
        *,
        page_number: int,
        series_name: Optional[str] = None,
        section_name: Optional[str] = None,
        known_series: Optional[list[str]] = None,
    ) -> list[Product]:
        """Parse a product-grid page into Product instances."""
        text_blocks = [b for b in blocks if b.block_type == "text"]
        image_blocks = [
            b for b in blocks
            if b.block_type == "image" and _is_product_image(b)
        ]

        if not image_blocks:
            logger.debug(
                "Page {}: no product images found, skipping grid parse",
                page_number,
            )
            return []

        # Detect series from page header (handles letter-spaced names)
        effective_series = series_name or ""
        if known_series:
            detected = detect_series_header(text_blocks, known_series)
            if detected:
                effective_series = detected

        if not effective_series:
            effective_series = section_name or "UNKNOWN"

        # Infer columns and bind images to captions
        columns = infer_columns(image_blocks)
        bindings = bind_images_to_captions(blocks, columns)

        # Printed page number from PDF page index
        printed_page = max(1, page_number - PRINTED_TO_PDF_PAGE_OFFSET)

        products: list[Product] = []
        product_counter = 0

        for binding in bindings:
            product_counter += 1
            img = binding.image_block

            # Tokenise caption
            parse_result = tokenise_caption(binding.caption_blocks)

            if not parse_result.tokens:
                # No SKUs parsed — create a review-queue product
                logger.warning(
                    "Page {}, image #{}: no tokens parsed from caption. "
                    "Warnings: {}",
                    page_number,
                    product_counter,
                    parse_result.warnings,
                )
                continue  # Skip — nothing useful to emit

            # Build variants from tokens
            variants: list[Variant] = []
            for token in parse_result.tokens:
                variant = Variant(
                    sku=token.sku,
                    mrp=token.mrp,
                    raw_caption_line=token.raw_text,
                    dimensions_or_size=token.dimensions_or_size,
                    description_suffix=(
                        token.description if not token.is_primary else None
                    ),
                    confidence=token.confidence,
                    extraction_method=token.extraction_method,
                )
                variants.append(variant)

            # Base description from the primary token
            primary_token = parse_result.tokens[0]
            base_title = primary_token.description or f"Product {primary_token.sku}"

            # Product-level confidence: min of binding confidence and caption confidence
            product_confidence = min(binding.confidence, parse_result.confidence)

            # Compute envelope bbox (image + caption)
            all_bboxes = [img.bbox] + [cb.bbox for cb in binding.caption_blocks]
            envelope = BoundingBox(
                x0=min(b.x0 for b in all_bboxes),
                y0=min(b.y0 for b in all_bboxes),
                x1=max(b.x1 for b in all_bboxes),
                y1=max(b.y1 for b in all_bboxes),
            )

            product_id = f"PROD_P{page_number:03d}_{product_counter:02d}"

            product = Product(
                product_id=product_id,
                series_name=effective_series,
                title=base_title,
                page_number=page_number,
                printed_page_number=printed_page,
                bbox=envelope,
                image_asset_id=None,  # Populated by asset exporter stage
                variants=variants,
                confidence=product_confidence,
                extraction_method="spatial_grid_join",
            )

            # Attach image xref as product-level metadata for the asset stage
            # (stored on the first variant's raw_caption_line for tracing)
            if img.xref is not None:
                product.image_asset_id = f"xref_{img.xref}"

            products.append(product)

        logger.info(
            "Page {}: {} images, {} products, {} total variants",
            page_number,
            len(image_blocks),
            len(products),
            sum(len(p.variants) for p in products),
        )

        return products

"""exporter.py - Extract, convert, deduplicate, and save raster images from PDF."""

import io
from pathlib import Path

import pymupdf
from loguru import logger
from PIL import Image

from pdfscraper.assets.dedupe import compute_phash
from pdfscraper.catalogue_spec import MIN_IMAGE_AREA_PX
from pdfscraper.schemas import Asset, Product


def export_assets(doc: pymupdf.Document, products: list[Product], output_dir: Path) -> list[Product]:
    """Export images for a list of products, deduplicate, and update image_asset_id."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Track seen phashes to asset ID
    phash_to_asset_id: dict[str, str] = {}
    
    for product in products:
        if not product.image_asset_id or not product.image_asset_id.startswith("xref_"):
            continue
            
        xref_str = product.image_asset_id.replace("xref_", "")
        try:
            xref = int(xref_str)
        except ValueError:
            product.image_asset_id = None
            continue
        
        # Extract image bytes
        try:
            base_image = doc.extract_image(xref)
            if not base_image:
                product.image_asset_id = None
                continue
                
            image_bytes = base_image["image"]
            img = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            logger.error(f"Failed to extract image xref {xref}: {e}")
            product.image_asset_id = None
            continue
            
        # Filter masks by area
        width, height = img.size
        if width * height < MIN_IMAGE_AREA_PX:
            logger.debug(f"Skipping xref {xref} (too small: {width}x{height})")
            product.image_asset_id = None
            continue
            
        # Convert CMYK to sRGB
        if img.mode == "CMYK":
            img = img.convert("RGB")
        elif img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
            
        # Compute phash
        phash = compute_phash(img)
        
        if phash in phash_to_asset_id:
            # Re-use existing asset
            asset_id = phash_to_asset_id[phash]
            product.image_asset_id = asset_id
            product.asset = Asset(
                asset_id=asset_id,
                page_number=product.page_number,
                bbox=product.bbox, 
                file_path=f"{asset_id}.webp",
                width_px=width,
                height_px=height,
                colorspace="sRGB",
                perceptual_hash=phash,
                role="product_image",
                confidence=1.0,
                extraction_method="pymupdf_image_stream"
            )
        else:
            # Save new asset
            asset_id = phash
            phash_to_asset_id[phash] = asset_id
            
            filename = f"{asset_id}.webp"
            thumb_filename = f"{asset_id}_thumb.webp"
            
            filepath = output_dir / filename
            thumb_filepath = output_dir / thumb_filename
            
            # Save full webp
            img.save(filepath, "WEBP", quality=90)
            
            # Save thumbnail
            img.thumbnail((400, 400), Image.Resampling.LANCZOS)
            img.save(thumb_filepath, "WEBP", quality=85)
            
            product.image_asset_id = asset_id
            product.asset = Asset(
                asset_id=asset_id,
                page_number=product.page_number,
                bbox=product.bbox,
                file_path=filename,
                width_px=width,
                height_px=height,
                colorspace="sRGB",
                perceptual_hash=phash,
                role="product_image",
                confidence=1.0,
                extraction_method="pymupdf_image_stream"
            )

    return products

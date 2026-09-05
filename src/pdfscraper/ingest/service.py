"""service.py - Deterministic PDF ingestion and catalog metadata registration."""

import hashlib
import json
from pathlib import Path
from typing import Optional
from loguru import logger
import pymupdf

from pdfscraper.catalogue_spec import (
    CURRENCY,
    MANUFACTURER,
    PDF_FILENAME,
    PRICE_EFFECTIVE_DATE_PATTERN,
    TOTAL_PAGES,
)
from pdfscraper.config import settings
from pdfscraper.schemas import Catalogue


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file efficiently in 64KB blocks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def ingest_catalogue(pdf_path: Optional[Path] = None) -> Catalogue:
    """Ingest source PDF: verify document, compute checksum, extract metadata, and save catalogue.json.

    Raises:
        FileNotFoundError: If PDF does not exist on disk.
        ValueError: If page count does not strictly equal TOTAL_PAGES (202), or price date cannot be extracted.
    """
    target = pdf_path or (settings.raw_data_dir / PDF_FILENAME)
    if not target.exists():
        raise FileNotFoundError(f"Source PDF not found at: {target}")

    logger.info("Computing SHA-256 checksum for: {}", target)
    sha256_hash = compute_sha256(target)
    logger.info("SHA-256: {}", sha256_hash)

    doc = pymupdf.open(str(target))
    page_count = len(doc)
    logger.info("Source PDF page count: {}", page_count)

    if page_count != TOTAL_PAGES:
        raise ValueError(
            f"Catalogue page count assertion failed! Expected {TOTAL_PAGES} pages, but found {page_count}."
        )

    # Page 1 (0-indexed) contains price effective date
    page1 = doc[0]
    p1_text = page1.get_text("text")
    match = PRICE_EFFECTIVE_DATE_PATTERN.search(p1_text)
    if not match:
        raise ValueError(
            f"Failed to extract price effective date from page 1 using regex: {PRICE_EFFECTIVE_DATE_PATTERN.pattern}"
        )

    price_effective_date = match.group(1).strip()
    logger.info("Extracted price effective date: {}", price_effective_date)

    catalogue = Catalogue(
        catalogue_id="jal_faucets_2025",
        filename=target.name,
        manufacturer=MANUFACTURER,
        edition="2025",
        total_pages=page_count,
        price_effective_date=price_effective_date,
        currency=CURRENCY,
        sha256=sha256_hash,
        confidence=1.0,
        extraction_method="deterministic_pdf_metadata",
    )

    settings.interim_data_dir.mkdir(parents=True, exist_ok=True)
    out_path = settings.interim_data_dir / "catalogue.json"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(catalogue.model_dump_json(indent=2))

    logger.info("Saved Catalogue record to: {}", out_path)
    return catalogue

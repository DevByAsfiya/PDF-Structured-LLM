"""test_phase1.py - Test stage 00 (ingest), stage 01 (index), and stage 02 (layout & classification)."""

import json
from pathlib import Path
import pandas as pd
import pymupdf
import pytest

from pdfscraper.catalogue_spec import PDF_FILENAME, PRINTED_TO_PDF_PAGE_OFFSET, TOTAL_PAGES
from pdfscraper.config import settings
from pdfscraper.ingest import ingest_catalogue, parse_index_and_sections
from pdfscraper.layout.blocks import extract_page_blocks
from pdfscraper.layout.classifier import classify_all_pages, save_pages_parquet


def test_stage00_ingest():
    catalogue = ingest_catalogue()
    assert catalogue.total_pages == 202
    assert catalogue.price_effective_date == "23.11.2024"
    assert catalogue.currency == "INR"
    assert catalogue.manufacturer == "JAL"
    assert catalogue.sha256 is not None
    assert len(catalogue.sha256) == 64

    cat_json = settings.interim_data_dir / "catalogue.json"
    assert cat_json.exists()
    with open(cat_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["total_pages"] == 202
        assert data["price_effective_date"] == "23.11.2024"


def test_stage01_index_parser():
    sections_info = parse_index_and_sections()
    assert sections_info["derived_offset"] == PRINTED_TO_PDF_PAGE_OFFSET
    assert sections_info["offset_matches_default"] is True
    assert sections_info["total_sections_count"] > 30
    assert "Tansa" in sections_info["faucet_series"]
    assert "Nalini Pro" in sections_info["faucet_series"]
    assert "Warna Pro" in sections_info["faucet_series"]

    sec_json = settings.interim_data_dir / "sections.json"
    assert sec_json.exists()


def test_stage02_blocks_extraction():
    doc = pymupdf.open(str(settings.raw_data_dir / PDF_FILENAME))
    # Test on page 40 (PDF page 40 is printed page 33, Tansa grid)
    p40_blocks = extract_page_blocks(doc[39], 40)
    assert len(p40_blocks) > 0

    text_blocks = [b for b in p40_blocks if b.block_type == "text"]
    image_blocks = [b for b in p40_blocks if b.block_type == "image"]

    assert len(text_blocks) > 0
    assert len(image_blocks) > 0

    # Ensure all bounding boxes are non-negative and valid
    for b in p40_blocks:
        assert b.bbox.width > 0
        assert b.bbox.height > 0
        assert b.bbox.area > 0


def test_stage02_pages_parquet():
    parquet_path = settings.interim_data_dir / "pages.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 202
    assert "page_no" in df.columns
    assert "archetype" in df.columns
    assert "confidence" in df.columns
    assert "series_header" in df.columns

    # Page 143 is an anomaly (vector text over products)
    p143 = df[df["page_no"] == 143].iloc[0]
    assert p143["has_vector_text"] == True
    assert p143["confidence"] < 0.70

    # Sanity ceiling: fewer than 15 pages in the review queue
    assert (df["confidence"] < 0.70).sum() < 15

    # product_grid is the dominant archetype
    assert (df["archetype"] == "product_grid").sum() > 90

    # Verify archetypes present
    archetypes = set(df["archetype"].unique())
    assert "cover" in archetypes
    assert "index" in archetypes
    assert "product_grid" in archetypes
    assert "lifestyle" in archetypes
    assert "parts_table" in archetypes

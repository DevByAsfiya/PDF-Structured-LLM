"""test_phase2.py - Regression guard for Phase 2 product grid extraction."""

import json
import pymupdf
import pytest

from pdfscraper.catalogue_spec import PDF_FILENAME
from pdfscraper.config import settings
from pdfscraper.layout.blocks import extract_page_blocks
from pdfscraper.extract.grid_parser import GridParser


def test_page40_grid_extraction_accuracy():
    """Lock in the exact extraction results for Page 40 (Tansa).

    If a future change breaks price extraction, this test must fail.
    """
    doc = pymupdf.open(str(settings.raw_data_dir / PDF_FILENAME))
    
    # Load sections to pass known_series
    with open(settings.interim_data_dir / "sections.json", "r", encoding="utf-8") as f:
        sections_info = json.load(f)
    known_series = sections_info.get("faucet_series", [])

    page_no = 40
    page = doc[page_no - 1]
    blocks = extract_page_blocks(page, page_no)
    
    parser = GridParser()
    products = parser.parse(
        page=page,
        blocks=blocks,
        page_number=page_no,
        series_name="Tansa",
        known_series=known_series
    )
    
    assert len(products) == 15, f"Expected 15 products, got {len(products)}"
    
    # Flatten variants for easier assertions
    variants = []
    for prod in products:
        variants.extend(prod.variants)
        
    assert len(variants) == 18, f"Expected 18 variants, got {len(variants)}"
    
    # Verify no duplicate SKUs
    skus = [v.sku for v in variants]
    assert len(skus) == len(set(skus)), "Found duplicate SKUs on Page 40"

    # Ground truth mapping: SKU -> Expected MRP
    ground_truth = {
        "82616": 5980.0,
        "82618": 5628.0,
        "82614": 17664.0,
        "82222": 3550.0,
        "82274": 3422.0,
        "82362": 2388.0,
        "82374": 3922.0,
        "82390": 2328.0,
        "82456": 1992.0,
        "82470": 2066.0,
        "82370": 2594.0,
        "82480": 1594.0,
        "82490": 2358.0,
        "82634": 5846.0,
        "82754": 8066.0,
        "82750": 7291.0,
        "82755": 8716.0,
        "82751": 7941.0,
    }

    # Verify all SKU-MRP pairs match exactly
    variant_dict = {v.sku: v.mrp for v in variants}
    for expected_sku, expected_mrp in ground_truth.items():
        assert expected_sku in variant_dict, f"SKU {expected_sku} missing from extraction"
        actual_mrp = variant_dict[expected_sku]
        assert actual_mrp == expected_mrp, f"SKU {expected_sku} MRP mismatch: got {actual_mrp}, expected {expected_mrp}"

"""test_phase3.py - Test parts table extraction."""

import pytest
import pymupdf
from pdfscraper.catalogue_spec import PDF_FILENAME
from pdfscraper.config import settings
from pdfscraper.extract.table_parser import TableParser
from pdfscraper.layout.blocks import extract_page_blocks

def test_parts_table_extraction():
    doc_path = settings.raw_data_dir / PDF_FILENAME
    if not doc_path.exists():
        pytest.skip("PDF not found")
        
    doc = pymupdf.open(str(doc_path))
    page_no = 198
    page = doc[page_no - 1]
    blocks = extract_page_blocks(page, page_no)
    
    parser = TableParser()
    products = parser.parse(page, blocks, page_number=page_no, series_name="PARTS")
    
    assert len(products) > 0, "Should extract products from parts table page 198"
    assert products[0].variants[0].sku != "", "Should extract SKU"
    # Basic sanity check
    for p in products:
        assert p.variants, "Every product must have at least one variant"
        assert p.extraction_method == "pdfplumber_table"


def test_kitchen_sinks_extraction():
    doc_path = settings.raw_data_dir / PDF_FILENAME
    if not doc_path.exists():
        pytest.skip("PDF not found")
        
    doc = pymupdf.open(str(doc_path))
    page_no = 190
    page = doc[page_no - 1]
    blocks = extract_page_blocks(page, page_no)
    
    parser = TableParser()
    products = parser.parse(page, blocks, page_number=page_no, series_name="KITCHEN SINKS")
    
    # Assert total count
    assert len(products) == 18, f"Expected 18 products on page 190, got {len(products)}"
    
    # Assert no duplicate SKUs
    skus = [p.variants[0].sku for p in products]
    assert len(skus) == len(set(skus)), "Should not extract duplicate SKUs on page 190"

    # Assert exact prices to guard against column misalignment
    expected_prices = {
        "90118": 9194.0,
        "90318": 6560.0,
        "90218": 10220.0,
        "90418": 7550.0,
        "90119": 9588.0,
        "90319": 6980.0,
        "90130": 13400.0,
        "99130": 13900.0,
    }

    for sku, expected_mrp in expected_prices.items():
        assert sku in skus, f"Expected SKU {sku} not found"
        p_sku = next(p for p in products if p.variants[0].sku == sku)
        assert p_sku.variants[0].mrp == expected_mrp, f"MRP for {sku} should be {expected_mrp}"
    
    # Check dimensions for 90118
    p_90118 = next(p for p in products if p.variants[0].sku == "90118")
    assert p_90118.variants[0].dimensions_or_size == "36*18*8"
    assert p_90118.variants[0].confidence == 0.8
    assert p_90118.extraction_method == "pdfplumber_text_lines_zip"

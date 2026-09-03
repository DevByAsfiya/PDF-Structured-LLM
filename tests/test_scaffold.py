"""test_scaffold.py - Basic verification of scaffolded schemas, config, and spec."""

from pdfscraper.catalogue_spec import (
    ARCHETYPE_PRODUCT_GRID,
    COVER_PAGE_INDEX,
    CURRENCY,
    GOLDEN_EVAL_PAGES,
    INDEX_PAGE_INDEX,
    MANUFACTURER,
    MRP_PATTERN,
    PDF_FILENAME,
    PRINTED_TO_PDF_PAGE_OFFSET,
    SKU_PATTERN,
    TABLE_PRICE_PATTERN,
    TOTAL_PAGES,
)
from pdfscraper.config import settings
from pdfscraper.schemas import (
    BoundingBox,
    Catalogue,
    Page,
    Product,
    Variant,
)


def test_catalogue_spec_constants():
    assert PDF_FILENAME == "JAL FAUCETS 2025.pdf"
    assert TOTAL_PAGES == 202
    assert MANUFACTURER == "JAL"
    assert CURRENCY == "INR"
    assert PRINTED_TO_PDF_PAGE_OFFSET == 7
    assert COVER_PAGE_INDEX == 1
    assert INDEX_PAGE_INDEX == 6
    assert GOLDEN_EVAL_PAGES == (40, 90, 150, 198)

    # Test SKU pattern across numeric and alphanumeric SKUs
    for sku in ("82456", "82470", "40120N", "76510S01", "73390S01", "75730S103"):
        match = SKU_PATTERN.search(sku)
        assert match is not None, f"Failed to match SKU: {sku}"
        assert match.group(1) == sku

    # Test MRP pattern for grid captions
    mrp_match = MRP_PATTERN.search("MRP 1992/-")
    assert mrp_match is not None
    assert mrp_match.group(1) == "1992"

    # Test TABLE_PRICE_PATTERN for parts table bare numbers
    assert TABLE_PRICE_PATTERN.match("1424.00").group(1) == "1424.00"
    assert TABLE_PRICE_PATTERN.match("1,424.00").group(1) == "1,424.00"
    assert TABLE_PRICE_PATTERN.match("Rs. 590.00").group(1) == "590.00"


def test_config_paths():
    assert settings.root_dir.exists()
    assert settings.data_dir.name == "data"
    assert settings.sqlite_db_path.name == "catalogue.sqlite"
    assert settings.confidence_threshold == 0.85


def test_schema_one_to_many_product_variant():
    bbox = BoundingBox(x0=10.0, y0=20.0, x1=110.0, y1=120.0)
    assert bbox.width == 100.0
    assert bbox.height == 100.0
    assert bbox.area == 10000.0

    v1 = Variant(
        sku="82456",
        mrp=1992.0,
        raw_caption_line="82456 Concealed Stop Cock with flange 15 mm MRP 1992/-",
        dimensions_or_size="15 mm",
        confidence=1.0,
        extraction_method="regex_grammar",
    )
    v2 = Variant(
        sku="82470",
        mrp=2066.0,
        raw_caption_line="82470 20 mm MRP 2066/-",
        dimensions_or_size="20 mm",
        confidence=1.0,
        extraction_method="regex_grammar",
    )

    product = Product(
        product_id="PROD_P040_01",
        series_name="WARNA PRO",
        title="Concealed Stop Cock with flange",
        page_number=40,
        printed_page_number=33,
        bbox=bbox,
        variants=[v1, v2],
        confidence=0.95,
        extraction_method="spatial_grid_join",
    )

    assert len(product.variants) == 2
    assert product.variants[0].sku == "82456"
    assert product.variants[1].sku == "82470"
    assert product.confidence == 0.95
    assert product.extraction_method == "spatial_grid_join"


def test_catalogue_and_page_schemas():
    cat = Catalogue(
        catalogue_id="jal_faucets_2025",
        filename="JAL FAUCETS 2025.pdf",
        manufacturer="JAL",
        total_pages=202,
        price_effective_date="23.11.2024",
        currency="INR",
        confidence=1.0,
        extraction_method="deterministic_pdf_metadata",
    )
    assert cat.total_pages == 202

    page = Page(
        page_number=40,
        printed_page_number=33,
        archetype=ARCHETYPE_PRODUCT_GRID,
        series_header="WARNA PRO",
        confidence=0.99,
        extraction_method="heuristic_classifier",
    )
    assert page.archetype == "product_grid"
    assert page.confidence == 0.99

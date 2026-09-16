"""test_phase4.py - Tests for Phase 4: Database loading and idempotency."""

import tempfile
from pathlib import Path

import pytest

from pdfscraper.config import settings
from pdfscraper.db.repository import CatalogueRepository


@pytest.fixture
def temp_repo(tmp_path):
    """Create a CatalogueRepository backed by a temp SQLite file."""
    db_path = tmp_path / "test_catalogue.sqlite"
    return CatalogueRepository(db_path=db_path)


class TestDatabaseLoad:
    """Tests for the load command and idempotency."""

    def test_load_products_from_parquet(self, temp_repo):
        """Loading products.parquet populates the database with correct counts."""
        parquet_path = settings.processed_data_dir / "products.parquet"
        if not parquet_path.exists():
            pytest.skip("products.parquet not found — run pipeline first")

        product_count = temp_repo.load_products_from_parquet(parquet_path=parquet_path)
        assert product_count == 1065
        assert temp_repo.get_variant_count() == 1332

    def test_load_is_idempotent(self, temp_repo):
        """Running load twice yields identical counts — no duplication."""
        parquet_path = settings.processed_data_dir / "products.parquet"
        if not parquet_path.exists():
            pytest.skip("products.parquet not found — run pipeline first")

        # First load
        temp_repo.load_products_from_parquet(parquet_path=parquet_path)
        products_first = temp_repo.get_product_count()
        variants_first = temp_repo.get_variant_count()

        # Second load — must replace, not duplicate
        temp_repo.load_products_from_parquet(parquet_path=parquet_path)
        products_second = temp_repo.get_product_count()
        variants_second = temp_repo.get_variant_count()

        assert products_first == products_second == 1065
        assert variants_first == variants_second == 1332

    def test_cross_page_sku_collisions_exist(self, temp_repo):
        """Cross-page SKU collisions are detected and reported."""
        parquet_path = settings.processed_data_dir / "products.parquet"
        if not parquet_path.exists():
            pytest.skip("products.parquet not found — run pipeline first")

        temp_repo.load_products_from_parquet(parquet_path=parquet_path)
        collisions = temp_repo.get_cross_page_sku_collisions()
        assert len(collisions) == 73

"""ingest module - PDF registration, metadata extraction, and index parsing."""

from pdfscraper.ingest.service import ingest_catalogue
from pdfscraper.ingest.index_parser import parse_index_and_sections

__all__ = ["ingest_catalogue", "parse_index_and_sections"]

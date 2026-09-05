"""base.py - Abstract base class for deterministic page parsers.

Each archetype (product_grid, parts_table, …) gets its own concrete parser.
All parsers share the same contract: take a page + its extracted blocks,
return a list of RawProduct dataclasses.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

import pymupdf

from pdfscraper.schemas import Product, RawBlock


class PageParser(ABC):
    """Abstract parser that converts a classified page into structured products.

    Subclasses implement ``parse`` for a single archetype.
    """

    @abstractmethod
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
        """Parse a single PDF page into zero or more Product instances.

        Args:
            page: The PyMuPDF page handle (for image xrefs, etc.).
            blocks: Pre-extracted RawBlock list for this page (text + image).
            page_number: 1-indexed PDF page number.
            series_name: Resolved series/collection header for the page.
            section_name: Section name from the INDEX mapping.
            known_series: All known series names (for header detection).

        Returns:
            List of fully-assembled Product instances, each carrying
            ``confidence`` and ``extraction_method``.
        """
        ...

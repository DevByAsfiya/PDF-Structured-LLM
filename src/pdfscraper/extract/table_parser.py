"""table_parser.py - Concrete parser for parts_table page archetype."""

import re
import string
from typing import Optional

import pdfplumber
import pymupdf
from loguru import logger

from pdfscraper.catalogue_spec import PRINTED_TO_PDF_PAGE_OFFSET, TABLE_PRICE_PATTERN, SKU_PATTERN
from pdfscraper.extract.base import PageParser
from pdfscraper.schemas import Attribute, BoundingBox, Product, RawBlock, Variant


class TableParser(PageParser):
    """Parser for ``parts_table`` pages using pdfplumber."""

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
        doc_path = page.parent.name
        printed_page = max(1, page_number - PRINTED_TO_PDF_PAGE_OFFSET)
        effective_series = series_name or section_name or "PARTS"

        with pdfplumber.open(doc_path) as pdf:
            p0 = pdf.pages[page_number - 1]
            tables = p0.extract_tables()
            
            products = self._parse_default_tables(
                tables, page_number, effective_series, printed_page
            )
            
            if not products:
                # Fallback to text/lines strategy and zipping
                tables_zip = p0.extract_tables(
                    table_settings={"vertical_strategy": "text", "horizontal_strategy": "lines"}
                )
                products = self._parse_zipped_tables(
                    tables_zip, page_number, effective_series, printed_page
                )

        logger.info(
            "Page {}: {} products extracted from table",
            page_number,
            len(products),
        )

        return products

    def _normalize_header(self, text: str) -> str:
        last_line = str(text).split("\n")[-1].strip().lower()
        for p in string.punctuation:
            last_line = last_line.replace(p, "")
        return last_line.strip()

    def _parse_default_tables(self, tables, page_number, effective_series, printed_page) -> list[Product]:
        products: list[Product] = []
        product_counter = 0

        for table_idx, table in enumerate(tables):
            if not table:
                continue

            # Find header row
            header_idx = -1
            for i, row in enumerate(table):
                row_text = " ".join([str(cell).strip().lower() for cell in row if cell])
                if "cat" in row_text and "no" in row_text:
                    header_idx = i
                    break

            if header_idx == -1:
                logger.warning(f"Page {page_number}: Could not find header row in table {table_idx}")
                continue

            header_row = [self._normalize_header(cell) if cell else "" for cell in table[header_idx]]

            cat_no_idx = -1
            mrp_idx = -1
            desc_idx = -1
            used_in_idx = -1

            for i, col_name in enumerate(header_row):
                if "cat no" in col_name or "sku" in col_name:
                    cat_no_idx = i
                elif "mrp" in col_name or "rs" in col_name:
                    mrp_idx = i
                elif "description" in col_name or "item" in col_name:
                    desc_idx = i
                elif "used in" in col_name:
                    used_in_idx = i

            if cat_no_idx == -1:
                continue

            for row_idx, row in enumerate(table[header_idx + 1:], start=header_idx + 1):
                cleaned_row = [str(cell).strip().replace("\n", " ") if cell else "" for cell in row]
                
                cat_no_val = cleaned_row[cat_no_idx] if cat_no_idx < len(cleaned_row) else ""
                if not cat_no_val or not SKU_PATTERN.search(cat_no_val):
                    continue

                product_counter += 1
                
                mrp_val = None
                conf = 0.9
                mrp_str = cleaned_row[mrp_idx] if mrp_idx != -1 and mrp_idx < len(cleaned_row) else ""
                if mrp_str:
                    m_mrp = TABLE_PRICE_PATTERN.search(mrp_str)
                    if m_mrp:
                        mrp_val = float(m_mrp.group(1).replace(",", ""))
                
                if mrp_val is None:
                    conf = 0.4

                desc_val = cleaned_row[desc_idx] if desc_idx != -1 and desc_idx < len(cleaned_row) else ""

                attributes = []
                size_val = None
                for i, col_name in enumerate(header_row):
                    if i in [cat_no_idx, mrp_idx, desc_idx, used_in_idx] or not col_name:
                        continue
                    if "image" in col_name:
                        continue

                    val = cleaned_row[i] if i < len(cleaned_row) else ""
                    if val:
                        if "size" in col_name:
                            size_val = val
                        else:
                            attributes.append(Attribute(name=col_name, value=val, confidence=conf, extraction_method="pdfplumber_table"))

                if used_in_idx != -1 and used_in_idx < len(cleaned_row):
                    val = cleaned_row[used_in_idx]
                    if val:
                        series_list = [s.strip() for s in val.split(",")]
                        attributes.append(Attribute(name="used_in", value=series_list, confidence=conf, extraction_method="pdfplumber_table"))

                raw_caption = " | ".join(c for c in cleaned_row if c)

                variant = Variant(
                    sku=cat_no_val,
                    mrp=mrp_val,
                    raw_caption_line=raw_caption,
                    dimensions_or_size=size_val,
                    attributes=attributes,
                    confidence=conf,
                    extraction_method="pdfplumber_table",
                )

                product_id = f"PROD_P{page_number:03d}_{product_counter:02d}"

                product = Product(
                    product_id=product_id,
                    series_name=effective_series,
                    title=desc_val or f"Part {cat_no_val}",
                    page_number=page_number,
                    printed_page_number=printed_page,
                    bbox=BoundingBox(x0=0.0, y0=0.0, x1=0.0, y1=0.0),
                    variants=[variant],
                    confidence=0.9,
                    extraction_method="pdfplumber_table",
                )
                products.append(product)

        return products


    def _parse_zipped_tables(self, tables, page_number, effective_series, printed_page) -> list[Product]:
        products: list[Product] = []
        product_counter = 0

        for table_idx, table in enumerate(tables):
            if not table:
                continue

            # Find header row
            header_idx = -1
            for i, row in enumerate(table):
                row_text = " ".join([str(cell).strip().lower() for cell in row if cell])
                if "cat" in row_text and "no" in row_text:
                    header_idx = i
                    break

            is_positional = False
            base_conf = 0.8
            cat_no_idx = -1
            mrp_idx = -1
            desc_idx = -1
            used_in_idx = -1
            header_row = []

            if header_idx != -1:
                raw_header = [str(cell) if cell else "" for cell in table[header_idx]]
                header_row = [self._normalize_header(cell) for cell in raw_header]

                for i, col_name in enumerate(header_row):
                    if "cat no" in col_name or "sku" in col_name:
                        cat_no_idx = i
                    elif "mrp" in col_name or "rs" in col_name:
                        mrp_idx = i
                    elif "description" in col_name or "item" in col_name:
                        desc_idx = i
                    elif "used in" in col_name:
                        used_in_idx = i
            elif len(table) > 0:
                first_row = table[0]
                split_cells = []
                for cell in first_row:
                    if not cell: split_cells.append([])
                    else: split_cells.append([line.strip() for line in str(cell).split("\n") if line.strip()])
                
                if len(split_cells) >= 2:
                    first_col = split_cells[0]
                    last_col = split_cells[-1]
                    if first_col and SKU_PATTERN.match(first_col[0]):
                        if last_col and TABLE_PRICE_PATTERN.search(last_col[0]):
                            is_positional = True
                            cat_no_idx = 0
                            mrp_idx = len(split_cells) - 1
                            base_conf = 0.6
                            header_row = [f"col_{i}" for i in range(len(split_cells))]
                            logger.info(f"Page {page_number}: Using positional inference for fallback table {table_idx}")

            if cat_no_idx == -1:
                logger.warning(f"Page {page_number}: Could not find header row or infer position in fallback table {table_idx}")
                continue

            for row_idx, row in enumerate(table[header_idx + 1:], start=header_idx + 1):
                split_cells = []
                for cell in row:
                    if not cell:
                        split_cells.append([])
                    else:
                        split_cells.append([line.strip() for line in str(cell).split("\n") if line.strip()])

                if cat_no_idx >= len(split_cells):
                    continue

                sku_col = split_cells[cat_no_idx]
                target_count = len(sku_col)
                if target_count == 0:
                    continue

                matching_cols = sum(1 for col in split_cells if len(col) == target_count)
                if matching_cols < len(split_cells) / 2:
                    logger.warning(
                        f"Page {page_number}: Abandoning row block, fewer than half columns match SKU count "
                        f"({matching_cols}/{len(split_cells)} match {target_count})"
                    )
                    continue

                padded_cols = []
                for col in split_cells:
                    if len(col) == target_count:
                        padded_cols.append(col)
                    else:
                        padded_cols.append([None] * target_count)

                zipped_rows = list(zip(*padded_cols))

                for r in zipped_rows:
                    cat_no_val = str(r[cat_no_idx]).strip() if cat_no_idx < len(r) and r[cat_no_idx] is not None else ""
                    if not cat_no_val or not SKU_PATTERN.search(cat_no_val):
                        continue

                    product_counter += 1

                    mrp_val = None
                    conf = base_conf
                    mrp_str = str(r[mrp_idx]).strip() if mrp_idx != -1 and mrp_idx < len(r) and r[mrp_idx] is not None else ""
                    if mrp_str:
                        m_mrp = TABLE_PRICE_PATTERN.search(mrp_str)
                        if m_mrp:
                            mrp_val = float(m_mrp.group(1).replace(",", ""))
                    
                    if mrp_val is None:
                        conf = 0.4

                    desc_val = str(r[desc_idx]).strip() if desc_idx != -1 and desc_idx < len(r) and r[desc_idx] is not None else ""

                    attributes = []
                    size_val = None
                    for i, col_name in enumerate(header_row):
                        if i in [cat_no_idx, mrp_idx, desc_idx, used_in_idx] or not col_name:
                            continue
                        if "image" in col_name:
                            continue

                        val = str(r[i]).strip() if i < len(r) and r[i] is not None else ""
                        if val:
                            if "size" in col_name:
                                size_val = val
                            else:
                                attributes.append(Attribute(name=col_name, value=val, confidence=conf, extraction_method="pdfplumber_text_lines_zip"))

                    if used_in_idx != -1 and used_in_idx < len(r):
                        val = r[used_in_idx]
                        if val is not None:
                            series_list = [s.strip() for s in str(val).split(",")]
                            attributes.append(Attribute(name="used_in", value=series_list, confidence=conf, extraction_method="pdfplumber_text_lines_zip"))

                    raw_caption = " | ".join(str(c) for c in r if c is not None)

                    variant = Variant(
                        sku=cat_no_val,
                        mrp=mrp_val,
                        raw_caption_line=raw_caption,
                        dimensions_or_size=size_val,
                        attributes=attributes,
                        confidence=conf,
                        extraction_method="pdfplumber_text_lines_zip",
                    )

                    product_id = f"PROD_P{page_number:03d}_{product_counter:02d}"
                    product = Product(
                        product_id=product_id,
                        series_name=effective_series,
                        title=desc_val or f"Part {cat_no_val}",
                        page_number=page_number,
                        printed_page_number=printed_page,
                        bbox=BoundingBox(x0=0.0, y0=0.0, x1=0.0, y1=0.0),
                        variants=[variant],
                        confidence=0.8,
                        extraction_method="pdfplumber_text_lines_zip",
                    )
                    products.append(product)

        return products

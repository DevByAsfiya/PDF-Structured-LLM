"""index_parser.py - Parse catalogue INDEX pages and empirically derive page offset."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional
from loguru import logger
import pymupdf

from pdfscraper.catalogue_spec import (
    INDEX_PAGE_INDEX,
    PDF_FILENAME,
    PRINTED_TO_PDF_PAGE_OFFSET,
    TOTAL_PAGES,
)
from pdfscraper.config import settings


def _clean_series_name(name: str) -> str:
    """Normalize whitespace and special characters from series names."""
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _parse_index_page(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Parse a single index page by spatially pairing title lines with page numbers on the same horizontal row."""
    data = page.get_text("dict")
    text_spans = []
    num_spans = []

    for block in data.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line.get("spans", []):
                text = span["text"].strip()
                if not text or text == "I N D E X":
                    continue

                bbox = span["bbox"]
                y_center = (bbox[1] + bbox[3]) / 2.0
                x0 = bbox[0]

                # Check if span is a pure page number (e.g. '31', '05', '144')
                if re.fullmatch(r"[0-9]{1,3}", text):
                    num_spans.append({
                        "page_num": int(text),
                        "y": y_center,
                        "x0": x0,
                    })
                else:
                    text_spans.append({
                        "text": text,
                        "y": y_center,
                        "x0": x0,
                        "size": span["size"],
                    })

    # Pair text spans with the closest page number in the same y-band (within 6 pt) and to the right
    entries = []
    matched_nums = set()

    for item in text_spans:
        # Find candidates with similar y and x > item['x0']
        candidates = [
            (idx, n) for idx, n in enumerate(num_spans)
            if idx not in matched_nums
            and abs(n["y"] - item["y"]) <= 6.0
            and n["x0"] > item["x0"]
        ]
        if candidates:
            # Pick closest in y, then closest in x
            candidates.sort(key=lambda c: (abs(c[1]["y"] - item["y"]), c[1]["x0"] - item["x0"]))
            idx, best_num = candidates[0]
            matched_nums.add(idx)
            entries.append({
                "name": _clean_series_name(item["text"]),
                "printed_page": best_num["page_num"],
                "y": item["y"],
                "x0": item["x0"],
            })

    return entries


def parse_index_and_sections(pdf_path: Optional[Path] = None) -> dict[str, Any]:
    """Parse INDEX pages (PDF pages 6 and 7), derive page offset, and write sections.json.

    Returns:
        dict containing derived_offset, series_list, sections, and validation status.
    """
    target = pdf_path or (settings.raw_data_dir / PDF_FILENAME)
    doc = pymupdf.open(str(target))

    # Page 6 (index 5) is primary INDEX
    p6_entries = _parse_index_page(doc[INDEX_PAGE_INDEX - 1])

    # Check Page 7 (index 6) for index continuation
    p7_entries = []
    if len(doc) >= 7:
        p7_text = doc[6].get_text("text")
        if any(keyword in p7_text for keyword in ["SHOWERS", "THERMOSTATS", "BATH ACCESSORIES", "NECESSARIES"]):
            p7_entries = _parse_index_page(doc[6])

    all_entries = p6_entries + p7_entries
    logger.info("Parsed {} index items across INDEX pages (PDF p.6 & p.7)", len(all_entries))

    # Empirical offset derivation
    # Test candidate series names across PDF pages around candidate = printed_page + default_offset
    offset_votes: list[int] = []
    verification_samples: list[dict[str, Any]] = []

    # Priority series for verification
    test_series = [e for e in all_entries if e["printed_page"] >= 5 and len(e["name"]) >= 3]

    for entry in test_series:
        name = entry["name"]
        p_num = entry["printed_page"]
        # Normalize name for search: e.g. "Tansa" -> ["TANSA", "T A N S A"]
        norm_name = name.upper().replace(" ", "")

        # Search in a ±5 page window around expected PDF page
        center_pdf_page = p_num + PRINTED_TO_PDF_PAGE_OFFSET
        window_start = max(1, center_pdf_page - 4)
        window_end = min(len(doc), center_pdf_page + 4)

        found_match = False
        for pdf_page_1idx in range(window_start, window_end + 1):
            page_text = doc[pdf_page_1idx - 1].get_text("text").upper()
            page_compact = page_text.replace(" ", "")

            if norm_name in page_compact:
                calc_offset = pdf_page_1idx - p_num
                offset_votes.append(calc_offset)
                verification_samples.append({
                    "series": name,
                    "printed_page": p_num,
                    "matched_pdf_page": pdf_page_1idx,
                    "calculated_offset": calc_offset,
                })
                found_match = True
                break

    if not offset_votes:
        logger.warning("Could not empirically derive offset from headers! Falling back to default: {}", PRINTED_TO_PDF_PAGE_OFFSET)
        derived_offset = PRINTED_TO_PDF_PAGE_OFFSET
    else:
        counter = Counter(offset_votes)
        derived_offset, most_common_count = counter.most_common(1)[0]
        logger.info(
            "Empirically derived offset: +{} ({} / {} votes from header verification)",
            derived_offset,
            most_common_count,
            len(offset_votes),
        )

    if derived_offset != PRINTED_TO_PDF_PAGE_OFFSET:
        logger.warning(
            "Derived offset ({}) differs from catalogue_spec default ({})!",
            derived_offset,
            PRINTED_TO_PDF_PAGE_OFFSET,
        )
    else:
        logger.info("Derived offset matches catalogue_spec default of {}", PRINTED_TO_PDF_PAGE_OFFSET)

    # Sort entries by printed page to resolve page ranges
    # Deduplicate entries by name & printed_page
    seen = set()
    unique_entries = []
    for e in sorted(all_entries, key=lambda x: x["printed_page"]):
        key = (e["name"], e["printed_page"])
        if key not in seen:
            seen.add(key)
            unique_entries.append(e)

    # Calculate resolved PDF page ranges
    sections = []
    for i, e in enumerate(unique_entries):
        start_pdf = e["printed_page"] + derived_offset
        if i + 1 < len(unique_entries):
            next_printed = unique_entries[i + 1]["printed_page"]
            if next_printed > e["printed_page"]:
                end_pdf = next_printed + derived_offset - 1
            else:
                end_pdf = start_pdf
        else:
            end_pdf = TOTAL_PAGES

        # Bound by TOTAL_PAGES
        end_pdf = min(end_pdf, TOTAL_PAGES)
        start_pdf = min(start_pdf, TOTAL_PAGES)
        if end_pdf < start_pdf:
            end_pdf = start_pdf

        sections.append({
            "name": e["name"],
            "printed_page": e["printed_page"],
            "pdf_page_start": start_pdf,
            "pdf_page_end": end_pdf,
        })

    # Filter faucet series specifically (printed pages roughly 31 to 120 or from page 6 FAUCETS block)
    faucet_series_names = [
        s["name"] for s in sections
        if s["printed_page"] >= 31 and s["printed_page"] <= 120
    ]

    result = {
        "derived_offset": derived_offset,
        "default_offset": PRINTED_TO_PDF_PAGE_OFFSET,
        "offset_matches_default": derived_offset == PRINTED_TO_PDF_PAGE_OFFSET,
        "verified_samples_count": len(verification_samples),
        "total_sections_count": len(sections),
        "faucet_series": faucet_series_names,
        "sections": sections,
    }

    settings.interim_data_dir.mkdir(parents=True, exist_ok=True)
    out_path = settings.interim_data_dir / "sections.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    logger.info("Saved sections and series mappings to: {}", out_path)
    return result

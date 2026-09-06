"""caption_grammar.py - Deterministic tokeniser for product-grid captions.

Turns the raw text spans beneath a product image into one or more
``(sku, description, mrp)`` tuples.  The first SKU is the primary product;
subsequent SKUs are variants that share the same image.

Hard rules (from AGENTS.md):
- No LLM.  Extraction is deterministic: regex + span geometry.
- Multi-SKU captions MUST be handled (page 40 pattern).
- Any caption that produces an unexpected shape (no SKU, no MRP,
  more SKUs than prices) gets low confidence rather than a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from pdfscraper.catalogue_spec import MRP_PATTERN, SKU_PATTERN, SIZE_PATTERN
from pdfscraper.schemas import RawBlock


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

@dataclass
class CaptionToken:
    """One parsed (sku, description, mrp) tuple from a caption block."""
    sku: str
    description: str
    mrp: Optional[float]
    raw_text: str
    dimensions_or_size: Optional[str] = None
    is_primary: bool = True
    confidence: float = 1.0
    extraction_method: str = "caption_grammar_regex"


@dataclass
class CaptionParseResult:
    """Full parse result for one caption block (may contain multiple SKUs)."""
    tokens: list[CaptionToken] = field(default_factory=list)
    raw_caption_text: str = ""
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex for parenthetical compatibility notes that contain model numbers
# which would otherwise be falsely identified as SKUs.
# Examples: "(Compatible with 52665 Concealed Body)"
#           "(82550RES25 Also Available in Rectangular Flange)"
# ---------------------------------------------------------------------------
_PAREN_RE = re.compile(r"\([^)]*(?:(?i:compatible)|\d{3,})[^)]*\)")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_mrp_string(mrp_str: str) -> float:
    """Convert a matched MRP string like '1,992' or '17664' to float."""
    cleaned = mrp_str.replace(",", "").strip()
    return float(cleaned)


def _extract_size(text: str) -> Optional[str]:
    """Extract a dimensional spec like '15 mm' or '20 mm' from text."""
    m = SIZE_PATTERN.search(text)
    return m.group(1).strip() if m else None


def _merge_caption_spans(caption_blocks: list[RawBlock]) -> str:
    """Merge text spans into a single caption string.

    Spans are sorted top-to-bottom, left-to-right.  We insert a newline
    when the vertical gap between spans exceeds ~4 pt (roughly half a line),
    and a space otherwise.
    """
    if not caption_blocks:
        return ""

    sorted_blocks = sorted(caption_blocks, key=lambda b: (b.bbox.y0, b.bbox.x0))

    parts: list[str] = []
    prev_y: Optional[float] = None

    for block in sorted_blocks:
        text = (block.text or "").strip()
        if not text:
            continue

        if prev_y is not None and (block.bbox.y0 - prev_y) > 4.0:
            parts.append("\n")
        elif parts and not parts[-1].endswith("\n"):
            parts.append(" ")

        parts.append(text)
        prev_y = block.bbox.y1

    return "".join(parts).strip()


def _is_inside_parenthetical(match_start: int, text: str) -> bool:
    """Check whether match_start falls inside a parenthetical group."""
    for m in _PAREN_RE.finditer(text):
        if m.start() <= match_start < m.end():
            return True
    return False


def _filter_sku_matches(
    sku_matches: list[re.Match[str]],
    mrp_matches: list[re.Match[str]],
    caption_text: str,
) -> list[re.Match[str]]:
    """Filter SKU regex matches to remove false positives.

    Removes matches that:
    1. Fall inside an MRP span (they're prices, not SKUs).
    2. Fall inside parenthetical notes like "(Compatible with 52665 ...)".
    3. Have codes like "52665" (5-digit starting with 5) that appear only
       inside compatibility references but are not JAL product SKUs in
       the grid context.
    """
    mrp_spans = [(m.start(), m.end()) for m in mrp_matches]

    filtered = []
    for sm in sku_matches:
        # Skip if inside an MRP span
        if any(ms <= sm.start() < me for ms, me in mrp_spans):
            continue

        # Skip if inside a parenthetical (compatibility note)
        if _is_inside_parenthetical(sm.start(), caption_text):
            continue

        filtered.append(sm)

    return filtered


def _split_caption_into_sku_segments(caption_text: str) -> list[str]:
    """Split a merged caption into segments, one per SKU.

    Strategy: find all SKU positions and all MRP positions, then carve the
    text into segments starting at each SKU.

    A leading SKU that has no MRP in its segment is a phantom decoration
    from an adjacent product image — we still emit it as a segment but
    _parse_single_segment will return None for it.

    Example caption:
        "82456 Concealed Stop Cock with flange 15 mm MRP 1992/-
         82470 20 mm MRP 2066/-"
    → ["82456 Concealed Stop Cock with flange 15 mm MRP 1992/-",
        "82470 20 mm MRP 2066/-"]
    """
    mrp_matches = list(MRP_PATTERN.finditer(caption_text))
    sku_matches = list(SKU_PATTERN.finditer(caption_text))

    valid_sku_matches = _filter_sku_matches(sku_matches, mrp_matches, caption_text)

    if not valid_sku_matches:
        return [caption_text]

    # Split at each valid SKU start position
    segments: list[str] = []
    for i, sm in enumerate(valid_sku_matches):
        start = sm.start()
        if i + 1 < len(valid_sku_matches):
            end = valid_sku_matches[i + 1].start()
        else:
            end = len(caption_text)
        segment = caption_text[start:end].strip()
        if segment:
            segments.append(segment)

    return segments if segments else [caption_text]


def _parse_single_segment(segment: str) -> Optional[CaptionToken]:
    """Parse a single SKU segment into a CaptionToken.

    Expected shape: ``<SKU> <description text> MRP <price>/-``
    """
    sku_match = SKU_PATTERN.search(segment)
    mrp_match = MRP_PATTERN.search(segment)

    if not sku_match:
        return None

    sku = sku_match.group(1)

    if not mrp_match:
        return None

    try:
        mrp = _clean_mrp_string(mrp_match.group(1))
    except (ValueError, IndexError):
        return None

    # Description: text between the SKU and the MRP marker
    desc_start = sku_match.end()
    desc_end = mrp_match.start()
    description = segment[desc_start:desc_end].strip()

    # Clean up stray punctuation and normalise whitespace
    description = re.sub(r"\s+", " ", description).strip()
    # Remove trailing/leading special chars
    description = description.strip("- /,")

    # Strip trailing parenthetical compatibility notes from description
    description = _PAREN_RE.sub("", description).strip().rstrip("- /,").strip()

    # Extract size/dimension
    size = _extract_size(description) or _extract_size(segment)

    confidence = 1.0
    if not description:
        confidence = 0.7  # SKU and price present but no description text

    return CaptionToken(
        sku=sku,
        description=description,
        mrp=mrp,
        raw_text=segment.strip(),
        dimensions_or_size=size,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tokenise_caption(caption_blocks: list[RawBlock]) -> CaptionParseResult:
    """Parse a list of caption text blocks into structured product tokens.

    This is the main entry point.  Returns a CaptionParseResult with one
    CaptionToken per SKU found.

    Handles:
    - Single-SKU captions (most common case)
    - Multi-SKU captions (e.g. page 40: 82456/82470, 82754/82750)
    - Captions with unexpected shapes → low confidence, not a guess

    Args:
        caption_blocks: The text RawBlock instances in the caption zone.

    Returns:
        CaptionParseResult with parsed tokens and aggregate confidence.
    """
    raw_text = _merge_caption_spans(caption_blocks)
    result = CaptionParseResult(raw_caption_text=raw_text)

    if not raw_text.strip():
        result.confidence = 0.0
        result.warnings.append("empty_caption")
        return result

    # Count SKUs and MRPs in the raw text to validate shape
    all_mrp_matches = list(MRP_PATTERN.finditer(raw_text))
    all_sku_matches = list(SKU_PATTERN.finditer(raw_text))
    real_sku_matches = _filter_sku_matches(all_sku_matches, all_mrp_matches, raw_text)

    num_skus = len(real_sku_matches)
    num_mrps = len(all_mrp_matches)

    # --- Shape validation ---
    if num_skus == 0 and num_mrps == 0:
        result.confidence = 0.2
        result.warnings.append("no_sku_found")
        return result

    if num_skus == 0 and num_mrps > 0:
        # Has prices but no SKU — the SKU might be in a decoration text
        # from adjacent image.  Flag low confidence.
        result.confidence = 0.3
        result.warnings.append("no_sku_but_has_mrp")
        return result

    if num_mrps == 0:
        result.confidence = 0.2
        result.warnings.append("no_mrp_found")
        # Still try to parse what we can — return SKU with 0 MRP flagged
        for i, sm in enumerate(real_sku_matches):
            result.tokens.append(CaptionToken(
                sku=sm.group(1),
                description=raw_text[sm.end():].strip()[:80],
                mrp=None,
                raw_text=raw_text,
                is_primary=(i == 0),
                confidence=0.2,
                extraction_method="caption_grammar_partial",
            ))
        return result

    # --- Segment and parse ---
    segments = _split_caption_into_sku_segments(raw_text)

    for i, seg in enumerate(segments):
        token = _parse_single_segment(seg)
        if token is not None:
            token.is_primary = (i == 0)
            result.tokens.append(token)

    # --- Handle phantom leading SKUs ---
    # If the first segment had no MRP (phantom from adjacent image decoration),
    # the first successfully-parsed token should be marked as primary.
    if result.tokens:
        # Ensure exactly one token is primary
        has_primary = any(t.is_primary for t in result.tokens)
        if not has_primary:
            result.tokens[0].is_primary = True

    # --- Post-parse confidence ---
    if not result.tokens:
        result.confidence = 0.2
        result.warnings.append("no_tokens_parsed")
    else:
        # Count how many SKUs actually parsed vs how many we expected
        parsed_count = len(result.tokens)
        expected_count = num_mrps  # At minimum, one SKU per MRP

        if parsed_count < expected_count:
            result.confidence = 0.6
            result.warnings.append(
                f"partial_parse: {parsed_count}/{expected_count} SKU-MRP pairs resolved"
            )
        elif num_skus > num_mrps:
            # More SKUs than MRPs found in the raw text. Instead of guessing
            # which SKU owns the price, set confidence < 0.5 to flag for review.
            result.confidence = 0.4
            result.warnings.append(f"too_many_skus: {num_skus} SKUs but only {num_mrps} MRPs")
            
            # Reduce confidence of the individual tokens as well
            for t in result.tokens:
                t.confidence = min(t.confidence, 0.4)
        else:
            # All SKUs resolved with prices — high confidence
            min_token_conf = min(t.confidence for t in result.tokens)
            result.confidence = min(0.95, min_token_conf)

    # Mark variant tokens
    for i, token in enumerate(result.tokens):
        if i > 0:
            token.is_primary = False

    return result

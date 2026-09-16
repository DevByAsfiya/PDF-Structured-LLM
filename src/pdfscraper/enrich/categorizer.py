"""categorizer.py - Two-step product categorization.

Step 1 (propose_taxonomy): One batched LLM pass over all distinct product
descriptions, proposing a category taxonomy. Output is written to
configs/taxonomy.yaml for human review. Stops there.

Step 2 (assign_categories): After the taxonomy is approved, assigns
categories to products. NOT executed until the user approves the taxonomy.
"""

from pathlib import Path
from typing import Optional

import yaml
from loguru import logger
from pydantic import BaseModel, Field

from pdfscraper.config import settings
from pdfscraper.db.repository import CatalogueRepository
from pdfscraper.enrich.llm_client import call_llm_structured, render_prompt


# ── Pydantic models for structured LLM output ────────────────────────


class TaxonomyCategory(BaseModel):
    """A single category in the proposed taxonomy."""

    category: str
    subcategories: list[str] = Field(default_factory=list)
    description: str = ""
    example_products: list[str] = Field(default_factory=list)


class TaxonomyProposal(BaseModel):
    """The full taxonomy proposal from the LLM."""

    taxonomy: list[TaxonomyCategory]


# ── Step 1: Propose taxonomy ─────────────────────────────────────────


def propose_taxonomy(
    output_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> Path:
    """Extract distinct product descriptions and propose a taxonomy via LLM.

    Writes the proposal to configs/taxonomy.yaml and returns the path.
    Does NOT assign categories — that requires human review first.
    """
    output_path = output_path or (settings.root_dir / "configs" / "taxonomy.yaml")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    repo = CatalogueRepository(db_path=db_path)

    # Get distinct product titles from the database
    with repo.session() as session:
        from pdfscraper.db.models import ProductRow

        titles = (
            session.query(ProductRow.title)
            .distinct()
            .order_by(ProductRow.title)
            .all()
        )

    descriptions = sorted(set(t[0] for t in titles if t[0]))
    logger.info("Found {} distinct product descriptions for taxonomy proposal", len(descriptions))

    # Render prompt from template
    prompt = render_prompt(
        "taxonomy_proposal.jinja",
        descriptions=descriptions,
    )

    system_prompt = (
        "You are a product taxonomy expert for plumbing fixtures and fittings. "
        "Respond only with valid JSON matching the requested schema."
    )

    # Call LLM
    logger.info("Calling LLM for taxonomy proposal ({} descriptions)...", len(descriptions))
    proposal = call_llm_structured(
        prompt=prompt,
        response_model=TaxonomyProposal,
        system_prompt=system_prompt,
        temperature=0.0,
    )

    # Write to YAML
    taxonomy_data = {
        "version": "1.0",
        "status": "proposed",
        "description_count": len(descriptions),
        "categories": [cat.model_dump() for cat in proposal.taxonomy],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(
            taxonomy_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    logger.info(
        "Taxonomy proposal written to {} ({} categories)",
        output_path,
        len(proposal.taxonomy),
    )

    return output_path

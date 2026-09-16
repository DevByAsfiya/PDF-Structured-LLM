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
    max_descriptions: int = 250,
    force: bool = False,
) -> Path:
    """Extract distinct product descriptions and propose a taxonomy via LLM.

    Writes the proposal to configs/taxonomy.yaml and returns the path.
    Does NOT assign categories — that requires human review first.
    """
    output_path = output_path or (settings.root_dir / "configs" / "taxonomy.yaml")
    
    if output_path.exists() and not force:
        with open(output_path, "r", encoding="utf-8") as f:
            existing = yaml.safe_load(f)
            if existing and existing.get("status") == "approved":
                logger.error("Taxonomy at {} is already approved. Use --force to overwrite.", output_path)
                return output_path

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
    total_desc = len(descriptions)
    
    if total_desc > max_descriptions:
        step = total_desc / max_descriptions
        sampled_descriptions = [descriptions[int(i * step)] for i in range(max_descriptions)]
        logger.info("Sampled {} descriptions out of {} for taxonomy proposal", len(sampled_descriptions), total_desc)
        descriptions_to_prompt = sampled_descriptions
    else:
        logger.info("Found {} distinct product descriptions for taxonomy proposal", total_desc)
        descriptions_to_prompt = descriptions

    # Render prompt from template
    prompt = render_prompt(
        "taxonomy_proposal.jinja",
        descriptions=descriptions_to_prompt,
    )

    system_prompt = (
        "You are a product taxonomy expert for plumbing fixtures and fittings. "
        "Respond only with valid JSON matching the requested schema."
    )

    # Call LLM
    logger.info("Calling LLM for taxonomy proposal ({} descriptions)...", len(descriptions_to_prompt))
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
        "total_descriptions_in_db": total_desc,
        "sampled_descriptions": len(descriptions_to_prompt),
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


# ── Step 2: Assign categories ─────────────────────────────────────────

class ProductAssignment(BaseModel):
    id: str = Field(..., alias="product_id")
    c: int = Field(..., description="1-indexed category ID")
    s: int = Field(..., description="1-indexed subcategory ID")

class BatchAssignmentResult(BaseModel):
    assignments: list[ProductAssignment]

def assign_categories(
    taxonomy_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
    batch_size: int = 20,
) -> None:
    """Load approved taxonomy into DB and assign categories to all products via LLM in batches."""
    taxonomy_path = taxonomy_path or (settings.root_dir / "configs" / "taxonomy.yaml")
    repo = CatalogueRepository(db_path=db_path)

    # 1. Load taxonomy into DB (validates 'approved' status)
    node_count = repo.load_taxonomy(taxonomy_path)
    logger.info("Loaded {} taxonomy nodes into database", node_count)

    # Load taxonomy data for prompting
    with open(taxonomy_path, "r", encoding="utf-8") as f:
        taxonomy_data = yaml.safe_load(f)
    categories_for_prompt = taxonomy_data.get("categories", [])

    # Create mapping from index to names
    idx_to_cat = {}
    idx_to_subcat = {}
    for i, cat in enumerate(categories_for_prompt, 1):
        idx_to_cat[i] = cat["category"]
        for j, sub in enumerate(cat.get("subcategories", []), 1):
            idx_to_subcat[(i, j)] = sub

    # 2. Fetch products needing assignment
    with repo.session() as session:
        from pdfscraper.db.models import ProductRow
        
        products = session.query(ProductRow.product_id, ProductRow.title).filter(ProductRow.category.is_(None)).all()
        total_products = len(products)
        if total_products == 0:
            logger.info("No products need categorization.")
            return

        logger.info("Found {} products to categorize", total_products)

        # 3. Batch and call LLM
        assigned_count = 0
        failed_count = 0
        distribution = {}

        for i in range(0, total_products, batch_size):
            batch = products[i : i + batch_size]
            product_dicts = [{"product_id": p.product_id, "title": p.title} for p in batch]
            
            prompt = render_prompt(
                "taxonomy_assignment.jinja",
                categories=categories_for_prompt,
                products=product_dicts,
            )
            
            system_prompt = (
                "You are a plumbing product taxonomy expert. "
                "Respond only with valid JSON matching the requested schema."
            )
            
            logger.info("Categorizing batch {}/{} ({} products)...", i // batch_size + 1, (total_products + batch_size - 1) // batch_size, len(batch))
            
            try:
                result = call_llm_structured(
                    prompt=prompt,
                    response_model=BatchAssignmentResult,
                    system_prompt=system_prompt,
                    temperature=0.0,
                    use_cache=False,
                    max_tokens=8192,
                )
                
                # 4. Update DB
                for assign in result.assignments:
                    cat_name = idx_to_cat.get(assign.c)
                    subcat_name = idx_to_subcat.get((assign.c, assign.s))
                    
                    if not cat_name or not subcat_name:
                        logger.error("Invalid category/subcategory index: c={}, s={} for product {}", assign.c, assign.s, assign.id)
                        failed_count += 1
                        continue

                    row = session.get(ProductRow, assign.id)
                    if row:
                        row.category = cat_name
                        row.subcategory = subcat_name
                        assigned_count += 1
                        distribution[cat_name] = distribution.get(cat_name, 0) + 1
                    else:
                        failed_count += 1
                
                session.commit()
                
            except Exception as e:
                logger.error("Batch failed: {}", e)
                session.rollback()
                failed_count += len(batch)
                
        logger.info("Categorization complete.")
        logger.info("Assigned: {}, Failed: {}", assigned_count, failed_count)
        logger.info("Distribution:")
        for cat, count in sorted(distribution.items(), key=lambda x: x[1], reverse=True):
            logger.info("  {}: {}", cat, count)

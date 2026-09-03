# Catalogue Intelligence Pipeline

A high-precision, deterministic extraction, enrichment, and retrieval pipeline that converts the `JAL FAUCETS 2025.pdf` catalogue (202 pages, 108 MB, A4) into a structured product database with hybrid vector search and an interactive Streamlit engineering interface.

## System Overview

Plumbing and interior engineers specify fittings by balancing collection aesthetics, mounting types, dimensional constraints, and budget. Flipping through a 202-page PDF for quotations is inefficient and error-prone. This pipeline provides:

1. **Deterministic Extraction (Stages 00–06)**: PyMuPDF bounding-box geometry, text span coordinate analysis, and caption grammars extract SKUs, MRPs, and image bindings with zero hallucination. No LLMs are used in this path.
2. **One-to-Many Variant Modeling**: A single visual fixture often features multiple SKUs (e.g. 15mm vs 20mm stop cocks). Modeled strictly as `Product` (visual item + base specs) with 1+ `Variant`s (SKU, MRP, dimensions).
3. **Statistical Price Tiering**: Price tiers are computed per-category using MRP quantiles (e.g. p33/p66/p90). A stop cock and a concealed basin mixer are never evaluated on a global price scale.
4. **Resumable & Idempotent Stages**: Every pipeline stage persists versioned Parquet/JSONL artifacts in `data/interim/` and `data/processed/`.
5. **Interactive Streamlit UI**: Specification search, BOM/quotation builder (Project Sheet), visual comparison, and a low-confidence human review queue.

---

## Directory Structure

```
0-PDF Scraper/
├── AGENTS.md
├── README.md
├── .env                     # local, gitignored
├── .gitignore
├── requirements.txt         # authoritative dependencies
├── pyproject.toml           # editable package metadata
├── data/                    # gitignored except .gitkeep
│   ├── raw/                 # JAL FAUCETS 2025.pdf lives here
│   ├── interim/             # per-stage parquet/jsonl
│   ├── processed/
│   ├── assets/              # exported product images (converted to sRGB)
│   ├── db/                  # catalogue.sqlite
│   └── vectors/             # lancedb
├── src/pdfscraper/
│   ├── config.py            # pydantic-settings (pathlib.Path, thresholds, env)
│   ├── catalogue_spec.py    # ALL JAL-specific constants, regexes, tolerances
│   ├── schemas.py           # pydantic v2 schemas with provenance & confidence
│   ├── cli.py               # typer CLI entrypoint
│   ├── layout/              # blocks.py, geometry.py, classifier.py
│   ├── extract/             # base.py, grid_parser.py, table_parser.py, caption_grammar.py
│   ├── assets/              # exporter.py, dedupe.py
│   ├── enrich/              # llm_client.py, prompts/, normalizer.py, categorizer.py, tier.py
│   ├── db/                  # models.py, repository.py
│   ├── index/               # text_embed.py, image_embed.py, vectorstore.py, hybrid.py
│   ├── recommend/           # intent.py, ranker.py, explain.py
│   └── eval/                # golden/, metrics.py
├── app/                     # Streamlit web application
│   ├── Home.py
│   ├── pages/
│   └── components/
├── notebooks/               # exploration only
└── tests/
```

---

## Quickstart

### 1. Activate Environment & Install Package
```powershell
# Windows PowerShell
.venv\Scripts\activate
pip install -e .
```

### 2. Configure Environment
Copy `.env.example` to `.env` and configure keys for downstream enrichment stages:
```powershell
Copy-Item .env.example .env
```

### 3. Pipeline CLI Commands

```powershell
# Show CLI help and options
python -m pdfscraper.cli --help

# Ingest PDF and read document metadata
python -m pdfscraper.cli ingest

# Fast development loop on golden pages (pages 38-45)
python -m pdfscraper.cli run --stages 02-06 --pages 38-45

# Full catalogue execution
python -m pdfscraper.cli run --stages 02-06

# Run precision/recall evaluation against golden dataset
python -m pdfscraper.cli eval

# Launch Streamlit web application
streamlit run app/Home.py
```

### 4. Running Tests
```powershell
pytest -q
```

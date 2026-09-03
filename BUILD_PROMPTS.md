# Build prompts for `agy` — run in order, one phase per session

Working directory for every command: `0-PDF Scraper/`.
`AGENTS.md` is loaded automatically, so these prompts stay short. Do not paste
the architecture doc into the prompt — the agent reads it from the folder.

Review the diff after every phase before starting the next. Each phase has an
exit gate; if the gate fails, fix it before moving on. Phase 2 is the real gate —
if extraction accuracy isn't there, nothing downstream matters.

---

## Phase 0 — Scaffold

```
Read AGENTS.md and catalogue-intelligence-architecture.md in this folder.

Scaffold the project exactly as the directory contract in AGENTS.md specifies.
Create every directory with .gitkeep, and create these files with real content
(not stubs): pyproject.toml (src layout, editable install, project name
"pdfscraper", Python >=3.11), requirements.txt, .gitignore, .env.example,
Makefile, README.md, src/pdfscraper/config.py, src/pdfscraper/catalogue_spec.py,
src/pdfscraper/schemas.py, src/pdfscraper/cli.py.

config.py: pydantic-settings, all paths resolved relative to the project root,
confidence thresholds, model IDs read from env with defaults.

catalogue_spec.py: every JAL-specific constant — SKU regex, MRP regex, the
series list, the printed-page-to-PDF-page offset, page ranges for front matter
and end matter, archetype names. All the facts from AGENTS.md, nothing else.

schemas.py: pydantic models for Catalogue, Page, RawBlock, Product, Variant,
Asset, Attribute, ExtractionResult. Every extraction model carries confidence
and extraction_method.

cli.py: typer app with `ingest`, `run --stages --pages`, `eval` commands, all
wired to stubs that log what they would do.

.gitignore must exclude: .venv/, data/, *.pdf, .env, __pycache__, .diskcache.

Do not implement any parsing logic yet. Then run `pip install -e .` and
`python -m pdfscraper.cli --help` to prove the scaffold imports cleanly.
```

**Gate:** `python -m pdfscraper.cli --help` prints all three commands.

---

## Phase 1 — Ingest, INDEX, page classification

```
Implement stages 00-02.

ingest: open data/raw/JAL FAUCETS 2025.pdf with PyMuPDF, compute sha256, read
page count and dimensions, extract the price effective date from page 1
("M.R.P. w.e.f 23.11.2024"). Write a Catalogue record to data/interim/catalogue.json.

index_parser: parse the INDEX page (PDF page 6, and check whether the index
continues onto page 7) into (series_name, printed_page) pairs. Derive the
printed-to-PDF page offset empirically by matching a few series headers, not by
hardcoding 7. Write data/interim/sections.json.

layout/blocks.py: extract text spans (with bbox, font, size) and image rects
(with bbox) from a page in one shared coordinate space.

layout/classifier.py: classify every page into cover / lifestyle / product_grid /
parts_table / tech_spec, using heuristics only — image count, image size
distribution, presence of MRP tokens, ruling lines, text density. No model calls.
Output a per-page confidence.

Write data/interim/pages.parquet with page_no, archetype, confidence, section_name.

Then print a summary table of archetype counts and list every page classified
with confidence below 0.7.
```

**Gate:** archetype counts look sane (roughly: ~30 front matter, ~150 product
grid, ~15 parts table). Spot-check 5 pages against the actual PDF. Sections from
the INDEX align with detected headers.

---

## Phase 2 — Grid parser (THE GATE)

```
Implement stages 03-05 for the product_grid archetype only.

extract/base.py: PageParser ABC with parse(page, blocks) -> list[RawProduct].

layout/geometry.py: infer column boundaries from image x-positions; for each
image, find the caption block below it (same column, nearest below, within the
max vertical offset from catalogue_spec).

extract/caption_grammar.py: tokenise a caption block into one or more
(sku, description, mrp) tuples. This MUST handle multi-SKU captions — see the
82456/82470 and 82754/82750 examples in AGENTS.md. The first SKU is the primary
product; subsequent ones are variants sharing the image. Set confidence lower
when a caption yields an unexpected shape.

extract/grid_parser.py: assemble Products and Variants, inherit the series from
the page header, attach the image bbox.

Then run on --pages 38-45 and print, per page: image count, SKU count, and every
(sku, description, mrp) tuple. I will check these against the PDF myself.
```

**Gate:** hand-check pages 38–45. Target ≥95% SKU recall and **100% price
exact-match**. Do not proceed until prices are perfect — this is the number that
ends up in a customer quotation.

---

## Phase 3 — Parts table, assets, full run

```
Implement extract/table_parser.py for the parts_table archetype using pdfplumber
ruling-line table detection. Columns: Cat No. | Image | Item Description |
Used In (Range) | MRP (Rs. Each). Note the "Used In" column contains a
comma-separated list of series names — store it as a list.

Implement assets/exporter.py: export each bound product image, convert CMYK to
sRGB with Pillow, save as WebP plus a 400px thumbnail into data/assets/,
filter out masks and decorations by area, and dedupe by perceptual hash
(imagehash) so a reused photo maps to multiple products rather than duplicating.

Implement eval/: hand-labelled golden fixtures for PDF pages 40, 90, 150, 198
(one per archetype) and metrics for SKU recall, price exact-match, and
image-binding accuracy.

Then run the full 202-page pipeline, write data/processed/products.parquet, and
report: total products, total variants, total images, rows below confidence
threshold, and the eval metrics.
```

**Gate:** <5% of rows in the review queue. Eval metrics recorded as the baseline.

---

## Phase 4 — Database, enrichment, tiering

```
Implement db/models.py (SQLAlchemy) matching the data model in the architecture
doc — catalogue, page, product, variant, asset, attribute (EAV), taxonomy_node,
review_item — plus db/repository.py as the only query surface. SQLite at
data/db/catalogue.sqlite. Add a `load` CLI command that writes the parquet into it.

Implement enrich/llm_client.py against Groq (OpenAI-compatible), with the model
ID from config, tenacity retry, diskcache keyed on (model, prompt_hash),
structured JSON output validated against pydantic, and per-call token and cost
logging.

Implement enrich/categorizer.py in two steps: first, one batched pass over all
distinct descriptions proposing a category taxonomy, written to
configs/taxonomy.yaml for me to review; second, deterministic assignment of
products to the approved taxonomy using embeddings, with the LLM used only for
low-similarity tie-breaks.

Implement enrich/normalizer.py to pull structured attributes out of descriptions
into the attribute table — mounting type, size (15mm/20mm/25mm), finish,
lever type, function. Unparseable values stay null, never guessed.

Implement enrich/tier.py: compute value/mid/premium/luxury from MRP quantiles
WITHIN each category. No LLM. Also compute a per-series price distribution so
series positioning is derived rather than declared.

Stop after writing configs/taxonomy.yaml and wait for my review before running
the assignment pass.
```

**Gate:** you personally review the taxonomy. It shapes every filter in the UI.

---

## Phase 5 — Search

```
Implement index/: BGE-M3 text embeddings over a composed product string
(series + category + description + attributes), SigLIP or CLIP image embeddings,
both into LanceDB at data/vectors/. Add BM25 via rank-bm25 and fuse with dense
results using reciprocal rank fusion, then rerank with bge-reranker-v2-m3.

Load models lazily and cache them. Use CPU-only torch.

Add a `search` CLI command so I can test retrieval before any UI exists.
Then run 20 varied queries and print top-5 for each.
```

**Gate:** top-5 relevance is acceptable on 20 handwritten queries.

---

## Phase 6 — Streamlit UI

```
Build app/ with Home.py plus pages: 1_Browse, 3_Compare, 9_Review_Queue.

Browse: sidebar filters for series (multi), category tree, price range slider
bound to the real min/max in the DB, mounting type, finish, tier. Paginated
card grid with thumbnail, SKU, description, MRP. Filters persist to URL query params.

Compare: pin 2-4 SKUs, aligned attribute table, highlight differences.

Review Queue: low-confidence rows with the rasterised source page region shown
side by side, accept/edit/reject, and corrections written back to the DB and
appended to the eval fixtures.

All data access through db/repository.py. Models cached with @st.cache_resource,
queries with @st.cache_data. No raw SQL in app/.
```

**Gate:** you can find a wall mixer under ₹8,000 in the TANSA series in under
ten seconds.

---

## Phase 7 — Ask, visualise, project sheet

```
Add app/pages/2_Ask.py backed by recommend/:

intent.py parses the natural-language query into a structured filter plus a
semantic residue. ranker.py applies the hard SQL filter FIRST, then hybrid
retrieve, rerank, and MMR diversify. explain.py writes the rationale grounded
strictly in the retrieved rows, citing SKU and MRP.

If a SKU appears in the answer that is not in the retrieved set, that is a bug —
add an assertion that fails loudly.

Add app/pages/5_Project_Sheet.py: room-by-room BOM builder (add SKU + quantity),
running MRP total, export to Excel via openpyxl and a PDF quotation.

Add a visualisation section on Home: price distribution by series, category
coverage, price-band histograms — all computed in pandas from SQL. The LLM may
write the commentary above each chart, never the numbers.
```

Interior image generation is deliberately last. Route it to Replicate or fal.ai
with SDXL plus IP-Adapter, cache by (sku, room_preset, style), and label every
output "AI-generated visualisation — not a product photograph" in the UI and
burned into the exported file.

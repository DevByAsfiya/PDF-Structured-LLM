# Catalogue Intelligence System — Architecture & Project Layout

**Status:** design only, no implementation
**Reference corpus:** `JAL_FAUCETS_2025.pdf` — 202pp, 108MB, A4, PDFium-produced
**Target runtime:** VS Code (primary) / Colab (experiments)

---

## 0. Findings from the source PDF that drive the design

These are measured, not assumed. They change several decisions.

| Finding | Consequence |
|---|---|
| Clean embedded text layer (Identity-H CID, all fonts embedded) | **This is not an OCR problem.** No Tesseract/PaddleOCR in the main path. Keep OCR as a fallback branch only. |
| One raster JPEG per product, ~300 DPI, CMYK | Image↔text association is solvable by **bounding-box geometry**, not by a VLM. Note: CMYK JPEGs need colour conversion or they render inverted. |
| Caption block sits directly below its image, in a fixed grid | A deterministic spatial join (nearest-image-above, column-aligned) will get you 90%+ before any model runs. |
| Some captions carry **multiple SKUs** (`82456 15mm MRP 1992/-` + `82470 20mm MRP 2066/-`) | image→SKU is **one-to-many**. Your schema needs a variant table, not a flat products table. |
| Series names are page headers (TANSA, WARNA PRO, KOLAB…) | Series is inherited from page context, carried forward until the next header. |
| Machine-readable INDEX page (`Tansa 31`, `Warna Pro 83`…) | Free ground truth for section boundaries. Parse it and use it to validate your header detection. |
| End matter is **tabular** (`Cat No. \| Image \| Description \| Used In \| MRP`) | At least 3 page archetypes exist. You need a page classifier, not one universal parser. |
| Front matter is lifestyle/marketing pages with zero products | Classifier must be able to say "no products here" and skip cheaply. |
| `M.R.P. w.e.f 23.11.2024` on page 1 | Catalogue-level metadata: price effective date, currency, edition. Essential for versioning. |
| "Brands" here = series/collections of one manufacturer | Your data model needs `manufacturer → series → product → variant`. Don't call it "brand". |

---

## 1. The single most important architectural decision

**Do not send pages to an LLM to extract data. Extract deterministically; use models only for enrichment, fallback, and search.**

Your original spec implies an LLM-first pipeline. On a 202-page catalogue with ~2,500+ SKUs, that approach gives you: non-reproducible output, silent price hallucinations, ₹-per-run costs that scale with re-runs, and no way to diff two catalogue editions. A misread price in a faucet quotation is a real commercial error.

The correct split:

| Layer | Method | Why |
|---|---|---|
| SKU code, price, description, image binding | **Deterministic** (PyMuPDF spans + bbox geometry + regex) | 100% reproducible, free, instant, auditable |
| Page archetype classification | Heuristics first, small VLM only on ambiguous pages | Cheap routing |
| Attribute normalisation, taxonomy, tags | LLM (structured output, batched) | Genuinely fuzzy work |
| Semantic search, recommendation | Embeddings + reranker | What models are actually good at |
| Interior visualisation | Diffusion + ControlNet | Generative by nature |
| Low-confidence rows | Human review queue in the UI | The honest answer for the last 5% |

Every extracted field carries a `confidence` and an `extraction_method`. Anything below threshold routes to review instead of silently entering the index.

---

## 2. Pipeline stages

```
[00] Ingest        → register PDF, hash, extract catalogue metadata (edition, price date, currency)
[01] Profile       → sample N pages, auto-detect layout profile → catalogue_profile.yaml
[02] Segment       → parse INDEX page; classify every page into an archetype
[03] Extract       → per-archetype parsers emit raw blocks (text spans + image bboxes)
[04] Associate     → spatial join: bind each image to its caption block
[05] Parse         → regex/grammar over caption → SKU(s), description, MRP(s), variants
[06] Assets        → export images, CMYK→sRGB, deduplicate by perceptual hash, thumbnail
[07] Enrich        → LLM pass: normalise, tag, classify into taxonomy, write search blurbs
[08] Tier          → statistical price tiering per category (NOT LLM-judged)
[09] Embed         → text embeddings + CLIP image embeddings → vector store
[10] Validate      → run assertion suite; anything failing → review queue
[11] Serve         → Streamlit UI over SQL + vector + object store
```

Stages 03–06 are pure functions over the PDF. Stage 07+ depends on models. **Keep that boundary hard** — it means you can re-run enrichment without re-parsing, and re-parse without re-paying for enrichment.

Each stage writes a versioned artefact to disk (Parquet/JSONL). Make it resumable and idempotent — on a 202-page, 108MB file you will re-run stages constantly.

---

## 3. Project structure

```
catalogue-intelligence/
├── README.md
├── pyproject.toml                    # uv or poetry; pin everything
├── .env.example                      # GROQ_API_KEY, HF_TOKEN, etc.
├── Makefile                          # make ingest / make extract / make ui
│
├── configs/
│   ├── settings.yaml                 # paths, thresholds, batch sizes
│   ├── models.yaml                   # model registry: provider, id, cost, fallback chain
│   ├── taxonomy.yaml                 # product taxonomy (seeded, then LLM-extended)
│   └── profiles/
│       ├── _schema.yaml              # what a catalogue profile must contain
│       └── jal_faucets_2025.yaml     # auto-generated, human-editable
│
├── src/catalogue/
│   ├── config.py                     # pydantic-settings; single source of truth
│   ├── schemas.py                    # ALL pydantic models live here
│   │
│   ├── ingest/
│   │   ├── loader.py                 # open PDF, hash, page count, metadata
│   │   ├── index_parser.py           # parse the INDEX page → section map
│   │   └── profiler.py               # auto-generate catalogue_profile.yaml
│   │
│   ├── layout/
│   │   ├── classifier.py             # page → archetype (cover/lifestyle/grid/table/spec)
│   │   ├── blocks.py                 # PyMuPDF span & image bbox extraction
│   │   └── geometry.py               # column detection, nearest-above, IoU, grid inference
│   │
│   ├── extract/
│   │   ├── base.py                   # PageParser ABC — the extension point
│   │   ├── grid_parser.py            # archetype: product grid
│   │   ├── table_parser.py           # archetype: spare-parts table
│   │   ├── spec_parser.py            # archetype: dimension/technical drawings
│   │   └── caption_grammar.py        # SKU / MRP / variant tokenisation
│   │
│   ├── assets/
│   │   ├── exporter.py               # image export + CMYK→sRGB + resize
│   │   ├── dedupe.py                 # perceptual hash; catalogues reuse images heavily
│   │   └── store.py                  # local FS now, S3/R2 later — same interface
│   │
│   ├── enrich/
│   │   ├── llm_client.py             # provider-agnostic; retry, cache, cost log
│   │   ├── prompts/                  # versioned .jinja templates, never inline strings
│   │   ├── normalizer.py             # units, finishes, materials, dimensions
│   │   ├── categorizer.py            # taxonomy assignment
│   │   ├── tier.py                   # statistical price tiering
│   │   └── vlm_fallback.py           # VLM only for pages the parser failed on
│   │
│   ├── index/
│   │   ├── text_embed.py             # BGE-M3 / e5
│   │   ├── image_embed.py            # CLIP / SigLIP
│   │   ├── vectorstore.py            # LanceDB or Qdrant behind one interface
│   │   └── hybrid.py                 # BM25 + dense fusion (RRF) + rerank
│   │
│   ├── recommend/
│   │   ├── intent.py                 # NL query → structured filter + semantic residue
│   │   ├── ranker.py                 # filter → retrieve → rerank → diversify
│   │   └── explain.py                # LLM writes the "why this" rationale
│   │
│   ├── visualize/
│   │   ├── render.py                 # interior scene generation
│   │   ├── compositor.py             # product cutout → scene placement
│   │   └── scene_prompts.py          # room presets: bathroom, kitchen, powder room
│   │
│   ├── db/
│   │   ├── models.py                 # SQLModel / SQLAlchemy
│   │   ├── migrations/               # alembic
│   │   └── repository.py             # query layer the UI calls — no raw SQL in UI
│   │
│   └── eval/
│       ├── golden/                   # hand-labelled pages: 33, 83, 143, 198
│       ├── metrics.py                # SKU recall, price exact-match, image-bind accuracy
│       └── report.py
│
├── app/                              # Streamlit
│   ├── Home.py
│   ├── pages/
│   │   ├── 1_Browse.py
│   │   ├── 2_Ask.py                  # NL recommendation
│   │   ├── 3_Compare.py
│   │   ├── 4_Visualize.py
│   │   ├── 5_Project_Sheet.py        # BOM / quotation builder
│   │   └── 9_Review_Queue.py         # low-confidence rows — the quality flywheel
│   ├── components/
│   └── state.py
│
├── notebooks/                        # Colab exploration; never import from these
│   ├── 01_layout_probe.ipynb
│   ├── 02_parser_tuning.ipynb
│   └── 03_embedding_eval.ipynb
│
├── data/                             # gitignored
│   ├── raw/  interim/  processed/  assets/  db/  vectors/
│
├── scripts/
│   └── run_pipeline.py               # CLI: --stages 03-06 --pages 30-50
│
└── tests/
```

**Why this shape:** `extract/base.py` as an ABC is the extension point that makes the system genuinely dynamic — a new catalogue with a new layout means writing one parser class, not touching the pipeline. `repository.py` between UI and DB means you can swap SQLite→Postgres without touching Streamlit. `prompts/` as versioned files means you can diff a regression to a prompt change.

---

## 4. Tech stack

### Extraction
| Need | Pick | Note |
|---|---|---|
| PDF parsing + bboxes | **PyMuPDF (fitz)** | Gives text spans *and* image rects in the same coordinate space. This is the whole ballgame. |
| Table pages | **pdfplumber** | Better ruling-line table detection than fitz |
| CLI probing | **poppler-utils** | `pdfinfo`, `pdfimages -list` for diagnostics |
| Image handling | **Pillow + ImageCIS** | CMYK→sRGB conversion is mandatory here |
| Dedupe | **imagehash** | pHash |
| OCR (fallback only) | **Surya** or **PaddleOCR** | Not needed for this PDF |

### Models
| Need | Open-source pick | Where to run |
|---|---|---|
| Enrichment LLM | Llama 3.3 70B / Qwen 2.5 72B class | **Groq** (fast, cheap, OpenAI-compatible) |
| Structured output | Same + `outlines` or JSON-schema mode | Enforce the schema, don't parse prose |
| VLM fallback | **Qwen2.5-VL-7B** | HF Inference / local on Colab T4+ |
| Text embeddings | **BGE-M3** (dense+sparse+colbert) or `e5-large-v2` | Local, ~2GB |
| Image embeddings | **SigLIP** or CLIP ViT-L/14 | Local |
| Reranker | **bge-reranker-v2-m3** | Local, big precision win |
| Image generation | **SDXL / FLUX.1-dev** + ControlNet + IP-Adapter | Replicate / fal.ai / HF; Colab A100 for local |

⚠️ **Groq does not do image generation.** It's an LLM/VLM inference host. Route generation to Replicate, fal.ai, or local diffusers. Model availability on all these providers shifts monthly — put model IDs in `models.yaml`, never in code, and define a fallback chain per role.

### Storage
| Need | Dev | Production |
|---|---|---|
| Structured | SQLite | Postgres (+ `pgvector`) |
| Vectors | **LanceDB** (embedded, Colab-friendly) | Qdrant |
| Assets | Local FS | S3 / Cloudflare R2 |
| Cache | `diskcache` | Redis |

Wrap vectors behind one interface so LanceDB→Qdrant is a config change. If you go Postgres, `pgvector` collapses two stores into one — worth it once the catalogue count grows.

### App
Streamlit + `st.cache_resource` for models, `st.cache_data` for queries, `pandas`/`polars`, `plotly` for the visualisation section.

---

## 5. Data model

```
catalogue        id, source_file, sha256, manufacturer, edition, price_effective_date,
                 currency, page_count, ingested_at, profile_id

page             id, catalogue_id, page_no, archetype, section_name, confidence

product          id, catalogue_id, series, category_id, subcategory,
                 base_description, page_id, bbox, primary_image_id, confidence

variant          id, product_id, sku, description_suffix, mrp, unit,
                 spec (JSONB), confidence, extraction_method
                 ↑ this table is why the multi-SKU caption problem is solved

asset            id, product_id, path, phash, width, height, is_primary, role

attribute        id, product_id, key, value, unit, source   ← EAV, keeps schema dynamic

taxonomy_node    id, parent_id, name, level, slug

embedding_ref    id, entity_type, entity_id, vector_id, model_id, created_at

review_item      id, entity_type, entity_id, issue, status, resolved_by, resolved_at
```

Use **EAV (`attribute`)** for product specs, not fixed columns. Faucets have flow rate and cartridge size; a tile catalogue has slip rating and calibre. Fixed columns kill the "dynamic" requirement on catalogue #2.

Every row is scoped to `catalogue_id`. That gives you multi-catalogue and edition-diffing for free.

---

## 6. How "dynamic" actually works

Your requirement to make this generic is the highest-risk part of the spec. Concretely:

**a) Catalogue profile auto-detection (stage 01).** Sample 8–12 pages, run a VLM once, and emit a YAML profile:

```yaml
catalogue_id: jal_faucets_2025
identifiers:
  sku_pattern: '\b\d{4,6}[A-Z]?\d*\b'
  price_pattern: 'MRP\s*([\d,]+(?:\.\d+)?)\s*/?-?'
  currency: INR
layout:
  archetypes: [cover, lifestyle, product_grid, parts_table, tech_spec]
  grid: {columns: 4, caption_position: below, max_caption_offset_pt: 90}
  section_header: {position: top_left, font_size_min: 20}
hierarchy:
  levels: [manufacturer, series, category, product, variant]
```

The profile is **generated once, then human-editable**. Ten minutes of correction beats a week of prompt engineering, and the file is the audit trail.

**b) Parser plugins.** `PageParser` ABC with `can_handle(page, profile) → float` and `parse(page, profile) → list[RawProduct]`. Registry picks the highest scorer. New layout = new class.

**c) Taxonomy bootstrapping.** Never hardcode "faucets". Run one LLM pass over all extracted descriptions → propose a taxonomy → you approve/edit → store in `taxonomy.yaml` → classify deterministically via embeddings, LLM only for tie-breaks.

**d) Prompt templating.** All prompts take the profile as context. No catalogue-specific strings in code.

---

## 7. Pricing tiers and recommendation

**Do not ask an LLM whether something is "budget" or "luxury".** It has no stable notion of Indian faucet pricing and will be inconsistent across runs.

Tier statistically, **within category**:

```
tier = quantile bucket of MRP within (category × function)
       ₹1,594 angle stop cock  and  ₹17,664 concealed basin mixer
       are not comparable — a global percentile makes every stop cock "budget"
```

Buckets: `value / mid / premium / luxury`, from category quantiles (e.g. p33/p66/p90), then let the LLM assign a *label and rationale* on top of the computed tier. Series-level positioning (TANSA vs WARNA PRO) becomes a second signal once you observe each series' price distribution — derive it, don't declare it.

**Retrieval pipeline for "show me budget-friendly wall mixers for a 2BHK":**

```
1. Intent parse (LLM, structured out) → {category: wall_mixer, tier: value,
                                         qty_hint: 2, semantic: "2BHK residential"}
2. Hard filter in SQL      → candidate set (fast, exact, no hallucination)
3. Hybrid retrieve         → BM25 + dense, fused via RRF
4. Rerank                  → bge-reranker, top-50 → top-10
5. Diversify (MMR)         → avoid 10 near-identical SKUs
6. Explain (LLM)           → grounded ONLY in retrieved rows; cite SKU + MRP
```

Structured filters must run **before** semantic search, not after. Price and category are exact constraints — never let a vector similarity score decide whether ₹17,664 counts as budget.

---

## 8. Interior visualisation

Realistically three tiers of effort:

| Tier | Approach | Fidelity | Cost |
|---|---|---|---|
| A | Text-to-image: "modern bathroom with chrome single-lever basin mixer" | Plausible scene, **wrong product** | Low |
| B | IP-Adapter conditioned on the catalogue image + SDXL | Recognisably similar product | Medium |
| C | Background-remove product → inpaint into a curated room template with ControlNet (depth/canny) | Actual SKU in scene | High |

Start at **A**, ship **B**. Tier C is a project in itself.

Non-negotiable: label every generated image **"AI-generated visualisation — not a product photograph"**, both in the UI and burned into the exported file. An engineer using this to pick fittings must never mistake a render for a spec image. Cache renders by `(sku, room_preset, style)` — generation is the most expensive operation in the system.

---

## 9. Streamlit UI

**Browse** — filters: series (multi), category tree, price slider bound to actual min/max, mounting type, finish, tier. Grid cards with image, SKU, description, MRP. Persist filters to URL params so a state can be shared.

**Ask** — natural language → recommendations with cited SKUs, price, and rationale.

**Compare** — pin 2–4 SKUs, aligned attribute table, delta highlighting.

**Visualize** — room preset + style, render, disclaimer, cache indicator.

**Project Sheet** — *this is the feature that actually replaces flipping through 202 pages.* Build a room-by-room BOM (basin mixer ×2, angle cocks ×4, overhead shower ×1), running total at MRP, export to Excel/PDF as a quotation. An engineer's real job is specifying a *set*, not finding a product.

**Review Queue** — low-confidence extractions with the source page image side-by-side. Corrections feed back as regression fixtures. This is what makes the system trustworthy over time.

**Visualisation section** (your "generated by LLM" requirement): price distribution by series, category coverage, price-band histograms, tier composition. Generate these from SQL with plotly — **let the LLM write the commentary, not the numbers.** LLM-computed statistics are wrong statistics.

Streamlit caveats: never load models per-rerun (`@st.cache_resource`), paginate the grid (2,500 SKUs will freeze the browser), lazy-load thumbnails.

---

## 10. Suggested changes to your original spec

1. **"LLM to run over the entire database for reliability"** → invert this. LLMs don't verify, they agree. Reliability comes from *deterministic assertions*: every product has ≥1 variant; every variant has a price in a plausible range; every SKU matches the pattern; SKUs are unique per catalogue; extracted SKU count per page matches image count ± variants; INDEX page sections align with detected headers. The LLM handles ambiguity, the assertion suite handles correctness.

2. **"Images and their relative text in same sequence"** → sequence isn't enough. Store `page_no`, `bbox`, `column_index`, `row_index`. Geometry is recoverable and debuggable; a bare ordinal is not.

3. **"Categorization on pricing and brands"** → rename to `series`, and add category/function/mounting-type. Users filter on function far more than on series.

4. **Add edition diffing.** You have a `w.e.f 23.11.2024` price date. When the 2026 catalogue lands, "what changed, what's discontinued, what repriced" is arguably more commercially valuable than the search itself. The data model above supports it for free.

5. **Add a golden eval set now.** Hand-label pages 33, 83, 143, 198 (one per archetype). Track SKU recall, price exact-match, image-binding accuracy. Without this you cannot tell whether a change helped.

6. **Add cost telemetry** from day one. Log tokens and ₹ per stage. It's the difference between a demo and something you can price.

7. **Consider skipping the DB for v0.** 2,500 rows is a Parquet file. Get extraction quality right first; add Postgres when you have a second catalogue or a second user.

---

## 11. Build order

| Milestone | Deliverable | Gate |
|---|---|---|
| M0 | Page classifier + block extraction on 10 pages | Archetypes correct on all 10 |
| M1 | Grid parser + spatial join + variant splitting | ≥95% SKU recall, 100% price exact-match on golden pages |
| M2 | Full 202-page run, assets exported, Parquet output | <5% rows in review queue |
| M3 | SQLite + enrichment + taxonomy + tiering | Taxonomy reviewed and signed off by you |
| M4 | Embeddings + hybrid search + rerank | Top-5 relevance on 20 handwritten queries |
| M5 | Streamlit: Browse + Compare + Review Queue | Usable end to end |
| M6 | Ask (NL recommendation) with grounded citations | No hallucinated SKUs across 20 queries |
| M7 | Visualize (Tier A→B) | Disclaimered, cached |
| M8 | Project Sheet + Excel/PDF export | — |
| M9 | Second catalogue → validate the profile mechanism | New catalogue works with ≤1 new parser class |

M1 is the real gate. If the deterministic parser doesn't hit near-perfect price extraction, nothing downstream matters.

---

## 12. Open decisions for you

1. **Scope of "dynamic"** — other JAL editions, other faucet brands, or any product catalogue? These are three very different amounts of work. My read: build for #2, architect so #3 is possible.
2. **Deployment target** — local tool for your own use, or hosted for MSME clients? Changes auth, multi-tenancy, and cost model substantially.
3. **Is the 108MB PDF the only input?** If the manufacturer has a price list in Excel, join against it and your price confidence goes to 100% immediately.
4. **Who reviews the queue?** The flywheel only turns if someone actually works it.
5. **Image licensing** — you're re-hosting manufacturer product photography and generating derivative renders. Worth a check before this goes client-facing.
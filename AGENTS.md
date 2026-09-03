# AGENTS.md — JAL Catalogue Scraper

## What this project is

A pipeline that turns `JAL FAUCETS 2025.pdf` (202 pages, 108 MB, A4) into a
searchable, filterable product database with a Streamlit UI, so a plumbing or
interiors engineer can specify fittings without flipping through the PDF.

**Scope is ONE catalogue.** Do not build catalogue auto-detection, layout
profiling, or multi-tenant abstractions. Hardcode JAL specifics in
`src/pdfscraper/catalogue_spec.py`. Keep parsers behind a base class so a second
catalogue is possible later — but do not build for it now.

## Hard rules — violating these is a bug, not a style preference

1. **Never use an LLM to extract SKU codes, prices, or image-to-text bindings.**
   The PDF has a clean embedded text layer. Extraction is deterministic:
   PyMuPDF spans + bounding-box geometry + regex. An LLM in this path produces
   non-reproducible output and wrong prices. Wrong prices are a commercial error.
2. **LLMs are allowed only for:** attribute normalisation, taxonomy assignment,
   search-blurb writing, natural-language query parsing, and recommendation
   rationale. Nothing else.
3. **Never let an LLM compute a statistic.** Charts and aggregates come from SQL
   or pandas. The LLM may write commentary about numbers it is given.
4. **Price tiers are computed statistically, within category** — quantiles of MRP
   grouped by category. Never a global percentile (a ₹1,594 stop cock and a
   ₹17,664 basin mixer are not on the same scale), and never an LLM judgement.
5. **Every extracted field carries `confidence` and `extraction_method`.**
   Anything below threshold goes to the review queue, never silently into the index.
6. **Stages are idempotent and resumable.** Each writes a versioned artefact to
   `data/interim/` or `data/processed/`. Re-running stage 5 must not require
   re-running stage 3.
7. **No secrets in code.** Read from `.env` via pydantic-settings. Never print or
   log an API key.
8. **No network calls in stages 00–06.** Those stages are pure functions over the PDF.
9. **Never write a constant you have not read from the source document.** If a
   value must come from the PDF, leave it to be parsed at runtime rather than
   guessing a plausible value.
10. **Never write files with `Set-Content -Encoding utf8`** — it emits a UTF-8 BOM
    that breaks tomllib. Always use utf8NoBOM (e.g. `[System.Text.UTF8Encoding]::new($false)`).

## Known facts about the source PDF — do not re-derive these

- Producer PDFium, PDF 1.7, 202 pages, A4 (595.276 × 841.89 pt), not encrypted, no forms.
- Text layer is clean. Fonts are embedded CID TrueType / Type0C, Identity-H.
  **Do not add OCR to the main path.**
- Product images are one raster JPEG per product, ~300 DPI, **CMYK colourspace**.
  They must be converted to sRGB on export or they render inverted.
- Product-grid pages: image on top, caption block directly below it, 3–4 columns.
  Caption = SKU code, then description, then `MRP <number>/-`.
- **A single caption can contain multiple SKUs.** Example from page 33 (PDF page 40):
  `82456 Concealed Stop Cock with flange 15 mm MRP 1992/-` followed by
  `82470 20 mm MRP 2066/-`. Also `82754` / `82750`, and `82755` / `82751`.
  Therefore image → SKU is **one-to-many**. Model this as `product` + `variant`.
- Series names (TANSA, KOLAB, WARNA PRO, NALINI PRO, DRAS, ZAURI, KOYNA, KONAR,
  VENNA, PENNA, VELLAR, TIZU, TAWI, JHELUM, HINDON, TORSA, SPITI …) appear as
  large top-left page headers and apply to all products on the page until the
  next header. These are **series/collections of one manufacturer, not brands.**
- There is a machine-readable **INDEX page** (PDF page 6) mapping series to
  printed page numbers. Parse it and use it as ground truth to validate header
  detection. Note: printed page number ≠ PDF page index (offset of ~7).
- **Page 1 carries `M.R.P. w.e.f 23.11.2024`** — catalogue-level metadata:
  price effective date, currency INR.
- At least four page archetypes exist:
  `cover`, `lifestyle` (marketing, zero products), `product_grid`,
  `parts_table` (end matter, ruled columns:
  `Cat No. | Image | Item Description | Used In (Range) | MRP (Rs. Each)`).
  A `tech_spec` archetype may also exist — detect, don't assume.

## Directory contract

Everything lives inside `0-PDF Scraper/`. Never write outside it. Never modify
the sibling folders (`1-Q&A Chatbot` … `7-Text Summarization`), the workspace-root
`venv/`, `requirements.txt`, or `.env`.

```
0-PDF Scraper/
├── AGENTS.md
├── README.md
├── .env                     # local, gitignored
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── Makefile
├── data/                    # gitignored except .gitkeep
│   ├── raw/                 # JAL FAUCETS 2025.pdf lives here
│   ├── interim/             # per-stage parquet/jsonl
│   ├── processed/
│   ├── assets/              # exported product images
│   ├── db/                  # catalogue.sqlite
│   └── vectors/             # lancedb
├── src/pdfscraper/
│   ├── config.py            # pydantic-settings; paths, thresholds
│   ├── catalogue_spec.py    # ALL JAL-specific constants and regexes
│   ├── schemas.py           # all pydantic models
│   ├── cli.py               # typer entrypoint
│   ├── layout/              # blocks.py, geometry.py, classifier.py
│   ├── extract/             # base.py, grid_parser.py, table_parser.py, caption_grammar.py
│   ├── assets/              # exporter.py, dedupe.py
│   ├── enrich/              # llm_client.py, prompts/, normalizer.py, categorizer.py, tier.py
│   ├── db/                  # models.py, repository.py
│   ├── index/               # text_embed.py, image_embed.py, vectorstore.py, hybrid.py
│   ├── recommend/           # intent.py, ranker.py, explain.py
│   └── eval/                # golden/, metrics.py
├── app/                     # Streamlit
│   ├── Home.py
│   ├── pages/
│   └── components/
├── notebooks/               # exploration only; never imported by src/
└── tests/
```

`src/` layout, installed editable. Import as `from pdfscraper.layout import blocks`.
Never use `sys.path` hacks. The parent folder has a space in its name — quote it in
every shell command.

## Commands

```bash
# from inside "0-PDF Scraper"
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

python -m pdfscraper.cli ingest
python -m pdfscraper.cli run --stages 02-06
python -m pdfscraper.cli run --stages 02-06 --pages 38-45   # fast dev loop
python -m pdfscraper.cli eval
streamlit run app/Home.py

pytest -q
```

**Always develop against `--pages 38-45` first.** A full 202-page run takes minutes
and burns tokens. Only run the full pipeline when a stage passes on the sample.

## Conventions

- Python 3.11+. Type hints everywhere. Pydantic v2 for every data structure that
  crosses a module boundary.
- `loguru` for logging, `rich` for CLI output, `typer` for the CLI. No `print()`.
- Prompts live in `src/pdfscraper/enrich/prompts/*.jinja` as versioned files.
  Never inline a prompt string in Python.
- LLM calls go through `enrich/llm_client.py` only: retry with `tenacity`,
  disk-cached with `diskcache` keyed on `(model, prompt_hash)`, token and cost
  logged per call. Request JSON via the provider's structured-output mode and
  validate against a pydantic model — never regex an LLM's prose.
- The Streamlit app talks to `db/repository.py`. **No raw SQL in `app/`.**
- Models are named in `config.py`, never hardcoded at a call site.

## Definition of done for a stage

A stage is not complete until: it runs from the CLI, is idempotent, writes its
artefact, has at least one test against the golden pages, and logs a summary
(rows in, rows out, rows to review).

## Gotchas that have already cost time — don't rediscover them

- CMYK JPEGs: convert with Pillow to sRGB before saving, or every product photo
  looks inverted in the UI.
- `pdfimages` also emits tiny mask/decoration images. Filter by pixel area and
  file size before treating something as a product photo.
- Catalogues reuse the same image across pages. Deduplicate by perceptual hash.
- Don't load models inside a Streamlit rerun — `@st.cache_resource`.
- Paginate the product grid. ~2,500 SKUs rendered at once will freeze the browser.
- The 108 MB PDF must never be committed. It is in `.gitignore`.

## Ask before doing

Stop and ask rather than guessing if: the taxonomy needs inventing, a page
archetype doesn't match anything above, a parser would need >10% of pages
hand-special-cased, or a dependency would add more than ~500 MB.

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
   Anything below threshold goes to the review queue, never silently into the
   index. Never drop a product silently — an unparseable caption must emit a
   low-confidence row, not just a log line.
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
11. **A null price is never zero.** `mrp` is `Optional[float]`. A missing price
    stores `None`. Zero displays as free and sorts to the top of budget filters.
12. **Do not run git commands.** Version control is handled manually.

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
  A variant whose description is a fragment (`20 mm`) inherits the primary's
  description and keeps its fragment as `description_suffix`.
- Series names appear as large top-left page headers and apply to all products on
  the page until the next header. These are **series/collections of one
  manufacturer, not brands.** **Do not hardcode the series list** — 84 sections
  are parsed at runtime from the INDEX into `data/interim/sections.json`.
  Series names may be letter-spaced in the PDF (`T A N S A`); strip whitespace
  before matching, and match longer names first so `NALINI` does not shadow
  `NALINI PRO` (likewise WARNA / WARNA PRO, DRAS / DRAS PRO).
- Machine-readable **INDEX on PDF pages 6 and 7**, yielding 84 sections. These
  include both series (Tansa, Kolab, Nalini Pro …) and functional categories
  (Sensor Faucets, Foot Operated Valves, Mirrors, Kitchen Sinks, Grab Bars …).
  Printed-to-PDF page offset is **+7**, verified empirically across six samples.
  Derive it at runtime and warn if the derived value differs.
- **Page 1 carries `M.R.P. w.e.f 23.11.2024`** — catalogue-level metadata:
  price effective date, currency INR.
- **Eight page archetypes**, confirmed by the Phase 1 classifier:
  `cover` (4), `index` (2), `hero` (35), `editorial` (30), `lifestyle` (16),
  `product_grid` (104), `parts_table` (9), `tech_spec` (2).
  Faucet series follow a strict template: page 1 = hero photo, page 2 =
  editorial bullets, pages 3–4 = product grids. That is why ~80 pages are
  legitimately product-free — this is not a parser miss.
- `parts_table` pages use ruled tables with varying columns. Spares:
  `Cat No. | Image | Item Description | Used In (Range) | MRP (Rs. Each)`.
  Kitchen Sinks (188–193): `Cat. No. | Size | S.S. Grade | Finish | Thickness |
  Depth | Bowl | MRP`. Detect the header row; do not assume a fixed schema.
  Prices vary: the spares table has bare numbers (`1424.00`), Kitchen Sinks
  use a `/-` suffix (`9194/-`). `TABLE_PRICE_PATTERN` handles both. Kitchen
  Sinks pages have no internal horizontal rules — pdfplumber's default
  strategy returns nothing, so the parser falls back to
  `vertical_strategy="text"` and zips columns split on newline.
- SKU formats vary: `82456` (plain), `40120N` (single suffix letter),
  `82369US25` / `82550RES25` (multi-letter), `76510S01` / `75730S103`
  (parts table). The pattern must handle all of these.
- Caption text contains concealed-body reference numbers that are **not**
  sellable SKUs — `52665`, `52651`, `716`, `735` inside "(Compatible with …)"
  phrases. Skip parentheticals containing "compatible" or a 3+ digit number,
  but preserve ordinary ones like `(QT)`, `(Conc.)`, `(Tall Model)`.

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
├── requirements.txt         # authoritative — do not regenerate
├── pyproject.toml           # metadata + editable install only
├── Makefile
├── logs/                    # gitignored; rotating loguru sink
├── docs/
│   ├── DECISIONS.md         # append-only; one entry per phase
│   └── Catalouge_Intelligence_Architecture.md
├── data/                    # gitignored except .gitkeep
│   ├── raw/                 # JAL FAUCETS 2025.pdf lives here
│   ├── interim/             # catalogue.json, sections.json, pages.parquet,
│   │                        # products.jsonl
│   ├── processed/
│   ├── assets/              # exported product images
│   ├── db/                  # catalogue.sqlite
│   └── vectors/             # lancedb
├── src/pdfscraper/
│   ├── config.py            # pydantic-settings; paths, thresholds
│   ├── catalogue_spec.py    # ALL JAL-specific constants and regexes
│   ├── schemas.py           # all pydantic models
│   ├── cli.py               # typer entrypoint
│   ├── ingest/              # service.py, index_parser.py
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
└── tests/                   # test_scaffold.py, test_phase1.py, test_phase2.py
```

`src/` layout, installed editable. Import as `from pdfscraper.layout import blocks`.
Never use `sys.path` hacks. The parent folder has a space in its name — quote it in
every shell command. This is Windows: use `pathlib.Path` in code, never string
path concatenation or forward slashes.

## Visual search requirement (Phases 5–6)

The system must accept a user-uploaded product photo and return the same
product or close alternatives from the catalogue. Phase 5's image index
serves this — build it with that use in mind, not only text-to-image
retrieval. Store the embedding model ID alongside each vector so
re-indexing is possible when the model changes.

In Phase 6, add an upload screen that runs background removal on the query
image, retrieves nearest neighbours, uses a vision model to identify the
fitting type, filters candidates to that type, and returns matches with
SKU, price, and a short rationale. If the uploaded image contains a legible
catalogue code, OCR it and treat an exact code match as outranking any
visual similarity.

## Commands

```bash
# from inside "0-PDF Scraper"
.venv\Scripts\activate             # Windows
pip install -e .

python -m pdfscraper.cli ingest
python -m pdfscraper.cli run --stages 02                     # classify all 202 pages
python -m pdfscraper.cli run --stages 03-05 --pages 38-45    # fast dev loop
python -m pdfscraper.cli eval
streamlit run app/Home.py

pytest -q
```

**Always develop against `--pages 38-45` first.** A full 202-page run takes
minutes and burns tokens. Only run the full pipeline when a stage passes on the
sample. Note stage 02 always writes all 202 rows to `pages.parquet` regardless of
`--pages`; the filter applies to downstream stages only.

## Conventions

- Python 3.11+. Type hints everywhere. Pydantic v2 for every data structure that
  crosses a module boundary.
- `loguru` for logging (stderr + rotating file sink in `logs/`), `rich` for CLI
  output, `typer` for the CLI. No `print()`.
- Prompts live in `src/pdfscraper/enrich/prompts/*.jinja` as versioned files.
  Never inline a prompt string in Python.
- LLM calls go through `enrich/llm_client.py` only: retry with `tenacity`,
  disk-cached with `diskcache` keyed on `(model, prompt_hash)`, token and cost
  logged per call. Request JSON via the provider's structured-output mode and
  validate against a pydantic model — never regex an LLM's prose.
- The Streamlit app talks to `db/repository.py`. **No raw SQL in `app/`.**
- Models are named in `config.py`, never hardcoded at a call site.
- Write files with your file-edit tool, never by embedding source in a
  `python -c` string or a shell heredoc. Diffs must be reviewable.
- This is Windows PowerShell. Use `Get-Content`, `Get-ChildItem`,
  `Select-String` — not `cat -n`, `ls -l`, or `grep`.
- Append a `docs/DECISIONS.md` entry at the end of every phase: date, what was
  decided, why, what was rejected. Never modify earlier entries.
- Append a `docs/DECISIONS.md` entry at the end of every phase: date, what was
  decided, why, what was rejected. Never modify earlier entries.

## Definition of done for a stage

A stage is not complete until: it runs from the CLI, is idempotent, writes its
artefact, has at least one test against the golden pages, and logs a summary
(rows in, rows out, rows to review).

## Gotchas that have already cost time — don't rediscover them

- **Page 40 is the golden page.** `tests/test_phase2.py` locks 18 verified
  SKU→MRP pairs, 15 products, 18 variants, no duplicates. If it fails, price
  extraction is broken. Never weaken or delete this test.
- **Column inference must cluster image *centres*** and merge down to
  `GRID_COLUMNS_MAX`. Building columns from x-extents produces phantom columns
  (page 40 reported 5 for a 4-column grid), which let caption zones bleed into
  the adjacent product and attach prices to the wrong SKU.
- **Caption zones are strictly bounded by their column** — no horizontal drift
  tolerance. This is what stops price cross-contamination.
- **Deduplicate images by xref.** The PDF reuses image components, producing
  the same product two or three times otherwise.
- **If a caption yields more SKUs than prices**, set confidence below 0.5 and
  flag for review. Never guess which SKU owns which price.
- **PDF page 143** contains a real product (Cat No. 7736, MRP 4288/-) rendered
  as vector outlines, invisible to `get_text()`. It is the only such page in the
  catalogue. It is flagged `has_vector_text=True` for manual review in Phase 3 —
  do not add OCR or a VLM to handle it.
- CMYK JPEGs: convert with Pillow to sRGB before saving, or every product photo
  looks inverted in the UI.
- `pdfimages` also emits tiny mask/decoration images. Filter by area before
  treating something as a product photo.
- Catalogues reuse the same image across pages. Deduplicate by perceptual hash.
- Don't load models inside a Streamlit rerun — `@st.cache_resource`.
- Paginate the product grid. ~2,500 SKUs rendered at once will freeze the browser.
- The 108 MB PDF must never be committed. It is in `.gitignore`.
- Windows `cmd` has no `#` comment syntax and no `make`. Prefer PowerShell.

## Ask before doing

Stop and ask rather than guessing if: the taxonomy needs inventing, a page
archetype doesn't match anything above, a parser would need >10% of pages
hand-special-cased, or a dependency would add more than ~500 MB.

Do not run more than three exploratory commands in a row without reporting what
you found. Batch page probes into one script rather than sampling one page per
command.
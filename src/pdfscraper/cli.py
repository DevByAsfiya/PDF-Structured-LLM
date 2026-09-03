"""cli.py - Command-line interface for the JAL Catalogue Scraper pipeline.

Built with Typer and Rich, logging with Loguru.
No parsing logic is executed in this scaffolding phase; commands are wired
to informative stubs logging planned actions and validating inputs.
"""

import sys
from pathlib import Path
from typing import Optional
from loguru import logger
from rich.console import Console
from rich.panel import Panel
import typer

from pdfscraper.catalogue_spec import (
    FAST_DEV_LOOP_PAGE_RANGE,
    GOLDEN_EVAL_PAGES,
    PDF_FILENAME,
)
from pdfscraper.config import settings

app = typer.Typer(
    name="pdfscraper",
    help="JAL Faucets 2025 catalogue extraction and search intelligence pipeline.",
    add_completion=False,
)
console = Console()


def configure_logging(level: str = "INFO") -> None:
    """Configure loguru sink and format."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=level,
    )


@app.command()
def ingest(
    pdf_path: Optional[Path] = typer.Option(
        None,
        "--pdf",
        "-f",
        help="Path to source PDF file. Defaults to data/raw/JAL FAUCETS 2025.pdf",
    ),
) -> None:
    """Ingest source PDF: register document, compute checksum, and extract catalogue metadata."""
    configure_logging(settings.log_level)
    target = pdf_path or (settings.raw_data_dir / PDF_FILENAME)

    console.print(Panel.fit(f"[bold cyan]Ingesting Catalogue PDF[/bold cyan]\nTarget: [yellow]{target}[/yellow]"))
    logger.info("Stage 00 [Ingest] started for: {}", target)

    if target.exists():
        size_mb = target.stat().st_size / (1024 * 1024)
        logger.info("Source PDF verified on disk: {:.2f} MB", size_mb)
    else:
        logger.warning("Source PDF not found at {}. Expecting file in data/raw/", target)

    logger.info("Stub action: Parse catalogue metadata (price effective date, 202 pages, INR currency)")
    logger.info("Stage 00 [Ingest] completed successfully (stub).")


@app.command()
def run(
    stages: str = typer.Option(
        "02-06",
        "--stages",
        "-s",
        help="Pipeline stages to run, e.g. '02-06' or '02,03,04,05,06'",
    ),
    pages: Optional[str] = typer.Option(
        None,
        "--pages",
        "-p",
        help="Page range to process (e.g. '38-45' for fast dev loop). Default: all pages.",
    ),
) -> None:
    """Execute pipeline stages: segmentation, block extraction, spatial association, and parsing."""
    configure_logging(settings.log_level)

    console.print(
        Panel.fit(
            f"[bold green]Running Pipeline[/bold green]\n"
            f"Stages: [bold white]{stages}[/bold white]\n"
            f"Pages: [bold white]{pages or 'ALL (1-202)'}[/bold white]"
        )
    )

    if pages:
        logger.info("Fast dev loop active. Restricting extraction to page range: {}", pages)
    else:
        logger.warning(
            "Full catalogue run requested. Recommendation: Develop against --pages {}-{} first.",
            FAST_DEV_LOOP_PAGE_RANGE[0],
            FAST_DEV_LOOP_PAGE_RANGE[1],
        )

    logger.info("Parsing requested stage sequence: {}", stages)
    logger.info("Stub action: Stage 02 [Segment] - Page archetype classification (cover/grid/table)")
    logger.info("Stub action: Stage 03 [Extract] - Deterministic PyMuPDF span & image bbox extraction")
    logger.info("Stub action: Stage 04 [Associate] - Nearest-above spatial join (image -> caption)")
    logger.info("Stub action: Stage 05 [Parse] - Caption grammar tokenization (SKU, MRP, variants)")
    logger.info("Stub action: Stage 06 [Assets] - CMYK -> sRGB image conversion & perceptual dedupe")
    logger.info("Pipeline execution completed successfully (stub).")


@app.command("eval")
def evaluate(
    golden_dir: Optional[Path] = typer.Option(
        None,
        "--golden-dir",
        "-g",
        help="Directory containing ground truth annotations for golden pages.",
    ),
) -> None:
    """Evaluate pipeline precision, recall, and accuracy against ground truth golden pages."""
    configure_logging(settings.log_level)
    target_dir = golden_dir or settings.eval_golden_dir

    console.print(
        Panel.fit(
            f"[bold magenta]Evaluating Pipeline Accuracy[/bold magenta]\n"
            f"Golden Directory: [yellow]{target_dir}[/yellow]\n"
            f"Benchmark Pages: [white]{GOLDEN_EVAL_PAGES}[/white]"
        )
    )

    logger.info("Stage 10 [Validate/Eval] initiated against golden dataset at: {}", target_dir)
    logger.info("Stub action: Loading hand-labeled ground truth for pages {}", GOLDEN_EVAL_PAGES)
    logger.info("Stub action: Measuring SKU recall, price exact-match, and image-binding accuracy")
    logger.info("Evaluation completed. Accuracy metrics within target threshold (stub).")


if __name__ == "__main__":
    app()

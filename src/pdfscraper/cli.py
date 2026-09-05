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

from rich.table import Table

from pdfscraper.catalogue_spec import (
    FAST_DEV_LOOP_PAGE_RANGE,
    GOLDEN_EVAL_PAGES,
    PDF_FILENAME,
    PRINTED_TO_PDF_PAGE_OFFSET,
)
from pdfscraper.config import settings
from pdfscraper.ingest import ingest_catalogue, parse_index_and_sections
from pdfscraper.layout.classifier import classify_all_pages, save_pages_parquet

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

app = typer.Typer(
    name="pdfscraper",
    help="JAL Faucets 2025 catalogue extraction and search intelligence pipeline.",
    add_completion=False,
)
console = Console()


def configure_logging(level: str = "INFO") -> None:
    """Configure loguru sinks for interactive stderr and rotating file logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=level,
    )
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        settings.logs_dir / "pdfscraper_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
        level=level,
        rotation="10 MB",
        retention="14 days",
        encoding="utf-8",
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

    console.print(Panel.fit(f"[bold cyan]Stage 00 [Ingest] & Stage 01 [INDEX][/bold cyan]\nTarget: [yellow]{target}[/yellow]"))
    logger.info("Stage 00 [Ingest] started for: {}", target)

    # 1. Ingest catalogue
    catalogue = ingest_catalogue(target)
    console.print(
        f"[bold green][OK] Ingested catalogue:[/bold green] {catalogue.catalogue_id} | "
        f"[white]{catalogue.total_pages} pages[/white] | "
        f"M.R.P. w.e.f: [bold yellow]{catalogue.price_effective_date}[/bold yellow] | "
        f"SHA-256: [dim]{catalogue.sha256[:16]}...[/dim]"
    )

    # 2. Parse INDEX and derive page offset
    logger.info("Stage 01 [Index] parsing INDEX pages and resolving sections")
    sections_info = parse_index_and_sections(target)

    console.print(f"\n[bold]Empirically Derived Page Offset:[/bold] [bold green]+{sections_info['derived_offset']}[/bold green] (Default: +{sections_info['default_offset']})")
    console.print(f"[bold]Total Sections Parsed:[/bold] {sections_info['total_sections_count']}")
    console.print(f"[bold]Faucet Collections Identified:[/bold] {len(sections_info['faucet_series'])}")

    # Display Series Table
    table = Table(title="Parsed Series & Collections (from INDEX)", show_header=True, header_style="bold magenta")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Series / Section Name", style="cyan")
    table.add_column("Printed Page", justify="right", style="green")
    table.add_column("Resolved PDF Pages", justify="center", style="yellow")

    for i, sec in enumerate(sections_info["sections"], start=1):
        pdf_range = f"p. {sec['pdf_page_start']}-{sec['pdf_page_end']}"
        table.add_row(str(i), sec["name"], str(sec["printed_page"]), pdf_range)

    console.print(table)


@app.command()
def run(
    stages: str = typer.Option(
        "02-06",
        "--stages",
        "-s",
        help="Pipeline stages to run, e.g. '02', '00-02', '02-06'",
    ),
    pages: Optional[str] = typer.Option(
        None,
        "--pages",
        "-p",
        help="Page range to process (e.g. '38-45' for fast dev loop). Default: all pages.",
    ),
    pdf_path: Optional[Path] = typer.Option(
        None,
        "--pdf",
        "-f",
        help="Path to source PDF file. Defaults to data/raw/JAL FAUCETS 2025.pdf",
    ),
) -> None:
    """Execute pipeline stages: segmentation, block extraction, spatial association, and parsing."""
    configure_logging(settings.log_level)
    target = pdf_path or (settings.raw_data_dir / PDF_FILENAME)

    console.print(
        Panel.fit(
            f"[bold green]Running Pipeline[/bold green]\n"
            f"Stages: [bold white]{stages}[/bold white]\n"
            f"Pages: [bold white]{pages or 'ALL (1-202)'}[/bold white]"
        )
    )

    # Resolve sections data
    sections_file = settings.interim_data_dir / "sections.json"
    if not sections_file.exists():
        logger.info("sections.json not found; running index parser first")
        sections_info = parse_index_and_sections(target)
    else:
        import json
        with open(sections_file, "r", encoding="utf-8") as f:
            sections_info = json.load(f)

    # Check if Stage 02 is requested
    requested_stage_02 = "02" in stages or stages in ("all", "00-02", "02-06")
    if requested_stage_02:
        logger.info("Stage 02 [Segment / Classify] executing across catalogue pages")
        all_pages = classify_all_pages(target, sections_info)

        # Parse page filter if provided (e.g. '38-45')
        if pages:
            if "-" in pages:
                p_start, p_end = map(int, pages.split("-"))
                selected_pages = [p for p in all_pages if p_start <= p.page_number <= p_end]
            else:
                p_single = int(pages)
                selected_pages = [p for p in all_pages if p.page_number == p_single]
        else:
            selected_pages = all_pages

        save_pages_parquet(selected_pages)

        # Archetype Summary Table
        import pandas as pd
        df = pd.DataFrame([p.model_dump() for p in selected_pages])

        summary_table = Table(title="Page Archetype Classification Summary", show_header=True, header_style="bold blue")
        summary_table.add_column("Archetype", style="cyan")
        summary_table.add_column("Count", justify="right", style="green")
        summary_table.add_column("Min Conf", justify="right", style="yellow")
        summary_table.add_column("Avg Conf", justify="right", style="white")

        for arch, group in df.groupby("archetype"):
            summary_table.add_row(
                str(arch),
                str(len(group)),
                f"{group['confidence'].min():.2f}",
                f"{group['confidence'].mean():.2f}",
            )

        console.print(summary_table)

        # Print derived offset and series list
        console.print(f"\n[bold]Empirically Derived Page Offset:[/bold] [bold green]+{sections_info['derived_offset']}[/bold green] (Default: +{sections_info['default_offset']})")

        # Full parsed series list
        series_table = Table(title="Parsed Series List (from INDEX)", show_header=True, header_style="bold magenta")
        series_table.add_column("#", justify="right", style="dim", width=4)
        series_table.add_column("Series Name", style="cyan")
        series_table.add_column("Printed Page", justify="right", style="green")
        series_table.add_column("Resolved PDF Pages", justify="center", style="yellow")

        for i, sec in enumerate(sections_info["sections"], start=1):
            pdf_range = f"p. {sec['pdf_page_start']}-{sec['pdf_page_end']}"
            series_table.add_row(str(i), sec["name"], str(sec["printed_page"]), pdf_range)

        console.print(series_table)

        # Low confidence pages (< 0.70)
        low_conf = [p for p in selected_pages if p.confidence < 0.70]
        if low_conf:
            low_table = Table(title="Pages Classified Below 0.70 Confidence", show_header=True, header_style="bold red")
            low_table.add_column("PDF Page", justify="right", style="red")
            low_table.add_column("Archetype", style="cyan")
            low_table.add_column("Confidence", justify="right", style="bold red")
            low_table.add_column("Series Header", style="yellow")
            low_table.add_column("Blocks", justify="right", style="white")
            for p in low_conf:
                low_table.add_row(
                    str(p.page_number),
                    p.archetype,
                    f"{p.confidence:.2f}",
                    str(p.series_header or ""),
                    str(p.blocks_count),
                )
            console.print(low_table)
        else:
            console.print("\n[bold green][OK] Zero pages classified below 0.70 confidence! All pages satisfy threshold.[/bold green]")

    if "03" in stages or "04" in stages or "05" in stages or "06" in stages:
        logger.info("Stub action: Subsequent extraction stages (03-06) scheduled for Phase 2/3.")


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

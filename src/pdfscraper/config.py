"""config.py - Configuration management using pydantic-settings.

All paths are resolved from the project root using pathlib.Path.
No string path concatenation or forward-slash path assumptions are made.
Settings read from environment variables or .env file with sensible defaults.
"""

from pathlib import Path
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve project root from this file location: src/pdfscraper/config.py -> 0-PDF Scraper
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Global configuration settings for the catalogue intelligence pipeline."""

    model_config = SettingsConfigDict(
        env_prefix="PDFSCRAPER_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base Paths (resolved via pathlib.Path)
    root_dir: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    interim_data_dir: Path = PROJECT_ROOT / "data" / "interim"
    processed_data_dir: Path = PROJECT_ROOT / "data" / "processed"
    assets_dir: Path = PROJECT_ROOT / "data" / "assets"
    db_dir: Path = PROJECT_ROOT / "data" / "db"
    vectors_dir: Path = PROJECT_ROOT / "data" / "vectors"

    # Database & Storage
    sqlite_db_path: Path = PROJECT_ROOT / "data" / "db" / "catalogue.sqlite"
    lancedb_dir: Path = PROJECT_ROOT / "data" / "vectors" / "lancedb"

    # Evaluation & Prompts Paths
    eval_golden_dir: Path = PROJECT_ROOT / "src" / "pdfscraper" / "eval" / "golden"
    prompts_dir: Path = PROJECT_ROOT / "src" / "pdfscraper" / "enrich" / "prompts"

    # Thresholds & Extraction Parameters
    confidence_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score required before flagging entity for human review",
    )
    min_image_area_px: int = Field(
        default=5000,
        ge=100,
        description="Minimum pixel area to filter out decorative icons and bullets",
    )
    max_image_area_ratio: float = Field(
        default=0.85,
        ge=0.1,
        le=1.0,
        description="Maximum bounding-box area ratio to filter out full-page backgrounds",
    )

    # Runtime Execution Settings
    batch_size: int = Field(default=10, ge=1, description="Batch size for pipeline processing")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level for loguru",
    )

    # Model Registry (Used exclusively in enrichment stages 07+)
    normalizer_model: str = Field(
        default="gemini-2.0-flash",
        description="Model ID for attribute normalization and structured taxonomy extraction",
    )
    enrichment_llm_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="LLM for search blurb generation and recommendations",
    )
    text_embed_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model for product textual representations",
    )
    image_embed_model: str = Field(
        default="clip-ViT-B-32",
        description="Vision model for visual asset embeddings",
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        description="Cross-encoder reranker for hybrid retrieval refinement",
    )

    # Optional API Keys (Never hardcoded; loaded from .env)
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")


settings = Settings()

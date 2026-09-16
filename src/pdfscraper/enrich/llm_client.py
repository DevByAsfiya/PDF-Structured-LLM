"""llm_client.py - Centralized LLM client for enrichment stages.

Uses Groq via its OpenAI-compatible endpoint. All LLM calls go through
this module: retry with tenacity, disk-cached with diskcache keyed on
(model, prompt_hash), token and cost logged per call. Structured JSON
output validated against a pydantic model.

Hard rules (AGENTS.md):
- Never use an LLM to extract SKU codes, prices, or image-to-text bindings.
- LLMs are allowed only for: attribute normalisation, taxonomy assignment,
  search-blurb writing, natural-language query parsing, and recommendation
  rationale.
- Never let an LLM compute a statistic.
- Prompts live in enrich/prompts/*.jinja as versioned files — never inline.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional, Type, TypeVar

import diskcache
import jinja2
from loguru import logger
from openai import OpenAI
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pdfscraper.config import settings

T = TypeVar("T", bound=BaseModel)

# Prompt template loader
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_PROMPTS_DIR)),
    autoescape=False,
    undefined=jinja2.StrictUndefined,
)

# Disk cache for LLM responses
_CACHE_DIR = settings.data_dir / "cache" / "llm"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_cache = diskcache.Cache(str(_CACHE_DIR))

# Approximate cost per million tokens (Groq pricing as of 2025)
_COST_PER_M_INPUT = {
    "llama-3.3-70b-versatile": 0.59,
    "llama-3.1-8b-instant": 0.05,
    "gemma2-9b-it": 0.20,
}
_COST_PER_M_OUTPUT = {
    "llama-3.3-70b-versatile": 0.79,
    "llama-3.1-8b-instant": 0.08,
    "gemma2-9b-it": 0.20,
}


def render_prompt(template_name: str, **kwargs: Any) -> str:
    """Render a Jinja2 prompt template from enrich/prompts/.

    Args:
        template_name: Filename of the .jinja template.
        **kwargs: Template variables.

    Returns:
        Rendered prompt string.
    """
    template = _jinja_env.get_template(template_name)
    return template.render(**kwargs)


def _cache_key(model: str, prompt: str) -> str:
    """Compute a deterministic cache key from model + prompt content."""
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return f"{model}:{prompt_hash}"


@retry(
    retry=retry_if_exception_type((Exception,)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=lambda retry_state: logger.warning(
        "LLM call attempt {} failed, retrying in {}s...",
        retry_state.attempt_number,
        retry_state.next_action.sleep,
    ),
)
def _call_llm(
    client: OpenAI,
    model: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
) -> dict:
    """Make a raw LLM call with retry. Returns the parsed JSON response."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    choice = response.choices[0]
    content = choice.message.content

    # Log token usage and estimated cost
    usage = response.usage
    if usage:
        input_cost = (usage.prompt_tokens / 1_000_000) * _COST_PER_M_INPUT.get(model, 0.59)
        output_cost = (usage.completion_tokens / 1_000_000) * _COST_PER_M_OUTPUT.get(model, 0.79)
        total_cost = input_cost + output_cost
        logger.info(
            "LLM call: model={} | input_tokens={} | output_tokens={} | cost=${:.6f}",
            model,
            usage.prompt_tokens,
            usage.completion_tokens,
            total_cost,
        )

    return json.loads(content)


def call_llm_structured(
    prompt: str,
    response_model: Type[T],
    *,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.0,
    use_cache: bool = True,
) -> T:
    """Call the LLM and validate the response against a pydantic model.

    Args:
        prompt: The user prompt (rendered from a .jinja template).
        response_model: Pydantic model class to validate the response.
        model: Model ID. Defaults to settings.enrichment_llm_model.
        system_prompt: Optional system prompt.
        temperature: Sampling temperature.
        use_cache: Whether to use disk cache.

    Returns:
        Validated pydantic model instance.
    """
    model = model or settings.enrichment_llm_model

    # Check cache
    key = _cache_key(model, prompt)
    if use_cache and key in _cache:
        logger.debug("Cache hit for LLM call: model={}", model)
        cached = _cache[key]
        return response_model.model_validate(cached)

    # Build client
    api_key = settings.groq_api_key
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to .env or set the environment variable."
        )

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    # Call LLM
    raw_response = _call_llm(
        client=client,
        model=model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
    )

    # Validate against pydantic model
    result = response_model.model_validate(raw_response)

    # Cache the raw response
    if use_cache:
        _cache[key] = raw_response

    return result

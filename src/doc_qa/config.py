"""Runtime configuration loaded from environment variables / .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the repo root so MCP launches with arbitrary cwd still find the file.
# config.py is at <repo>/src/doc_qa/config.py, so parents[2] is <repo>.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    # ----- Anthropic -----
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    answer_model: str = Field(default="claude-sonnet-4-6", alias="ANSWER_MODEL")
    judge_model: str = Field(default="claude-haiku-4-5", alias="JUDGE_MODEL")
    # Extra models a /ask client may request, comma-separated. ANSWER_MODEL is
    # always allowed; anything else is refused so a caller cannot pick the
    # most expensive model on the operator's key.
    allowed_models: str = Field(default="", alias="ALLOWED_MODELS")

    # ----- Embeddings -----
    voyage_api_key: str = Field(default="", alias="VOYAGE_API_KEY")
    voyage_model: str = Field(default="voyage-3-large", alias="VOYAGE_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_embed_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBED_MODEL")
    openai_embed_dimensions: int = Field(default=1024, alias="OPENAI_EMBED_DIMENSIONS")
    embedding_dim: int = Field(default=1024, alias="EMBEDDING_DIM")
    # Explicit override. Set to "voyage" or "openai" to force a provider when
    # both keys are present. Empty means: auto-detect (prefer voyage).
    embedding_provider_override: str = Field(default="", alias="EMBEDDING_PROVIDER")

    # ----- Database -----
    database_url: str = Field(
        default="postgresql://docqa:docqa@localhost:5432/docqa",
        alias="DATABASE_URL",
    )

    # ----- Crawl -----
    crawl_base_url: str = Field(default="https://docs.anthropic.com", alias="CRAWL_BASE_URL")
    crawl_sitemap_url: str = Field(
        default="https://docs.anthropic.com/sitemap.xml",
        alias="CRAWL_SITEMAP_URL",
    )
    crawl_max_pages: int = Field(default=120, alias="CRAWL_MAX_PAGES")
    crawl_path_allow: str = Field(
        default="/docs/en/",
        alias="CRAWL_PATH_ALLOW",
    )
    # Deny list excludes /docs/en/api/ entirely. These are endpoint reference
    # and SDK reference pages: auto-generated, low signal for natural-language
    # Q&A, and they outrank conceptual docs on keyword overlap when both are
    # in the corpus. Conceptual API guidance lives at /docs/en/build-with-claude/.
    crawl_path_deny: str = Field(
        default="/docs/en/api/",
        alias="CRAWL_PATH_DENY",
    )

    # ----- API -----
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # ----- Retrieval -----
    retrieve_candidates: int = Field(default=20, alias="RETRIEVE_CANDIDATES")
    retrieve_final_k: int = Field(default=5, alias="RETRIEVE_FINAL_K")

    @property
    def embedding_provider(self) -> str:
        override = self.embedding_provider_override.strip().lower()
        if override in {"voyage", "openai"}:
            return override
        if self.voyage_api_key:
            return "voyage"
        if self.openai_api_key:
            return "openai"
        return "none"

    @property
    def allowed_model_ids(self) -> set[str]:
        extra = {m.strip() for m in self.allowed_models.split(",") if m.strip()}
        return {self.answer_model} | extra

    @property
    def path_allow_prefixes(self) -> list[str]:
        return [p.strip() for p in self.crawl_path_allow.split(",") if p.strip()]

    @property
    def path_deny_prefixes(self) -> list[str]:
        return [p.strip() for p in self.crawl_path_deny.split(",") if p.strip()]


settings = Settings()

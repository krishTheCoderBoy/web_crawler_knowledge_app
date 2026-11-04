from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


class ModelInfo:
    def __init__(self, provider: str, model_id: str, label: str, multimodal: bool = False):
        self.provider = provider
        self.model_id = model_id
        self.label = label
        self.multimodal = multimodal

    def dict(self):
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "label": self.label,
            "multimodal": self.multimodal,
        }


AVAILABLE_MODELS: List[ModelInfo] = [
    ModelInfo("openrouter", "openrouter/free", "Auto (any available free model)"),
    ModelInfo("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra 550B (NVIDIA)"),
    ModelInfo("openrouter", "poolside/laguna-s-2.1:free", "Laguna S 2.1 (Poolside)"),
    ModelInfo("openrouter", "dots-studio/dots-3-note-preview:free", "Dots 3 Note Preview (Dots Studio)"),
]

DEFAULT_MODEL = next(m for m in AVAILABLE_MODELS if m.model_id == "openrouter/free")

# If the primary LLM_MODEL call fails, these are tried in order as fallbacks.
LLM_FALLBACK_MODELS: List[str] = [
    "openrouter/free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "poolside/laguna-s-2.1:free",
    "dots-studio/dots-3-note-preview:free",
]

MODEL_ID_ALIASES = {
    "gpt-oss-120b": "openrouter/free",
    "openai/gpt-oss-120b:free": "openrouter/free",
    "llama-3.3-70b": "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free": "openrouter/free",
    "deepseek-r1": "openrouter/free",
    "deepseek/deepseek-r1-0528:free": "openrouter/free",
    "qwen3-235b": "openrouter/free",
    "qwen/qwen3-235b-a22b:free": "openrouter/free",
    "glm-4.5-air": "openrouter/free",
    "z-ai/glm-4.5-air:free": "openrouter/free",
    "gemma-3-27b": "openrouter/free",
    "google/gemma-3-27b-it:free": "openrouter/free",
    "nvidia/nemotron-3-super-120b-a12b:free": "openrouter/free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "openrouter/free",
    "moonshotai/kimi-k2:free": "openrouter/free",
    "mistralai/mistral-7b-instruct:free": "openrouter/free",
    "microsoft/phi-4:free": "openrouter/free",
    "liquid/lfm-2.5-1.2b-thinking:free": "openrouter/free",
    "thinkingmachines/inkling:free": "openrouter/free",
    "minimax/minimax-m2.7:free": "openrouter/free",
}


class Settings(BaseSettings):
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    DATABASE_URL: str = "sqlite:///./rag_app.db"
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    UPLOAD_DIR: str = "./uploads"

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_SITE_URL: str = "http://localhost:3000"
    OPENROUTER_APP_NAME: str = "web-crawler-rag"

    FIRECRAWL_API_KEY: str = ""

    LLM_PROVIDER: str = DEFAULT_MODEL.provider
    LLM_MODEL: str = DEFAULT_MODEL.model_id
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 900

    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_REDIRECT_URI: str = "http://localhost:8000/auth/github/callback"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"

    FRONTEND_URL: str = "http://localhost:3000"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


def model_chain(requested: str | None) -> List[str]:
    """Try the selected model, then OpenRouter's free-model router if it fails."""
    if requested:
        selected = MODEL_ID_ALIASES.get(requested, requested)
        if selected == "openrouter/free":
            return [selected]
        return [selected, "openrouter/free"]

    primary = settings.LLM_MODEL
    chain = [primary]
    for m in LLM_FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain

Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

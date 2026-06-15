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
    ModelInfo("openrouter", "meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B Instruct (Meta)", multimodal=False),
    ModelInfo("openrouter", "openai/gpt-oss-120b:free", "GPT OSS 120B (OpenAI)", multimodal=False),
    ModelInfo("openrouter", "deepseek/deepseek-r1-0528:free", "DeepSeek R1 0528", multimodal=False),
    ModelInfo("openrouter", "qwen/qwen3-235b-a22b:free", "Qwen3 235B A22B (Alibaba)", multimodal=False),
    ModelInfo("openrouter", "nvidia/nemotron-3-super-120b-a12b:free", "Nemotron 3 Super 120B (NVIDIA)", multimodal=False),
    ModelInfo("openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "Nemotron 3 Nano Omni 30B (NVIDIA)", multimodal=True),
    ModelInfo("openrouter", "google/gemma-3-27b-it:free", "Gemma 3 27B IT (Google)", multimodal=True),
    ModelInfo("openrouter", "moonshotai/kimi-k2:free", "Kimi K2 (Moonshot AI)", multimodal=False),
    ModelInfo("openrouter", "mistralai/mistral-7b-instruct:free", "Mistral 7B Instruct", multimodal=False),
    ModelInfo("openrouter", "microsoft/phi-4:free", "Phi-4 (Microsoft)", multimodal=False),
    ModelInfo("openrouter", "liquid/lfm-2.5-1.2b-thinking:free", "LFM 2.5 1.2B Thinking (Liquid)", multimodal=False),
    ModelInfo("openrouter", "z-ai/glm-4.5-air:free", "GLM-4.5 Air (Z-AI)", multimodal=False),
]

DEFAULT_MODEL = AVAILABLE_MODELS[0]


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

    LLM_PROVIDER: str = DEFAULT_MODEL.provider
    LLM_MODEL: str = DEFAULT_MODEL.model_id
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 900

    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

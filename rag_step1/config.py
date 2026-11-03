"""Runtime configuration; company and reporting years belong to the upload manifest."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"
REVIEW_DIR = DATA_DIR / "validation" / "prompt1"
INDEX_ROOT = DATA_DIR / "rag_indexes"
MODELS_DIR = DATA_DIR / "models"
load_dotenv(ROOT / ".env")

# A new key prevents the legacy English-only model disabling Chinese retrieval.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_MODEL = os.getenv("AIF_EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
CHUNK_SIZE = 128
CHUNK_OVERLAP = 24

class ConfigError(RuntimeError):
    pass

def deepseek_api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise ConfigError("缺少 DEEPSEEK_API_KEY；离线检索和测试不需要密钥，在线 Agent 问答需要。")
    return key

def local_embedding_dir() -> Path | None:
    configured = Path(EMBEDDING_MODEL)
    if configured.is_dir():
        return configured
    vendored = MODELS_DIR / EMBEDDING_MODEL.split("/")[-1]
    return vendored if (vendored / "config.json").is_file() else None

def resolve_embedding_model() -> str:
    local = local_embedding_dir()
    return str(local) if local else EMBEDDING_MODEL

def create_llm():
    from llama_index.llms.deepseek import DeepSeek
    llm = DeepSeek(model=DEEPSEEK_MODEL, api_key=deepseek_api_key(),
                   api_base=DEEPSEEK_BASE_URL, temperature=0, timeout=90, max_retries=1)
    if not llm.metadata.is_function_calling_model:
        raise ConfigError("配置的 LLM 不声明支持 FunctionAgent 工具调用。")
    return llm

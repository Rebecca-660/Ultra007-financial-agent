"""Prepare an embedding model from its official repository, not financial data."""
from __future__ import annotations
import sys
import os
from pathlib import Path
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from huggingface_hub import snapshot_download
from rag_step1.config import EMBEDDING_MODEL, MODELS_DIR
os.environ.setdefault("HF_XET_CACHE", str(MODELS_DIR / ".xet_cache"))

def main():
    if Path(EMBEDDING_MODEL).is_dir():
        print("Configured local model already exists.")
        return
    target = MODELS_DIR / EMBEDDING_MODEL.split("/")[-1]
    snapshot_download(repo_id=EMBEDDING_MODEL, endpoint="https://huggingface.co",
                      local_dir=str(target), cache_dir=str(MODELS_DIR / ".hf_cache"),
                      allow_patterns=["*.json", "*.txt", "*.safetensors", "*.model"],
                      ignore_patterns=["onnx/*", "openvino/*"], max_workers=2)
    print(f"Embedding model ready: {target}")

if __name__ == "__main__":
    main()

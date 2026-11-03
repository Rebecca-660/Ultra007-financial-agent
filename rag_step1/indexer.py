"""Page-preserving LlamaIndex storage scoped to one immutable report set.

Each build writes a new generation. Switching the small ``current.json`` pointer
never deletes an earlier index or an uploaded report.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, report
from .report import ReportSet, extract_source

PROJECT_ID = "aif_report_evidence_v1"
INDEX_DIR = config.INDEX_ROOT
_EMBEDDINGS: dict[str, Any] = {}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _local_model_path() -> Path:
    model = config.resolve_embedding_model()
    path = Path(model)
    if path.is_dir():
        return path.resolve()
    # Only already downloaded snapshots may identify reproducible models.
    try:
        from huggingface_hub import snapshot_download
        return Path(snapshot_download(repo_id=model, local_files_only=True)).resolve()
    except Exception as exc:
        raise config.ConfigError(
            f"Embedding model {model!r} is not available locally. Prepare the model "
            "or set AIF_EMBEDDING_MODEL to its local directory. --offline uses a "
            "lexical test embedding and cannot validate multilingual retrieval."
        ) from exc


def embedding_profile(*, offline: bool = False) -> dict:
    if offline:
        return {"kind": "offline_lexical_test_only",
                "model_name": "deterministic_lexical_sha256_v1",
                "model_hash": _digest({"algorithm": "word_hash_v1", "dimensions": 1024}),
                "multilingual_validation": False}
    path = _local_model_path()
    inventory = []
    for item in sorted(path.rglob("*")):
        if item.is_file() and not any(part.startswith(".") for part in item.relative_to(path).parts):
            inventory.append({"name": item.relative_to(path).as_posix(),
                              "sha256": _file_hash(item), "size": item.stat().st_size})
    if not inventory or not (path / "config.json").is_file():
        raise config.ConfigError(f"Embedding model directory is incomplete: {path}")
    return {"kind": "huggingface_local", "model_name": config.EMBEDDING_MODEL,
            "model_hash": _digest(inventory), "model_files": inventory,
            "local_path": str(path), "multilingual_validation": True}


def _embedding(profile: dict):
    key = profile["model_hash"]
    if key in _EMBEDDINGS:
        return _EMBEDDINGS[key]
    if profile["kind"] == "offline_lexical_test_only":
        from llama_index.core.embeddings import BaseEmbedding

        class LexicalTestEmbedding(BaseEmbedding):
            """Deterministic word hashing; deliberately no multilingual claims."""

            def _encode(self, text: str) -> list[float]:
                import math
                vector = [0.0] * 1024
                for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()):
                    digest = hashlib.sha256(token.encode("utf-8")).digest()
                    vector[int.from_bytes(digest[:4], "big") % 1024] += 1.0
                norm = math.sqrt(sum(value * value for value in vector)) or 1.0
                return [value / norm for value in vector]

            def _get_query_embedding(self, query: str) -> list[float]:
                return self._encode(query)

            async def _aget_query_embedding(self, query: str) -> list[float]:
                return self._encode(query)

            def _get_text_embedding(self, text: str) -> list[float]:
                return self._encode(text)

        model = LexicalTestEmbedding(model_name=profile["model_name"])
    else:
        import torch
        torch.set_num_threads(int(os.getenv("AIF_TORCH_THREADS", "4")))
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        model = HuggingFaceEmbedding(model_name=profile["local_path"], device="cpu",
                                    embed_batch_size=8, trust_remote_code=False,
                                    local_files_only=True)
    _EMBEDDINGS[key] = model
    return model


def configure_embedding(*, offline: bool = False):
    """Return an explicit model; do not mutate global LlamaIndex Settings."""
    return _embedding(embedding_profile(offline=offline))


def expected_manifest(report_set: ReportSet, *, offline: bool = False) -> dict:
    if not report_set.sources:
        raise ValueError("A report set must contain at least one uploaded report.")
    sources = []
    for source in report_set.sources:
        actual_hash = _file_hash(source.pdf_path)
        if actual_hash != source.file_hash:
            raise RuntimeError("An uploaded source changed after its report set was created. Confirm a new report set.")
        sources.append({"file_name": source.file_name, "file_hash": actual_hash,
                        "report_year": source.report_year,
                        "verified_printed_pages": list(source.verified_printed_pages)})
    if len({source["file_name"] for source in sources}) != len(sources):
        raise ValueError("Uploaded report file names must be unique within a report set.")
    profile = embedding_profile(offline=offline)
    identity_profile = {key: value for key, value in profile.items() if key != "local_path"}
    packages = ["PyMuPDF", "llama-index-core"]
    if not offline:
        packages.append("sentence-transformers")
    dependencies = {name: importlib.metadata.version(name) for name in packages}
    inputs = {"project_id": PROJECT_ID, "company_id": report_set.company_id,
              "report_set_id": report_set.report_set_id,
              "sources": sources, "embedding": identity_profile,
              "chunk_size_tokens": config.CHUNK_SIZE,
              "chunk_overlap_tokens": config.CHUNK_OVERLAP, "page_preserving": True,
              "chunk_tokenizer": "llamaindex_default" if offline else "embedding_model_with_special_tokens",
              "parser_version": report.PARSER_VERSION, "dependencies": dependencies}
    return {**inputs, "fingerprint": _digest(inputs), "embedding": profile}


def _index_dir(report_set: ReportSet, index_dir: Path | None) -> Path:
    return Path(index_dir) if index_dir is not None else config.INDEX_ROOT / report_set.report_set_id


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Missing or invalid index metadata: {path}") from exc


def _owner(report_set: ReportSet) -> dict:
    return {"project_id": PROJECT_ID, "company_id": report_set.company_id,
            "report_set_id": report_set.report_set_id}


def _check_owner(report_set: ReportSet, base: Path, *, create: bool = False) -> None:
    marker = base / "project.json"
    if not base.exists():
        if not create:
            raise RuntimeError("No index exists for this report set. Run the index command first.")
        base.mkdir(parents=True, exist_ok=False)
        marker.write_text(json.dumps(_owner(report_set), indent=2) + "\n", encoding="utf-8")
    elif not marker.is_file():
        raise RuntimeError("Index directory has no AIF ownership marker; use a new --index-dir.")
    if _read_json(marker) != _owner(report_set):
        raise RuntimeError("Index directory belongs to another company or report set; use a separate directory.")


def _current_generation(base: Path) -> Path:
    pointer = _read_json(base / "current.json")
    name = pointer.get("generation", "")
    if not isinstance(name, str) or not re.fullmatch(r"[a-f0-9]{64}-[a-f0-9]{32}", name):
        raise RuntimeError("Invalid index generation pointer.")
    target = (base / "generations" / name).resolve()
    allowed = (base / "generations").resolve()
    if not target.is_relative_to(allowed) or not target.is_dir():
        raise RuntimeError("Index generation is missing or outside its owned directory.")
    return target


def _trusted_generation(report_set: ReportSet, base: Path) -> tuple[Path, dict]:
    """Check ownership and every persisted payload before loading any cache."""
    _check_owner(report_set, base)
    generation = _current_generation(base)
    manifest = _read_json(generation / "manifest.json")
    if any(manifest.get(key) != value for key, value in _owner(report_set).items()):
        raise RuntimeError("Persisted index manifest belongs to another company or report set.")
    hashes = manifest.get("storage_hashes", {})
    required = {"docstore.json", "index_store.json", "default__vector_store.json"}
    if not isinstance(hashes, dict) or not required.issubset(hashes):
        raise RuntimeError("Persisted index is incomplete; rebuild it.")
    for name, digest in hashes.items():
        path = generation / name
        if Path(name).name != name or not path.is_file() or _file_hash(path) != digest:
            raise RuntimeError(f"Persisted index is missing or corrupted: {name}; rebuild it.")
    return generation, manifest


def _verify_generation(report_set: ReportSet, base: Path, expected: dict) -> tuple[Path, dict]:
    generation, manifest = _trusted_generation(report_set, base)
    if manifest.get("fingerprint") != expected["fingerprint"]:
        raise RuntimeError("Index is stale: reports, embedding model, parser or chunk configuration changed. Rebuild it.")
    return generation, manifest


def _cached_embeddings(report_set: ReportSet, base: Path, expected: dict) -> dict[str, list[float]]:
    """Reuse only exact raw text and a verified, identical model snapshot.

    Parser metadata may change without changing embedding input. A corrupt or
    foreign generation contributes no vectors. Old metadata never enters new
    nodes, and no vector is keyed by normalized/translated text or by page ID.
    """
    if not (base / "current.json").is_file():
        return {}
    try:
        generation, previous = _trusted_generation(report_set, base)
        if previous.get("embedding", {}).get("model_hash") != expected["embedding"]["model_hash"]:
            return {}
        old_inference_version = previous.get("dependencies", {}).get("sentence-transformers")
        if old_inference_version and old_inference_version != expected["dependencies"].get("sentence-transformers"):
            return {}
        from llama_index.core.storage.docstore import SimpleDocumentStore
        from llama_index.core.vector_stores import SimpleVectorStore
        from llama_index.core.schema import MetadataMode

        docstore = SimpleDocumentStore.from_persist_dir(str(generation))
        vector_store = SimpleVectorStore.from_persist_dir(str(generation))
        cache = {}
        dimension = None
        for node_id, node in docstore.docs.items():
            text = node.get_content(metadata_mode=MetadataMode.NONE)
            if not set(node.metadata).issubset(node.excluded_embed_metadata_keys):
                continue
            if node.get_content(metadata_mode=MetadataMode.EMBED) != text:
                continue
            if node.metadata.get("company_id") != report_set.company_id or node.metadata.get("report_set_id") != report_set.report_set_id:
                continue
            vector = vector_store.data.embedding_dict.get(node_id)
            if not isinstance(vector, list) or not vector:
                continue
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                   not math.isfinite(value) for value in vector):
                return {}
            dimension = dimension or len(vector)
            if len(vector) != dimension:
                return {}
            cache[text] = vector
        return cache
    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
        # Cache is an optimization, never a reason to trust damaged storage.
        return {}


def build_index(report_set: ReportSet, index_dir: Path | None = None, *,
                force: bool = False, offline: bool = False) -> dict:
    from llama_index.core import VectorStoreIndex
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.schema import TextNode

    base = _index_dir(report_set, index_dir)
    expected = expected_manifest(report_set, offline=offline)
    _check_owner(report_set, base, create=True)
    if not force and (base / "current.json").exists():
        try:
            generation, manifest = _verify_generation(report_set, base, expected)
            return {**manifest, "status": "already_built", "index_dir": str(base),
                    "generation_dir": str(generation)}
        except RuntimeError:
            pass  # A fresh immutable generation safely replaces a stale pointer.

    embedding = _embedding(expected["embedding"])
    tokenizer = None
    if not offline:
        if config.CHUNK_SIZE > embedding.max_length:
            raise config.ConfigError("CHUNK_SIZE exceeds the embedding model's maximum input length.")
        tokenizer = lambda text: embedding._model.tokenizer.encode(
            text, add_special_tokens=True, truncation=False, verbose=False)
    splitter = SentenceSplitter(chunk_size=config.CHUNK_SIZE,
                                chunk_overlap=config.CHUNK_OVERLAP, tokenizer=tokenizer)
    embedding_cache = _cached_embeddings(report_set, base, expected)
    nodes = []
    reused_embeddings = 0
    indexed_pages = 0
    warning_pages = []
    for source in report_set.sources:
        file_hash = _file_hash(source.pdf_path)
        for page in extract_source(source):
            warnings = list(page.parsing_warnings)
            if warnings:
                warning_pages.append({"file_name": source.file_name, "pdf_page": page.pdf_page,
                                      "warnings": warnings})
            if not page.text.strip():
                continue
            indexed_pages += 1
            metadata = {"company_id": report_set.company_id, "report_set_id": report_set.report_set_id,
                        "file_name": source.file_name, "file_hash": file_hash,
                        "report_year": source.report_year, "pdf_page": page.pdf_page,
                        "printed_page": page.printed_page, "parsing_warnings": warnings}
            for part, text in enumerate(splitter.split_text(page.text)):
                if tokenizer is not None and len(tokenizer(text)) > embedding.max_length:
                    raise config.ConfigError("A page chunk exceeds the embedding model input limit; reduce CHUNK_SIZE.")
                node_id = _digest({"metadata": metadata, "part": part, "text": text})
                cached = embedding_cache.get(text)
                if cached is not None:
                    reused_embeddings += 1
                nodes.append(TextNode(id_=node_id, text=text, metadata=metadata, embedding=cached,
                                      excluded_embed_metadata_keys=list(metadata),
                                      excluded_llm_metadata_keys=list(metadata)))
    if not nodes:
        raise ValueError("Uploaded reports contain no extractable text. OCR scanned PDFs before indexing.")
    index = VectorStoreIndex(nodes, embed_model=embedding, show_progress=not offline)
    if expected_manifest(report_set, offline=offline)["fingerprint"] != expected["fingerprint"]:
        raise RuntimeError("A report or model changed during indexing. Retry with stable source files.")
    generations = base / "generations"
    generations.mkdir(exist_ok=True)
    name = expected["fingerprint"] + "-" + uuid.uuid4().hex
    staging = generations / (".building-" + uuid.uuid4().hex)
    staging.mkdir()
    index.storage_context.persist(persist_dir=str(staging))
    storage_hashes = {path.name: _file_hash(path) for path in sorted(staging.iterdir()) if path.is_file()}
    manifest = {**expected, "indexed_pages": indexed_pages, "indexed_chunks": len(nodes),
                "reused_embeddings": reused_embeddings,
                "new_embeddings": len(nodes) - reused_embeddings,
                "warning_pages": warning_pages, "storage_hashes": storage_hashes,
                "created_at_utc": datetime.now(timezone.utc).isoformat()}
    (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    generation = generations / name
    staging.rename(generation)
    pointer_tmp = base / (".current-" + uuid.uuid4().hex + ".json")
    pointer_tmp.write_text(json.dumps({"generation": name}) + "\n", encoding="utf-8")
    os.replace(pointer_tmp, base / "current.json")
    return {**manifest, "status": "built", "index_dir": str(base), "generation_dir": str(generation)}


def load_index(report_set: ReportSet, index_dir: Path | None = None, *, offline: bool = False):
    from llama_index.core import StorageContext, load_index_from_storage

    expected = expected_manifest(report_set, offline=offline)
    generation, _ = _verify_generation(report_set, _index_dir(report_set, index_dir), expected)
    storage = StorageContext.from_defaults(persist_dir=str(generation))
    return load_index_from_storage(storage, embed_model=_embedding(expected["embedding"]))

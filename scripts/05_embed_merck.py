"""Embed Merck RAG chunks and build a searchable local vector store."""

import json
import logging
import math
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path: Optional[str] = None) -> None:
    env_path = path or os.path.join(PROJECT_ROOT, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as env_file:
            for raw in env_file:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logger.warning("Could not read .env: %s", exc)


_load_dotenv()


class BaseEmbedder(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> np.ndarray:
        raise NotImplementedError


class TfidfEmbedder(BaseEmbedder):
    """Lightweight local embedder using TF-IDF (no external API/model required)."""

    def __init__(self) -> None:
        self.vocabulary: Dict[str, int] = {}
        self.idf: Optional[np.ndarray] = None

    @property
    def name(self) -> str:
        return "tfidf_local"

    @property
    def dimension(self) -> int:
        return len(self.vocabulary)

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return TOKEN_PATTERN.findall(text.lower())

    def _build_vocabulary(self, texts: List[str]) -> None:
        tokens_seen: Dict[str, None] = {}
        for text in texts:
            for token in self._tokenize(text):
                tokens_seen[token] = None
        self.vocabulary = {token: idx for idx, token in enumerate(sorted(tokens_seen))}

    def _compute_tfidf_matrix(self, texts: List[str]) -> np.ndarray:
        doc_count = len(texts)
        vocab_size = len(self.vocabulary)
        tf = np.zeros((doc_count, vocab_size), dtype=np.float32)
        df = np.zeros(vocab_size, dtype=np.float32)

        fit_mode = self.idf is None
        for doc_index, text in enumerate(texts):
            counts: Dict[str, int] = {}
            for token in self._tokenize(text):
                if not fit_mode and token not in self.vocabulary:
                    continue
                counts[token] = counts.get(token, 0) + 1
            for token, count in counts.items():
                token_index = self.vocabulary[token]
                tf[doc_index, token_index] = count
                if fit_mode:
                    df[token_index] += 1.0

        tf = np.log1p(tf)
        if fit_mode:
            self.idf = np.log((doc_count + 1) / (df + 1)) + 1.0
        vectors = tf * self.idf
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def fit_transform(self, texts: List[str]) -> np.ndarray:
        self._build_vocabulary(texts)
        return self._compute_tfidf_matrix(texts)

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if not self.vocabulary or self.idf is None:
            raise RuntimeError("TfidfEmbedder must be fit before embedding new texts")
        return self._compute_tfidf_matrix(texts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vocabulary": self.vocabulary,
            "idf": self.idf.tolist() if self.idf is not None else [],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TfidfEmbedder":
        embedder = cls()
        embedder.vocabulary = data.get("vocabulary", {})
        idf_list = data.get("idf", [])
        embedder.idf = np.array(idf_list, dtype=np.float32) if idf_list else None
        return embedder


class SentenceTransformerEmbedder(BaseEmbedder):
    """Optional semantic embedder if sentence-transformers is installed."""

    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        batch_size: int = 64,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "Install sentence-transformers for semantic embeddings: "
                "pip install sentence-transformers"
            ) from exc
        self.model_name = model_name
        self.batch_size = batch_size
        logger.info("Loading sentence-transformers model: %s", model_name)
        # Prefer local cache to avoid HuggingFace network calls at API startup.
        # When offline flags are set, fail fast instead of hanging on proxy/download.
        offline = any(
            (os.getenv(k) or "").strip().lower() in {"1", "true", "yes"}
            for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "ANIMA_EMBED_OFFLINE")
        )
        if offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            # local_files_only can still trip transformers hub probes; fall back
            # to a normal load while HF offline env is set (uses cache only).
            self.model = SentenceTransformer(model_name, local_files_only=True)
        except Exception as local_exc:
            if offline:
                try:
                    self.model = SentenceTransformer(model_name)
                except Exception as offline_exc:
                    raise RuntimeError(
                        f"Sentence-transformers model {model_name!r} not in local cache "
                        f"and offline mode is enabled (HF_HUB_OFFLINE / "
                        f"TRANSFORMERS_OFFLINE / ANIMA_EMBED_OFFLINE). "
                        f"Warm the HF cache once online, or set MERCK_EMBEDDER=tfidf."
                    ) from offline_exc
            else:
                logger.info("Local cache miss for %s — downloading", model_name)
                self.model = SentenceTransformer(model_name)
        sample = self.model.encode(["warmup"], normalize_embeddings=True)
        self._dimension = int(sample.shape[1])

    @property
    def name(self) -> str:
        return f"sentence_transformers:{self.model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        # Batched encode keeps memory stable for ~10k chunks.
        show_bar = len(texts) >= 200
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=show_bar,
            convert_to_numpy=True,
        )
        return np.asarray(vectors, dtype=np.float32)


def resolve_vector_store_dir(project_root: Optional[str] = None) -> str:
    """Prefer merged A+B+C store when present; override with ANIMA_VECTOR_STORE_DIR."""
    root = project_root or PROJECT_ROOT
    env = (os.getenv("ANIMA_VECTOR_STORE_DIR") or "").strip()
    if env:
        return env if os.path.isabs(env) else os.path.join(root, env)
    merged = os.path.join(root, "data", "processed", "merged_vector_store")
    if os.path.isfile(os.path.join(merged, "manifest.json")):
        return merged
    return os.path.join(root, "data", "processed", "merck_vector_store")


def supabase_credentials() -> Tuple[str, str]:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return url, key


def resolve_retrieval_mode(explicit: Optional[str] = None) -> str:
    """local | supabase | auto (RPC when keys exist, else local numpy)."""
    raw = (explicit or os.getenv("ANIMA_RETRIEVAL") or "auto").strip().lower()
    aliases = {"rpc": "supabase", "cloud": "supabase", "pgvector": "supabase"}
    raw = aliases.get(raw, raw)
    if raw not in {"local", "supabase", "auto"}:
        raise ValueError(
            f"ANIMA_RETRIEVAL={raw!r} invalid; use local, supabase, or auto"
        )
    return raw


class MerckVectorStore:
    """Build, persist, and query a Merck chunk vector index."""

    def __init__(
        self,
        chunks_path: Optional[str] = None,
        store_dir: Optional[str] = None,
        embedder_backend: Optional[str] = None,
        retrieval: Optional[str] = None,
    ) -> None:
        project_root = PROJECT_ROOT
        self.chunks_path = chunks_path or os.path.join(
            project_root, "data", "processed", "merck_emergencies_chunks.json"
        )
        self.store_dir = store_dir or resolve_vector_store_dir(project_root)
        self.embedder_backend = (
            embedder_backend or os.getenv("MERCK_EMBEDDER", "tfidf").lower()
        )
        self.retrieval = resolve_retrieval_mode(retrieval)
        # None until a query actually runs; a guess here would be indistinguishable
        # from a measured value.
        self.last_backend: Optional[str] = None
        self.retrieval_fallbacks: int = 0
        self.embedder: Optional[BaseEmbedder] = None
        self.vectors: Optional[np.ndarray] = None
        self.records: List[Dict[str, Any]] = []

    @staticmethod
    def _sanitize_matrix(vectors: np.ndarray) -> np.ndarray:
        """float32, finite, row-L2-normalized matrix for stable cosine search."""
        matrix = np.ascontiguousarray(vectors, dtype=np.float32)
        matrix = np.nan_to_num(matrix, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        safe = norms.squeeze(axis=1) > 1e-8
        out = np.zeros_like(matrix)
        if np.any(safe):
            out[safe] = matrix[safe] / norms[safe]
        return np.ascontiguousarray(out, dtype=np.float32)

    @staticmethod
    def _sanitize_vector(vector: np.ndarray) -> np.ndarray:
        vec = np.ascontiguousarray(vector, dtype=np.float32).reshape(-1)
        vec = np.nan_to_num(vec, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        norm = float(np.linalg.norm(vec))
        if norm > 1e-8:
            return vec / norm
        return np.zeros_like(vec)

    def _create_embedder(self) -> BaseEmbedder:
        if self.embedder_backend in {"tfidf", "local", "tfidf_local"}:
            return TfidfEmbedder()
        if self.embedder_backend in {"sentence_transformers", "st", "semantic"}:
            model = os.getenv(
                "MERCK_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
            )
            return SentenceTransformerEmbedder(model_name=model)
        raise ValueError(
            f"Unsupported embedder backend: {self.embedder_backend}. "
            "Use 'tfidf' or 'sentence_transformers'."
        )

    def _load_chunks(self) -> List[Dict[str, Any]]:
        with open(self.chunks_path, encoding="utf-8") as chunks_file:
            payload = json.load(chunks_file)
        chunks = payload.get("chunks", payload)
        if not isinstance(chunks, list) or not chunks:
            raise ValueError(f"No chunks found in {self.chunks_path}")
        return chunks

    def build(self) -> Dict[str, Any]:
        start = time.perf_counter()
        chunks = self._load_chunks()
        texts = [chunk["content"] for chunk in chunks]
        self.embedder = self._create_embedder()

        if isinstance(self.embedder, TfidfEmbedder):
            raw_vectors = self.embedder.fit_transform(texts)
        else:
            raw_vectors = self.embedder.embed_texts(texts)
        self.vectors = self._sanitize_matrix(raw_vectors)

        self.records = [
            {
                "chunk_id": chunk["chunk_id"],
                "content": chunk["content"],
                "metadata": chunk.get("metadata", {}),
            }
            for chunk in chunks
        ]
        elapsed_ms = (time.perf_counter() - start) * 1000
        manifest = self._save(elapsed_ms)
        logger.info(
            "Built vector store: %d vectors, dim=%d, backend=%s (%.1f ms)",
            len(self.records),
            self.embedder.dimension,
            self.embedder.name,
            elapsed_ms,
        )
        return manifest

    def _save(self, build_elapsed_ms: float) -> Dict[str, Any]:
        os.makedirs(self.store_dir, exist_ok=True)
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "embedder": self.embedder.name if self.embedder else None,
            "dimension": self.embedder.dimension if self.embedder else 0,
            "vector_count": len(self.records),
            "build_elapsed_ms": round(build_elapsed_ms, 2),
            "source_chunks_file": os.path.basename(self.chunks_path),
        }
        np.save(os.path.join(self.store_dir, "vectors.npy"), self.vectors)
        with open(os.path.join(self.store_dir, "records.json"), "w", encoding="utf-8") as f:
            json.dump(self.records, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.store_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        if isinstance(self.embedder, TfidfEmbedder):
            with open(
                os.path.join(self.store_dir, "tfidf_model.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(self.embedder.to_dict(), f, ensure_ascii=False)
        return manifest

    def load(self) -> None:
        manifest_path = os.path.join(self.store_dir, "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        embedder_name = manifest.get("embedder", "tfidf_local")
        if embedder_name.startswith("sentence_transformers:"):
            model_name = embedder_name.split(":", 1)[1]
            self.embedder = SentenceTransformerEmbedder(model_name=model_name)
        else:
            tfidf_path = os.path.join(self.store_dir, "tfidf_model.json")
            with open(tfidf_path, encoding="utf-8") as f:
                self.embedder = TfidfEmbedder.from_dict(json.load(f))
        raw = np.load(os.path.join(self.store_dir, "vectors.npy"))
        self.vectors = self._sanitize_matrix(raw)
        with open(os.path.join(self.store_dir, "records.json"), encoding="utf-8") as f:
            self.records = json.load(f)
        if len(self.records) != int(self.vectors.shape[0]):
            raise ValueError(
                f"Vector/record mismatch: {self.vectors.shape[0]} vectors vs "
                f"{len(self.records)} records in {self.store_dir}"
            )

    def active_backend(self) -> str:
        """Backend that search() will try first."""
        if self.retrieval == "auto":
            url, key = supabase_credentials()
            return "supabase" if url and key else "local"
        return self.retrieval

    def search(
        self,
        query: str,
        top_k: int = 5,
        filter_module: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if self.embedder is None:
            self.load()
        query_text = (query or "").strip()
        if not query_text or top_k <= 0:
            return []
        module = (filter_module or "").strip().upper() or None
        if module and module not in {"A", "B", "C"}:
            raise ValueError(f"filter_module must be A, B, or C; got {module!r}")

        backend = self.active_backend()
        if backend == "supabase":
            try:
                hits = self._search_supabase(query_text, top_k, filter_module=module)
                self.last_backend = "supabase"
                return hits
            except Exception as exc:
                if self.retrieval == "supabase":
                    raise
                self.retrieval_fallbacks += 1
                logger.warning(
                    "Supabase RPC failed (%s); falling back to local "
                    "(fallback #%s) — check /health retrieval_fallbacks",
                    exc,
                    self.retrieval_fallbacks,
                )

        self.last_backend = "local"
        return self._search_local(query_text, top_k, filter_module=module)

    def _embed_query(self, query_text: str) -> np.ndarray:
        if self.embedder is None:
            self.load()
        assert self.embedder is not None
        return self._sanitize_vector(self.embedder.embed_texts([query_text])[0])

    def _search_supabase(
        self,
        query_text: str,
        top_k: int,
        filter_module: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        import httpx

        url, key = supabase_credentials()
        if not url or not key:
            raise RuntimeError(
                "ANIMA_RETRIEVAL=supabase requires SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY"
            )
        query_vector = self._embed_query(query_text)
        emb = "[" + ",".join(f"{float(x):.8f}" for x in query_vector.tolist()) + "]"
        payload: Dict[str, Any] = {
            "query_embedding": emb,
            "match_count": int(top_k),
        }
        if filter_module:
            payload["filter_module"] = str(filter_module).upper()

        endpoint = url.rstrip("/") + "/rest/v1/rpc/match_knowledge_chunks"
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(endpoint, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"match_knowledge_chunks HTTP {resp.status_code}: {resp.text[:300]}"
                )
            rows = resp.json()
        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected RPC payload type: {type(rows).__name__}")

        results: List[Dict[str, Any]] = []
        for rank, row in enumerate(rows, start=1):
            meta = dict(row.get("metadata") or {})
            if row.get("module") and "module" not in meta:
                meta["module"] = row["module"]
            if row.get("source") and "source" not in meta:
                meta["source"] = row["source"]
            results.append(
                {
                    "rank": rank,
                    "score": float(row.get("similarity") or 0.0),
                    "chunk_id": row.get("id") or "",
                    "content": row.get("content") or "",
                    "metadata": meta,
                }
            )
        return results

    def _search_local(
        self,
        query_text: str,
        top_k: int,
        filter_module: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if self.vectors is None or not self.records:
            self.load()
        assert self.embedder is not None and self.vectors is not None

        if self.vectors.shape[0] == 0:
            return []

        query_vector = self._embed_query(query_text)
        if query_vector.shape[0] != self.vectors.shape[1]:
            raise ValueError(
                f"Query dim {query_vector.shape[0]} != store dim {self.vectors.shape[1]}"
            )

        # Use .dot (not @): macOS Accelerate emits spurious divide/overflow
        # RuntimeWarnings for ndarray@vector even on finite, unit-norm inputs.
        scores = self.vectors.dot(query_vector)
        scores = np.nan_to_num(scores, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        scores = np.clip(scores, -1.0, 1.0)
        if filter_module:
            mask = np.array(
                [
                    str((rec.get("metadata") or {}).get("module") or "A").upper()
                    == filter_module
                    for rec in self.records
                ],
                dtype=bool,
            )
            if mask.shape[0] != scores.shape[0]:
                raise ValueError("module mask / score length mismatch")
            scores = np.where(mask, scores, -np.inf)

        finite = np.isfinite(scores)
        if not np.any(finite):
            return []
        k = min(int(top_k), int(np.count_nonzero(finite)))
        # argpartition then sort the shortlist — stable top-k without full argsort.
        candidate_idx = np.argpartition(scores, -k)[-k:]
        top_indices = candidate_idx[np.argsort(scores[candidate_idx])[::-1]]

        results = []
        for rank, index in enumerate(top_indices, start=1):
            idx = int(index)
            record = self.records[idx]
            results.append(
                {
                    "rank": rank,
                    "score": float(scores[idx]),
                    "chunk_id": record["chunk_id"],
                    "content": record["content"],
                    "metadata": record.get("metadata", {}),
                }
            )
        return results


if __name__ == "__main__":
    store = MerckVectorStore()
    manifest = store.build()

    demo_queries = [
        "dog heart rate tachycardia shock",
        "poisoning activated charcoal treatment",
        "heat stroke cooling first aid",
        "itching pruritus lick paws dermatitis dog",
        "一直舔脚 瘙痒 皮肤",
    ]
    print(json.dumps(manifest, indent=2))
    print()
    for query in demo_queries:
        hits = store.search(query, top_k=3)
        print(f"Query: {query}")
        for hit in hits:
            chunk_type = hit["metadata"].get("chunk_type", "unknown")
            print(
                f"  #{hit['rank']} score={hit['score']:.4f} "
                f"[{chunk_type}] {hit['content'][:100]}..."
            )
        print()

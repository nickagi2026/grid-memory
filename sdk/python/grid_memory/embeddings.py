"""
embeddings.py — Semantic search for the Grid Memory engine.

Provides embedding generation and cosine similarity scoring.
Supports multiple providers:
  - sentence-transformers (local, free, offline)
  - OpenAI-compatible API (OpenAI, any v1 proxy)

Usage:
    from grid_memory.embeddings import EmbeddingEngine

    # Sentence-transformers (local)
    ee = EmbeddingEngine(provider="local", model_name="all-MiniLM-L6-v2")

    # OpenAI
    ee = EmbeddingEngine(provider="openai", api_key="sk-...")

    vector = ee.embed("What's the database config?")
    similarity = ee.similarity(vector1, vector2)
"""

import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple, Any


# ─── Error Types ────────────────────────────────────────────────────────────────


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""
    pass


# ─── Cosine Similarity ──────────────────────────────────────────────────────────


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─── Embedding Engine ───────────────────────────────────────────────────────────


class EmbeddingEngine:
    """Generates embeddings for semantic search.

    Args:
        provider: "local" (sentence-transformers) or "openai" (API-compatible)
        model_name: Model name for local, or model ID for API (default: text-embedding-3-small)
        api_key: API key for remote provider
        api_url: Custom API URL (default: https://api.openai.com)
        dimensions: Embedding dimensions (OpenAI default: 1536)
        device: Torch device for local model ("cpu", "cuda", "auto")
        cache_dir: Directory for caching embeddings
    """

    def __init__(self, provider: str = "local",
                 model_name: Optional[str] = None,
                 api_key: Optional[str] = None,
                 api_url: Optional[str] = None,
                 dimensions: int = 1536,
                 device: str = "auto",
                 cache_dir: Optional[str] = None):
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("GRID_EMBEDDING_API_KEY", "")
        self.api_url = (api_url or os.environ.get("GRID_EMBEDDING_URL", "https://api.openai.com")).rstrip("/")
        self.dimensions = dimensions
        self.device = device
        self.cache_dir = cache_dir or os.path.join(
            os.path.expanduser("~"), ".openclaw", "cache", "embeddings"
        )
        self._model = None
        self._cache: Dict[str, List[float]] = {}

        if provider == "local":
            self._init_local()
        elif provider == "openai":
            self._init_openai()
        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'local' or 'openai'.")

    def _init_local(self):
        """Initialize sentence-transformers model."""
        if not self.model_name:
            self.model_name = os.environ.get("GRID_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        # Deferred import — only when actually used
        self._model_ref = ("sentence-transformers", self.model_name)

    def _init_openai(self):
        """Initialize OpenAI-compatible API."""
        if not self.model_name:
            self.model_name = os.environ.get("GRID_EMBEDDING_MODEL", "text-embedding-3-small")
        if not self.api_key:
            raise EmbeddingError(
                "OpenAI provider requires api_key. Set GRID_EMBEDDING_API_KEY env var."
            )

    def _get_local_model(self):
        """Lazy-load sentence-transformers model."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
            import torch

            device = self.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            self._model = SentenceTransformer(self.model_name, device=device)
            print(f"[Grid Embeddings] Loaded local model '{self.model_name}' on {device}",
                  file=sys.stderr)
            return self._model
        except ImportError:
            raise EmbeddingError(
                "Local embeddings require 'sentence-transformers' package. "
                "Install with: pip install sentence-transformers"
            )
        except Exception as e:
            raise EmbeddingError(f"Failed to load model '{self.model_name}': {e}")

    def _api_embed(self, texts: List[str]) -> List[List[float]]:
        """Embed texts via OpenAI-compatible API."""
        # Ensure cache directory exists
        os.makedirs(self.cache_dir, exist_ok=True)

        results = []
        uncached_indices = []
        uncached_texts = []

        for i, text in enumerate(texts):
            cache_key = hashlib.sha256(text.encode()).hexdigest()
            cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")
            if text in self._cache:
                results.append(self._cache[text])
            elif os.path.exists(cache_path):
                with open(cache_path) as f:
                    cached = json.load(f)
                results.append(cached["embedding"])
                self._cache[text] = cached["embedding"]
            else:
                results.append(None)
                uncached_indices.append(i)
                uncached_texts.append(text)

        if not uncached_texts:
            return results

        # Batch API call
        body = {
            "model": self.model_name,
            "input": uncached_texts,
            "dimensions": self.dimensions,
        }

        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.api_url}/v1/embeddings",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                response = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                detail = json.loads(body)
                msg = detail.get("error", {}).get("message", body[:200])
            except json.JSONDecodeError:
                msg = body[:200]
            raise EmbeddingError(f"API error ({e.code}): {msg}")
        except urllib.error.URLError as e:
            raise EmbeddingError(f"API connection failed: {e.reason}")

        # Process response
        api_data = response.get("data", [])
        for idx, result_idx in enumerate(uncached_indices):
            api_entry = next((d for d in api_data if d.get("index") == idx), None)
            if api_entry and "embedding" in api_entry:
                vector = api_entry["embedding"]
                results[result_idx] = vector
                self._cache[uncached_texts[idx]] = vector
                # Cache to disk
                cache_key = hashlib.sha256(uncached_texts[idx].encode()).hexdigest()
                cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")
                try:
                    with open(cache_path, "w") as f:
                        json.dump({"text": uncached_texts[idx], "embedding": vector}, f)
                except IOError:
                    pass

        return results

    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text string.

        Args:
            text: Input text

        Returns:
            List of floats (embedding vector)

        Raises:
            EmbeddingError: If embedding generation fails
        """
        if self.provider == "local":
            model = self._get_local_model()
            return model.encode(text, show_progress_bar=False).tolist()
        else:
            results = self._api_embed([text])
            if results[0] is None:
                raise EmbeddingError("Failed to generate embedding")
            return results[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        if self.provider == "local":
            model = self._get_local_model()
            return model.encode(texts, show_progress_bar=False).tolist()
        else:
            return self._api_embed(texts)

    def similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        return cosine_similarity(a, b)

    def rank_by_similarity(self, query_vector: List[float],
                           candidates: List[Tuple[str, List[float]]]) -> List[Tuple[str, float]]:
        """Rank candidate texts by similarity to query vector.

        Args:
            query_vector: Query embedding
            candidates: List of (text_id, vector) tuples

        Returns:
            List of (text_id, score) tuples sorted by score descending
        """
        scored = []
        for text_id, vec in candidates:
            if vec and len(vec) == len(query_vector):
                sim = self.similarity(query_vector, vec)
                scored.append((text_id, sim))
        scored.sort(key=lambda x: -x[1])
        return scored

    def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
        try:
            if self.provider == "local":
                # Just check if sentence-transformers is importable
                import sentence_transformers  # noqa
                return True
            else:
                # Check API connectivity
                req = urllib.request.Request(
                    f"{self.api_url}/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status == 200
        except Exception:
            return False


# ─── Convenience — register entry embedder that auto-embeds on write ───────────


def auto_embed(grid_entries: List[Dict],
               embedding_engine: EmbeddingEngine,
               content_key: str = "content") -> List[Dict]:
    """Auto-generate embeddings for Grid entries that don't have them."""
    texts = []
    entries_to_embed = []
    for e in grid_entries:
        if e.get("embedding") is None and e.get(content_key):
            texts.append(e[content_key])
            entries_to_embed.append(e)

    if not texts:
        return grid_entries

    try:
        vectors = embedding_engine.embed_batch(texts)
        for e, vec in zip(entries_to_embed, vectors):
            e["embedding"] = vec
    except EmbeddingError:
        pass

    return grid_entries

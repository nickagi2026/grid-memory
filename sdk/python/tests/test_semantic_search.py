"""Tests for semantic search and EmbeddingEngine."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.embeddings import EmbeddingEngine, cosine_similarity, EmbeddingError


class TestCosineSimilarity(unittest.TestCase):
    def test_identical_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1, 0, 0], [1, 0, 0]), 1.0)

    def test_opposite_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [-1, 0]), -1.0)

    def test_orthogonal_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_empty_vectors(self):
        self.assertEqual(cosine_similarity([], []), 0.0)

    def test_mixed_dimensions(self):
        self.assertEqual(cosine_similarity([1, 0], [1]), 0.0)

    def test_magnitude_independent(self):
        sim = cosine_similarity([2, 0], [1, 1])
        self.assertAlmostEqual(sim, 1 / (2**0.5))


class TestEmbeddingEngine(unittest.TestCase):
    """Tests for embedding engine (requires API or sentence-transformers)."""

    def test_openai_requires_key(self):
        with self.assertRaises(EmbeddingError):
            EmbeddingEngine(provider="openai")

    def test_cosine_similarity_dimensions(self):
        """OpenAI returns 1536-dim embeddings."""
        api_key = os.environ.get("GRID_EMBEDDING_API_KEY")
        if not api_key:
            self.skipTest("No embedding API key configured")
        ee = EmbeddingEngine(provider="openai", api_key=api_key)
        vec = ee.embed("test")
        self.assertEqual(len(vec), 1536)


class TestSemanticQuery(unittest.TestCase):
    """Tests for semantic query mode on LocalGrid."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_semantic_query_falls_through_without_engine(self):
        """Semantic query without engine returns tag results."""
        self.grid.fact("Database config", tags=["database"], agent_id="test")
        result = self.grid.query(semantic="tell me about databases")
        self.assertGreaterEqual(len(result["entries"]), 0)
        self.assertFalse(result["query_meta"]["semantic_available"])

    def test_entries_have_embedding_field(self):
        """All entries have embedding field (default None)."""
        entry = self.grid.fact("Test", tags=["test"], agent_id="test")
        with open(self.grid._store_path) as f:
            import json
            store = json.load(f)
        stored = next(e for e in store["entries"] if e["id"] == entry["entry_id"])
        self.assertIn("embedding", stored)
        self.assertIsNone(stored["embedding"])

    def test_semantic_meta_in_query(self):
        """Query metadata includes semantic flags."""
        self.grid.fact("Test", tags=["test"], agent_id="test")
        result = self.grid.query(semantic="test query")
        meta = result["query_meta"]
        self.assertIn("semantic", meta)
        self.assertIn("semantic_available", meta)
        self.assertTrue(meta["semantic"])

    def test_entry_has_semantic_fields_in_response(self):
        """Response entries include has_embedding and relevance_score."""
        self.grid.fact("Test content", tags=["test"], agent_id="test")
        result = self.grid.query(tags=["test"])
        entry = result["entries"][0]
        self.assertIn("has_embedding", entry)
        self.assertIn("relevance_score", entry)


if __name__ == "__main__":
    unittest.main()

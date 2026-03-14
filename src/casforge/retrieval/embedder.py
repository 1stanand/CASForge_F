"""
catalogue/embedder.py
---------------------
Builds and persists a FAISS vector index over all unique step texts.

Model used : sentence-transformers/all-MiniLM-L6-v2
             384 dimensions, ~80 MB, CPU-only, no internet required
             after the first download (cached locally by sentence-transformers).

Index type  : faiss.IndexFlatIP (inner product on L2-normalised vectors
              = cosine similarity, range 0â€“1)

Saved files (in workspace/index/ by default):
    faiss_index.bin   â€” serialised FAISS index
    step_id_map.npy   â€” numpy int64 array: FAISS position â†’ step DB id

Public API
----------
build_index(step_rows)       â€” build + save from a list of {id, step_text} dicts
load_index()                 â€” load from disk; returns (index, id_map)
search_index(index, id_map, query_text, top_k) â†’ [(step_id, score), ...]
"""

import os
import logging
import numpy as np

from casforge.shared.settings import FAISS_INDEX_DIR, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_INDEX_DIR   = FAISS_INDEX_DIR
_INDEX_PATH  = os.path.join(_INDEX_DIR, "faiss_index.bin")
_ID_MAP_PATH = os.path.join(_INDEX_DIR, "step_id_map.npy")

_MODEL_NAME  = EMBEDDING_MODEL
_BATCH_SIZE  = 256

# In locked-down environments (no internet), embedding model load must not
# trigger long network retries. Keep this local-only by default, while still
# allowing opt-in downloads via EMBEDDING_ALLOW_DOWNLOAD=1.
_ALLOW_DOWNLOAD = os.getenv("EMBEDDING_ALLOW_DOWNLOAD", "0").strip().lower() in {
    "1", "true", "yes", "on"
}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Internal: lazy-loaded model singleton
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model '%s' ...", _MODEL_NAME)
        try:
            _model = SentenceTransformer(
                _MODEL_NAME,
                local_files_only=not _ALLOW_DOWNLOAD,
            )
        except TypeError:
            # Backward compatibility for older sentence-transformers versions
            # that may not support local_files_only.
            _model = SentenceTransformer(_MODEL_NAME)
        logger.info("Model loaded.")
    return _model


def _embed(texts: list[str]) -> np.ndarray:
    """
    Embed a list of strings.
    Returns float32 array of shape (len(texts), 384).
    Vectors are L2-normalised (unit length) for cosine similarity via dot product.
    """
    model = _get_model()
    import faiss
    # sentence-transformers returns numpy array by default
    vecs = model.encode(
        texts,
        batch_size=_BATCH_SIZE,
        show_progress_bar=len(texts) > 500,
        convert_to_numpy=True,
        normalize_embeddings=True,   # L2 normalise
    )
    return vecs.astype(np.float32)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Public: build
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_index(step_rows: list[dict]) -> None:
    """
    Build and save a FAISS index from step rows.

    Args:
        step_rows: list of dicts, each must have keys ``id`` (int) and
                   ``step_text`` (str).  Typically loaded from the
                   unique_steps materialised view.
    """
    import faiss

    if not step_rows:
        logger.warning("build_index called with empty step list â€” nothing to do.")
        return

    os.makedirs(_INDEX_DIR, exist_ok=True)

    ids   = [row["id"]        for row in step_rows]
    texts = [row["step_text"] for row in step_rows]

    logger.info("Embedding %d unique steps ...", len(texts))
    vecs = _embed(texts)                    # shape: (N, 384)

    dim = vecs.shape[1]
    index = faiss.IndexFlatIP(dim)          # cosine sim via inner product
    index.add(vecs)

    faiss.write_index(index, _INDEX_PATH)
    np.save(_ID_MAP_PATH, np.array(ids, dtype=np.int64))

    logger.info(
        "FAISS index saved â€” %d vectors, dim=%d  â†’  %s",
        index.ntotal, dim, _INDEX_DIR
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Public: load
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def load_index():
    """
    Load FAISS index and id map from disk.

    Returns:
        (index, id_map)  where id_map is a numpy int64 array mapping
        FAISS position â†’ step DB id.

    Raises:
        FileNotFoundError if index files are missing (run build_index.py first).
    """
    import faiss

    if not os.path.exists(_INDEX_PATH) or not os.path.exists(_ID_MAP_PATH):
        raise FileNotFoundError(
            f"FAISS index not found at {_INDEX_DIR}. "
            "Run:  python tools/cli/build_index.py"
        )

    index  = faiss.read_index(_INDEX_PATH)
    id_map = np.load(_ID_MAP_PATH)
    logger.debug("FAISS index loaded â€” %d vectors.", index.ntotal)
    return index, id_map


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Public: search
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def search_index(
    index,
    id_map: np.ndarray,
    query_text: str,
    top_k: int = 50,
) -> list[tuple[int, float]]:
    """
    Embed ``query_text`` and return the top_k most similar steps.

    Returns:
        List of (step_db_id, cosine_score) tuples, sorted descending by score.
        Scores are in [0, 1] (cosine similarity on unit vectors).
    """
    query_vec = _embed([query_text])           # shape (1, 384)
    k = min(top_k, index.ntotal)
    if k == 0:
        return []

    scores, positions = index.search(query_vec, k)   # both shape (1, k)

    results = []
    for pos, score in zip(positions[0], scores[0]):
        if pos < 0:   # FAISS returns -1 for empty slots
            continue
        step_id = int(id_map[pos])
        results.append((step_id, float(score)))

    return results






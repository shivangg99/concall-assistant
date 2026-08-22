"""Chroma persistent vector store wrapper. Local DB per PRD Phase 1-3 (8.5)."""
import os
import chromadb

PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chroma")
COLLECTION_NAME = "concall_chunks"

_client = None
_collection = None


def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=PERSIST_DIR)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    return _collection


def upsert_chunks(chunks: list[dict], embeddings: list[list[float]]):
    col = get_collection()
    col.upsert(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=embeddings,
        documents=[c["text"] for c in chunks],
        metadatas=[{k: v for k, v in c.items() if k not in ("chunk_id", "text")} for c in chunks],
    )


def query(query_embedding: list[float], top_k: int = 8, where: dict = None):
    col = get_collection()
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({**meta, "text": doc, "score": round(1 - dist, 4)})
    return hits


def stats():
    col = get_collection()
    all_meta = col.get(include=["metadatas"])["metadatas"]
    by_ticker_quarter = {}
    for m in all_meta:
        key = (m["ticker"], m["quarter"])
        by_ticker_quarter[key] = by_ticker_quarter.get(key, 0) + 1
    return {"total_chunks": len(all_meta), "by_ticker_quarter": by_ticker_quarter}

"""
Phase 1 retrieval layer (prototype).
Loads chunks.json, builds a TF-IDF index (stand-in for embeddings — see note
in ingest.py), and exposes a query() function returning top-k chunks with
metadata, optionally filtered by quarter.
"""
import json
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

with open("chunks.json") as f:
    CHUNKS = json.load(f)

_texts = [c["text"] for c in CHUNKS]
_vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_df=0.85)
_matrix = _vectorizer.fit_transform(_texts)

def query(question: str, top_k: int = 6, quarter_filter: str = None):
    idxs = list(range(len(CHUNKS)))
    if quarter_filter:
        idxs = [i for i in idxs if CHUNKS[i]["quarter"] == quarter_filter]
    if not idxs:
        return []

    q_vec = _vectorizer.transform([question])
    sims = cosine_similarity(q_vec, _matrix[idxs]).flatten()
    ranked = sorted(zip(idxs, sims), key=lambda x: x[1], reverse=True)[:top_k]

    results = []
    for i, score in ranked:
        c = CHUNKS[i]
        results.append({**c, "score": round(float(score), 4)})
    return results

if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "What is management saying about margins?"
    hits = query(q, top_k=5)
    print(f"Query: {q}\n")
    for h in hits:
        print(f"[{h['quarter']} | {h['speaker']} | {h['section']} | score={h['score']}]")
        print(h["text"][:300], "...\n")

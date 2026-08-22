"""Query pipeline: embed question -> search Chroma -> assemble prompt -> Claude -> cited answer."""
import os

import anthropic
from dotenv import load_dotenv

from .embeddings import embed_query
from .store import query as vector_query

load_dotenv()

GENERATION_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You are a research assistant for a long-term equity investor. You answer \
questions strictly from the provided earnings-call transcript excerpts.

Rules:
- Answer only using the provided excerpts. Never use outside knowledge or invent figures.
- Every factual claim must carry an inline citation in the form (Quarter, Speaker), \
e.g. (Q2FY26, Narendra Mantri).
- If the excerpts don't contain the answer, say so plainly instead of guessing.
- When asked about trends across quarters, organize the answer chronologically and cite each quarter used.
- Be concise and precise; prefer the management's own phrasing over paraphrase for numbers/guidance."""

_client = None


def _get_client():
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _client = anthropic.Anthropic()
    return _client


def retrieve(question: str, top_k: int = 8, ticker: str = None, quarter: str = None):
    q_embedding = embed_query(question)
    where = None
    conditions = []
    if ticker:
        conditions.append({"ticker": ticker})
    if quarter:
        conditions.append({"quarter": quarter})
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}
    return vector_query(q_embedding, top_k=top_k, where=where)


def _format_context(hits: list[dict]) -> str:
    blocks = []
    for h in hits:
        blocks.append(
            f"[{h['quarter']} | {h['speaker']} ({h['speaker_role']}) | {h['section']}]\n{h['text']}"
        )
    return "\n\n---\n\n".join(blocks)


def answer(question: str, top_k: int = 8, ticker: str = None, quarter: str = None, stream: bool = False):
    hits = retrieve(question, top_k=top_k, ticker=ticker, quarter=quarter)
    if not hits:
        return {"answer": "No relevant transcript chunks found for this query.", "sources": []}

    context = _format_context(hits)
    user_message = f"Transcript excerpts:\n\n{context}\n\n---\n\nQuestion: {question}"

    client = _get_client()
    if stream:
        return client.messages.stream(
            model=GENERATION_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ), hits

    resp = client.messages.create(
        model=GENERATION_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    text = next((block.text for block in resp.content if block.type == "text"), "")
    return {"answer": text, "sources": hits}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "What is management saying about the order book?"
    result = answer(q)
    print(f"Q: {q}\n")
    print(result["answer"])
    print("\n--- Sources ---")
    for s in result["sources"]:
        print(f"[{s['quarter']} | {s['speaker']} | {s['section']} | score={s['score']}]")

"""Voyage AI embedding wrapper. Requires VOYAGE_API_KEY in the environment."""
import os
import time

import voyageai
import voyageai.error

MODEL = "voyage-3.5"

_client = None

# Voyage's unverified-tier throttle (3 RPM) can trip even on a single
# small query embed if a request landed in the same rolling window - retry
# with backoff so both ingestion and live chat queries ride through it.
RETRY_DELAYS = [5, 10, 20, 30, 45]


def _get_client():
    global _client
    if _client is None:
        if not os.environ.get("VOYAGE_API_KEY"):
            raise RuntimeError(
                "VOYAGE_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        _client = voyageai.Client()
    return _client


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    last_error = None
    for delay in RETRY_DELAYS + [None]:
        try:
            result = _get_client().embed(texts, model=MODEL, input_type=input_type)
            return result.embeddings
        except voyageai.error.RateLimitError as e:
            last_error = e
            if delay is None:
                break
            time.sleep(delay)
    raise last_error


def embed_documents(texts: list[str]) -> list[list[float]]:
    return _embed(texts, "document")


def embed_query(text: str) -> list[float]:
    return _embed([text], "query")[0]

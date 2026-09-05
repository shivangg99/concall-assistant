"""Voyage AI embedding wrapper. Requires VOYAGE_API_KEY in the environment."""
import os
import time

import voyageai
import voyageai.error

MODEL = "voyage-3.5"

_client = None

# Voyage's unverified-tier throttle (3 RPM) can trip even on a single small
# query embed if a request landed in the same rolling window, and Voyage's
# own infra occasionally throws a transient 500 unrelated to anything on our
# end (seen in practice: a bare "hello world" request failed once, succeeded
# immediately on retry) - retry with backoff on anything that's plausibly
# transient. Auth/malformed-request errors are deliberately NOT retried here
# since retrying an identical bad request just fails the same way again.
RETRY_DELAYS = [5, 10, 20, 30, 45]
RETRYABLE_ERRORS = (
    voyageai.error.RateLimitError,
    voyageai.error.ServerError,
    voyageai.error.ServiceUnavailableError,
    voyageai.error.APIConnectionError,
    voyageai.error.Timeout,
    voyageai.error.TryAgain,
)


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
        except RETRYABLE_ERRORS as e:
            last_error = e
            if delay is None:
                break
            time.sleep(delay)
    raise last_error


def embed_documents(texts: list[str]) -> list[list[float]]:
    return _embed(texts, "document")


def embed_query(text: str) -> list[float]:
    return _embed([text], "query")[0]

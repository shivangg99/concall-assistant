"""
Ingestion pipeline: R2 -> PDF -> parse -> chunk -> embed -> Chroma.

Source PDFs live in Cloudflare R2 under <TICKER>/<filename>.pdf, not on local
disk - see src/cloud.py. Adding a new company is just uploading its transcript
PDFs under a new ticker prefix (python -m src.upload_transcripts) - no code
changes needed. Re-running is idempotent: chunk_ids are stable, so upsert
overwrites in place.
"""
import argparse
import hashlib
import time

from dotenv import load_dotenv

from . import cloud
from .parse import parse_transcript
from .chunk import chunk_turns
from .embeddings import embed_documents
from .store import upsert_chunks, stats, existing_ids

load_dotenv()

# Sized for Voyage's unverified-tier limits: 3 requests/min AND 10K tokens
# PER REQUEST (not just per minute) - a batch that's too large fails outright
# no matter how many times it's retried, it's not just a pacing problem.
# At up to ~400 tokens/chunk, 15/batch stays safely under the 10K ceiling;
# 21s spacing keeps to 3 req/min. Add a payment method on the Voyage
# dashboard to lift both limits and speed this up.
EMBED_BATCH_SIZE = 15
SECONDS_BETWEEN_BATCHES = 21


def _content_hash(turns) -> str:
    joined = "\n".join(f"{s}:{t}" for s, t in turns)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def ingest_ticker(ticker: str, verbose: bool = True):
    keys = cloud.list_pdfs(ticker)
    if not keys:
        raise FileNotFoundError(f"No PDFs found in R2 under {ticker}/ (bucket: {cloud.BUCKET})")

    seen_hashes = {}
    all_chunks = []

    for key in keys:
        filename = key.rsplit("/", 1)[-1]
        pdf_bytes = cloud.download_bytes(key)
        turns, meta = parse_transcript(pdf_bytes)
        if not meta["quarter"]:
            if verbose:
                print(f"  SKIP {filename}: could not determine quarter from PDF text")
            continue

        h = _content_hash(turns)
        if h in seen_hashes:
            if verbose:
                print(f"  SKIP {filename}: duplicate content of {seen_hashes[h]}")
            continue
        seen_hashes[h] = filename

        chunks = chunk_turns(
            turns, ticker, meta["quarter"], meta["fiscal_year"],
            meta["call_date"], meta["management_names"],
        )
        if verbose:
            print(f"  {filename} -> {meta['quarter']} ({meta['call_date']}): {len(chunks)} chunks")
        all_chunks.extend(chunks)

    if not all_chunks:
        if verbose:
            print(f"No chunks produced for {ticker}.")
        return 0

    # Skip re-embedding chunks that are already in the store unchanged - the
    # chunk_id is stable for identical (ticker, quarter, section, index), so
    # a chunk that's already there is already correct. Only new/changed
    # chunk_ids (a newly-recovered file, or a chunking-logic change) get an
    # embedding call - this is what makes re-running cheap and fast instead
    # of re-embedding a whole ticker's history every time.
    already_have = existing_ids([c["chunk_id"] for c in all_chunks])
    new_chunks = [c for c in all_chunks if c["chunk_id"] not in already_have]

    if verbose:
        print(f"  {len(all_chunks)} chunk(s) total, {len(new_chunks)} new (skipping {len(already_have)} already stored)")

    if not new_chunks:
        return len(all_chunks)

    for i in range(0, len(new_chunks), EMBED_BATCH_SIZE):
        batch = new_chunks[i:i + EMBED_BATCH_SIZE]
        embeddings = embed_documents([c["text"] for c in batch])
        upsert_chunks(batch, embeddings)
        if verbose:
            print(f"  embedded+stored {i + len(batch)}/{len(new_chunks)}")
        if i + EMBED_BATCH_SIZE < len(new_chunks):
            time.sleep(SECONDS_BETWEEN_BATCHES)

    return len(new_chunks)


def main():
    parser = argparse.ArgumentParser(description="Ingest concall transcripts (from R2) into the vector store.")
    parser.add_argument("ticker", nargs="?", default=None, help="Ticker prefix in the R2 bucket (default: all)")
    args = parser.parse_args()

    tickers = [args.ticker] if args.ticker else cloud.list_tickers()

    total = 0
    for t in tickers:
        print(f"\n=== {t} ===")
        total += ingest_ticker(t)

    print(f"\nDone. {total} chunks ingested this run.")
    print("Store stats:", stats())


if __name__ == "__main__":
    main()

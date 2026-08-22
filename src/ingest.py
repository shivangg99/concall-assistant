"""
Ingestion pipeline: PDF -> parse -> chunk -> embed -> Chroma.

Scans cocnall-scripts/<TICKER>/*.pdf. Adding a new company is just adding a
new ticker folder with its transcript PDFs - no code changes needed.
Re-running is idempotent: chunk_ids are stable, so upsert overwrites in place.
"""
import argparse
import glob
import hashlib
import os
import time

from dotenv import load_dotenv

from .parse import parse_transcript
from .chunk import chunk_turns
from .embeddings import embed_documents
from .store import upsert_chunks, stats

load_dotenv()

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cocnall-scripts")
# Small batch + throttle so this works even on Voyage's unverified free tier
# (3 requests/min, 10K tokens/min). Add a payment method on the Voyage
# dashboard to lift this and speed up ingestion - the token quota stays free.
# embeddings.py retries individual calls on rate-limit errors too.
EMBED_BATCH_SIZE = 15
SECONDS_BETWEEN_BATCHES = 21


def _content_hash(turns) -> str:
    joined = "\n".join(f"{s}:{t}" for s, t in turns)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def ingest_ticker(ticker: str, scripts_dir: str = SCRIPTS_DIR, verbose: bool = True):
    pdf_paths = sorted(glob.glob(os.path.join(scripts_dir, ticker, "*.pdf")))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDFs found for ticker {ticker} in {scripts_dir}")

    seen_hashes = {}
    all_chunks = []

    for path in pdf_paths:
        turns, meta = parse_transcript(path)
        if not meta["quarter"]:
            if verbose:
                print(f"  SKIP {os.path.basename(path)}: could not determine quarter from PDF text")
            continue

        h = _content_hash(turns)
        if h in seen_hashes:
            if verbose:
                print(f"  SKIP {os.path.basename(path)}: duplicate content of {seen_hashes[h]}")
            continue
        seen_hashes[h] = os.path.basename(path)

        chunks = chunk_turns(
            turns, ticker, meta["quarter"], meta["fiscal_year"],
            meta["call_date"], meta["management_names"],
        )
        if verbose:
            print(f"  {os.path.basename(path)} -> {meta['quarter']} ({meta['call_date']}): {len(chunks)} chunks")
        all_chunks.extend(chunks)

    if not all_chunks:
        if verbose:
            print(f"No chunks produced for {ticker}.")
        return 0

    for i in range(0, len(all_chunks), EMBED_BATCH_SIZE):
        batch = all_chunks[i:i + EMBED_BATCH_SIZE]
        embeddings = embed_documents([c["text"] for c in batch])
        upsert_chunks(batch, embeddings)
        if verbose:
            print(f"  embedded+stored {i + len(batch)}/{len(all_chunks)}")
        if i + EMBED_BATCH_SIZE < len(all_chunks):
            time.sleep(SECONDS_BETWEEN_BATCHES)

    return len(all_chunks)


def main():
    parser = argparse.ArgumentParser(description="Ingest concall transcripts into the vector store.")
    parser.add_argument("ticker", nargs="?", default=None, help="Ticker folder under cocnall-scripts/ (default: all)")
    args = parser.parse_args()

    if args.ticker:
        tickers = [args.ticker]
    else:
        tickers = sorted(
            d for d in os.listdir(SCRIPTS_DIR)
            if os.path.isdir(os.path.join(SCRIPTS_DIR, d))
        )

    total = 0
    for t in tickers:
        print(f"\n=== {t} ===")
        total += ingest_ticker(t)

    print(f"\nDone. {total} chunks ingested this run.")
    print("Store stats:", stats())


if __name__ == "__main__":
    main()

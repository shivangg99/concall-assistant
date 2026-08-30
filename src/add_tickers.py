"""
End-to-end: scrape Screener.in -> upload new PDFs to R2 -> ingest, per ticker.

This is the "give me a list of tickers" entry point - everything happens in
memory (scraped bytes go straight to R2, nothing touches local disk) and is
safe to re-run: PDFs already in the bucket are skipped, and ingestion only
re-runs when there's something new to embed.

Usage:
    python -m src.add_tickers JINDALSAW HDFCBANK TCS
    python -m src.add_tickers --file portfolio.txt   # one ticker per line, '#' comments allowed
"""
import argparse
import time

from dotenv import load_dotenv

from . import cloud
from .scrape_screener import fetch_transcripts, fetch_pdf, slug
from .ingest import ingest_ticker
from .store import available_tickers

load_dotenv()

SECONDS_BETWEEN_DOWNLOADS = 1
SECONDS_BETWEEN_TICKERS = 2


def add_ticker(ticker: str, statement: str = "consolidated", verbose: bool = True) -> dict:
    """Scrape, upload anything new, and (re-)ingest one ticker.
    Returns {"found": n, "uploaded": n, "chunks": n}."""
    existing_files = {key.rsplit("/", 1)[-1] for key in cloud.list_pdfs(ticker)}

    transcripts = fetch_transcripts(ticker, statement)
    if not transcripts:
        if verbose:
            print(f"  No transcripts found on Screener for {ticker}.")
        return {"found": 0, "uploaded": 0, "chunks": 0}

    uploaded = 0
    for t in transcripts:
        filename = f"{slug(t['date'])}.pdf"
        if filename in existing_files:
            continue
        try:
            content = fetch_pdf(t["url"])
        except Exception as e:
            if verbose:
                print(f"  SKIP {filename}: {e}")
            continue
        cloud.upload_bytes(content, f"{ticker}/{filename}")
        if verbose:
            print(f"  uploaded {t['date']} -> {ticker}/{filename}")
        uploaded += 1
        time.sleep(SECONDS_BETWEEN_DOWNLOADS)

    if verbose:
        print(f"  {uploaded} new file(s) uploaded ({len(transcripts)} found, {len(existing_files)} already had).")

    chunks = 0
    if uploaded > 0 or ticker not in available_tickers():
        chunks = ingest_ticker(ticker, verbose=verbose)
    elif verbose:
        print("  Nothing new to ingest.")

    return {"found": len(transcripts), "uploaded": uploaded, "chunks": chunks}


def main():
    parser = argparse.ArgumentParser(description="Scrape, upload, and ingest concall transcripts for one or more tickers.")
    parser.add_argument("tickers", nargs="*", help="Tickers to add, e.g. JINDALSAW HDFCBANK TCS")
    parser.add_argument("--file", help="Path to a text file with one ticker per line ('#' comments allowed)")
    parser.add_argument("--statement", default="consolidated", choices=["consolidated", "standalone"])
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers]
    if args.file:
        with open(args.file) as f:
            tickers += [
                line.strip().upper() for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    # de-dupe, keep order
    seen = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]

    if not tickers:
        parser.error("Give at least one ticker, or --file with a ticker list.")

    results = {}
    for i, ticker in enumerate(tickers):
        print(f"\n=== {ticker} ===")
        try:
            results[ticker] = add_ticker(ticker, args.statement)
        except Exception as e:
            print(f"  FAILED: {e}")
            results[ticker] = {"error": str(e)}
        if i < len(tickers) - 1:
            time.sleep(SECONDS_BETWEEN_TICKERS)

    print("\n=== Summary ===")
    for ticker, r in results.items():
        if "error" in r:
            print(f"  {ticker}: FAILED - {r['error']}")
        else:
            print(f"  {ticker}: {r['found']} found, {r['uploaded']} new, {r['chunks']} chunks ingested")


if __name__ == "__main__":
    main()

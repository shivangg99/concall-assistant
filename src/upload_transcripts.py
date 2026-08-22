"""
Upload local transcript PDFs to R2, under <ticker>/<filename>.pdf.

Usage:
    python -m src.upload_transcripts cocnall-scripts/JINDALSAW JINDALSAW
    python -m src.upload_transcripts path/to/new_pdfs NEWTICKER
"""
import argparse
import glob
import os

from dotenv import load_dotenv

from . import cloud

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Upload local transcript PDFs to the R2 bucket.")
    parser.add_argument("local_dir", help="Local folder containing this ticker's PDF files")
    parser.add_argument("ticker", help="Ticker prefix to upload under in R2")
    args = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(args.local_dir, "*.pdf")))
    if not paths:
        print(f"No PDFs found in {args.local_dir}")
        return

    for path in paths:
        key = f"{args.ticker}/{os.path.basename(path)}"
        cloud.upload_file(path, key)
        print(f"uploaded {path} -> r2://{cloud.BUCKET}/{key}")

    print(f"\nDone. {len(paths)} file(s) uploaded under {args.ticker}/.")
    print(f"Next: python -m src.ingest {args.ticker}")


if __name__ == "__main__":
    main()

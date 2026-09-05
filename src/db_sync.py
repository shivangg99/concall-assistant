"""
Sync the local Chroma DB to/from R2.

Ingestion is unaffected by this - it always runs locally against
data/chroma/, exactly as before. This module is what gets that data to a
*deployed* instance (Streamlit Cloud, etc.), which starts with an empty
disk on a different machine and has no other way to reach it:

    python -m src.db_sync upload     # run locally after ingesting, to publish
    python -m src.db_sync download   # run once on a fresh deployment

app.py calls download_snapshot() automatically on startup if data/chroma/
doesn't exist yet, so a freshly deployed instance bootstraps itself.
"""
import argparse
import os
import zipfile
from io import BytesIO

from dotenv import load_dotenv

from . import cloud
from .store import PERSIST_DIR

load_dotenv()

SNAPSHOT_KEY = "_snapshot/chroma.zip"


def upload_snapshot(verbose: bool = True):
    if not os.path.isdir(PERSIST_DIR) or not os.listdir(PERSIST_DIR):
        raise FileNotFoundError(f"No local DB at {PERSIST_DIR} to snapshot.")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(PERSIST_DIR):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, PERSIST_DIR)
                zf.write(full, rel)
    data = buf.getvalue()

    cloud.upload_bytes(data, SNAPSHOT_KEY, content_type="application/zip")
    if verbose:
        print(f"Uploaded DB snapshot ({len(data) / 1e6:.1f} MB) to r2://{cloud.BUCKET}/{SNAPSHOT_KEY}")


def download_snapshot(force: bool = False, verbose: bool = True) -> bool:
    """Returns True if a snapshot was actually downloaded and extracted."""
    if os.path.isdir(PERSIST_DIR) and os.listdir(PERSIST_DIR) and not force:
        if verbose:
            print(f"{PERSIST_DIR} already has data, skipping download (use --force to overwrite).")
        return False

    buf = cloud.download_bytes(SNAPSHOT_KEY)
    os.makedirs(PERSIST_DIR, exist_ok=True)
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(PERSIST_DIR)
    if verbose:
        print(f"Downloaded and extracted DB snapshot into {PERSIST_DIR}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Sync the local Chroma DB with R2.")
    parser.add_argument("action", choices=["upload", "download"])
    parser.add_argument("--force", action="store_true", help="On download, overwrite existing local data")
    args = parser.parse_args()

    if args.action == "upload":
        upload_snapshot()
    else:
        download_snapshot(force=args.force)


if __name__ == "__main__":
    main()

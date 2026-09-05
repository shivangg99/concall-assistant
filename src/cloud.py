"""
Cloudflare R2 storage for source transcript PDFs.

R2 speaks the S3 API, so this is just boto3 pointed at R2's endpoint - no
AWS account involved. Objects are keyed "<TICKER>/<filename>.pdf", mirroring
the local cocnall-scripts/<TICKER>/ layout it replaces as the source of truth.
"""
import io
import os

import boto3

BUCKET = os.environ.get("R2_BUCKET_NAME", "concall-transcripts")

_client = None


def _get_client():
    global _client
    if _client is None:
        # R2_ENDPOINT_URL (copy-pasted straight from the bucket's Settings ->
        # S3 API page) is the easy path - falls back to building the URL from
        # R2_ACCOUNT_ID if that's what you've got instead.
        endpoint_url = os.environ.get("R2_ENDPOINT_URL")
        account_id = os.environ.get("R2_ACCOUNT_ID")
        access_key = os.environ.get("R2_ACCESS_KEY_ID")
        secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
        if not endpoint_url and not account_id:
            raise RuntimeError(
                "Set either R2_ENDPOINT_URL or R2_ACCOUNT_ID (plus R2_ACCESS_KEY_ID / "
                "R2_SECRET_ACCESS_KEY) in .env"
            )
        if not all([access_key, secret_key]):
            raise RuntimeError("R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY must be set in .env")
        _client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
    return _client


def list_tickers() -> list[str]:
    """Top-level 'folders' in the bucket, i.e. the ticker prefixes. Anything
    starting with "_" is reserved for non-ticker use (e.g. "_snapshot/" for
    the DB backup - see src/db_sync.py) and excluded here."""
    resp = _get_client().list_objects_v2(Bucket=BUCKET, Delimiter="/")
    return sorted(
        p["Prefix"].rstrip("/") for p in resp.get("CommonPrefixes", [])
        if not p["Prefix"].startswith("_")
    )


def list_pdfs(ticker: str) -> list[str]:
    """Object keys for every PDF under <ticker>/, sorted."""
    client = _get_client()
    prefix = f"{ticker}/"
    keys = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(".pdf"):
                keys.append(obj["Key"])
    return sorted(keys)


def download_bytes(key: str) -> io.BytesIO:
    """Pull an object straight into memory - pdfplumber can open a BytesIO
    directly, so ingestion never needs to touch the local disk."""
    buf = io.BytesIO()
    _get_client().download_fileobj(BUCKET, key, buf)
    buf.seek(0)
    return buf


def upload_file(local_path: str, key: str):
    _get_client().upload_file(local_path, BUCKET, key)


def upload_bytes(data: bytes, key: str, content_type: str = "application/pdf"):
    """Write straight to R2 without a local file - used when a transcript is
    fetched from a scraper directly into memory, or for the DB snapshot zip."""
    _get_client().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)

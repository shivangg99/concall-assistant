"""
Scrape concall transcript PDFs off a Screener.in company page and save them
locally under cocnall-scripts/<TICKER>/, in the same MM-YY.pdf layout that
src.upload_transcripts expects to push to R2.

Usage:
    python -m src.scrape_screener HDFCBANK
    python -m src.scrape_screener HDFCBANK --statement standalone --out-dir cocnall-scripts
"""
import argparse
import os
import re

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.screener.in/company/{ticker}/{statement}/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def _slug(date_label: str) -> str:
    """'Jul 2026' -> '07-26'."""
    month, year = date_label.split()
    return f"{MONTHS[month]}-{year[2:]}"


def fetch_transcripts(ticker: str, statement: str = "consolidated") -> list[dict]:
    """Return [{"date": "Jul 2026", "url": "https://.../....pdf"}, ...] for
    every concall with a raw transcript link on the company's Screener page."""
    url = BASE_URL.format(ticker=ticker, statement=statement)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code == 404 and statement != "standalone":
        # Some companies (e.g. those without consolidated financials) only
        # have the plain /company/<ticker>/ page.
        url = f"https://www.screener.in/company/{ticker}/"
        resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for link in soup.select("a.concall-link"):
        if link.get_text(strip=True) != "Transcript":
            continue
        li = link.find_parent("li")
        date_div = li.find("div") if li else None
        date_label = date_div.get_text(strip=True) if date_div else None
        pdf_url = link.get("href")
        if date_label and pdf_url:
            results.append({"date": date_label, "url": pdf_url})
    return results


def download_transcripts(ticker: str, statement: str = "consolidated", out_dir: str = "cocnall-scripts") -> int:
    transcripts = fetch_transcripts(ticker, statement)
    if not transcripts:
        print(f"No transcripts found for {ticker} ({statement}).")
        return 0

    dest = os.path.join(out_dir, ticker)
    os.makedirs(dest, exist_ok=True)

    downloaded = 0
    for t in transcripts:
        filename = f"{_slug(t['date'])}.pdf"
        path = os.path.join(dest, filename)
        if os.path.exists(path):
            print(f"  SKIP {filename}: already downloaded")
            continue

        try:
            pdf_resp = requests.get(t["url"], headers=HEADERS, timeout=30)
            pdf_resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  SKIP {filename}: download failed ({e})")
            continue
        if not pdf_resp.content.startswith(b"%PDF"):
            print(f"  SKIP {filename}: response wasn't a PDF ({t['url']})")
            continue

        with open(path, "wb") as f:
            f.write(pdf_resp.content)
        print(f"  {t['date']} -> {path}")
        downloaded += 1

    print(f"\nDone. {downloaded} new transcript(s) saved under {dest}/.")
    if downloaded:
        print(f"Next: python -m src.upload_transcripts {dest} {ticker}")
    return downloaded


def main():
    parser = argparse.ArgumentParser(description="Scrape concall transcript PDFs from Screener.in.")
    parser.add_argument("ticker", help="Screener ticker, e.g. HDFCBANK")
    parser.add_argument("--statement", default="consolidated", choices=["consolidated", "standalone"])
    parser.add_argument("--out-dir", default="cocnall-scripts")
    args = parser.parse_args()

    ticker = re.sub(r"\s+", "", args.ticker.upper())
    download_transcripts(ticker, args.statement, args.out_dir)


if __name__ == "__main__":
    main()

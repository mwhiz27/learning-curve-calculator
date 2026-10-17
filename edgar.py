"""Shared helpers: polite SEC EDGAR + BLS access with a local cache."""
import html
import json
import os
import re
import subprocess
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
# SEC requires a descriptive User-Agent with contact info (no API key needed).
UA = "BYU strategy class learning-curve tool mhwhisenant@gmail.com"


def _get(url, cache_name, post=None):
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    cmd = ["curl", "-s", "-f", "-A", UA, url]
    if post is not None:
        cmd = ["curl", "-s", "-f", "-X", "POST", "-H", "Content-Type: application/json",
               "-d", json.dumps(post), url]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(f"fetch failed: {url}")
    text = out.stdout.decode("utf-8", "ignore")
    os.makedirs(CACHE, exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)
    time.sleep(0.15)  # stay well under SEC's 10 requests/second limit
    return text


def cik_for(ticker):
    tickers = json.loads(_get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json"))
    for row in tickers.values():
        if row["ticker"].upper() == ticker.upper():
            return row["cik_str"], row["title"]
    raise SystemExit(f"Ticker {ticker} not found in SEC company_tickers.json")


def company_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    return json.loads(_get(url, f"facts_{cik}.json"))


def submissions(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    return json.loads(_get(url, f"submissions_{cik}.json"))


def filing_url(cik, accession, doc):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{doc}"


def filing_index_url(cik, accession):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"


def filing_text(cik, accession, doc):
    """Download a filing's primary HTML document and flatten it to plain text."""
    raw = _get(filing_url(cik, accession, doc), f"doc_{accession}.htm")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text)


def cpi_monthly(start_year, end_year):
    """CPI-U, U.S. city average, all items, not seasonally adjusted (BLS series CUUR0000SA0)."""
    out = {}
    y = start_year
    while y <= end_year:  # BLS v1 API (no key) allows 10 years per request
        y2 = min(y + 9, end_year)
        body = json.loads(_get("https://api.bls.gov/publicAPI/v1/timeseries/data/",
                               f"cpi_{y}_{y2}.json",
                               post={"seriesid": ["CUUR0000SA0"], "startyear": str(y), "endyear": str(y2)}))
        for row in body["Results"]["series"][0]["data"]:
            if row["period"] == "M13":
                continue
            try:
                out[f"{row['year']}-{row['period'][1:]}"] = float(row["value"])
            except ValueError:
                pass  # BLS publishes "-" for months it skipped (e.g. Oct 2025 shutdown)
        y = y2 + 1
    return dict(sorted(out.items()))

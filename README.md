# Learning-Curve Calculator

Fits the experience curve `Cost(N) = Cost(1) × N^-b` to unit costs pulled from SEC EDGAR filings.
Live tool: https://mwhiz27.github.io/learning-curve-calculator/

- `extract_tko_ufc.py` builds `data/TKO.json`: UFC segment direct operating costs and event counts
  regex-parsed from TKO's 10-K/10-Q filings and 2023 S-1, with cross-filing consistency checks.
- `fetch_edgar.py TICKER --price P --price-source "..."` builds `data/TICKER.json` for any ticker
  from XBRL COGS/revenue (units via revenue proxy).
- `build.py` inlines `data/*.json` + `context.json` into `template.html` → `dist/index.html`.

No dependencies beyond Python 3 and curl. Data: SEC EDGAR (no key) and BLS CPI-U (no key).

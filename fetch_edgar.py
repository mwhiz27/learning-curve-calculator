"""Pull cost of revenue (COGS) and revenue for ANY ticker from SEC EDGAR's XBRL API and write
data/<TICKER>.json for the web tool.

Units are not in XBRL, so this path uses the revenue proxy: units = revenue / average price.
Pass --price (average selling price in the first period, in dollars) and say where it came
from with --price-source. If the price is held constant, it cancels out of the learning rate
(only the intercept moves); --price-index cpi grows it with inflation instead.

Usage: python3 fetch_edgar.py GOLF --price 300 --price-source "Estimate: ..." [--price-index cpi]
"""
import argparse
import json
import os
from datetime import date

import edgar

COST_TAGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
             "CostOfGoodsAndServicesSoldExcludingDepreciationDepletionAndAmortization", "CostOfServices"]
REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax"]


def days(f):
    return (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days


def series(gaap, tags):
    """period (start, end) -> (value, fact); earlier tags win, latest filing wins within a tag."""
    out = {}
    for tag in reversed(tags):  # later tags first so earlier (preferred) tags overwrite
        facts = gaap.get(tag, {}).get("units", {}).get("USD", [])
        per_tag = {}
        for f in sorted(facts, key=lambda f: f["filed"]):
            if f.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A") or "start" not in f:
                continue
            per_tag[(f["start"], f["end"])] = (f["val"], {**f, "tag": tag})
        out.update(per_tag)
    return out


def quarterize(s):
    """Return {(start,end): value} for quarters, deriving Q4 = fiscal year - first three quarters."""
    q = {k: v for k, v in s.items() if 80 <= days({"start": k[0], "end": k[1]}) <= 100}
    for (st, en), (val, fact) in s.items():
        if 350 <= days({"start": st, "end": en}) <= 380:
            inside = sorted(k for k in q if st <= k[0] and k[1] <= en)
            if len(inside) == 3:
                last_end = inside[-1][1]
                q4_start = (date.fromisoformat(last_end).toordinal() + 1)
                key = (date.fromordinal(q4_start).isoformat(), en)
                if key not in q:
                    q[key] = (val - sum(q[k][0] for k in inside),
                              {**fact, "derived": "fiscal year minus Q1-Q3"})
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--price", type=float, required=True, help="average selling price per unit, $")
    ap.add_argument("--price-source", required=True, help="where the average price comes from")
    ap.add_argument("--price-index", choices=["constant", "cpi"], default="constant")
    ap.add_argument("--unit-label", default="unit")
    a = ap.parse_args()

    cik, title = edgar.cik_for(a.ticker)
    gaap = edgar.company_facts(cik)["facts"]["us-gaap"]
    cost_q, rev_q = quarterize(series(gaap, COST_TAGS)), quarterize(series(gaap, REV_TAGS))
    keys = sorted(k for k in cost_q if k in rev_q)
    if len(keys) < 8:
        raise SystemExit(f"Only {len(keys)} quarters with both COGS and revenue tagged; try another ticker.")

    # Cumulative units need an unbroken run: keep only quarters after the last gap.
    start_i = 0
    for i in range(1, len(keys)):
        if (date.fromisoformat(keys[i][0]) - date.fromisoformat(keys[i - 1][1])).days > 5:
            start_i = i
    keys = keys[start_i:]

    rows = []
    for st, en in keys:
        cost, cf = cost_q[(st, en)]
        rev, _ = rev_q[(st, en)]
        rows.append({
            "label": f"Q{(int(en[5:7]) - 1) // 3 + 1} {en[:4]}", "start": st, "end": en, "kind": "quarter",
            "cost": round(cost / 1e6, 3), "revenue": round(rev / 1e6, 3),
            "source": {"form": cf["form"], "period": en, "filed": cf["filed"], "accession": cf["accn"],
                       "url": edgar.filing_index_url(cik, cf["accn"]),
                       "note": f"XBRL tag {cf['tag']}" + (f"; {cf['derived']}" if cf.get("derived") else "")},
        })
    first_year = int(rows[0]["start"][:4])
    out = {
        "ticker": a.ticker.upper(), "company": title, "segment": "Consolidated", "cik": cik,
        "cost_label": "Cost of revenue (XBRL)", "cost_unit": "USD millions",
        "unit_label": a.unit_label, "unit_label_plural": a.unit_label + "s",
        "units_type": "proxy",
        "price": {"base": a.price, "source": a.price_source, "index": a.price_index},
        "units_note": (f"Revenue proxy: units = revenue / average price (${a.price:,.0f} in {rows[0]['label']}, "
                       f"{'indexed to CPI' if a.price_index == 'cpi' else 'held constant'}). Source: {a.price_source}"),
        "cost_note": "COGS from SEC XBRL company facts; quarterly values, Q4 derived as fiscal year minus Q1–Q3.",
        "series": {"quarterly": {"name": "Quarterly (10-Q / 10-K)", "rows": rows}},
        "default_series": "quarterly",
        "cpi": edgar.cpi_monthly(first_year, date.today().year),
        "generated": date.today().isoformat(),
    }
    path = os.path.join(edgar.ROOT, "data", f"{a.ticker.upper()}.json")
    json.dump(out, open(path, "w"), indent=1)
    print(f"wrote {path}: {len(rows)} quarters {rows[0]['label']} to {rows[-1]['label']}")


if __name__ == "__main__":
    main()

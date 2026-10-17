"""Build data/TKO.json: UFC segment direct operating costs and event counts, pulled from
TKO Group Holdings' SEC filings (10-K, 10-Q, and the 2023 S-1 for pre-merger Zuffa years).

Every number is parsed from the filing text with a regex; nothing is typed in by hand
except the two 2020/2021 event counts, which the S-1 states only in prose (and are checked
against the regex-matched sentences below).

Usage: python3 extract_tko_ufc.py
"""
import json
import os
import re
from datetime import date

import edgar

CIK = 1973266
NUM = r"\(?\$?\s?([\d,]+\.?\d*)\s?\)?"


def nums(s):
    return [float(x.replace(",", "")) for x in re.findall(r"[\d,]+\.\d+|[\d,]+", s)]


def ufc_table(text):
    """Return (direct operating cost columns, total-events columns) from the UFC segment table."""
    m = re.search(r"UFC The following table sets forth our UFC segment results for the", text)
    if not m:
        raise ValueError("UFC segment table not found")
    block = text[m.start(): m.start() + 3000]
    doc = re.search(r"Direct operating costs ((?:\$ ?[\d,\.]+ ?){2,4})", block)
    ev = re.search(r"Total events ((?:\d+ ){2,4})", block)
    return nums(doc.group(1)), [int(x) for x in nums(ev.group(1))], block


def quarter_label(end):
    y, mo = int(end[:4]), int(end[5:7])
    return f"Q{(mo - 1) // 3 + 1} {y}"


def qbounds(y, q):
    start = date(y, 3 * q - 2, 1)
    end = {1: date(y, 3, 31), 2: date(y, 6, 30), 3: date(y, 9, 30), 4: date(y, 12, 31)}[q]
    return start.isoformat(), end.isoformat()


def main():
    subs = edgar.submissions(CIK)
    r = subs["filings"]["recent"]
    filings = [dict(form=f, accn=a, doc=d, period=p, filed=fd)
               for f, a, d, p, fd in zip(r["form"], r["accessionNumber"], r["primaryDocument"],
                                         r["reportDate"], r["filingDate"])
               if f in ("10-K", "10-Q", "S-1")][::-1]  # oldest first: cite the original filing

    quarters = {}   # (year, q) -> {cost, events, source}
    annual = {}     # year -> {cost, events, source}
    ytd9 = {}       # year -> (cost, events) for nine months ended Sep 30
    checks = []

    def src(f, note):
        return {"form": f["form"], "period": f["period"] or "n/a", "filed": f["filed"],
                "accession": f["accn"], "url": edgar.filing_url(CIK, f["accn"], f["doc"]), "note": note}

    def put(store, key, cost, events, source):
        if key in store:  # same period reported in two filings: must agree
            old = store[key]
            if abs(old["cost"] - cost) > 0.15 or old["events"] != events:
                raise ValueError(f"Mismatch for {key}: {old} vs {cost},{events}")
            checks.append(f"{key}: {source['form']} {source['period']} matches {old['source']['form']} {old['source']['period']}")
            return
        store[key] = {"cost": cost, "events": events, "source": source}

    s1 = None
    for f in filings:
        if f["form"] == "S-1":
            s1 = f
            continue
        text = edgar.filing_text(CIK, f["accn"], f["doc"])
        cost, events, _ = ufc_table(text)
        y, mo = int(f["period"][:4]), int(f["period"][5:7])
        if f["form"] == "10-K":
            put(annual, y, cost[0], events[0], src(f, "UFC segment table, MD&A"))
            put(annual, y - 1, cost[1], events[1], src(f, "UFC segment table, MD&A (prior-year column)"))
        else:
            q = (mo - 1) // 3 + 1
            put(quarters, (y, q), cost[0], events[0], src(f, "UFC segment table, MD&A (three months)"))
            put(quarters, (y - 1, q), cost[1], events[1], src(f, "UFC segment table, MD&A (prior-year three months)"))
            if q == 3:
                ytd9[y] = (cost[2], events[2], src(f, "nine months"))
                ytd9[y - 1] = (cost[3], events[3], src(f, "nine months, prior-year column"))

    # Pre-merger years (Zuffa Parent, LLC = UFC) from the S-1 financial statements.
    t = edgar.filing_text(CIK, s1["accn"], s1["doc"])
    m = re.search(r"ZUFFA PARENT, LLC CONSOLIDATED STATEMENTS OF OPERATIONS \(In thousands\) Year Ended "
                  r"December 31, 2022 2021 2020 .{0,80}?Direct operating costs \(2\) ([\d,]+) ([\d,]+) ([\d,]+)", t)
    c22, c21, c20 = [v / 1000 for v in nums(" ".join(m.groups()))]
    m6 = re.search(r"Six Months Ended June 30, 2023 2022 Revenue \(1\) .{0,60}?Direct operating costs \(2\) "
                   r"([\d,]+) ([\d,]+)", t)
    h1_23, h1_22 = [v / 1000 for v in nums(" ".join(m6.groups()))]
    # Event counts for 2020 and 2021 are given only in MD&A prose, relative to the prior year.
    fewer = re.search(r"holding one fewer event", t)
    more = re.search(r"\$58\.3 million from holding two additional events", t)
    assert fewer and more, "S-1 event-count sentences not found"
    e22 = annual[2022]["events"]
    e21 = e22 + 1   # "2022 ... holding one fewer event" than 2021
    e20 = e21 - 2   # "2021 ... holding two additional events" than 2020
    s1_note = ("Zuffa Parent, LLC (UFC) audited statements in TKO S-1. Event count from MD&A prose: "
               "2022 had 'one fewer event' than 2021; 2021 had 'two additional events' vs 2020.")
    put(annual, 2022, round(c22, 1), e22, src(s1, "Zuffa Parent statements of operations"))
    annual[2021] = {"cost": c21, "events": e21, "source": src(s1, s1_note)}
    annual[2020] = {"cost": c20, "events": e20, "source": src(s1, s1_note)}

    # Derive periods the filings report only as remainders.
    for y in sorted(annual):
        if y in ytd9 and (y, 4) not in quarters:
            c9, e9, s9 = ytd9[y]
            src4 = dict(annual[y]["source"])
            src4["note"] = f"Derived: FY{y} (10-K) minus nine months (10-Q {s9['period']})"
            src4["derived_from"] = [annual[y]["source"]["url"], s9["url"]]
            quarters[(y, 4)] = {"cost": round(annual[y]["cost"] - c9, 1), "events": annual[y]["events"] - e9,
                                "source": src4}
    c9, e9, s9 = ytd9[2022]
    h1_22_events = e9 - quarters[(2022, 3)]["events"]
    assert abs((c9 - quarters[(2022, 3)]["cost"]) - h1_22) < 0.2, "H1 2022 cross-check failed"
    checks.append(f"H1 2022: S-1 cost {h1_22:.1f} = 9M'22 {c9} - Q3'22 {quarters[(2022, 3)]['cost']}")

    def row(label, start, end, rec, kind):
        return {"label": label, "start": start, "end": end, "kind": kind,
                "cost": round(rec["cost"], 3), "units": rec["events"], "source": rec["source"]}

    annual_rows = [row(str(y), f"{y}-01-01", f"{y}-12-31", annual[y], "year") for y in sorted(annual)]
    q_rows = [row(f"Q{q} {y}", *qbounds(y, q), quarters[(y, q)], "quarter") for (y, q) in sorted(quarters)]
    h1 = {"cost": h1_22, "events": h1_22_events,
          "source": {**src(s1, "Six months ended June 30, 2022 (Zuffa Parent, unaudited). Events = 9M'22 (32) minus Q3'22 (11), from 10-Q 2023-09-30."),
                     "derived_from": [ytd9[2022][2]["url"]]}}
    # Longest gap-free series: 2020, 2021 annual -> H1 2022 -> every quarter from Q3 2022 on.
    mixed = [r for r in annual_rows if r["label"] in ("2020", "2021")]
    mixed.append(row("H1 2022", "2022-01-01", "2022-06-30", h1, "half"))
    mixed += [r for r in q_rows if r["start"] >= "2022-07-01"]

    cpi = edgar.cpi_monthly(2019, date.today().year)
    out = {
        "ticker": "TKO",
        "company": "TKO Group Holdings, Inc. (NYSE: TKO)",
        "segment": "UFC segment",
        "cik": CIK,
        "cost_label": "UFC direct operating costs",
        "cost_unit": "USD millions",
        "unit_label": "live event",
        "unit_label_plural": "live events",
        "units_type": "direct",
        "units_note": ("Direct unit count: total UFC events (numbered events + Fight Nights) as disclosed in the "
                       "'UFC Operating Metrics' table of each 10-K/10-Q. No revenue proxy needed."),
        "cost_note": ("Direct operating costs = athlete costs, production, venue, marketing and event costs "
                      "(TKO's closest analog to COGS; TKO has no 'cost of revenue' line). Excludes SG&A and D&A."),
        "series": {
            "mixed": {"name": "Max detail: 2020–21 annual, H1 2022, then quarterly", "rows": mixed},
            "quarterly": {"name": "Quarterly only (Q1 2023 on)", "rows": [r for r in q_rows if r["start"] >= "2023-01-01"]},
            "annual": {"name": "Annual (10-K / S-1)", "rows": annual_rows},
        },
        "default_series": "mixed",
        "cross_checks": checks,
        "cpi": cpi,
        "generated": date.today().isoformat(),
    }
    path = os.path.join(edgar.ROOT, "data", "TKO.json")
    json.dump(out, open(path, "w"), indent=1)
    print(f"wrote {path}")
    for r in mixed:
        print(f"  {r['label']:8} cost {r['cost']:8.1f}  events {r['units']:3}  {r['source']['form']} {r['source']['period']}")
    print(f"  {len(checks)} cross-filing checks passed")


if __name__ == "__main__":
    main()

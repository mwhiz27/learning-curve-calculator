"""Inline every data/<TICKER>.json (plus context.json) into template.html -> dist/index.html.

Usage: python3 build.py
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
context = json.load(open(os.path.join(ROOT, "context.json")))
datasets = {}
for path in sorted(glob.glob(os.path.join(ROOT, "data", "*.json"))):
    d = json.load(open(path))
    d["context"] = context.get(d["ticker"], {})
    datasets[d["ticker"]] = d

order = ["TKO"] + [t for t in datasets if t != "TKO"]
payload = json.dumps({t: datasets[t] for t in order if t in datasets}, separators=(",", ":"))
html = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
html = html.replace("/*__DATA__*/null", payload.replace("</", "<\\/"))
os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
out = os.path.join(ROOT, "dist", "index.html")
open(out, "w", encoding="utf-8").write(html)
print(f"wrote {out} ({len(html) // 1024} KB) with datasets: {', '.join(order)}")

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.munpia.com/best/plsa.eachtoday"
OUT = Path("data/data.json")
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.munpia.com/"
}

def clean(x):
    return re.sub(r"\s+", " ", x or "").strip()

r = requests.get(URL, headers=HEADERS, timeout=30)
r.raise_for_status()
soup = BeautifulSoup(r.text, "html.parser")

results = []

for tag in soup.find_all(["li", "article", "div"]):
    text = clean(tag.get_text(" ", strip=True))
    m = re.match(r"^(\d{1,3})\s+", text)

    if not m:
        continue

    rank = int(m.group(1))
    if not 1 <= rank <= 200:
        continue

    a = tag.find("a", href=True)
    if not a:
        continue

    title = clean(a.get_text(" ", strip=True))
    if not title:
        continue

    results.append({
        "rank": rank,
        "title": title
    })

by_rank = {}
for x in results:
    if x["rank"] not in by_rank:
        by_rank[x["rank"]] = x

stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

snapshot = {
    "captured_at_kst": stamp,
    "count": len(by_rank),
    "items": [by_rank[n] for n in sorted(by_rank)]
}

OUT.parent.mkdir(parents=True, exist_ok=True)

try:
    old = json.loads(OUT.read_text(encoding="utf-8"))
    if not isinstance(old, list):
        old = []
except Exception:
    old = []

old.append(snapshot)
old = old[-720:]

OUT.write_text(
    json.dumps(old, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"Saved {len(by_rank)} ranks at {stamp}")

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://www.munpia.com/best/plsa.eachtoday?displayType=GRID"
OUT = Path("data/data.json")
KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_metrics(text):
    """문피아 카드/목록의 '시간'과 '지수'를 읽는다."""
    text = clean(text)

    # 상단 1~5위 카드: '시간20 지수70,610'
    m = re.search(r"시간\s*(\d{1,2})\s*지수\s*([\d,]+)", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))

    # 6~200위 표: 끝부분이 '... 12 39,130', 또는 '... 12 39,130 NEW/3'
    m = re.search(r"\s(\d{1,2})\s+([\d,]+)(?:\s+(?:NEW|[-+]?\d+))?\s*$", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))

    return None, None

r = requests.get(URL, headers=HEADERS, timeout=30)
r.raise_for_status()
soup = BeautifulSoup(r.text, "html.parser")

items = []
seen = set()

# 작품 링크는 현재 페이지에서 순위 순서대로 등장한다.
for a in soup.find_all("a", href=True):
    href = a.get("href", "")
    if "/novel/detail/" not in href:
        continue

    full_url = urljoin(URL, href)
    novel_id = full_url.rstrip("/").split("/")[-1].split("?")[0]

    if not novel_id.isdigit() or novel_id in seen:
        continue

    raw = clean(a.get_text(" ", strip=True))
    if not raw:
        continue

    seen.add(novel_id)
    hours, score = parse_metrics(raw)

    items.append({
        "rank": len(items) + 1,
        "novel_id": novel_id,
        "url": full_url,
        "hours_after_upload": hours,
        "score": score,
        "raw": raw,
    })

    if len(items) == 200:
        break

if len(items) < 180:
    raise RuntimeError(
        f"Only {len(items)} unique ranked novels found; Munpia HTML may have changed."
    )

# 지수 파싱이 거의 안 된 경우 성공 처리하지 않는다.
parsed_scores = sum(1 for x in items if x["score"] is not None)
if parsed_scores < 180:
    raise RuntimeError(
        f"Found {len(items)} novels, but parsed scores for only {parsed_scores}."
    )

stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
snapshot = {
    "captured_at_kst": stamp,
    "count": len(items),
    "items": items,
}

OUT.parent.mkdir(parents=True, exist_ok=True)

try:
    old = json.loads(OUT.read_text(encoding="utf-8"))
    if not isinstance(old, list):
        old = []
except Exception:
    old = []

old.append(snapshot)
old = old[-720:]  # 시간당 1회 기준 약 30일

OUT.write_text(
    json.dumps(old, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(
    f"Saved {len(items)} ranks / {parsed_scores} scores at {stamp}"
)

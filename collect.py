import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://www.munpia.com/best/plsa.eachtoday"
OUT = Path("data/data.json")
KST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

r = requests.get(URL, headers=HEADERS, timeout=30)
r.raise_for_status()
soup = BeautifulSoup(r.text, "html.parser")

# 문피아 베스트 페이지는 1~5위와 6~200위의 화면 구조가 다르다.
# 대신 모든 작품 링크(/novel/detail/...)는 순위 순서대로 등장하므로
# 작품 링크를 중복 제거한 뒤 등장 순서 자체를 순위로 사용한다.
items = []
seen = set()

for a in soup.find_all("a", href=True):
    href = a.get("href", "")
    if "/novel/detail/" not in href:
        continue

    full_url = urljoin(URL, href)
    novel_id = full_url.rstrip("/").split("/")[-1].split("?")[0]
    if not novel_id.isdigit() or novel_id in seen:
        continue

    title = " ".join(a.stripped_strings).strip()
    if not title:
        title = (a.get("title") or "").strip()
    if not title:
        continue

    seen.add(novel_id)
    items.append({
        "rank": len(items) + 1,
        "title": title,
        "novel_id": novel_id,
        "url": full_url,
    })

    if len(items) == 200:
        break

if len(items) < 180:
    raise RuntimeError(
        f"Only {len(items)} unique ranked novels found; Munpia HTML may have changed."
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

# 매시간 1회 기준 약 30일치
old = old[-720:]

OUT.write_text(
    json.dumps(old, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"Saved {len(items)} ranks at {stamp}")

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = "https://www.munpia.com/best/today?displayType=GRID"
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
    """
    무료 투데이베스트의 '시간'과 '조회'를 읽는다.
    조회 = 사용자가 원하는 무료 투데이베스트 24시간 인증조회수
    """
    text = clean(text)

    # 상단 1~5위 카드: 예) '시간22 조회10,048'
    m = re.search(r"시간\s*(\d{1,2})\s*조회\s*([\d,]+)", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))

    # 6~200위 표: 예) '... 15 4,881 1' 또는 '... 21 195 NEW'
    m = re.search(r"\s(\d{1,2})\s+([\d,]+)(?:\s+(?:NEW|[-+]?\d+))?\s*$", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))

    return None, None

r = requests.get(URL, headers=HEADERS, timeout=30)
r.raise_for_status()
soup = BeautifulSoup(r.text, "html.parser")

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

    # 링크 자체 텍스트보다 주변 컨테이너의 텍스트가 시간/조회까지 포함할 가능성이 높다.
    candidates = []
    node = a
    for _ in range(6):
        if node is None:
            break
        txt = clean(node.get_text(" ", strip=True))
        if txt:
            candidates.append(txt)
        node = node.parent

    hours = views = None
    raw = ""
    for txt in candidates:
        h, v = parse_metrics(txt)
        if h is not None and v is not None:
            hours, views, raw = h, v, txt
            break

    if not raw:
        raw = clean(a.get_text(" ", strip=True))

    seen.add(novel_id)
    items.append({
        "rank": len(items) + 1,
        "novel_id": novel_id,
        "url": full_url,
        "hours_after_upload": hours,
        "score": views,
        "views_24h_verified": views,
        "raw": raw,
    })

    if len(items) == 200:
        break

if len(items) < 180:
    raise RuntimeError(
        f"Only {len(items)} unique ranked novels found; Munpia HTML may have changed."
    )

parsed = sum(1 for x in items if x["views_24h_verified"] is not None)
if parsed < 180:
    raise RuntimeError(
        f"Found {len(items)} novels, but parsed verified views for only {parsed}."
    )

stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
snapshot = {
    "captured_at_kst": stamp,
    "count": len(items),
    "metric": "free_today_verified_views_24h",
    "items": items,
}

OUT.parent.mkdir(parents=True, exist_ok=True)

try:
    old = json.loads(OUT.read_text(encoding="utf-8"))
    if not isinstance(old, list):
        old = []
except Exception:
    old = []

# 예전 유료 지수 데이터와 섞이지 않도록,
# 무료 투베 인증조회수 데이터만 남긴다.
old = [s for s in old if isinstance(s, dict) and s.get("metric") == "free_today_verified_views_24h"]

old.append(snapshot)
old = old[-720:]  # 약 30일

OUT.write_text(
    json.dumps(old, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(
    f"Saved {len(items)} ranks / {parsed} verified views at {stamp}"
)

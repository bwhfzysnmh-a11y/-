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
    text = clean(text)

    # 상단 1~5위 카드
    m = re.search(r"시간\s*(\d{1,2})\s*조회\s*([\d,]+)", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))

    # 6~200위 표
    m = re.search(r"\s(\d{1,2})\s+([\d,]+)(?:\s+(?:NEW|[-+]?\d+))?\s*$", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))

    return None, None

def parse_rank(text):
    text = clean(text)

    # 상단 카드: '1위', '2위' ...
    m = re.search(r"\b([1-5])\s*위\b", text)
    if m:
        return int(m.group(1))

    # 표 행: 맨 앞의 순위 숫자
    m = re.match(r"^\s*(\d{1,3})\b", text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 200:
            return n

    return None

r = requests.get(URL, headers=HEADERS, timeout=30)
r.raise_for_status()
soup = BeautifulSoup(r.text, "html.parser")

items_by_rank = {}
seen_novels = set()

for a in soup.find_all("a", href=True):
    href = a.get("href", "")
    if "/novel/detail/" not in href:
        continue

    full_url = urljoin(URL, href)
    novel_id = full_url.rstrip("/").split("/")[-1].split("?")[0]

    if not novel_id.isdigit() or novel_id in seen_novels:
        continue

    candidates = []
    node = a
    for _ in range(8):
        if node is None:
            break
        txt = clean(node.get_text(" ", strip=True))
        if txt:
            candidates.append(txt)
        node = node.parent

    rank = hours = views = None
    raw = ""

    # 가장 가까운 컨테이너부터 실제 순위 + 시간/조회가 같이 있는 곳을 찾는다.
    for txt in candidates:
        rr = parse_rank(txt)
        hh, vv = parse_metrics(txt)
        if rr is not None and hh is not None and vv is not None:
            rank, hours, views, raw = rr, hh, vv, txt
            break

    # 일부 상단 카드에서 순위 텍스트와 시간/조회가 서로 다른 부모에 있을 수 있어 보완
    if rank is None:
        for txt in candidates:
            rr = parse_rank(txt)
            if rr is not None:
                rank = rr
                break

    if hours is None or views is None:
        for txt in candidates:
            hh, vv = parse_metrics(txt)
            if hh is not None and vv is not None:
                hours, views, raw = hh, vv, txt
                break

    if rank is None:
        continue

    seen_novels.add(novel_id)

    # 같은 순위가 중복 탐지되면 처음 제대로 잡힌 항목 유지
    if rank not in items_by_rank:
        items_by_rank[rank] = {
            "rank": rank,
            "novel_id": novel_id,
            "url": full_url,
            "hours_after_upload": hours,
            "score": views,
            "views_24h_verified": views,
            "raw": raw or clean(a.get_text(" ", strip=True)),
        }

# 실제 순위 기준으로 정렬
items = [items_by_rank[r] for r in sorted(items_by_rank)]

parsed = sum(1 for x in items if x["views_24h_verified"] is not None)

if 200 not in items_by_rank:
    raise RuntimeError(
        f"Rank 200 was not found. Parsed actual ranks: {len(items_by_rank)}"
    )

if len(items_by_rank) < 190:
    raise RuntimeError(
        f"Only {len(items_by_rank)} actual ranks found; Munpia HTML may have changed."
    )

if parsed < 190:
    raise RuntimeError(
        f"Found {len(items)} ranked novels, but parsed verified views for only {parsed}."
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

# 무료 투베 인증조회수 기록만 유지
old = [
    s for s in old
    if isinstance(s, dict)
    and s.get("metric") == "free_today_verified_views_24h"
]

old.append(snapshot)
old = old[-720:]

OUT.write_text(
    json.dumps(old, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(
    f"Saved {len(items)} actual ranks / {parsed} verified views "
    f"(rank 200={items_by_rank[200]['views_24h_verified']}) at {stamp}"
)

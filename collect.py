import json
import os
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
    m = re.search(r"시간\s*(\d{1,2})\s*조회\s*([\d,]+)", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))
    m = re.search(r"\s(\d{1,2})\s+([\d,]+)(?:\s+(?:NEW|[-+]?\d+))?\s*$", text)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))
    return None, None

def parse_rank(text):
    text = clean(text)
    m = re.search(r"\b([1-5])\s*위\b", text)
    if m:
        return int(m.group(1))
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

    for txt in candidates:
        rr = parse_rank(txt)
        hh, vv = parse_metrics(txt)
        if rr is not None and hh is not None and vv is not None:
            rank, hours, views, raw = rr, hh, vv, txt
            break

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

items = [items_by_rank[r] for r in sorted(items_by_rank)]
parsed = sum(1 for x in items if x["views_24h_verified"] is not None)

# 동률 때문에 일부 순위 번호(예: 120위, 200위)가 건너뛰어질 수 있음.
# 200위가 정확히 없어도 실제 순위가 190개 이상이면 정상 데이터로 저장.
if len(items_by_rank) < 190:
    raise RuntimeError(
        f"Only {len(items_by_rank)} actual ranks found; Munpia HTML may have changed."
    )

if parsed < 190:
    raise RuntimeError(
        f"Found {len(items)} ranked novels, but parsed verified views for only {parsed}."
    )

now_kst = datetime.now(KST)
stamp = now_kst.strftime("%Y-%m-%d %H:%M:%S")

OUT.parent.mkdir(parents=True, exist_ok=True)

try:
    old = json.loads(OUT.read_text(encoding="utf-8"))
    if not isinstance(old, list):
        old = []
except Exception:
    old = []

old = [
    s for s in old
    if isinstance(s, dict)
    and s.get("metric") == "free_today_verified_views_24h"
]

def parse_kst(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except Exception:
        return None

def scheduled_slot(t):
    # 매시간 :15를 해당 시간대 슬롯으로 사용.
    # 00:15부터는 새 날짜/새 요일.
    base = t.replace(minute=15, second=0, microsecond=0)
    if t.minute < 15:
        base -= timedelta(hours=1)
    return base

current_slot = scheduled_slot(now_kst)
slot = current_slot

# 실패한 GitHub Action을 Re-run한 경우 최근 누락 시간대를 자동 복구.
# 예: 22:15 실패 -> 재실행 시 slot_at_kst = 22:15
run_attempt = int(os.getenv("GITHUB_RUN_ATTEMPT", "1") or "1")
if run_attempt > 1 and old:
    existing_slots = set()
    for s in old:
        raw = s.get("slot_at_kst") or s.get("captured_at_kst")
        d = parse_kst(raw)
        if d:
            existing_slots.add(scheduled_slot(d).strftime("%Y-%m-%d %H:%M:%S"))

    probe = current_slot - timedelta(hours=1)
    for _ in range(48):
        key = probe.strftime("%Y-%m-%d %H:%M:%S")
        if key not in existing_slots:
            slot = probe
            break
        probe -= timedelta(hours=1)

snapshot = {
    "captured_at_kst": stamp,
    "slot_at_kst": slot.strftime("%Y-%m-%d %H:%M:%S"),
    "count": len(items),
    "metric": "free_today_verified_views_24h",
    "items": items,
}

old.append(snapshot)
old = old[-720:]

OUT.write_text(
    json.dumps(old, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

rank200 = items_by_rank.get(200)
rank200_text = (
    str(rank200["views_24h_verified"])
    if rank200 and rank200["views_24h_verified"] is not None
    else "skipped"
)

print(
    f"Saved {len(items)} actual ranks / {parsed} verified views "
    f"(rank 200={rank200_text}) captured={stamp} slot={snapshot['slot_at_kst']}"
)

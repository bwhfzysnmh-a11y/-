import json
import os
import re
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

TODAY_URL = "https://www.munpia.com/best/today?displayType=GRID"
NEW_MOBILE_URL = "https://m.munpia.com/mobile/extra/rankNovels?section=new.novel.today"
MODE = os.getenv("MUNPIA_BEST_MODE", "today")
LEGACY_OUT = Path("data/new/latest.json") if MODE == "new" else Path("data/data.json")
ARCHIVE_ROOT = Path("data/new/archive") if MODE == "new" else Path("data/today/archive")
KST = timezone(timedelta(hours=9))
HEADERS = {"User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"),"Accept-Language":"ko-KR,ko;q=0.9,en;q=0.8"}

def clean(s): return re.sub(r"\s+", " ", s or "").strip()
def parse_metrics(text):
    text=clean(text);m=re.search(r"시간\s*(\d{1,2})\s*조회\s*([\d,]+)",text)
    if m:return int(m.group(1)),int(m.group(2).replace(",",""))
    m=re.search(r"\s(\d{1,2})\s+([\d,]+)(?:\s+(?:NEW|[-+]?\d+))?\s*$",text)
    return (int(m.group(1)),int(m.group(2).replace(",",""))) if m else (None,None)
def parse_rank(text):
    text=clean(text);m=re.search(r"\b([1-5])\s*위\b",text)
    if m:return int(m.group(1))
    m=re.match(r"^\s*(\d{1,3})\b",text)
    if m and 1<=int(m.group(1))<=200:return int(m.group(1))
    return None
def _candidate_texts(a,depth=8):
    out=[];node=a
    for _ in range(depth):
        if node is None:break
        txt=clean(node.get_text(" ",strip=True))
        if txt and txt not in out:out.append(txt)
        node=node.parent
    return out

def collect_today_items():
    r=requests.get(TODAY_URL,headers=HEADERS,timeout=30);r.raise_for_status();soup=BeautifulSoup(r.text,"html.parser")
    items_by_rank={};seen=set()
    for a in soup.find_all("a",href=True):
        href=a.get("href","")
        if "/novel/detail/" not in href:continue
        full=urljoin(TODAY_URL,href);nid=full.rstrip("/").split("/")[-1].split("?")[0]
        if not nid.isdigit() or nid in seen:continue
        cand=_candidate_texts(a);rank=hours=views=None;raw=""
        for txt in cand:
            rr=parse_rank(txt);hh,vv=parse_metrics(txt)
            if rr is not None and hh is not None and vv is not None:rank,hours,views,raw=rr,hh,vv,txt;break
        if rank is None:
            for txt in cand:
                rr=parse_rank(txt)
                if rr is not None:rank=rr;break
        if hours is None or views is None:
            for txt in cand:
                hh,vv=parse_metrics(txt)
                if hh is not None and vv is not None:hours,views,raw=hh,vv,txt;break
        if rank is None:continue
        seen.add(nid)
        if rank not in items_by_rank:items_by_rank[rank]={"rank":rank,"novel_id":nid,"title":clean(a.get_text(" ",strip=True)) or None,"url":full,"hours_after_upload":hours,"score":views,"views_24h_verified":views,"raw":raw or clean(a.get_text(" ",strip=True))}
    items=[items_by_rank[r] for r in sorted(items_by_rank)];parsed=sum(x["views_24h_verified"] is not None for x in items)
    if len(items_by_rank)<190:raise RuntimeError(f"Only {len(items_by_rank)} actual Today ranks found; Munpia HTML may have changed.")
    if parsed<190:raise RuntimeError(f"Found {len(items)} Today novels, but parsed verified views for only {parsed}.")
    return items,items_by_rank,parsed

def _parse_mobile_new_entry(a,page_url):
    href=a.get("href","")
    if "/novel/detail/" not in href:return None
    full=urljoin(page_url,href);mid=re.search(r"/novel/detail/(\d+)",full)
    if not mid:return None
    rank=views=None;raw="";pat=re.compile(r"(?:^|\s)(\d{1,4})(?:\s+(?:NEW|[-+]?\d+))?\s*\(([\d,]+)\)")
    for txt in _candidate_texts(a,7):
        m=pat.search(txt)
        if m:rank=int(m.group(1));views=int(m.group(2).replace(",",""));raw=txt;break
    if rank is None or views is None:return None
    title=clean(a.get("title") or "") or clean(a.get_text(" ",strip=True)) or None
    return {"rank":rank,"novel_id":mid.group(1),"title":title,"url":full,"hours_after_upload":None,"score":views,"views_24h_verified":views,"raw":raw or title}

def collect_new_mobile_items():
    items_by_rank={};seen=set()
    for page in range(30):
        page_url=f"{NEW_MOBILE_URL}&page={page}";r=requests.get(page_url,headers=HEADERS,timeout=30);r.raise_for_status();soup=BeautifulSoup(r.text,"html.parser");added=0
        for a in soup.find_all("a",href=True):
            item=_parse_mobile_new_entry(a,page_url)
            if not item:continue
            rank=item["rank"];nid=item["novel_id"]
            if nid in seen or rank in items_by_rank:continue
            seen.add(nid);items_by_rank[rank]=item;added+=1
        if added==0:break
        print(f"Mobile New Best page {page}: +{added}, max rank={max(items_by_rank)}")
    items=[items_by_rank[r] for r in sorted(items_by_rank)];parsed=sum(x["views_24h_verified"] is not None for x in items)
    if len(items)<25:raise RuntimeError(f"Only {len(items)} mobile New Best ranks found; mobile HTML may have changed.")
    if parsed!=len(items):raise RuntimeError(f"Found {len(items)} mobile New Best novels, but parsed verified views for only {parsed}.")
    return items,items_by_rank,parsed

if MODE=="new":items,items_by_rank,parsed=collect_new_mobile_items()
else:items,items_by_rank,parsed=collect_today_items()

now_kst = datetime.now(KST)
stamp = now_kst.strftime("%Y-%m-%d %H:%M:%S")

ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)

def load_snapshots(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [
            x for x in data
            if isinstance(x, dict)
            and x.get("metric") == ("free_new_verified_views_24h" if MODE == "new" else "free_today_verified_views_24h")
        ]
    except Exception:
        return []

def parse_kst(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except Exception:
        return None

def scheduled_slot(t):
    # 투베는 매시 :15, 신베는 매시 :05를 해당 시간대 슬롯으로 사용.
    slot_minute = 5 if MODE == "new" else 15
    base = t.replace(minute=slot_minute, second=0, microsecond=0)
    if t.minute < slot_minute:
        base -= timedelta(hours=1)
    return base

current_slot = scheduled_slot(now_kst)
slot = current_slot

# 누락 슬롯 판단에는 모든 월별 보관 파일을 확인한다.
all_old = []
for path in sorted(ARCHIVE_ROOT.glob("*/*.json")):
    all_old.extend(load_snapshots(path))

# 처음 구조를 바꿀 때 기존 data/data.json의 과거 기록도 함께 참고한다.
legacy_old = load_snapshots(LEGACY_OUT)
if legacy_old:
    known = {
        (x.get("slot_at_kst") or x.get("captured_at_kst"), x.get("captured_at_kst"))
        for x in all_old
    }
    for x in legacy_old:
        key = (x.get("slot_at_kst") or x.get("captured_at_kst"), x.get("captured_at_kst"))
        if key not in known:
            all_old.append(x)
            known.add(key)

# 실패한 GitHub Action을 Re-run한 경우 최근 누락 시간대를 자동 복구.
run_attempt = int(os.getenv("GITHUB_RUN_ATTEMPT", "1") or "1")
if run_attempt > 1 and all_old:
    existing_slots = set()
    for old_snapshot in all_old:
        raw = old_snapshot.get("slot_at_kst") or old_snapshot.get("captured_at_kst")
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
    "metric": ("free_new_verified_views_24h" if MODE == "new" else "free_today_verified_views_24h"),
    "items": items,
}

# 실제로 복구된 슬롯의 연/월 파일에 저장한다.
archive_file = (
    ARCHIVE_ROOT
    / slot.strftime("%Y")
    / f"{slot.strftime('%m')}.json"
)
archive_file.parent.mkdir(parents=True, exist_ok=True)

month_data = load_snapshots(archive_file)

# 첫 실행 때 기존 단일 data.json에 있던 같은 달 기록을 월별 파일로 이관한다.
if legacy_old:
    existing = {
        (x.get("slot_at_kst") or x.get("captured_at_kst"), x.get("captured_at_kst"))
        for x in month_data
    }
    for old_snapshot in legacy_old:
        raw = old_snapshot.get("slot_at_kst") or old_snapshot.get("captured_at_kst")
        d = parse_kst(raw)
        if d and d.strftime("%Y-%m") == slot.strftime("%Y-%m"):
            key = (raw, old_snapshot.get("captured_at_kst"))
            if key not in existing:
                month_data.append(old_snapshot)
                existing.add(key)

month_data.append(snapshot)
month_data.sort(
    key=lambda x: (
        x.get("slot_at_kst") or x.get("captured_at_kst") or "",
        x.get("captured_at_kst") or "",
    )
)

archive_file.write_text(
    json.dumps(month_data, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

# 현재 대시보드 호환용 파일.
# 사이트가 아직 data/data.json을 읽으므로 전체 누적본도 같이 갱신한다.
# 이후 index.html을 월별 archive를 읽도록 바꾸면 이 호환 파일은 제거 가능하다.
combined = []
for path in sorted(ARCHIVE_ROOT.glob("*/*.json")):
    combined.extend(load_snapshots(path))

combined.sort(
    key=lambda x: (
        x.get("slot_at_kst") or x.get("captured_at_kst") or "",
        x.get("captured_at_kst") or "",
    )
)

LEGACY_OUT.parent.mkdir(parents=True, exist_ok=True)
LEGACY_OUT.write_text(
    json.dumps(combined, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

max_rank = max(items_by_rank) if items_by_rank else 0
rank200 = items_by_rank.get(200)
rank200_text = str(rank200["views_24h_verified"]) if rank200 and rank200["views_24h_verified"] is not None else "skipped"
print(
    f"Saved {len(items)} actual ranks / {parsed} verified views "
    f"(max rank={max_rank}, rank 200={rank200_text}) captured={stamp} slot={snapshot['slot_at_kst']} archive={archive_file}"
)

# ---------------------------------------------------------------------------
# 내 작품 추적: 1화 '전체조회수' + 현재 최신화 정보
#
# - 인증조회수는 위 투베/신베 스냅샷에서만 사용한다.
# - 여기의 first_episode_views는 문피아 작품 API의 회차별 누적 viewCount,
#   즉 '전체조회수'이며 인증조회수로 표시하면 안 된다.
# - 투베(today) 작업에서만 실행해 작품당 매시간 1회 정도 기록한다.
# ---------------------------------------------------------------------------
MUNPIA_API_BASE = "https://www.munpia.com"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")


def _as_int(value, default=0):
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        return int(value)
    except (TypeError, ValueError):
        return default


def _munpia_datetime(value):
    """문피아 createdAt(타임존 없음=KST)을 aware datetime으로 변환."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "").split("+")[0].split(".")[0]
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=KST)
        except ValueError:
            pass
    return None


def _munpia_chapter_page(session, novel_id, page, size=100):
    url = f"{MUNPIA_API_BASE}/api/v1/pc/novel-detail/{novel_id}/chapters"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Origin": MUNPIA_API_BASE,
        "Referer": f"{MUNPIA_API_BASE}/novel/detail/{novel_id}",
    }
    resp = session.get(url, params={"page": page, "size": size}, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "M000_00000":
        raise RuntimeError(
            f"Munpia chapter API error novel={novel_id}: "
            f"{payload.get('code')} {payload.get('message', '')}"
        )
    return payload.get("result") or {}


def _episode_summary_for_work(session, novel_id):
    """첫 화와 최신 공개화를 찾는다. 긴 작품도 첫/끝 페이지만 요청한다."""
    size = 100
    first_page = _munpia_chapter_page(session, novel_id, 1, size)
    rows = list(first_page.get("list") or [])
    total = _as_int(first_page.get("total"), len(rows))
    if not rows:
        raise RuntimeError(f"No chapters found for novel={novel_id}")

    last_page_no = max(1, math.ceil(total / size)) if total else 1
    if last_page_no > 1:
        last_page = _munpia_chapter_page(session, novel_id, last_page_no, size)
        rows.extend(last_page.get("list") or [])

    # 같은 회차가 섞여 와도 한 번만 사용.
    unique = {}
    for row in rows:
        entry_id = _as_int(row.get("id"), 0)
        key = entry_id or ("num", _as_int(row.get("num"), 0), str(row.get("createdAt") or ""))
        unique[key] = row
    rows = list(unique.values())

    # 공지는 회차로 보지 않는다.
    normal = [r for r in rows if not bool(r.get("notice"))]
    if not normal:
        normal = rows

    # '1화'는 num == 1을 우선. 구작/특수작은 가장 이른 양수 회차로 대체.
    first_candidates = [r for r in normal if _as_int(r.get("num"), 0) == 1]
    if first_candidates:
        first_ep = first_candidates[0]
    else:
        positive = [r for r in normal if _as_int(r.get("num"), 0) > 0]
        if not positive:
            raise RuntimeError(f"No numbered chapters found for novel={novel_id}")
        first_ep = min(positive, key=lambda r: _as_int(r.get("num"), 10**9))

    # 예약글이 목록에 포함되더라도 현재 시각보다 미래인 회차는 최신화에서 제외.
    now = datetime.now(KST)
    published = []
    for row in normal:
        dt = _munpia_datetime(row.get("createdAt"))
        num = _as_int(row.get("num"), 0)
        if num > 0 and (dt is None or dt <= now):
            published.append((row, dt))
    if not published:
        raise RuntimeError(f"No published chapters found for novel={novel_id}")

    latest_ep, latest_dt = max(
        published,
        key=lambda pair: (
            _as_int(pair[0].get("num"), 0),
            pair[1] or datetime.min.replace(tzinfo=KST),
        ),
    )

    episode_views = {}
    for row in normal:
        num = _as_int(row.get("num"), 0)
        if num > 0:
            episode_views[str(num)] = _as_int(row.get("viewCount"), 0)

    return {
        "first_episode_views": _as_int(first_ep.get("viewCount"), 0),
        "latest_episode_no": _as_int(latest_ep.get("num"), 0),
        "latest_episode_views": _as_int(latest_ep.get("viewCount"), 0),
        "latest_episode_title": clean(str(latest_ep.get("title") or "")) or None,
        "latest_episode_published_at": latest_dt.isoformat() if latest_dt else None,
        "episode_views": episode_views,
    }


def collect_registered_work_snapshots():
    if MODE != "today":
        return
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        print("Work tracking skipped: Supabase environment variables are missing.")
        return

    sb_headers = {
        # 새 sb_secret_ 키는 JWT가 아니므로 Authorization Bearer가 아니라 apikey에 넣는다.
        "apikey": SUPABASE_SECRET_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    works_url = f"{SUPABASE_URL}/rest/v1/registered_works"
    resp = requests.get(
        works_url,
        headers=sb_headers,
        params={"select": "novel_id,novel_url", "active": "eq.true", "order": "novel_id.asc"},
        timeout=30,
    )
    resp.raise_for_status()
    works = resp.json()
    if not isinstance(works, list) or not works:
        print("Work tracking: no registered works yet.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": HEADERS["User-Agent"]})
    captured_at = datetime.now(timezone.utc).isoformat()
    rows_to_insert = []

    for work in works:
        novel_id = _as_int(work.get("novel_id"), 0)
        if novel_id <= 0:
            continue
        try:
            summary = _episode_summary_for_work(session, novel_id)
            rows_to_insert.append({
                "novel_id": novel_id,
                "captured_at": captured_at,
                **summary,
            })
            print(
                f"Work {novel_id}: 1화 전체조회수={summary['first_episode_views']} "
                f"최신화={summary['latest_episode_no']} 전체조회수={summary['latest_episode_views']}"
            )
        except Exception as exc:
            # 한 작품 실패가 투베 수집 전체를 실패시키지 않게 격리한다.
            print(f"Work tracking warning novel={novel_id}: {exc}")

    if not rows_to_insert:
        print("Work tracking: no snapshots to insert.")
        return

    insert_url = f"{SUPABASE_URL}/rest/v1/work_snapshots"
    insert_headers = dict(sb_headers)
    insert_headers["Prefer"] = "return=minimal"
    resp = requests.post(
        insert_url,
        headers=insert_headers,
        json=rows_to_insert,
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Work tracking: inserted {len(rows_to_insert)} snapshot(s) into Supabase.")


collect_registered_work_snapshots()

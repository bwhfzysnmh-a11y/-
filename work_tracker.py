import os, re, math
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
MUNPIA = "https://www.munpia.com"
TODAY_URL = MUNPIA + "/best/today?displayType=GRID"
NEW_URL = "https://m.munpia.com/mobile/extra/rankNovels?section=new.novel.today"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-8].rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

def clean(s): return re.sub(r"\s+", " ", s or "").strip()
def as_int(v, default=0):
    try: return int(str(v).replace(",", "").strip())
    except: return default

def parse_dt(v):
    if not v: return None
    text=str(v).strip().replace("Z", "").split("+")[0].split(".")[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S","%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M","%Y-%m-%d %H:%M","%Y-%m-%d"):
        try: return datetime.strptime(text,fmt).replace(tzinfo=KST)
        except ValueError: pass
    return None

def chapter_page(session, novel_id, page, size=100):
    url=f"{MUNPIA}/api/v1/pc/novel-detail/{novel_id}/chapters"
    h={"Accept":"application/json, text/plain, */*","Accept-Language":"ko-KR,ko;q=0.9","Origin":MUNPIA,"Referer":f"{MUNPIA}/novel/detail/{novel_id}"}
    r=session.get(url,params={"page":page,"size":size},headers=h,timeout=30); r.raise_for_status()
    payload=r.json()
    if payload.get("code") != "M000_00000": raise RuntimeError(f"Munpia API {payload.get('code')}")
    return payload.get("result") or {}

def episode_summary(session, novel_id):
    size=100; first=chapter_page(session,novel_id,1,size); rows=list(first.get("list") or [])
    total=as_int(first.get("total"),len(rows))
    if not rows: raise RuntimeError("no chapters")
    last_page=max(1,math.ceil(total/size)) if total else 1
    if last_page>1: rows.extend((chapter_page(session,novel_id,last_page,size).get("list") or []))
    unique={}
    for row in rows:
        key=as_int(row.get("id"),0) or ("num",as_int(row.get("num"),0),str(row.get("createdAt") or "")); unique[key]=row
    rows=list(unique.values()); normal=[r for r in rows if not bool(r.get("notice"))] or rows
    firsts=[r for r in normal if as_int(r.get("num"),0)==1]
    first_ep=firsts[0] if firsts else min([r for r in normal if as_int(r.get("num"),0)>0],key=lambda r:as_int(r.get("num"),10**9))
    now=datetime.now(KST); published=[]
    for row in normal:
        d=parse_dt(row.get("createdAt")); num=as_int(row.get("num"),0)
        if num>0 and (d is None or d<=now): published.append((row,d))
    latest, pub=max(published,key=lambda p:(as_int(p[0].get("num"),0),p[1] or datetime.min.replace(tzinfo=KST)))
    views={str(as_int(r.get("num"),0)):as_int(r.get("viewCount"),0) for r in normal if as_int(r.get("num"),0)>0}
    return {
        "first_episode_views":as_int(first_ep.get("viewCount"),0),
        "latest_episode_no":as_int(latest.get("num"),0),
        "latest_episode_views":as_int(latest.get("viewCount"),0),
        "latest_episode_title":clean(str(latest.get("title") or "")) or None,
        "latest_episode_published_at":pub.isoformat() if pub else None,
        "episode_views":views,
    }, pub

def candidate_texts(a, depth=8):
    out=[]; node=a
    for _ in range(depth):
        if node is None: break
        t=clean(node.get_text(" ",strip=True))
        if t and t not in out: out.append(t)
        node=node.parent
    return out

def today_auth(target_ids):
    r=requests.get(TODAY_URL,headers=HEADERS,timeout=30); r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser")
    found={}
    for a in soup.find_all("a",href=True):
        href=a.get("href",""); m=re.search(r"/novel/detail/(\d+)",href)
        if not m or m.group(1) not in target_ids: continue
        nid=m.group(1); rank=views=None
        for t in candidate_texts(a):
            rm=re.match(r"^\s*(\d{1,3})\b",t); vm=re.search(r"시간\s*(\d{1,2})\s*조회\s*([\d,]+)",t)
            if rm and vm: rank=int(rm.group(1)); views=int(vm.group(2).replace(",","")); break
        if views is not None: found[nid]=(views,"today",rank)
    return found

def new_auth(target_ids):
    found={}
    pat=re.compile(r"(?:^|\s)(\d{1,4})(?:\s+(?:NEW|[-+]?\d+))?\s*\(([\d,]+)\)")
    for page in range(8):
        url=f"{NEW_URL}&page={page}"; r=requests.get(url,headers=HEADERS,timeout=30)
        if r.status_code in (400,404): break
        r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser")
        for a in soup.find_all("a",href=True):
            m=re.search(r"/novel/detail/(\d+)",a.get("href",""))
            if not m or m.group(1) not in target_ids or m.group(1) in found: continue
            for t in candidate_texts(a,7):
                mm=pat.search(t)
                if mm: found[m.group(1)]=(int(mm.group(2).replace(",","")),"new",int(mm.group(1))); break
        if target_ids.issubset(found.keys()): break
    return found

def main():
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY: raise RuntimeError("Supabase secrets missing")
    sb={"apikey":SUPABASE_SECRET_KEY,"Accept":"application/json","Content-Type":"application/json"}
    r=requests.get(f"{SUPABASE_URL}/rest/v1/registered_works",headers=sb,params={"select":"novel_id,novel_url","active":"eq.true","order":"novel_id.asc"},timeout=30); r.raise_for_status(); works=r.json()
    if not works: print("No registered works"); return
    session=requests.Session(); session.headers.update(HEADERS); now=datetime.now(KST)
    prepared=[]; due_ids=set()
    for w in works:
        nid=str(as_int(w.get("novel_id"),0))
        if nid=="0": continue
        try:
            summary,pub=episode_summary(session,nid)
            if pub:
                age_min=(now-pub).total_seconds()/60
                target=pub+timedelta(hours=24); delta=(target-now).total_seconds()/60
                # 저장은 업로드 직후 기준값(최대 약 10분)과 24시간 목표 근처만.
                # 이렇게 해야 5분 실행이어도 DB가 불필요하게 커지지 않는다.
                if 0 <= age_min <= 10 or -5 <= delta <= 15:
                    prepared.append((nid,summary,pub))
                # 목표 15분 전부터 5분 후까지만 랭킹 인증값도 확인한다.
                if -5 <= delta <= 15: due_ids.add(nid)
        except Exception as e: print(f"work {nid} warning: {e}")
    auth={}
    if due_ids:
        try: auth.update(today_auth(due_ids))
        except Exception as e: print("today auth warning:",e)
        remaining=due_ids-set(auth)
        if remaining:
            try: auth.update(new_auth(remaining))
            except Exception as e: print("new auth warning:",e)
    captured=datetime.now(timezone.utc).isoformat(); rows=[]
    for nid,summary,pub in prepared:
        row={"novel_id":int(nid),"captured_at":captured,**summary,"auth_views":None,"auth_source":None,"auth_rank":None,"auth_observed_at":None}
        if nid in auth:
            v,src,rank=auth[nid]; row.update({"auth_views":v,"auth_source":src,"auth_rank":rank,"auth_observed_at":captured})
            print(f"24h auth candidate {nid}: {src} rank={rank} views={v}")
        rows.append(row)
    if rows:
        h=dict(sb); h["Prefer"]="return=minimal"
        r=requests.post(f"{SUPABASE_URL}/rest/v1/work_snapshots",headers=h,json=rows,timeout=30); r.raise_for_status()
        print(f"Inserted {len(rows)} work snapshot(s) at {captured}; due={len(due_ids)}")

if __name__=="__main__": main()

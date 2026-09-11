import json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL="https://www.munpia.com/best/plsa.eachtoday?displayType=GRID"
OUT=Path("data/data.json")
KST=timezone(timedelta(hours=9))
HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36","Accept-Language":"ko-KR,ko;q=0.9"}

def clean(x): return re.sub(r"\s+"," ",x or "").strip()

html=requests.get(URL,headers=HEADERS,timeout=30)
html.raise_for_status()
soup=BeautifulSoup(html.text,"html.parser")

rows=[]
for tr in soup.select("tr"):
    c=[clean(x.get_text(" ",strip=True)) for x in tr.select("th,td")]
    if c and re.fullmatch(r"\d{1,3}",c[0]):
        n=int(c[0])
        if 1<=n<=200: rows.append(c)

# 보조: li/article/div 안에 순위 텍스트가 있는 구조
if len(rows)<180:
    for tag in soup.find_all(["li","article","div"]):
        txt=clean(tag.get_text(" ",strip=True))
        m=re.match(r"^(\d{1,3})\s+",txt)
        if m and 1<=int(m.group(1))<=200:
            # 너무 큰 컨테이너는 제외
            if len(txt)<500:
                rows.append(txt.split(" "))

by={}
for c in rows:
    try:n=int(c[0])
    except:continue
    if n not in by:
        by[n]=c

if len(by)<180:
    raise RuntimeError(f"Only {len(by)} ranks parsed; Munpia HTML may have changed.")

stamp=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
new=[]
for n in sorted(by):
    c=by[n]
    new.append({
        "captured_at_kst":stamp,
        "rank":n,
        "title":c[1] if len(c)>1 else "",
        "author":c[2] if len(c)>2 else "",
        "genre":c[3] if len(c)>3 else "",
        "age":c[4] if len(c)>4 else "",
        "score":c[5] if len(c)>5 else "",
        "change":c[6] if len(c)>6 else ""
    })

old=json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
old.extend(new)
# 너무 커지지 않도록 최근 30일만 유지
old=old[-(200*24*30):]
OUT.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"saved {len(new)} rows at {stamp}")

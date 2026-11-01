#!/usr/bin/env python3
"""Collect independently sourced S&P 500 index 1-minute bars; never substitute XAUUSD."""
import datetime as dt, json, pathlib, urllib.request, urllib.parse
from zoneinfo import ZoneInfo
ROOT=pathlib.Path(__file__).resolve().parents[1]
out=ROOT/"sp500-reactions.json"
old=json.loads(out.read_text()) if out.exists() else {}
news=json.loads((ROOT/"news.json").read_text())
now=dt.datetime.now(dt.timezone.utc)
ny=ZoneInfo("America/New_York")
items={x["url"]:x for x in old.get("items",[]) if x.get("source")=="Yahoo Finance ^GSPC M1"}
checks={}
# Yahoo's public chart interface only provides a short 1-minute lookback.
url="https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?"+urllib.parse.urlencode({"interval":"1m","range":"7d"})
bars={}
try:
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=25) as response: data=json.load(response)
 result=data["chart"]["result"][0]
 quotes=result["indicators"]["quote"][0]
 for i,stamp in enumerate(result["timestamp"]):
  try:
   c,h,l=[float(quotes[k][i]) for k in ("close","high","low")]
   if 1000<c<20000 and l<=h: bars[int(stamp)//60]=(c,l,h)
  except (TypeError,ValueError,IndexError): continue
 checks["feed"]=f"{len(bars)} valid ^GSPC M1 bars"
except Exception as e: checks["feed"]=f"{type(e).__name__}: {str(e)[:180]}"
for e in news.get("items",[]):
 try:
  pub=dt.datetime.fromisoformat(e["published"].replace("Z","+00:00"))
  cat=e["category"]
  title=e.get("title","").lower()
  if cat in ("CPI","PPI","GDP","PCE","CLAIMS"): hour=8
  elif cat=="FOMC" and ("fomc statement" in title or "minutes of the federal open market committee" in title): hour=14
  else: continue
  local=pub.astimezone(ny)
  event=dt.datetime(local.year,local.month,local.day,hour,30 if hour==8 else 0,tzinfo=ny).astimezone(dt.timezone.utc)
  minute=int(event.timestamp())//60
  if event>now-dt.timedelta(minutes=35) or e["url"] in items: continue
  baseline=bars.get(minute-1)
  if baseline is None: continue
  spikes={};moves={}
  for n in (1,5,15,30):
   segment=[bars.get(minute+i) for i in range(n)]
   if any(x is None for x in segment):continue
   direction="UP" if segment[0][0]>baseline[0] else "DOWN" if segment[0][0]<baseline[0] else "FLAT"
   spikes[str(n)]={"up_points":round(max(0,max(x[2] for x in segment)-baseline[0]),3),"down_points":round(max(0,baseline[0]-min(x[1] for x in segment)),3),"first_minute_direction":direction}
   moves[str(n)]=round(segment[-1][0]-baseline[0],3)
  if "5" not in spikes:continue
  items[e["url"]]={"url":e["url"],"category":cat,"title":e["title"],"release_time_utc":event.isoformat(),"baseline":baseline[0],"spikes":spikes,"moves":moves,"source":"Yahoo Finance ^GSPC M1","unit":"index points","method_version":1}
 except (KeyError,ValueError,TypeError):continue
result={"updated_at":now.isoformat(),"market":"S&P 500 cash index (^GSPC), not broker US500 CFD","method":"Yahoo Finance ^GSPC 1-minute OHLC, short rolling history; pre-release close to 1/5/15/30-minute highs and lows, index points","items":sorted(items.values(),key=lambda x:x["release_time_utc"],reverse=True),"checks":checks}
out.write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({"verified":len(items),"checks":checks}))

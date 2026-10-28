#!/usr/bin/env python3
"""Calculate verified historical XAUUSD reactions using Dukascopy BID M1 candles."""
import datetime as dt, json, pathlib, urllib.request, lzma, struct, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
news=json.loads((ROOT/"news.json").read_text())
path=ROOT/"reactions.json"
old={}
if path.exists():
 try: old=json.loads(path.read_text())
 except (ValueError,OSError): pass
saved={x["url"]:x for x in old.get("items",[]) if x.get("url")}
dates={}
now=dt.datetime.now(dt.timezone.utc)
for e in news.get("items",[]):
 try: stamp=dt.datetime.fromisoformat(e["published"].replace("Z","+00:00"))
 except (ValueError,TypeError,AttributeError): continue
 if stamp>now-dt.timedelta(hours=3) or stamp<now-dt.timedelta(days=365*2): continue
 dates.setdefault(stamp.date(),[]).append((e,stamp))
# Process at most 4 new event dates per run, oldest first to build history incrementally.
todo=[(day,events) for day,events in sorted(dates.items(),reverse=True) if any(e["url"] not in saved for e,_ in events)][:4]
def candles(day):
 url=f"https://datafeed.dukascopy.com/datafeed/XAUUSD/{day.year}/{day.month-1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 SpikeHunterResearch"})
 with urllib.request.urlopen(req,timeout=25) as resp: raw=resp.read()
 if not raw: return {}
 blob=lzma.decompress(raw,format=lzma.FORMAT_ALONE)
 if len(blob)%24: raise ValueError("Invalid candle file length")
 out={}
 for sec,op,close,low,high,volume in struct.iter_unpack(">IIIIIf",blob):
  if sec>=86400 or not (100000<close<20000000): continue
  out[sec//60]=close/1000
 return out
checks={}
for day,events in todo:
 try:
  candles_today=candles(day)
  tomorrow=day+dt.timedelta(days=1)
  next_day=candles(tomorrow) if any(stamp.hour>=22 for _,stamp in events) else {}
  for e,stamp in events:
   minute=stamp.hour*60+stamp.minute
   # Use pre-announcement candle close as baseline, avoiding post-release leakage.
   base=candles_today.get(minute-1)
   if base is None: continue
   moves={}
   for n in (1,5,15,30,60):
    target=minute+n-1
    p=(candles_today if target<1440 else next_day).get(target%1440)
    moves[str(n)]=round(p-base,3) if p is not None else None
   if all(v is None for v in moves.values()): continue
   saved[e["url"]]={"url":e["url"],"category":e["category"],"title":e["title"],"published":e["published"],"baseline":base,"moves":moves,"source":"Dukascopy XAUUSD bid M1; baseline is pre-release minute close","unit":"USD/oz"}
  checks[str(day)]="ok"
 except Exception as exc: checks[str(day)]=str(exc)[:150]
 time.sleep(1)
out={"updated_at":now.isoformat(),"method":"Dukascopy XAUUSD BID M1. Difference between close of minute before release and close of minute at +1,+5,+15,+30,+60. UTC timestamps. No tick-level peak analysis.","items":sorted(saved.values(),key=lambda x:x["published"],reverse=True),"checks":checks}
path.write_text(json.dumps(out,indent=2)+"\n")
print(json.dumps({"reactions":len(saved),"checks":checks}))

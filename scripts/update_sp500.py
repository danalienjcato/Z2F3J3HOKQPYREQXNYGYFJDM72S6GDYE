#!/usr/bin/env python3
"""Backfill USA500 index reactions from Dukascopy M1 bid candles; never substitute Gold."""
import datetime as dt
import json
import lzma
import pathlib
import struct
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT=pathlib.Path(__file__).resolve().parents[1]
PATH=ROOT/"sp500-reactions.json"
NEWS=ROOT/"news.json"
now=dt.datetime.now(dt.timezone.utc)
ny=ZoneInfo("America/New_York")
old=json.loads(PATH.read_text()) if PATH.exists() else {}
news=json.loads(NEWS.read_text())
# Preserve cash-index observations but do not treat them as USA500 observations.
items={x["url"]:x for x in old.get("items",[]) if x.get("source")=="Dukascopy USA500IDXUSD BID M1" and x.get("method_version")==2}
checks={}
retry=old.get("retry",{})
events={}
def release(e):
    try: pub=dt.datetime.fromisoformat(e["published"].replace("Z","+00:00"))
    except (KeyError,TypeError,ValueError,AttributeError): return None
    cat=e.get("category"); title=e.get("title","").lower()
    if cat in ("CPI","PPI","GDP","PCE","CLAIMS"): hour,minute=8,30
    elif cat=="FOMC" and ("fomc statement" in title or "minutes of the federal open market committee" in title): hour,minute=14,0
    else:return None
    local=pub.astimezone(ny)
    return dt.datetime(local.year,local.month,local.day,hour,minute,tzinfo=ny).astimezone(dt.timezone.utc)

for e in news.get("items",[]):
    stamp=release(e)
    if stamp and stamp < now-dt.timedelta(minutes=70) and stamp>now-dt.timedelta(days=730):
        events.setdefault(stamp.date(),[]).append((e,stamp))

def download(day):
    url=f"https://datafeed.dukascopy.com/datafeed/USA500IDXUSD/{day.year}/{day.month-1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
    request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 SpikeHunterResearch"})
    with urllib.request.urlopen(request,timeout=18) as response: compressed=response.read()
    if not compressed:raise ValueError("No index candles for date")
    raw=lzma.decompress(compressed,format=lzma.FORMAT_ALONE)
    if len(raw)%24:raise ValueError("Invalid Dukascopy candle record size")
    rows=list(struct.iter_unpack(">IIIIIf",raw))
    # Dukascopy price integers are pip-scaled; infer divisor only if resulting
    # index level is plausible, then retain a consistent divisor for this day.
    sample=next((r[2] for r in rows if r[2]>0),None)
    if sample is None:raise ValueError("No nonzero closes")
    scales=[s for s in (1,10,100,1000,10000,100000) if 1000 < sample/s < 15000]
    if len(scales)!=1:raise ValueError("Ambiguous price scaling; cannot verify USA500 index points")
    divisor=scales[0]
    candles={}
    for sec,opening,close,low,high,volume in rows:
        if sec>=86400 or not (low<=min(opening,close)<=max(opening,close)<=high):continue
        price=close/divisor
        if 1000<price<15000:
            candles[sec//60]=(price,low/divisor,high/divisor)
    if not candles:raise ValueError("No valid minute prices")
    return candles

# Twelve days per run to limit cloud timeouts; later scheduled runs continue backfill.
todo=[(day,es) for day,es in sorted(events.items(),reverse=True) if any(e["url"] not in items for e,_ in es)][:12]
for day,day_events in todo:
    try:
        bars=download(day)
        matched=0
        for e,event in day_events:
            minute=event.hour*60+event.minute
            base=bars.get(minute-1)
            if base is None:continue
            moves={};spikes={}
            for n in (1,5,15,30):
                segment=[bars.get(minute+i) for i in range(n)]
                if any(b is None for b in segment):continue
                first=segment[0][0]-base[0]
                spikes[str(n)]={"up_points":round(max(0,max(b[2] for b in segment)-base[0]),3),
                                "down_points":round(max(0,base[0]-min(b[1] for b in segment)),3),
                                "first_minute_direction":"UP" if first>0 else "DOWN" if first<0 else "FLAT"}
                moves[str(n)]=round(segment[-1][0]-base[0],3)
            if "5" not in spikes:continue
            items[e["url"]]={"url":e["url"],"category":e["category"],"title":e["title"],
                "release_time_utc":event.isoformat(),"baseline":round(base[0],3),
                "spikes":spikes,"moves":moves,"source":"Dukascopy USA500IDXUSD BID M1",
                "unit":"index points","method_version":2}
            matched+=1
        checks[str(day)]=f"bars={len(bars)}, matched={matched}"
        if matched==0:raise ValueError("No complete release-minute price windows")
        retry.pop(str(day),None)
    except Exception as exc:
        checks[str(day)]=f"{type(exc).__name__}: {str(exc)[:160]}"
        retry[str(day)]={"last_error":checks[str(day)],"last_attempt":now.isoformat()}
    time.sleep(0.1)

eligible={e["url"] for es in events.values() for e,_ in es}
missing=[{"url":e["url"],"category":e["category"],"release_time_utc":stamp.isoformat()}
    for es in events.values() for e,stamp in es if e["url"] not in items]
result={"updated_at":now.isoformat(),"market":"Dukascopy USA500.IDX/USD CFD index (not exchange futures or ^GSPC)",
    "method":"Dukascopy USA500 BID M1 OHLC; pre-release close to 1/5/15/30-minute highs and lows in index points; no tick-level ordering or causality inference",
    "eligible_count":len(eligible),"missing_count":len(missing),"missing_events":missing,
    "complete":len(missing)==0,"items":sorted(items.values(),key=lambda x:x["release_time_utc"],reverse=True),
    "checks":checks,"retry":retry}
PATH.write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({"verified":len(items),"eligible":len(eligible),"missing":len(missing),"checks":checks}),flush=True)

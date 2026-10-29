#!/usr/bin/env python3
"""Spike Hunter official-news RSS monitor. Python standard library only."""
import datetime as dt
import json
import pathlib
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/"news.json"
FEEDS={
 "FOMC":"https://www.federalreserve.gov/feeds/press_monetary.xml",
 "CPI":"https://www.bls.gov/feed/cpi.rss",
 "PPI":"https://www.bls.gov/feed/ppi.rss",
}
def fetch(kind,url):
    req=urllib.request.Request(url,headers={"User-Agent":"SpikeHunterNews/1.0 (official RSS reader)","Accept":"application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req,timeout=22) as res:
        xml=res.read()
    root=ET.fromstring(xml)
    entries=[]
    for item in root.iter():
        if item.tag.rsplit("}",1)[-1] not in ("item","entry"): continue
        def field(tag):
            for child in item:
                if child.tag.rsplit("}",1)[-1] == tag:
                    return (child.text or "").strip()
            return ""
        title=field("title")
        link=field("link")
        if not link:
            for child in item:
                if child.tag.rsplit("}",1)[-1]=="link":
                    link=child.attrib.get("href","")
                    if link: break
        if not title or not link.startswith("https://"): continue
        pub=field("pubDate") or field("published") or field("updated")
        try: published=parsedate_to_datetime(pub).astimezone(dt.timezone.utc).isoformat()
        except (TypeError,ValueError):
            try: published=dt.datetime.fromisoformat(pub.replace("Z","+00:00")).astimezone(dt.timezone.utc).isoformat()
            except (TypeError,ValueError): published=None
        entries.append({"category":kind,"title":title,"url":link,"published":published,"summary":field("description")[:450]})
    return entries[:30]
def main():
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    old={}
    if OUT.exists():
        try: old=json.loads(OUT.read_text())
        except (ValueError,OSError): pass
    existing=old.get("items",[])
    merged={(e.get("category"),e.get("url")):e for e in existing if e.get("url")}
    checks={}
    good=0
    for kind,url in FEEDS.items():
        try:
            entries=fetch(kind,url)
            if not entries: raise ValueError("No RSS items returned")
            for e in entries: merged[(kind,e["url"])]=e
            checks[kind]={"ok":True,"checked_at":now,"count":len(entries)}
            good+=1
        except Exception as ex:
            checks[kind]={"ok":False,"checked_at":now,"error":str(ex)[:180]}
    # Verified 29 October 2026 economic-calendar events (08:30 New York time).
    # Calendar entries are not news results or surprises; do not infer outcomes.
    for kind, title, url in [
        ("GDP", "US GDP Q3 advance estimate", "https://www.bea.gov/data/gdp/gross-domestic-product"),
        ("PCE", "US personal income and PCE inflation September", "https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
        ("CLAIMS", "US initial unemployment claims", "https://www.dol.gov/agencies/eta/ui-data")
    ]:
        key=(kind, url+"#2026-10-29")
        merged[key]={"category":kind,"title":title,"url":key[1],
                     "published":"2026-10-29T12:30:00+00:00",
                     "summary":"Scheduled release; outcome not verified"}
    items=sorted(merged.values(),key=lambda e:e.get("published") or "",reverse=True)[:120]
    data={"updated_at":now,"sources":checks,"items":items,"note":"Official release headlines, not instant execution signals. Scheduled checks may be delayed."}
    OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"sources_ok":good,"items":len(items),"checks":checks}))
    if not good and not existing: raise SystemExit("No feeds available and no prior data")
if __name__=="__main__": main()

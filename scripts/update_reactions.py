#!/usr/bin/env python3
"""Compute release-time-aligned historical XAUUSD reactions from Dukascopy BID M1."""
import datetime as dt
import json
import lzma
import pathlib
import struct
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
news = json.loads((ROOT / "news.json").read_text())
path = ROOT / "reactions.json"
now = dt.datetime.now(dt.timezone.utc)
ny = ZoneInfo("America/New_York")
VERSION = 2

def event_time(e):
    """Use official release clock time, NOT potentially early RSS publish timestamp."""
    try:
        published = dt.datetime.fromisoformat(e["published"].replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError, KeyError):
        return None
    kind = e.get("category")
    title = e.get("title", "").lower()
    if kind in ("CPI", "PPI"):
        hour, minute = 8, 30  # BLS scheduled releases, America/New_York
    elif kind == "FOMC" and ("fomc statement" in title or "minutes of the federal open market committee" in title):
        hour, minute = 14, 0  # Fed statement / FOMC minutes, America/New_York
    else:
        return None  # Board discount-rate minutes and projections are not separate FOMC events
    day = published.astimezone(ny).date()
    local = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=ny)
    return local.astimezone(dt.timezone.utc)

old = {}
if path.exists():
    try:
        old = json.loads(path.read_text())
    except (ValueError, OSError):
        pass
valid = {}
events_by_date = {}
for e in news.get("items", []):
    event = event_time(e)
    if event is None or event > now - dt.timedelta(minutes=70) or event < now - dt.timedelta(days=730):
        continue
    events_by_date.setdefault(event.date(), []).append((e, event))
for x in old.get("items", []):
    event = next((event for day_events in events_by_date.values() for e, event in day_events if e.get("url") == x.get("url")), None)
    if event and x.get("method_version") == VERSION and x.get("release_time_utc") == event.isoformat():
        valid[x["url"]] = x

def candles(day):
    url = f"https://datafeed.dukascopy.com/datafeed/XAUUSD/{day.year}/{day.month-1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
    last_error = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SpikeHunterResearch"})
            with urllib.request.urlopen(req, timeout=22) as resp:
                raw = resp.read()
            if not raw:
                return {}
            blob = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
            if len(blob) % 24:
                raise ValueError("Invalid candle file length")
            out = {}
            for sec, op, close, low, high, volume in struct.iter_unpack(">IIIIIf", blob):
                if sec < 86400 and 100000 < close < 20000000:
                    out[sec // 60] = close / 1000
            return out
        except Exception as exc:
            last_error = exc
            time.sleep(1 + attempt)
    raise last_error

todo = [(day, es) for day, es in sorted(events_by_date.items(), reverse=True)
        if any(e.get("url") not in valid for e, _ in es)][:4]
checks = {}
for day, events in todo:
    try:
        day_prices = candles(day)
        next_prices = candles(day + dt.timedelta(days=1)) if any(event.hour >= 22 for _, event in events) else {}
        for e, event in events:
            minute = event.hour * 60 + event.minute
            base = day_prices.get(minute - 1)
            if base is None:
                continue
            moves = {}
            for n in (1, 5, 15, 30, 60):
                target = minute + n - 1
                price = (day_prices if target < 1440 else next_prices).get(target % 1440)
                moves[str(n)] = round(price - base, 3) if price is not None else None
            if all(x is None for x in moves.values()):
                continue
            valid[e["url"]] = {
                "url": e["url"], "category": e["category"], "title": e["title"],
                "published": e["published"], "release_time_utc": event.isoformat(),
                "baseline": base, "moves": moves,
                "source": "Dukascopy XAUUSD BID M1",
                "timing_source": "Scheduled 08:30 ET BLS release or 14:00 ET FOMC release",
                "method_version": VERSION, "unit": "USD/oz"
            }
        checks[str(day)] = "ok"
    except Exception as exc:
        checks[str(day)] = str(exc)[:150]
    time.sleep(1)
result = {
    "updated_at": now.isoformat(),
    "method": "Dukascopy BID M1 close-to-close differences from minute preceding scheduled release. CPI/PPI 08:30 New York time; FOMC statement/minutes 14:00 New York time. No intraminute high/low or causality claim.",
    "items": sorted(valid.values(), key=lambda x: x["release_time_utc"], reverse=True),
    "checks": checks
}
path.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"verified_reactions": len(valid), "checks": checks}))

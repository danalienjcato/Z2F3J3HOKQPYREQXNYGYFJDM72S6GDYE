#!/usr/bin/env python3
"""Compute release-time-aligned historical XAUUSD reactions from Dukascopy BID M1."""
import datetime as dt
import json
import lzma
import os
import urllib.parse
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
            with urllib.request.urlopen(req, timeout=15) as resp:
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
            if attempt == 0:
                time.sleep(3)
    raise last_error

def backup_candles(day):
    """Optional independent 1m XAU/USD source; requires GOLDPRICE_API_KEY (Pro)."""
    key = os.environ.get("GOLDPRICE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GOLDPRICE_API_KEY not configured")
    start = dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    params = urllib.parse.urlencode({
        "symbol": "XAU-USD-SPOT", "interval": "1m",
        "from": start.isoformat(), "to": end.isoformat(), "limit": "2000"
    })
    url = "https://api.goldprice.dev/v1/bars?" + params
    req = urllib.request.Request(url, headers={"X-API-Key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    bars = data.get("bars", [])
    out = {}
    for bar in bars:
        stamp = bar.get("bar_start") or bar.get("time") or bar.get("timestamp")
        if not stamp or bar.get("close") is None:
            continue
        moment = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("Backup bars have no timezone")
        moment = moment.astimezone(dt.timezone.utc)
        if moment.date() == day and bar.get("is_closed", True):
            out[moment.hour * 60 + moment.minute] = float(bar["close"])
    if not out:
        raise ValueError("Backup returned no usable closed 1m bars")
    return out


def fetch_prices(day):
    try:
        return candles(day), "Dukascopy XAUUSD BID M1"
    except Exception as primary:
        if not os.environ.get("GOLDPRICE_API_KEY"):
            raise RuntimeError(f"Primary failed: {primary}; backup requires GOLDPRICE_API_KEY") from primary
        try:
            return backup_candles(day), "goldprice.dev XAU/USD spot M1 close"
        except Exception as backup:
            raise RuntimeError(f"Primary failed: {primary}; backup failed: {backup}") from backup

# Respect Dukascopy's rate limits: at most three missing days per run, with
# persisted exponential cooldowns after 503s/timeouts. Do not let a
# repeatedly failing recent date block the older historical backfill.
retry = old.get("retry", {})
checks = dict(old.get("checks", {}))
todo = []
for day, es in sorted(events_by_date.items(), reverse=True):
    if all(e.get("url") in valid for e, _ in es):
        continue
    state = retry.get(str(day), {})
    try:
        next_attempt = dt.datetime.fromisoformat(state["next_attempt"])
        if next_attempt > now:
            continue
    except (KeyError, TypeError, ValueError):
        pass
    todo.append((day, es))
    if len(todo) >= 3:
        break
for day, events in todo:
    try:
        day_prices, price_source = fetch_prices(day)
        next_prices = {}
        matched = 0
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
            matched += 1
            valid[e["url"]] = {
                "url": e["url"], "category": e["category"], "title": e["title"],
                "published": e["published"], "release_time_utc": event.isoformat(),
                "baseline": base, "moves": moves,
                "source": price_source,
                "timing_source": "Scheduled 08:30 ET BLS release or 14:00 ET FOMC release",
                "method_version": VERSION, "unit": "USD/oz"
            }
        if matched == 0:
            raise ValueError(f"No usable release-minute candles; day has {len(day_prices)} candles")
        checks[str(day)] = f"source={price_source}, candles={len(day_prices)}, events={len(events)}, matched={matched}"
        retry.pop(str(day), None)
    except Exception as exc:
        checks[str(day)] = f"{type(exc).__name__}: {exc}"[:300]
        failures = retry.get(str(day), {}).get("failures", 0) + 1
        cooldown_minutes = min(240, 15 * (2 ** min(failures - 1, 4)))
        retry[str(day)] = {
            "failures": failures,
            "last_error": checks[str(day)],
            "next_attempt": (now + dt.timedelta(minutes=cooldown_minutes)).isoformat()
        }
    time.sleep(1)
result = {
    "updated_at": now.isoformat(),
    "method": "Dukascopy BID M1 close-to-close differences from minute preceding scheduled release. CPI/PPI 08:30 New York time; FOMC statement/minutes 14:00 New York time. No intraminute high/low or causality claim.",
    "items": sorted(valid.values(), key=lambda x: x["release_time_utc"], reverse=True),
    "checks": checks,
    "retry": retry,\n    "backup_configured": bool(os.environ.get("GOLDPRICE_API_KEY"))\n}
path.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"verified_reactions": len(valid), "attempted_days": [str(day) for day, _ in todo], "checks": checks, "retry": retry}), flush=True)

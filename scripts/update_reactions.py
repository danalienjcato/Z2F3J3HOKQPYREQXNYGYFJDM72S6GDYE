#!/usr/bin/env python3
"""Compute release-time-aligned historical XAUUSD reactions from BID M1 feeds."""
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
VERSION = 3

def event_time(e):
    """Use official release clock time, NOT potentially early RSS publish timestamp."""
    try:
        published = dt.datetime.fromisoformat(e["published"].replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError, KeyError):
        return None
    kind = e.get("category")
    title = e.get("title", "").lower()
    if kind in ("GDP", "PCE", "CLAIMS"):
        hour, minute = 8, 30
    elif kind in ("CPI", "PPI"):
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
                    out[sec // 60] = (close / 1000, low / 1000, high / 1000)
            return out
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(3)
    raise last_error

_histdata_month_cache = {}

def histdata_candles(day):
    """HistData XAUUSD BID M1; source clock is fixed EST (UTC-05), not DST."""
    from histdata_fetcher import fetch_data
    # EST day overlaps two UTC days; request adjacent dates to avoid boundary loss.
    month = (day.year, day.month)
    if month not in _histdata_month_cache:
        first = day.replace(day=1)
        if day.month == 12:
            last = dt.date(day.year, 12, 31)
        else:
            last = day.replace(month=day.month + 1, day=1) - dt.timedelta(days=1)
        result = fetch_data(
            pair="XAUUSD", start_date=first, end_date=last,
            timeframe="1min", output_format=None, max_workers=1
        )
        if result.data is None or result.data.empty:
            raise ValueError(f"HistData has no XAUUSD M1 bars for {month}")
        _histdata_month_cache[month] = result.data
    frame = _histdata_month_cache[month]
    out = {}
    for row in frame.itertuples(index=False):
        stamp = row.datetime.to_pydatetime() if hasattr(row.datetime, "to_pydatetime") else row.datetime
        # HistData explicitly uses EST UTC-5 year round; never America/New_York.
        utc = stamp.replace(tzinfo=dt.timezone(dt.timedelta(hours=-5))).astimezone(dt.timezone.utc)
        if utc.date() == day:
            close = float(row.close)
            if 100 < close < 100000:
                out[utc.hour * 60 + utc.minute] = (close, float(row.low), float(row.high))
    if not out:
        raise ValueError(f"HistData lacks usable XAUUSD UTC bars for {day}")
    return out


def fetch_prices(day):
    errors = []
    try:
        prices = candles(day) if (day.year, day.month) == (now.year, now.month) else {}
        if prices:
            return prices, "Dukascopy XAUUSD BID M1"
        errors.append("Dukascopy skipped or returned no candles")
    except Exception as exc:
        errors.append(f"Dukascopy: {exc}")
    try:
        return histdata_candles(day), "HistData XAUUSD BID M1 (fixed EST UTC-5)"
    except Exception as exc:
        errors.append(f"HistData: {exc}")
    if os.environ.get("GOLDPRICE_API_KEY"):
        try:
            return backup_candles(day), "goldprice.dev XAU/USD spot M1 close"
        except Exception as exc:
            errors.append(f"goldprice.dev: {exc}")
    raise RuntimeError("; ".join(errors))


def backup_candles(day):
    """Optional paid provider, only if explicitly configured."""
    key = os.environ["GOLDPRICE_API_KEY"]
    start = dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    params = urllib.parse.urlencode({
        "symbol": "XAU-USD-SPOT", "interval": "1m",
        "from": start.isoformat(), "to": end.isoformat(), "limit": "2000"
    })
    req = urllib.request.Request("https://api.goldprice.dev/v1/bars?" + params,
                                 headers={"X-API-Key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    out = {}
    for bar in data.get("bars", []):
        stamp = bar.get("bar_start") or bar.get("time") or bar.get("timestamp")
        if not stamp or bar.get("close") is None:
            continue
        moment = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("Backup bars have no timezone")
        moment = moment.astimezone(dt.timezone.utc)
        if moment.date() == day and bar.get("is_closed", True):
            out[moment.hour * 60 + moment.minute] = (float(bar["close"]), float(bar.get("low", bar["close"])), float(bar.get("high", bar["close"])))
    if not out:
        raise ValueError("Backup returned no closed 1m bars")
    return out

# Process the complete remaining historical queue in one run. For past months,
# use HistData monthly downloads; for the current month, try Dukascopy first.
# Keep per-day failures isolated so one unavailable date cannot block older data.
retry = old.get("retry", {})
checks = dict(old.get("checks", {}))
todo = []
for day, es in sorted(events_by_date.items(), reverse=True):
    if all(e.get("url") in valid for e, _ in es):
        continue
    # HistData fallback is independent of Dukascopy cooldowns; retry each run.
    todo.append((day, es))
    if len(todo) >= 40:
        break
for day, events in todo:
    try:
        day_prices, price_source = fetch_prices(day)
        next_prices = {}
        matched = 0
        for e, event in events:
            minute = event.hour * 60 + event.minute
            base_bar = day_prices.get(minute - 1)
            if base_bar is None:
                continue
            base = base_bar[0]
            if base is None:
                continue
            moves = {}
            for n in (1, 5, 15, 30, 60):
                target = minute + n - 1
                price = (day_prices if target < 1440 else next_prices).get(target % 1440)
                moves[str(n)] = round(price[0] - base, 3) if price is not None else None
            spikes = {}
            for n in (1, 5, 15, 30):
                bars = [day_prices.get(minute + offset) for offset in range(n)]
                if any(bar is None for bar in bars):
                    spikes[str(n)] = None
                    continue
                max_up = round(max(bar[2] for bar in bars) - base, 3)
                max_down = round(base - min(bar[1] for bar in bars), 3)
                first = bars[0][0] - base
                spikes[str(n)] = {"up_usd": max(0, max_up), "down_usd": max(0, max_down), "first_minute_direction": "UP" if first > 0 else "DOWN" if first < 0 else "FLAT"}
            if all(x is None for x in moves.values()):
                continue
            matched += 1
            valid[e["url"]] = {
                "url": e["url"], "category": e["category"], "title": e["title"],
                "published": e["published"], "release_time_utc": event.isoformat(),
                "baseline": base, "moves": moves, "spikes": spikes,
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
    time.sleep(0.2)
eligible_urls = {e["url"] for day_events in events_by_date.values() for e, _ in day_events}
missing_events = [
    {"url": e["url"], "category": e["category"], "title": e["title"], "release_time_utc": event.isoformat()}
    for day_events in events_by_date.values() for e, event in day_events
    if e["url"] not in valid
]
result = {
    "updated_at": now.isoformat(),
    "eligible_count": len(eligible_urls),
    "missing_count": len(missing_events),
    "missing_events": sorted(missing_events, key=lambda x: x["release_time_utc"], reverse=True),
    "complete": len(missing_events) == 0,
    "method": "XAUUSD BID M1 OHLC. Spike extrema measured from pre-release minute close to maximum high/minimum low during first 1, 5, 15 and 30 minutes. First-minute direction uses first minute close. No tick-level first move or causality claim.",
    "items": sorted(valid.values(), key=lambda x: x["release_time_utc"], reverse=True),
    "checks": checks,
    "retry": retry,
    "backup_configured": bool(os.environ.get("GOLDPRICE_API_KEY"))
}
path.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"verified_reactions": len(valid), "eligible": len(eligible_urls), "missing": len(missing_events), "attempted_days": [str(day) for day, _ in todo], "checks": checks, "retry": retry}), flush=True)

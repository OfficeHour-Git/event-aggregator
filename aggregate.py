#!/usr/bin/env python3
"""
Event Feed Aggregator — definitive version
- Strips Luma's "[Luma Calendar (cal-xxx)]" prefix from event names
- Filters out events outside US and Europe (keywords first, then GEO)
- Filters out past events
- Deduplicates by title + start time
"""

import re
import os
import sys
import uuid
import json
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from dateutil.parser import parse as parse_dt

# ─── Luma iCal sources ────────────────────────────────────────────────────────

LUMA_DIRECT_ICS_URLS = {
    "Luma Calendar 1":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-yrYsEKDQ91hPMWy",
    "Luma Calendar 2":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-61Cv6COs4g9GKw7",
    "Luma Calendar 3":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-7Q5A70Bz5Idxopu",
    "Luma Calendar 4":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-iOipAs7mv59Hbuz",
    "Luma Calendar 5":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-tBOSmnsBzW0kTrf",
    "Luma Calendar 6":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-E74MDlDKBaeAwXK",
    "Nebius Community":       "https://api2.luma.com/ics/get?entity=calendar&id=cal-36Kb7AwwNrfc0eU",
    "Luma Calendar 8":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-2mLDnq80EKWoGy8",
    "Luma Calendar 9":        "https://api2.luma.com/ics/get?entity=calendar&id=cal-r8BcsXhhHYmA3tp",
    "Luma Calendar 10":       "https://api2.luma.com/ics/get?entity=calendar&id=cal-8zLyKMgaKTvonbT",
    "Luma Calendar 11":       "https://api2.luma.com/ics/get?entity=calendar&id=cal-vSo9sRaAQOgoflu",
    "Luma Calendar 12":       "https://api2.luma.com/ics/get?entity=calendar&id=cal-YKwEv0xAlmNR6VN",
    "Luma Calendar 13":       "https://api2.luma.com/ics/get?entity=calendar&id=cal-UAliCb7j5QccLrn",
    "AI Builders Collective": "https://api2.luma.com/ics/get?entity=calendar&id=cal-QvcuRhmCBjOA1T7",
    "Luma Calendar 15":       "https://api2.luma.com/ics/get?entity=calendar&id=cal-RHI1LJC6K8JRBLI",
    "Luma Calendar 16":       "https://api2.luma.com/ics/get?entity=calendar&id=cal-l7gcEleWIMCKLbv",
}

OTHER_SOURCES = {
    "Verci Events":              "https://www.verci.com/events",
    "Betaworks Events":          "https://www.betaworks.com/events",
    "AI Tinkerers (All Cities)": "https://aitinkerers.org/all_cities?m=r",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

VTIMEZONE_NYC = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE"""

_NOW = datetime.now(timezone.utc)

# ─── Prefix stripping ─────────────────────────────────────────────────────────

# Luma prepends "[Luma Calendar (cal-xxx)]" to event names when curating
# events from other calendars. Strip it to get the real event name.
_LUMA_PREFIX = re.compile(r'^\[Luma Calendar \(cal-[A-Za-z0-9]+\)\]\s*', re.IGNORECASE)

def clean_summary(raw: str) -> str:
    s = raw.strip()
    while True:
        stripped = _LUMA_PREFIX.sub('', s).strip()
        if stripped == s:
            break
        s = stripped
    return s or "Event"

# ─── Location / geo filter ────────────────────────────────────────────────────

# Word-boundary regex — "india" won't match "indiana", etc.
_EXCLUDED = re.compile(
    r'\b(' + '|'.join([
        # Middle East
        'dubai', 'united arab emirates', 'abu dhabi', 'uae',
        'saudi arabia', 'riyadh', 'qatar', 'doha',
        # East Asia
        'singapore', 'hong kong', 'tokyo', 'osaka', 'japan',
        'china', 'beijing', 'shanghai', 'hangzhou', 'chengdu',
        'guangzhou', 'nanjing', 'wuhan', 'shenzhen',
        'south korea', 'seoul', 'taiwan', 'taipei',
        'thailand', 'bangkok', 'vietnam', 'hanoi',
        'indonesia', 'jakarta', 'philippines', 'manila',
        'malaysia', 'kuala lumpur',
        # South Asia
        'india', 'bangalore', 'mumbai', 'delhi', 'hyderabad',
        # Canada
        'toronto', 'canada', 'vancouver', 'montreal', 'ottawa',
        'halifax', 'calgary', 'edmonton', 'winnipeg',
        # Latin America
        'brazil', 'sao paulo', 'são paulo',
        'mexico', 'guadalajara', 'monterrey', 'culiacan',
        # Africa
        'south africa', 'johannesburg', 'nigeria', 'kenya',
        'addis ababa', 'nairobi', 'ghana',
        # Oceania
        'australia', 'sydney', 'melbourne', 'brisbane', 'perth',
        'auckland', 'new zealand',
        # URL slug fragments used by AU/NZ calendar
        'buildercommunityanz', 'aunz',
        # Other
        'israel', 'tel aviv', 'el salvador',
    ]) + r')\b',
    re.IGNORECASE,
)

# US bounding box (covers CONUS, Hawaii, Alaska)
_US_LAT  = (18,  72)
_US_LON  = (-180, -60)
# Europe bounding box
_EU_LAT  = (34,  72)
_EU_LON  = (-25,  45)

def _in_us(lat, lon):
    return _US_LAT[0] <= lat <= _US_LAT[1] and _US_LON[0] <= lon <= _US_LON[1]

def _in_eu(lat, lon):
    return _EU_LAT[0] <= lat <= _EU_LAT[1] and _EU_LON[0] <= lon <= _EU_LON[1]

def is_allowed(vevent) -> bool:
    """
    Return True if the event should be included (US, Europe, or virtual).

    Order of checks:
    1. Keywords — always first. Catches Canada/Mexico whose coordinates
       overlap the US bounding box, plus any event naming a foreign city.
    2. GEO bounding box — if coordinates are present AND outside both boxes,
       exclude (catches Taiwan, Australia, Japan, etc. with no keywords).
    3. Default KEEP — no GEO, no excluded keywords → virtual/online event.
    """
    # Build search text from all identifying fields
    text = " ".join([
        str(vevent.get("summary",     "")),
        str(vevent.get("location",    "")),
        str(vevent.get("description", "")),
        str(vevent.get("uid",         "")),
    ])

    # 1. Keywords
    if _EXCLUDED.search(text):
        return False

    # 2. GEO
    geo = vevent.get("geo")
    if geo is not None:
        try:
            lat = float(geo.latitude)
            lon = float(geo.longitude)
            if _in_us(lat, lon) or _in_eu(lat, lon):
                return True
            return False   # GEO present but outside both boxes
        except Exception:
            pass  # malformed GEO — fall through to default

    # 3. Default: keep (virtual / no location)
    return True


def is_future(vevent) -> bool:
    """Return True if the event starts today or later."""
    dtstart = vevent.get("dtstart")
    if dtstart is None:
        return True
    start = dtstart.dt
    if hasattr(start, "tzinfo"):
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    else:
        start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start >= today


# ─── Location extractor ───────────────────────────────────────────────────────

def real_location(vevent) -> str:
    """Return physical address when available, otherwise Luma URL."""
    loc = str(vevent.get("location", ""))
    if loc and not loc.startswith("http"):
        return loc
    # Try to parse address from description
    desc = str(vevent.get("description", ""))
    m = re.search(r"Address:\n(.+?)(?:\n\n|\nHosted by|$)", desc, re.DOTALL)
    if m:
        addr = m.group(1).strip()
        if addr.lower() not in ("check event page for more details.", ""):
            return addr
    return loc


# ─── VEVENT builder ───────────────────────────────────────────────────────────

def make_vevent(src: Event) -> Event:
    """Copy a raw Luma VEVENT into a clean output VEVENT."""
    dst = Event()

    # UID — keep original so Google Calendar can track updates
    dst.add("uid", str(src.get("uid", str(uuid.uuid4()))))
    dst.add("dtstamp", src.get("dtstamp", _NOW))

    # Summary — strip Luma's "[Luma Calendar (cal-xxx)]" prefix
    dst.add("summary", clean_summary(str(src.get("summary", "Event"))))

    # Dates
    for field in ("dtstart", "dtend", "created", "last-modified"):
        val = src.get(field)
        if val is not None:
            dst.add(field, val.dt if hasattr(val, "dt") else val)

    # Location — prefer real address over luma URL
    loc = real_location(src)
    if loc:
        dst.add("location", loc)

    # GEO — preserve for downstream use
    geo = src.get("geo")
    if geo is not None:
        dst.add("geo", geo)

    # Description + URL
    dst.add("description", str(src.get("description", "")))
    url = src.get("url")
    if url:
        dst.add("url", str(url))

    # Force CONFIRMED so Google renders events normally (not greyed out)
    dst.add("status", "CONFIRMED")

    organizer = src.get("organizer")
    if organizer:
        dst.add("organizer", organizer)

    return dst


def scraped_to_vevent(ev: dict) -> Event:
    """Convert a scraped dict to a VEVENT."""
    vevent = Event()
    vevent.add("uid",         str(uuid.uuid4()) + "@event-aggregator")
    vevent.add("summary",     ev.get("summary", "Event"))
    vevent.add("description", ev.get("description", "") + f"\n\nSource: {ev.get('url', '')}")
    vevent.add("status",      "CONFIRMED")
    vevent.add("dtstamp",     _NOW)
    vevent.add("created",     _NOW)

    if ev.get("url"):
        vevent.add("url", ev["url"])
    if ev.get("location"):
        vevent.add("location", ev["location"])

    if ev.get("dtstart"):
        try:
            vevent.add("dtstart", parse_dt(ev["dtstart"]))
        except Exception:
            vevent.add("dtstart", _NOW)
    else:
        vevent.add("dtstart", _NOW)

    if ev.get("dtend"):
        try:
            vevent.add("dtend", parse_dt(ev["dtend"]))
        except Exception:
            pass

    return vevent


# ─── Fetchers ─────────────────────────────────────────────────────────────────

def fetch_luma(name: str, url: str) -> list[Event]:
    kept = skipped_loc = skipped_past = 0
    events = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            if not is_allowed(component):
                skipped_loc += 1
                continue
            if not is_future(component):
                skipped_past += 1
                continue
            events.append(make_vevent(component))
            kept += 1
        print(f"  ✓  {name} ({kept} kept, {skipped_loc} location-filtered, {skipped_past} past)")
    except Exception as e:
        print(f"  ✗  {name}: {e}", file=sys.stderr)
    return events


def scrape_json_ld(url: str, source_name: str, base_url: str = "") -> list[dict]:
    events = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    # Require startDate to filter out page-nav junk
                    if item.get("@type") == "Event" and item.get("startDate"):
                        events.append({
                            "summary":     item.get("name", f"{source_name} Event"),
                            "description": item.get("description", ""),
                            "url":         item.get("url", url),
                            "dtstart":     item.get("startDate"),
                            "dtend":       item.get("endDate"),
                            "location":    (item.get("location") or {}).get("name", ""),
                        })
            except Exception:
                pass

        if not events:
            for card in soup.select("article, .event-card, [class*='event'], a[href*='/event']"):
                link  = card.find("a") if card.name != "a" else card
                title = card.find(["h2", "h3", "h4"]) or card
                if title and title.get_text(strip=True):
                    href = link["href"] if link and link.get("href") else url
                    if href.startswith("/") and base_url:
                        href = base_url + href
                    events.append({"summary": title.get_text(strip=True)[:120], "url": href})

        print(f"  ✓  {source_name} ({len(events)} events)")
    except Exception as e:
        print(f"  ✗  {source_name}: {e}", file=sys.stderr)
    return events


# ─── Main ─────────────────────────────────────────────────────────────────────

def build_merged_calendar(output_path: str = "docs/events.ics") -> None:
    merged = Calendar()
    merged.add("prodid",        "-//NYC AI Event Aggregator//EN")
    merged.add("version",       "2.0")
    merged.add("calscale",      "GREGORIAN")
    merged.add("method",        "PUBLISH")
    merged.add("x-wr-calname",  "NYC AI & Tech Events — Aggregated")
    merged.add("x-wr-caldesc",  "Auto-aggregated from Luma, Verci, Betaworks, AI Tinkerers & more.")
    merged.add("x-wr-timezone", "America/New_York")

    # Embed timezone block
    tz_cal = Calendar.from_ical(
        "BEGIN:VCALENDAR\nVERSION:2.0\n" + VTIMEZONE_NYC + "\nEND:VCALENDAR"
    )
    for component in tz_cal.walk():
        if component.name == "VTIMEZONE":
            merged.add_component(component)

    event_count = 0
    seen: set[tuple] = set()

    def is_duplicate(vevent) -> bool:
        key = (
            str(vevent.get("summary", "")).strip().lower(),
            str(vevent.get("dtstart").dt) if vevent.get("dtstart") else "",
        )
        if key in seen:
            return True
        seen.add(key)
        return False

    # Luma calendars
    print("\n📡 Fetching Luma calendars…")
    for name, url in LUMA_DIRECT_ICS_URLS.items():
        for vevent in fetch_luma(name, url):
            if not is_duplicate(vevent):
                merged.add_component(vevent)
                event_count += 1

    # Scraped sources
    print("\n🕸  Scraping non-Luma sources…")
    for name, url, base in [
        ("Verci Events",             OTHER_SOURCES["Verci Events"],             "https://www.verci.com"),
        ("Betaworks Events",         OTHER_SOURCES["Betaworks Events"],         "https://www.betaworks.com"),
        ("AI Tinkerers (All Cities)",OTHER_SOURCES["AI Tinkerers (All Cities)"],"https://aitinkerers.org"),
    ]:
        for ev in scrape_json_ld(url, name, base):
            vevent = scraped_to_vevent(ev)
            if is_allowed(vevent) and is_future(vevent) and not is_duplicate(vevent):
                merged.add_component(vevent)
                event_count += 1

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(merged.to_ical())

    print(f"\n✅  Written {event_count} events → {output_path}")


if __name__ == "__main__":
    build_merged_calendar()

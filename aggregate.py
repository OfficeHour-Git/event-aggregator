#!/usr/bin/env python3
"""
Event Feed Aggregator
Merges multiple event calendars (Luma + others) into a single .ics feed.
- No source prefix tags on event names
- Deduplication by title + start time
- Filters out events outside US and Europe
- Filters out past events
"""

import requests
import re
import os
import sys
import uuid
import json
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from icalendar import Calendar, Event, vText
from dateutil.parser import parse as parse_dt

# ─── Source Definitions ───────────────────────────────────────────────────────

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
    "New York AI":               "https://newyorkai.org",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EventAggregator/1.0; "
        "+https://github.com/your-username/event-aggregator)"
    )
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

# ─── Filters ──────────────────────────────────────────────────────────────────

# Matches location/description text that signals a non-US/Europe event.
# Uses \b word boundaries so "india" won't match "indiana",
# "melb" won't match "melbourne" legitimate uses, etc.
_EXCLUDED_PATTERNS = re.compile(
    r"\b(" + "|".join([
        # Middle East
        "dubai", "united arab emirates", "abu dhabi", "uae",
        "saudi arabia", "riyadh", "qatar", "doha",
        # East Asia
        "singapore", "hong kong", "tokyo", "osaka", "japan",
        "china", "beijing", "shanghai", "hangzhou", "chengdu",
        "guangzhou", "nanjing", "wuhan", "shenzhen",
        "south korea", "seoul", "taiwan", "taipei",
        "thailand", "bangkok", "vietnam", "hanoi",
        "indonesia", "jakarta", "philippines", "manila",
        "malaysia", "kuala lumpur",
        # South Asia
        "india", "bangalore", "mumbai", "delhi", "hyderabad",
        # Americas outside US
        "toronto", "canada", "vancouver", "montreal", "ottawa",
        "halifax", "calgary", "edmonton", "winnipeg",
        "brazil", "sao paulo", "são paulo",
        "mexico city", "guadalajara", "monterrey", "culiacan",
        "mexico",  # catches "Cursor Meetup Mexico City" etc in title
        # Africa
        "south africa", "johannesburg", "nigeria", "kenya",
        "addis ababa", "nairobi",
        # Oceania — city names AND URL slug fragments
        "australia", "sydney", "melbourne", "brisbane", "perth",
        "auckland", "new zealand",
        "melb", "bris", "startupweekendsydney",
        # Calendar slugs that are clearly Australia/NZ communities
        "buildercommunityanz", "aunz",
        # Other
        "israel", "tel aviv", "el salvador",
    ]) + r")\b",
    re.IGNORECASE,
)

# Today's date in UTC — used to filter out past events
_NOW = datetime.now(timezone.utc)


def is_future_event(vevent) -> bool:
    """Return True if the event starts today or in the future."""
    dtstart = vevent.get("dtstart")
    if dtstart is None:
        return True  # no start date — keep it
    start = dtstart.dt
    # Handle both date and datetime objects
    if hasattr(start, "tzinfo"):
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    else:
        # date-only — convert to datetime at midnight UTC
        start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    return start >= _NOW.replace(hour=0, minute=0, second=0, microsecond=0)


def is_us_or_europe(vevent) -> bool:
    """
    Return True if the event is in the US or Europe (or is virtual/unknown).

    1. Keyword exclusion — always checked first, catches Canada/Mexico/etc
       even when their GEO coordinates overlap with the US bounding box.
    2. GEO lat/lon bounding box — used to positively confirm US/Europe
       only after keywords have not excluded it.
    3. Default keep — virtual/online events with no location pass through.
    """
    # ── 1. Keyword exclusion — always runs first ──────────────────────────────
    # Canada and Mexico share lat/lon ranges with the US so GEO alone can't
    # distinguish them. Keywords on SUMMARY/LOCATION/DESCRIPTION/UID catch
    # events like "Cursor Meetup Toronto", "Build with Cursor Mexico City".
    summary  = str(vevent.get("summary", ""))
    location = str(vevent.get("location", ""))
    desc     = str(vevent.get("description", ""))
    uid      = str(vevent.get("uid", ""))
    text     = summary + " " + location + " " + desc + " " + uid
    if _EXCLUDED_PATTERNS.search(text):
        return False

    # ── 2. GEO bounding box — confirms US/Europe after keywords pass ──────────
    geo = vevent.get("geo")
    if geo is not None:
        try:
            lat = float(geo.latitude)
            lon = float(geo.longitude)
            in_us     = (18 <= lat <= 72) and (-180 <= lon <= -60)
            in_europe = (34 <= lat <= 72) and (  -25 <= lon <=  45)
            return in_us or in_europe
        except Exception:
            pass  # malformed GEO — fall through

    # ── 3. Default: keep ──────────────────────────────────────────────────────
    return True


# ─── Location extractor ───────────────────────────────────────────────────────

def extract_real_location(vevent) -> str:
    """Use the physical address when available; fall back to Luma URL."""
    loc = str(vevent.get("location", ""))
    if loc and not loc.startswith("http"):
        return loc
    # Try to extract address from description
    desc = str(vevent.get("description", ""))
    m = re.search(r"Address:\n(.+?)(?:\n\n|\nHosted by|$)", desc, re.DOTALL)
    if m:
        addr = m.group(1).strip()
        if addr.lower() not in ("check event page for more details.", ""):
            return addr
    return loc


# ─── VEVENT builder ───────────────────────────────────────────────────────────

def make_clean_vevent(src: Event) -> Event:
    """
    Build a fresh VEVENT from a raw Luma component.
    - NO source prefix tag on the summary
    - Uses real address for location when available
    - GEO preserved for downstream use
    - Status forced to CONFIRMED
    """
    dst = Event()
    dst.add("uid",     str(src.get("uid", str(uuid.uuid4()))))
    dst.add("dtstamp", src.get("dtstamp", _NOW))
    # Summary copied exactly as Luma provides — no prefix added
    dst.add("summary", str(src.get("summary", "Event")))

    for field in ("dtstart", "dtend", "created", "last-modified"):
        val = src.get(field)
        if val is not None:
            dst.add(field, val.dt if hasattr(val, "dt") else val)

    location = extract_real_location(src)
    if location:
        dst.add("location", location)

    geo = src.get("geo")
    if geo is not None:
        dst.add("geo", geo)

    dst.add("description", str(src.get("description", "")))

    url = src.get("url")
    if url:
        dst.add("url", str(url))

    dst.add("status", "CONFIRMED")

    organizer = src.get("organizer")
    if organizer:
        dst.add("organizer", organizer)

    return dst


# ─── Fetchers ─────────────────────────────────────────────────────────────────

def fetch_luma(name: str, url: str) -> list[Event]:
    """Fetch a Luma iCal URL, filter by location and date, return clean VEVENTs."""
    events = []
    skipped_geo = 0
    skipped_past = 0
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            # Filter on raw component (GEO is present here)
            if not is_us_or_europe(component):
                skipped_geo += 1
                continue
            if not is_future_event(component):
                skipped_past += 1
                continue
            events.append(make_clean_vevent(component))
        print(f"  ✓  {name} ({len(events)} kept, {skipped_geo} geo-filtered, {skipped_past} past)")
    except Exception as e:
        print(f"  ✗  {name}: {e}", file=sys.stderr)
    return events


def dict_to_vevent(ev: dict) -> Event:
    """Convert a scraped event dict to a clean VEVENT. No source prefix."""
    vevent = Event()
    vevent.add("uid",     str(uuid.uuid4()) + "@event-aggregator")
    vevent.add("summary", ev.get("summary", "Event"))  # no prefix
    vevent.add("description", ev.get("description", "") + f"\n\nSource: {ev.get('url', '')}")
    vevent.add("status", "CONFIRMED")

    if ev.get("url"):
        vevent.add("url", ev["url"])
    if ev.get("location"):
        vevent.add("location", ev["location"])

    now = _NOW
    vevent.add("dtstamp", now)
    vevent.add("created", now)

    if ev.get("dtstart"):
        try:
            vevent.add("dtstart", parse_dt(ev["dtstart"]))
        except Exception:
            vevent.add("dtstart", now)
    else:
        vevent.add("dtstart", now)

    if ev.get("dtend"):
        try:
            vevent.add("dtend", parse_dt(ev["dtend"]))
        except Exception:
            pass

    return vevent


def scrape_json_ld(url: str, source_name: str, base_url: str = "") -> list[dict]:
    """Generic JSON-LD + fallback HTML scraper."""
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
                    # Must be an Event AND have a startDate — filters out
                    # page navigation junk like "In Person", "Browse Library"
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
                    events.append({
                        "summary": title.get_text(strip=True)[:120],
                        "url": href,
                    })

        print(f"  ✓  {source_name} ({len(events)} events)")
    except Exception as e:
        print(f"  ✗  {source_name}: {e}", file=sys.stderr)
    return events


# ─── Merge & Write ────────────────────────────────────────────────────────────

def build_merged_calendar(output_path: str = "docs/events.ics") -> None:
    merged = Calendar()
    merged.add("prodid",        "-//NYC AI Event Aggregator//EN")
    merged.add("version",       "2.0")
    merged.add("calscale",      "GREGORIAN")
    merged.add("method",        "PUBLISH")
    merged.add("x-wr-calname",  "NYC AI & Tech Events — Aggregated")
    merged.add("x-wr-caldesc",  "Auto-aggregated from Luma, Verci, Betaworks, AI Tinkerers & more.")
    merged.add("x-wr-timezone", "America/New_York")

    # Embed VTIMEZONE so clients render UTC times correctly
    tz_cal = Calendar.from_ical(
        "BEGIN:VCALENDAR\nVERSION:2.0\n" + VTIMEZONE_NYC + "\nEND:VCALENDAR"
    )
    for component in tz_cal.walk():
        if component.name == "VTIMEZONE":
            merged.add_component(component)

    event_count = 0
    seen = set()  # deduplication: (lowercase_title, start_str)

    def is_duplicate(vevent) -> bool:
        summary = str(vevent.get("summary", "")).strip().lower()
        dtstart = vevent.get("dtstart")
        start   = str(dtstart.dt) if dtstart else ""
        key = (summary, start)
        if key in seen:
            return True
        seen.add(key)
        return False

    # ── Luma calendars ────────────────────────────────────────────────────────
    print("\n📡 Fetching Luma calendars…")
    for name, url in LUMA_DIRECT_ICS_URLS.items():
        for vevent in fetch_luma(name, url):
            if not is_duplicate(vevent):
                merged.add_component(vevent)
                event_count += 1

    # ── Scraped sources ───────────────────────────────────────────────────────
    print("\n🕸  Scraping non-Luma sources…")
    scraped = [
        ("Verci Events",             OTHER_SOURCES["Verci Events"],             "https://www.verci.com"),
        ("Betaworks Events",         OTHER_SOURCES["Betaworks Events"],         "https://www.betaworks.com"),
        ("AI Tinkerers (All Cities)",OTHER_SOURCES["AI Tinkerers (All Cities)"],"https://aitinkerers.org"),
        ("New York AI",              OTHER_SOURCES["New York AI"],              "https://newyorkai.org"),
    ]
    for name, url, base in scraped:
        items = scrape_json_ld(url, name, base)
        for ev in items:
            vevent = dict_to_vevent(ev)
            if is_us_or_europe(vevent) and is_future_event(vevent) and not is_duplicate(vevent):
                merged.add_component(vevent)
                event_count += 1

    # ── Write output ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(merged.to_ical())

    print(f"\n✅  Written {event_count} events → {output_path}")


if __name__ == "__main__":
    build_merged_calendar()

#!/usr/bin/env python3
"""
Event Feed Aggregator
Merges multiple event calendars (Luma + others) into a single .ics feed.
"""

import requests
import re
import os
import sys
import uuid
import json
from copy import deepcopy
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from icalendar import Calendar, Event, vText, vDatetime
from dateutil.parser import parse as parse_dt

# ─── Source Definitions ───────────────────────────────────────────────────────

LUMA_DIRECT_ICS_URLS = {
    "Luma Calendar 1":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-yrYsEKDQ91hPMWy",
    "Luma Calendar 2":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-61Cv6COs4g9GKw7",
    "Luma Calendar 3":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-7Q5A70Bz5Idxopu",
    "Luma Calendar 4":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-iOipAs7mv59Hbuz",
    "Luma Calendar 5":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-tBOSmnsBzW0kTrf",
    "Luma Calendar 6":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-E74MDlDKBaeAwXK",
    "Nebius Community":         "https://api2.luma.com/ics/get?entity=calendar&id=cal-36Kb7AwwNrfc0eU",
    "Luma Calendar 8":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-2mLDnq80EKWoGy8",
    "Luma Calendar 9":          "https://api2.luma.com/ics/get?entity=calendar&id=cal-r8BcsXhhHYmA3tp",
    "Luma Calendar 10":         "https://api2.luma.com/ics/get?entity=calendar&id=cal-8zLyKMgaKTvonbT",
    "Luma Calendar 11":         "https://api2.luma.com/ics/get?entity=calendar&id=cal-vSo9sRaAQOgoflu",
    "Luma Calendar 12":         "https://api2.luma.com/ics/get?entity=calendar&id=cal-YKwEv0xAlmNR6VN",
    "Luma Calendar 13":         "https://api2.luma.com/ics/get?entity=calendar&id=cal-UAliCb7j5QccLrn",
    "AI Builders Collective":   "https://api2.luma.com/ics/get?entity=calendar&id=cal-QvcuRhmCBjOA1T7",
    "Luma Calendar 15":         "https://api2.luma.com/ics/get?entity=calendar&id=cal-RHI1LJC6K8JRBLI",
    "Luma Calendar 16":         "https://api2.luma.com/ics/get?entity=calendar&id=cal-l7gcEleWIMCKLbv",
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

# VTIMEZONE block for America/New_York — required for correct time display
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

# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_real_location(vevent) -> str:
    """
    Luma often sets LOCATION to a luma.com URL.
    When that happens, try to pull the real address from DESCRIPTION instead.
    """
    loc = str(vevent.get("location", ""))
    # If location looks like a real address, use it
    if loc and not loc.startswith("http"):
        return loc

    # Otherwise dig the address out of the description
    desc = str(vevent.get("description", ""))
    # Pattern: "Address:\nLine1\nLine2\n..." up to a blank line or "Hosted by"
    m = re.search(r"Address:\n(.+?)(?:\n\n|\nHosted by|$)", desc, re.DOTALL)
    if m:
        addr = m.group(1).strip()
        if addr.lower() != "check event page for more details.":
            return addr

    # Fall back to the luma URL if nothing better
    return loc


def make_clean_vevent(src: Event, source_name: str) -> Event:
    """
    Create a fresh VEVENT from src, properly copying all fields,
    fixing the location, and prefixing the source name to the summary.
    """
    dst = Event()

    # Core required fields — copy directly
    dst.add("uid",     str(src.get("uid",  str(uuid.uuid4()))) )
    dst.add("dtstamp", src.get("dtstamp", datetime.now(timezone.utc)))

    # Summary — prefix with source name
    raw_summary = str(src.get("summary", "Event"))
    if not raw_summary.startswith("["):
        raw_summary = f"[{source_name}] {raw_summary}"
    dst.add("summary", raw_summary)

    # Dates — preserve as-is (already UTC with Z suffix from Luma)
    for field in ("dtstart", "dtend", "created", "last-modified"):
        val = src.get(field)
        if val:
            dst.add(field, val.dt if hasattr(val, "dt") else val)

    # Location — use real address when possible
    location = extract_real_location(src)
    if location:
        dst.add("location", location)

    # Description — keep original
    desc = str(src.get("description", ""))
    dst.add("description", desc)

    # URL — keep original
    url = src.get("url")
    if url:
        dst.add("url", str(url))

    # Status — use CONFIRMED so Google shows events normally
    dst.add("status", "CONFIRMED")

    # Organizer — copy if present
    organizer = src.get("organizer")
    if organizer:
        dst.add("organizer", organizer)

    return dst


# ─── Luma iCal Fetching ───────────────────────────────────────────────────────

def fetch_luma(name: str, url: str) -> list[Event]:
    """Fetch a Luma iCal URL and return a list of clean VEVENT objects."""
    events = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
        for component in cal.walk():
            if component.name == "VEVENT":
                events.append(make_clean_vevent(component, name))
        print(f"  ✓  {name} ({len(events)} events)")
    except Exception as e:
        print(f"  ✗  {name}: {e}", file=sys.stderr)
    return events


# ─── HTML Scrapers ────────────────────────────────────────────────────────────

def dict_to_vevent(ev: dict, source_name: str) -> Event:
    """Convert a scraped event dict to a clean VEVENT component."""
    vevent = Event()
    vevent.add("uid",     str(uuid.uuid4()) + "@event-aggregator")
    vevent.add("summary", f"[{source_name}] {ev.get('summary', 'Event')}")
    vevent.add("description", ev.get("description", "") + f"\n\nSource: {ev.get('url','')}")
    vevent.add("status",  "CONFIRMED")

    url = ev.get("url", "")
    if url:
        vevent.add("url", url)
    if ev.get("location"):
        vevent.add("location", ev["location"])

    now = datetime.now(timezone.utc)
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
                    if item.get("@type") == "Event":
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
                link = card.find("a") if card.name != "a" else card
                title = card.find(["h2", "h3", "h4"]) or card
                if title and title.get_text(strip=True):
                    href = (link["href"] if link and link.get("href") else url)
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
    merged.add("prodid",       "-//NYC AI Event Aggregator//EN")
    merged.add("version",      "2.0")
    merged.add("calscale",     "GREGORIAN")
    merged.add("method",       "PUBLISH")
    merged.add("x-wr-calname", "NYC AI & Tech Events — Aggregated")
    merged.add("x-wr-caldesc", "Auto-aggregated from Luma, Verci, Betaworks, AI Tinkerers & more.")
    merged.add("x-wr-timezone","America/New_York")

    # Embed VTIMEZONE so clients know how to render UTC times
    tz_cal = Calendar.from_ical(
        "BEGIN:VCALENDAR\nVERSION:2.0\n" + VTIMEZONE_NYC + "\nEND:VCALENDAR"
    )
    for component in tz_cal.walk():
        if component.name == "VTIMEZONE":
            merged.add_component(component)

    event_count = 0

    # ── Luma calendars ────────────────────────────────────────────────────────
    print("\n📡 Fetching Luma calendars…")
    for name, url in LUMA_DIRECT_ICS_URLS.items():
        for vevent in fetch_luma(name, url):
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
            merged.add_component(dict_to_vevent(ev, name))
            event_count += 1

    # ── Write output ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(merged.to_ical())

    print(f"\n✅  Written {event_count} events → {output_path}")


if __name__ == "__main__":
    build_merged_calendar()

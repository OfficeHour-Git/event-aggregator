#!/usr/bin/env python3
"""
Event Feed Aggregator
Merges multiple event calendars (Luma + others) into a single .ics feed.
"""

import requests
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from icalendar import Calendar, Event, vText
import uuid
import json
import sys

# ─── Source Definitions ───────────────────────────────────────────────────────

# Direct iCal URLs from Luma (api2.luma.com format)
# Two are identified; others labeled by cal-ID until confirmed
LUMA_DIRECT_ICS_URLS = {
    "Luma Calendar (cal-yrYsEKDQ91hPMWy)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-yrYsEKDQ91hPMWy",
    "Luma Calendar (cal-61Cv6COs4g9GKw7)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-61Cv6COs4g9GKw7",
    "Luma Calendar (cal-7Q5A70Bz5Idxopu)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-7Q5A70Bz5Idxopu",
    "Luma Calendar (cal-iOipAs7mv59Hbuz)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-iOipAs7mv59Hbuz",
    "Luma Calendar (cal-tBOSmnsBzW0kTrf)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-tBOSmnsBzW0kTrf",
    "Luma Calendar (cal-E74MDlDKBaeAwXK)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-E74MDlDKBaeAwXK",
    "Nebius Community":                      "https://api2.luma.com/ics/get?entity=calendar&id=cal-36Kb7AwwNrfc0eU",
    "Luma Calendar (cal-2mLDnq80EKWoGy8)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-2mLDnq80EKWoGy8",
    "Luma Calendar (cal-r8BcsXhhHYmA3tp)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-r8BcsXhhHYmA3tp",
    "Luma Calendar (cal-8zLyKMgaKTvonbT)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-8zLyKMgaKTvonbT",
    "Luma Calendar (cal-vSo9sRaAQOgoflu)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-vSo9sRaAQOgoflu",
    "Luma Calendar (cal-YKwEv0xAlmNR6VN)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-YKwEv0xAlmNR6VN",
    "Luma Calendar (cal-UAliCb7j5QccLrn)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-UAliCb7j5QccLrn",
    "AI Builders Collective":                "https://api2.luma.com/ics/get?entity=calendar&id=cal-QvcuRhmCBjOA1T7",
    "Luma Calendar (cal-RHI1LJC6K8JRBLI)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-RHI1LJC6K8JRBLI",
    "Luma Calendar (cal-l7gcEleWIMCKLbv)":  "https://api2.luma.com/ics/get?entity=calendar&id=cal-l7gcEleWIMCKLbv",
}

OTHER_SOURCES = {
    "Verci Events":             "https://www.verci.com/events",
    "Betaworks Events":         "https://www.betaworks.com/events",
    "AI Tinkerers (All Cities)":"https://aitinkerers.org/all_cities?m=r",
    "New York AI":              "https://newyorkai.org",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EventAggregator/1.0; "
        "+https://github.com/your-username/event-aggregator)"
    )
}

# ─── Luma iCal Fetching ───────────────────────────────────────────────────────

def fetch_luma_direct(name: str, url: str) -> Calendar | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)
        count = sum(1 for c in cal.walk() if c.name == "VEVENT")
        print(f"  ✓  {name} ({count} events)")
        return cal
    except Exception as e:
        print(f"  ✗  {name}: {e}", file=sys.stderr)
        return None

# ─── HTML Scrapers ────────────────────────────────────────────────────────────

def scrape_verci(url: str) -> list[dict]:
    """Scrape Verci events page."""
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
                            "summary":     item.get("name", "Verci Event"),
                            "description": item.get("description", ""),
                            "url":         item.get("url", url),
                            "dtstart":     item.get("startDate"),
                            "dtend":       item.get("endDate"),
                            "location":    (item.get("location") or {}).get("name", ""),
                        })
            except Exception:
                pass

        if not events:
            for card in soup.select("a[href*='/events/']"):
                title = card.get_text(strip=True)
                if title and len(title) > 3:
                    events.append({
                        "summary": title,
                        "url": "https://www.verci.com" + card["href"]
                               if card["href"].startswith("/") else card["href"],
                    })
        print(f"  ✓  Verci Events ({len(events)} events)")
    except Exception as e:
        print(f"  ✗  Verci Events: {e}", file=sys.stderr)
    return events


def scrape_betaworks(url: str) -> list[dict]:
    """Scrape Betaworks events page."""
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
                            "summary":     item.get("name", "Betaworks Event"),
                            "description": item.get("description", ""),
                            "url":         item.get("url", url),
                            "dtstart":     item.get("startDate"),
                            "dtend":       item.get("endDate"),
                            "location":    (item.get("location") or {}).get("name", ""),
                        })
            except Exception:
                pass

        if not events:
            for card in soup.select("article, .event-card, [class*='event']"):
                link = card.find("a")
                title = card.find(["h2", "h3", "h4"])
                if title:
                    href = link["href"] if link else url
                    if href.startswith("/"):
                        href = "https://www.betaworks.com" + href
                    events.append({
                        "summary": title.get_text(strip=True),
                        "url": href,
                    })
        print(f"  ✓  Betaworks Events ({len(events)} events)")
    except Exception as e:
        print(f"  ✗  Betaworks Events: {e}", file=sys.stderr)
    return events


def scrape_aitinkerers(url: str) -> list[dict]:
    """Scrape AI Tinkerers events page."""
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
                            "summary":     item.get("name", "AI Tinkerers Event"),
                            "description": item.get("description", ""),
                            "url":         item.get("url", url),
                            "dtstart":     item.get("startDate"),
                            "dtend":       item.get("endDate"),
                            "location":    (item.get("location") or {}).get("name", ""),
                        })
            except Exception:
                pass

        if not events:
            for card in soup.select(".event, [class*='event-card'], article"):
                link = card.find("a")
                title = card.find(["h2", "h3", "h4", "strong"])
                if title:
                    href = link["href"] if link else url
                    if href.startswith("/"):
                        href = "https://aitinkerers.org" + href
                    events.append({
                        "summary": title.get_text(strip=True),
                        "url": href,
                    })
        print(f"  ✓  AI Tinkerers ({len(events)} events)")
    except Exception as e:
        print(f"  ✗  AI Tinkerers: {e}", file=sys.stderr)
    return events


def scrape_newyorkai(url: str) -> list[dict]:
    """Scrape New York AI events page."""
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
                            "summary":     item.get("name", "NY AI Event"),
                            "description": item.get("description", ""),
                            "url":         item.get("url", url),
                            "dtstart":     item.get("startDate"),
                            "dtend":       item.get("endDate"),
                            "location":    (item.get("location") or {}).get("name", ""),
                        })
            except Exception:
                pass

        if not events:
            for card in soup.select("a[href*='event'], article, .event"):
                title = card.find(["h2", "h3", "h4"])
                if not title:
                    title = card
                if title and title.get_text(strip=True):
                    href = card.get("href", url) if card.name == "a" else url
                    events.append({
                        "summary": title.get_text(strip=True)[:100],
                        "url": href,
                    })
        print(f"  ✓  New York AI ({len(events)} events)")
    except Exception as e:
        print(f"  ✗  New York AI: {e}", file=sys.stderr)
    return events

# ─── iCal Helpers ─────────────────────────────────────────────────────────────

def dict_to_vevent(ev: dict, source_name: str) -> Event:
    """Convert a scraped event dict to a VEVENT component."""
    vevent = Event()
    vevent.add("uid", str(uuid.uuid4()) + "@event-aggregator")
    vevent.add("summary", f"[{source_name}] {ev.get('summary', 'Event')}")
    vevent.add("description", ev.get("description", "") + f"\n\nSource: {ev.get('url','')}")
    vevent.add("url", ev.get("url", ""))
    if ev.get("location"):
        vevent.add("location", ev["location"])

    now = datetime.now(timezone.utc)
    vevent.add("dtstamp", now)
    vevent.add("created", now)

    if ev.get("dtstart"):
        try:
            from dateutil.parser import parse as parse_dt
            vevent.add("dtstart", parse_dt(ev["dtstart"]))
        except Exception:
            vevent.add("dtstart", now)
    else:
        vevent.add("dtstart", now)

    if ev.get("dtend"):
        try:
            from dateutil.parser import parse as parse_dt
            vevent.add("dtend", parse_dt(ev["dtend"]))
        except Exception:
            pass

    return vevent


def stamp_source(vevent: Event, source_name: str) -> Event:
    """Prefix the summary of an existing VEVENT with the source name."""
    existing = str(vevent.get("summary", ""))
    if not existing.startswith("["):
        vevent["summary"] = vText(f"[{source_name}] {existing}")
    return vevent

# ─── Merge & Write ────────────────────────────────────────────────────────────

def build_merged_calendar(output_path: str = "docs/events.ics") -> None:
    merged = Calendar()
    merged.add("prodid", "-//NYC AI Event Aggregator//EN")
    merged.add("version", "2.0")
    merged.add("calscale", "GREGORIAN")
    merged.add("method", "PUBLISH")
    merged.add("x-wr-calname", "NYC AI & Tech Events — Aggregated")
    merged.add("x-wr-caldesc",
               "Auto-aggregated from Luma, Verci, Betaworks, AI Tinkerers, New York AI & more.")
    merged.add("x-wr-timezone", "America/New_York")

    event_count = 0

    # ── Luma direct iCal URLs ─────────────────────────────────────────────────
    print("\n📡 Fetching Luma calendars…")
    for name, url in LUMA_DIRECT_ICS_URLS.items():
        cal = fetch_luma_direct(name, url)
        if cal:
            for component in cal.walk():
                if component.name == "VEVENT":
                    stamp_source(component, name)
                    merged.add_component(component)
                    event_count += 1

    # ── Scraped sources ───────────────────────────────────────────────────────
    print("\n🕸  Scraping non-Luma sources…")
    scrapers = [
        ("Verci Events",             OTHER_SOURCES["Verci Events"],             scrape_verci),
        ("Betaworks Events",         OTHER_SOURCES["Betaworks Events"],         scrape_betaworks),
        ("AI Tinkerers (All Cities)",OTHER_SOURCES["AI Tinkerers (All Cities)"],scrape_aitinkerers),
        ("New York AI",              OTHER_SOURCES["New York AI"],              scrape_newyorkai),
    ]
    for name, url, scraper in scrapers:
        items = scraper(url)
        for ev in items:
            merged.add_component(dict_to_vevent(ev, name))
            event_count += 1

    # ── Write output ──────────────────────────────────────────────────────────
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(merged.to_ical())

    print(f"\n✅  Written {event_count} events → {output_path}")


if __name__ == "__main__":
    build_merged_calendar()

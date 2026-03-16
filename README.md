# NYC AI & Tech Events — Aggregated Feed

A self-hosted iCal aggregator that merges **18 NYC AI/tech event calendars** into
a single `.ics` feed, auto-updated every 6 hours via GitHub Actions and served via
GitHub Pages.

## Sources

| Calendar | URL | Method |
|---|---|---|
| Tavily Community | luma.com/eventstavily | Luma iCal API |
| Nebius Community | luma.com/calendar/cal-36Kb7AwwNrfc0eU | Luma iCal API |
| Bond AI NYC | luma.com/genai-ny | Luma iCal API |
| Open Source for AI | luma.com/oss4ai | Luma iCal API |
| The AI Collective | luma.com/genai-collective | Luma iCal API |
| Build Club | luma.com/buildercommunityanz | Luma iCal API |
| Rho Community | luma.com/rhoevents | Luma iCal API |
| Leverage SF | luma.com/LeverageSF | Luma iCal API |
| Startup Grind NYC | luma.com/startupgrindnyc | Luma iCal API |
| AI Builders Collective | luma.com/calendar/cal-QvcuRhmCBjOA1T7 | Luma iCal API |
| Fractal Tech NYC | luma.com/nyc-tech | Luma iCal API |
| Verci Events | verci.com/events | HTML scrape |
| Betaworks | betaworks.com/events | HTML scrape |
| AI Tinkerers | aitinkerers.org | HTML scrape |
| New York AI | newyorkai.org | HTML scrape |
| The Shortlist NYC | @TheShortlistNYC (X/Twitter) | Manual |
| Pitch & Run NYC | PitchandrunNYC | Manual |

---

## Setup (5 minutes)

### 1 — Fork / create this repo on GitHub

```bash
gh repo create event-aggregator --public --clone
# Copy these files in, then:
git add . && git commit -m "init" && git push
```

### 2 — Enable GitHub Pages

1. Go to your repo → **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / folder: `/docs`
4. Save — your feed URL will be:
   ```
   https://YOUR-USERNAME.github.io/event-aggregator/events.ics
   ```

### 3 — Trigger the first run

Go to **Actions → Update Event Feed → Run workflow**.

The `docs/events.ics` file will be created and pushed automatically.

---

## Adding to Google Calendar

```
https://calendar.google.com/calendar/r?cid=YOUR_ICS_URL_ENCODED
```

Or:
1. Open Google Calendar → **+ Other Calendars → From URL**
2. Paste: `https://YOUR-USERNAME.github.io/event-aggregator/events.ics`
3. Click **Add Calendar** — done. Google syncs ~every 12 hrs.

> **Tip:** To force a sync, remove and re-add the calendar.

---

## Adding to Notion

### Option A — Simple embed (read-only)
1. In a Notion page, type `/embed`
2. Paste the `.ics` URL — Notion will show an iframe

### Option B — Live database via Make.com (recommended)
1. Create a **Make.com** (free) account
2. New scenario: **Google Calendar → Watch Events** → **Notion → Create Database Item**
3. Map fields: `Name`, `Date`, `Location`, `URL`, `Source`
4. Schedule: every 1 hour
5. You'll have a fully searchable Notion database of all events.

---

## Local development

```bash
pip install -r requirements.txt
python aggregate.py
# outputs → docs/events.ics
```

---

## Customizing

- **Add more sources:** Edit `LUMA_COMMUNITY_SLUGS` or `LUMA_CALENDAR_IDS` in `aggregate.py`
- **Change update frequency:** Edit the cron in `.github/workflows/update-feed.yml`
- **Filter by city/topic:** Add keyword filtering in `build_merged_calendar()`

---

## Notes on Twitter/X sources

- **The Shortlist NYC** (`@TheShortlistNYC`) and **Pitch & Run NYC** post events on X.
  Twitter's API no longer supports free event scraping, so these are not automatically included.
  **Workaround:** Use [Zapier + Twitter](https://zapier.com/apps/twitter/integrations) to
  watch for tweets and push them to a Google Calendar event.

#!/usr/bin/env python3
"""
Morbidity Hub Daily Monitor
Searches NewsAPI for deaths, health emergencies, and tour cancellations
involving watchlist artists and high-profile music figures.
Sends email alerts and updates morbidity_data.js.
"""

import json
import os
import re
import smtplib
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── Configuration ───────────────────────────────────────────────
NEWSAPI_KEY = "ac97e04f91654a608d318da51ebf7aaf"
GMAIL_USER = "todd.burns@gmail.com"
GMAIL_APP_PASSWORD = "budy tcbf dous axiq"
ALERT_RECIPIENT = "todd.burns@gmail.com"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "morbidity_data.js")
LOG_FILE = os.path.join(SCRIPT_DIR, "morbidity_monitor.log")

# ─── Trusted Sources ────────────────────────────────────────────
# Only accept alerts from reputable music/entertainment/news outlets.
# Domains are matched as substrings against the article URL.
TRUSTED_DOMAINS = [
    "billboard.com", "rollingstone.com", "variety.com", "nme.com",
    "pitchfork.com", "consequence.net", "stereogum.com", "loudwire.com",
    "ultimateclassicrock.com", "classicrock.com", "musicradar.com",
    "brooklynvegan.com", "spin.com", "paste.com", "exclaim.ca",
    "bbc.com", "bbc.co.uk", "theguardian.com", "nytimes.com",
    "washingtonpost.com", "apnews.com", "reuters.com", "cnn.com",
    "nbcnews.com", "abcnews.go.com", "cbsnews.com", "usatoday.com",
    "latimes.com", "independent.co.uk", "telegraph.co.uk",
    "ew.com", "deadline.com", "hollywoodreporter.com", "tmz.com",
    "people.com", "pagesix.com", "vulture.com", "avclub.com",
    "udiscovermusic.com", "goldminemag.com", "americansongwriter.com",
    "hiphopdx.com", "complex.com", "hotnewhiphop.com", "xxlmag.com",
    "npr.org", "fox.com", "foxnews.com", "msnbc.com",
    "irishtimes.com", "sky.com", "skynews.com", "news.sky.com",
    "cbc.ca", "abc.net.au", "stuff.co.nz",
]

# ─── Watchlist with search hints ─────────────────────────────────
# "search_name" is used for ambiguous/short names to reduce false positives.
WATCHLIST = [
    {"name": "Barry Gibb", "age": 79},
    {"name": "Berry Gordy", "age": 96},
    {"name": "Bill Wyman", "age": 89},
    {"name": "Bob Dylan", "age": 84},
    {"name": "Brenda Holloway", "age": 79},
    {"name": "Brian May", "age": 78, "search_name": "Brian May Queen"},
    {"name": "Buddy Guy", "age": 89},
    {"name": "Carole Kaye", "age": 91},
    {"name": "Diana Ross", "age": 82},
    {"name": "Dion", "age": 86, "search_name": "Dion DiMucci"},
    {"name": "Dr. Dre", "age": 61},
    {"name": "Elton John", "age": 78},
    {"name": "Eric Clapton", "age": 80},
    {"name": "Garth Hudson", "age": 88},
    {"name": "George Thorogood", "age": 75},
    {"name": "Glenn Hughes", "age": 73, "search_name": "Glenn Hughes Deep Purple"},
    {"name": "Herb Alpert", "age": 91},
    {"name": "Ian Hunter", "age": 86, "search_name": "Ian Hunter Mott the Hoople"},
    {"name": "Iggy Pop", "age": 78},
    {"name": "John Fogerty", "age": 80},
    {"name": "Joni Mitchell", "age": 82},
    {"name": "Keith Richards", "age": 82},
    {"name": "Kenny Burrell", "age": 93},
    {"name": "Kim Weston", "age": 87, "search_name": "Kim Weston singer"},
    {"name": "Klaus Voormann", "age": 87},
    {"name": "Manfred Eicher", "age": 82, "search_name": "Manfred Eicher ECM"},
    {"name": "Marshall Allen", "age": 101, "search_name": "Marshall Allen Sun Ra"},
    {"name": "Martha Reeves", "age": 84},
    {"name": "Mavis Staples", "age": 86},
    {"name": "Mick Jagger", "age": 82},
    {"name": "Mike Stoller", "age": 93, "search_name": "Mike Stoller Leiber Stoller"},
    {"name": "Neil Diamond", "age": 85},
    {"name": "Ozzy Osbourne", "age": 77},
    {"name": "Paul McCartney", "age": 83},
    {"name": "Randy Newman", "age": 82},
    {"name": "Ray Cooper", "age": 79, "search_name": "Ray Cooper musician"},
    {"name": "Ray Davies", "age": 81, "search_name": "Ray Davies Kinks"},
    {"name": "Ringo Starr", "age": 85},
    {"name": "Rod Stewart", "age": 81},
    {"name": "Roger Daltrey", "age": 82},
    {"name": "Ron Carter", "age": 88, "search_name": "Ron Carter jazz"},
    {"name": "Smokey Robinson", "age": 86},
    {"name": "Sonny Rollins", "age": 95},
    {"name": "Steve Winwood", "age": 78},
    {"name": "Tom Waits", "age": 76},
    {"name": "Tony Iommi", "age": 77},
    {"name": "Wanda Jackson", "age": 88},
    {"name": "Willie Nelson", "age": 92},
    {"name": "Yoko Ono", "age": 93},
    {"name": "Anni-Frid Lyngstad", "age": 80},
    {"name": "Barbra Streisand", "age": 83},
    {"name": "Benny Andersson", "age": 79},
    {"name": "Björn Ulvaeus", "age": 80},
    {"name": "Booker T. Jones", "age": 81},
    {"name": "Donald Fagen", "age": 78},
    {"name": "Engelbert Humperdinck", "age": 89},
    {"name": "George Clinton", "age": 84, "search_name": "George Clinton Parliament Funkadelic"},
    {"name": "Jerry Butler", "age": 86, "search_name": "Jerry Butler singer"},
    {"name": "John Cale", "age": 83, "search_name": "John Cale Velvet Underground"},
    {"name": "John Williams", "age": 94, "search_name": "John Williams composer"},
    {"name": "Kris Kristofferson", "age": 88},
    {"name": "Lalo Schifrin", "age": 93},
    {"name": "Patti LaBelle", "age": 81},
    {"name": "Randy Bachman", "age": 82},
    {"name": "Shirley Bassey", "age": 89},
    {"name": "Steven Tyler", "age": 77},
    {"name": "Richard Davis", "age": 96, "search_name": "Richard Davis bassist jazz"},
]

DEATH_KEYWORDS = ["died", "dead", "dies", "death of", "passed away", "passes away",
                   "obituary", "rip ", "r.i.p.", "mourns", "mourning"]
HEALTH_KEYWORDS = ["hospitalized", "hospitalised", "hospital", "critical condition",
                    "health scare", "health crisis", "intensive care", "icu",
                    "diagnosed", "surgery", "stroke", "heart attack"]
TOUR_KEYWORDS = ["canceled tour", "cancelled tour", "cancels tour",
                  "postponed tour", "postpones tour", "tour canceled",
                  "tour cancelled", "tour postponed"]


# ─── Logging ─────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ─── NewsAPI Queries ─────────────────────────────────────────────
def search_news(query, from_date=None, page_size=20):
    """Search NewsAPI for articles matching query."""
    if from_date is None:
        from_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    params = urllib.parse.urlencode({
        "q": query,
        "from": from_date,
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": NEWSAPI_KEY,
        "language": "en",
    })
    url = f"https://newsapi.org/v2/everything?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MorbidityMonitor/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "ok":
                return data.get("articles", [])
            else:
                log(f"  NewsAPI error: {data.get('message', 'unknown')}")
                return []
    except Exception as e:
        log(f"  Request error for query '{query[:50]}...': {e}")
        return []


# ─── Filtering ───────────────────────────────────────────────────
def is_trusted_source(article):
    """Check if article comes from a trusted news/entertainment source."""
    url = (article.get("url") or "").lower()
    source_name = ((article.get("source") or {}).get("name") or "").lower()
    for domain in TRUSTED_DOMAINS:
        if domain in url or domain.replace(".com", "").replace(".co.uk", "") in source_name:
            return True
    return False


def artist_in_title(artist_name, article):
    """Check if the artist's name actually appears in the headline."""
    title = (article.get("title") or "").lower()
    name_lower = artist_name.lower()

    # Check full name
    if name_lower in title:
        return True

    # Check last name for multi-word names (e.g., "McCartney" for "Paul McCartney")
    parts = artist_name.split()
    if len(parts) >= 2:
        last = parts[-1].lower()
        # Avoid matching very short/common last names
        if len(last) >= 4 and last in title:
            return True

    return False


def keyword_near_name_in_title(artist_name, title_text, keywords):
    """Check if a keyword appears in the title AND the artist name is in the title.
    This ensures the keyword is actually about the artist, not some unrelated part.
    """
    title_lower = title_text.lower()
    name_lower = artist_name.lower()

    # Artist must be in the title
    name_in_title = name_lower in title_lower
    if not name_in_title:
        parts = artist_name.split()
        if len(parts) >= 2:
            last = parts[-1].lower()
            if len(last) >= 4:
                name_in_title = last in title_lower

    if not name_in_title:
        return False

    # At least one keyword must also be in the title
    for kw in keywords:
        if kw in title_lower:
            return True

    return False


def validate_watchlist_article(artist_name, article):
    """Apply all filters to determine if an article is a genuine alert.
    Returns (is_valid, category) or (False, None).
    """
    title = (article.get("title") or "")
    desc = (article.get("description") or "")
    title_lower = title.lower()

    # FILTER 1: Must come from a trusted source
    if not is_trusted_source(article):
        return False, None

    # FILTER 2: Artist name must appear in the title
    if not artist_in_title(artist_name, article):
        return False, None

    # FILTER 3: A relevant keyword must appear in the title alongside the artist
    if keyword_near_name_in_title(artist_name, title, DEATH_KEYWORDS):
        return True, "death"
    if keyword_near_name_in_title(artist_name, title, HEALTH_KEYWORDS):
        return True, "health"
    if keyword_near_name_in_title(artist_name, title, TOUR_KEYWORDS):
        return True, "tour"

    # FILTER 3b: Fallback — keyword in title even without strict proximity
    # (title is short enough that co-occurrence is meaningful)
    for kw in DEATH_KEYWORDS:
        if kw in title_lower:
            return True, "death"
    for kw in HEALTH_KEYWORDS:
        if kw in title_lower:
            return True, "health"
    for kw in TOUR_KEYWORDS:
        if kw in title_lower:
            return True, "tour"

    return False, None


def validate_general_article(article):
    """Validate a general music death article (not tied to a watchlist artist)."""
    if not is_trusted_source(article):
        return False, None

    title = (article.get("title") or "").lower()

    # Must have a death keyword in the title
    for kw in DEATH_KEYWORDS:
        if kw in title:
            return True, "death"

    return False, None


# ─── Search Functions ────────────────────────────────────────────
def search_watchlist_artist(artist):
    """Search for a watchlist artist using combined query. Returns validated articles."""
    search_name = artist.get("search_name", artist["name"])
    display_name = artist["name"]

    q = (f'"{search_name}" AND (died OR dies OR death OR "passed away" OR obituary '
         f'OR hospitalized OR "critical condition" OR "health scare" OR hospital '
         f'OR "canceled tour" OR "cancelled tour" OR "postponed tour")')
    articles = search_news(q, page_size=10)
    time.sleep(1.0)  # Rate limiting — NewsAPI free tier: 100 req/day

    results = []
    for a in articles:
        is_valid, category = validate_watchlist_article(display_name, a)
        if is_valid:
            results.append({**a, "_category": category, "_artist": display_name})

    return results


def search_general_music_deaths():
    """Search for general high-profile music figure deaths."""
    q = 'musician died OR "singer died" OR "guitarist died" OR "rapper died" OR "music legend died"'
    articles = search_news(q, page_size=30)

    results = []
    for a in articles:
        is_valid, category = validate_general_article(a)
        if is_valid:
            results.append({**a, "_category": category, "_artist": ""})

    return results


# ─── Processing ──────────────────────────────────────────────────
def deduplicate(articles):
    """Remove duplicate articles by URL."""
    seen = set()
    unique = []
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(a)
    return unique


def classify_article(article):
    """Build a structured alert from a raw article."""
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "artistName": article.get("_artist", ""),
        "category": article.get("_category", "general"),
        "headline": article.get("title", "") or "",
        "url": article.get("url", ""),
        "source": (article.get("source") or {}).get("name", ""),
    }


# ─── Email ───────────────────────────────────────────────────────
def send_email(subject, html_body):
    """Send email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_USER
    msg["To"] = ALERT_RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        log(f"  Email sent: {subject}")
        return True
    except Exception as e:
        log(f"  Email failed: {e}")
        return False


def send_death_alert(alert):
    """Send immediate email for a watchlist artist death."""
    subject = f"URGENT: {alert['artistName']} — Death Reported"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;">
        <h2 style="color:#FF0000;">⚠️ Watchlist Artist Death Alert</h2>
        <p><strong>{alert['artistName']}</strong> — potential death reported.</p>
        <p><strong>Headline:</strong> {alert['headline']}</p>
        <p><strong>Source:</strong> {alert['source']}</p>
        <p><a href="{alert['url']}" style="color:#0066cc;">Read article →</a></p>
        <hr>
        <p style="font-size:12px;color:#666;">Morbidity Hub Monitor — {alert['date']}</p>
    </div>
    """
    send_email(subject, body)


def send_daily_digest(alerts):
    """Send daily digest of all findings."""
    if not alerts:
        subject = "Morbidity Hub: No alerts today"
        body = """
        <div style="font-family:Arial,sans-serif;max-width:600px;">
            <h2>Morbidity Hub Daily Digest</h2>
            <p>No relevant news found today. All watchlist artists appear safe.</p>
            <p style="font-size:12px;color:#666;">Monitoring {count} artists.</p>
        </div>
        """.format(count=len(WATCHLIST))
        send_email(subject, body)
        return

    subject = f"Morbidity Hub: {len(alerts)} alert(s) — {datetime.now().strftime('%b %d, %Y')}"

    deaths = [a for a in alerts if a["category"] == "death"]
    health = [a for a in alerts if a["category"] == "health"]
    tours = [a for a in alerts if a["category"] == "tour"]
    general = [a for a in alerts if a["category"] == "general"]

    def render_section(title, items, color):
        if not items:
            return ""
        rows = ""
        for a in items:
            artist = f"<strong>{a['artistName']}</strong>: " if a["artistName"] else ""
            rows += f'<li>{artist}<a href="{a["url"]}" style="color:#0066cc;">{a["headline"]}</a> <span style="color:#999;">({a["source"]})</span></li>\n'
        return f'<h3 style="color:{color};">{title} ({len(items)})</h3><ul>{rows}</ul>'

    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;">
        <h2>Morbidity Hub Daily Digest</h2>
        <p>{len(alerts)} alert(s) found on {datetime.now().strftime('%B %d, %Y')}.</p>
        {render_section("Deaths", deaths, "#FF0000")}
        {render_section("Health Emergencies", health, "#FF8800")}
        {render_section("Tour Cancellations (Health)", tours, "#0088FF")}
        {render_section("General Music Deaths", general, "#8B5CF6")}
        <hr>
        <p style="font-size:12px;color:#666;">Morbidity Hub Monitor — monitoring {len(WATCHLIST)} artists</p>
    </div>
    """
    send_email(subject, body)


# ─── Update Data File ────────────────────────────────────────────
def load_existing_alerts():
    """Load existing alerts from morbidity_data.js."""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r") as f:
            content = f.read()
        match = re.search(r"const MORBIDITY_ALERTS\s*=\s*\[(.*?)\];", content, re.DOTALL)
        if match:
            arr_text = match.group(1).strip()
            if not arr_text or arr_text.startswith("//"):
                return []
            cleaned = re.sub(r"//[^\n]*", "", arr_text)
            cleaned = f"[{cleaned}]"
            return json.loads(cleaned)
    except Exception as e:
        log(f"  Could not parse existing alerts: {e}")
    return []


def update_data_file(new_alerts):
    """Rewrite morbidity_data.js with current watchlist and merged alerts."""
    existing = load_existing_alerts()

    seen_urls = set()
    merged = []
    for a in new_alerts + existing:
        url = a.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged.append(a)
    merged = merged[:200]

    status_map = {
        "Barry Gibb": "In Edits", "Ian Hunter": "In Edits",
        "Booker T. Jones": "Written", "John Williams": "Written", "Patti LaBelle": "Written",
        "Richard Davis": "Published",
    }

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"// Morbidity Hub Data — auto-updated by monitor_morbidity.py",
        f"// Last updated: {now}",
        "",
        f'const MORBIDITY_LAST_RUN = "{now}";',
        "",
        "const MORBIDITY_WATCHLIST = [",
    ]
    for artist in WATCHLIST:
        status = status_map.get(artist["name"], "Pending")
        lines.append(f'    {{ name: "{artist["name"]}", age: {artist["age"]}, preObitStatus: "{status}" }},')
    lines.append("];")
    lines.append("")
    lines.append("const MORBIDITY_ALERTS = [")
    for a in merged:
        safe = {k: str(v).replace('"', '\\"').replace("\n", " ") for k, v in a.items()}
        lines.append(
            f'    {{ date: "{safe.get("date","")}", artistName: "{safe.get("artistName","")}", '
            f'category: "{safe.get("category","")}", headline: "{safe.get("headline","")}", '
            f'url: "{safe.get("url","")}", source: "{safe.get("source","")}" }},'
        )
    lines.append("];")
    lines.append("")

    with open(DATA_FILE, "w") as f:
        f.write("\n".join(lines))
    log(f"  Updated {DATA_FILE} with {len(merged)} alerts")


# ─── Main ────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("Morbidity Hub Monitor — starting run")
    log(f"Monitoring {len(WATCHLIST)} watchlist artists")
    log(f"Trusted sources: {len(TRUSTED_DOMAINS)} domains")

    all_articles = []
    watchlist_death_alerts = []

    # Search for each watchlist artist
    for i, artist in enumerate(WATCHLIST):
        log(f"  [{i+1}/{len(WATCHLIST)}] Searching: {artist['name']}")
        results = search_watchlist_artist(artist)
        if results:
            log(f"    ✓ {len(results)} validated alert(s)")
            all_articles.extend(results)

    # Search for general music deaths
    log("  Searching general music deaths...")
    general = search_general_music_deaths()
    if general:
        log(f"    ✓ {len(general)} validated article(s)")
        all_articles.extend(general)

    # Deduplicate and classify
    unique = deduplicate(all_articles)
    log(f"  {len(unique)} unique validated alerts")

    alerts = [classify_article(a) for a in unique]

    # Separate watchlist deaths for immediate alerts
    watchlist_names = {a["name"].lower() for a in WATCHLIST}
    for alert in alerts:
        if alert["category"] == "death" and alert["artistName"].lower() in watchlist_names:
            watchlist_death_alerts.append(alert)

    # Send immediate alerts for watchlist deaths
    for alert in watchlist_death_alerts:
        log(f"  URGENT: Sending death alert for {alert['artistName']}")
        send_death_alert(alert)

    # Send daily digest (all alerts except already-sent death alerts)
    digest_alerts = [a for a in alerts if a not in watchlist_death_alerts]
    log(f"  Sending daily digest with {len(digest_alerts)} alert(s)")
    send_daily_digest(digest_alerts)

    # Update data file
    update_data_file(alerts)

    log(f"Monitor run complete. {len(alerts)} total alerts found.")
    log("=" * 60)


if __name__ == "__main__":
    main()

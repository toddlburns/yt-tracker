#!/usr/bin/env python3
"""Daily Music News Email - fetches RSS feeds and emails articles mentioning tracked artists."""

import re, smtplib, ssl, os, sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

GMAIL_ADDRESS = os.environ.get('GMAIL_ADDRESS', 'todd.burns@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

FEEDS = [
    {'name': 'Billboard', 'url': 'https://www.billboard.com/feed/'},
    {'name': 'Variety', 'url': 'https://variety.com/v/music/feed/'},
    {'name': 'Rolling Stone', 'url': 'https://www.rollingstone.com/music/feed/'},
]

TRACKED_ARTISTS = [
    'Aerosmith','Akon','Amy Winehouse','Andrea Bocelli','Audioslave','Beastie Boys',
    'Bee Gees','Billy Idol','Black Eyed Peas','Bob Marley','Bob Seger','Bon Jovi',
    'Boyz II Men','Cat Stevens','Yusuf Islam','Chris Cornell','Common',"D'Angelo",
    'Def Leppard','DMX','Elton John','Elvis Costello','Erykah Badu','Fall Out Boy',
    'Frank Sinatra','Frank Zappa','Glen Campbell','Godsmack',"Guns N' Roses",
    'Heart','Janet Jackson','Jeremih','Jimmy Eat World','Jodeci','John Lennon',
    'John Mellencamp','Johnny Cash','Juvenile','Kenny Rogers','Keyshia Cole','Kiss',
    'Lenny Kravitz','Lionel Richie','Little Big Town','LL COOL J','Mariah Carey',
    'Marvin Gaye','Mary J. Blige','Neil Diamond','Nelly Furtado','Nirvana',
    'OneRepublic','Paul McCartney','Peter Frampton','Queens Of The Stone Age',
    'Ringo Starr','Roger Hodgson','Rush','Shania Twain','Smashing Pumpkins',
    'Sonic Youth','Soundgarden','Spice Girls','Sting','Supertramp','The Beach Boys',
    'The Beatles','The Black Crowes','The Cranberries','The Game','The Rolling Stones',
    'The Who','Toby Keith','Tom Petty','Heartbreakers','Trisha Yearwood','U2','Weezer','Nelly',
]

_artist_pattern = re.compile(
    r'\b(' + '|'.join(re.escape(a) for a in TRACKED_ARTISTS) + r')\b', re.IGNORECASE
)


def fetch_feed(feed):
    try:
        req = Request(feed['url'], headers={'User-Agent': 'MusicNewsDigest/1.0'})
        with urlopen(req, timeout=15) as resp:
            xml = resp.read()
        root = ET.fromstring(xml)
        articles = []
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub_date = (item.findtext('pubDate') or '').strip()
            desc_raw = (item.findtext('description') or '').strip()
            desc = re.sub(r'<[^>]*>', '', desc_raw)[:300]
            try:
                dt = parsedate_to_datetime(pub_date)
            except Exception:
                dt = None
            artists = list(set(_artist_pattern.findall(title + ' ' + desc)))
            articles.append({
                'title': title, 'link': link, 'date': dt,
                'description': desc, 'source': feed['name'],
                'artists': artists,
            })
        return articles
    except Exception as e:
        print(f"  Error fetching {feed['name']}: {e}")
        return []


def time_ago(dt, now):
    diff = now - dt
    hours = diff.total_seconds() / 3600
    if hours < 1:
        return f"{int(diff.total_seconds()/60)}m ago"
    elif hours < 24:
        return f"{int(hours)}h ago"
    else:
        return f"{int(hours/24)}d ago"


def build_email():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)

    all_articles = []
    for feed in FEEDS:
        articles = fetch_feed(feed)
        all_articles.extend(articles)
        print(f"  {feed['name']}: {len(articles)} articles")

    relevant = [a for a in all_articles if a['artists'] and a['date'] and a['date'] > cutoff]
    all_recent = [a for a in all_articles if a['date'] and a['date'] > cutoff]

    relevant.sort(key=lambda a: a['date'], reverse=True)
    all_recent.sort(key=lambda a: a['date'], reverse=True)

    today_str = datetime.now().strftime('%B %d, %Y')

    html = f"""<html><body style="font-family: -apple-system, Arial, sans-serif; background: #f5f5f5; padding: 20px;">
<div style="max-width: 640px; margin: 0 auto; background: #fff; border-radius: 8px; overflow: hidden;">
<div style="background: linear-gradient(135deg, #0a1628, #1a0a20); padding: 24px 20px; color: white;">
    <h1 style="margin:0; font-size: 22px;">Music News Digest</h1>
    <p style="margin: 4px 0 0; opacity: 0.7; font-size: 14px;">{today_str}</p>
</div>
<div style="padding: 20px;">
"""

    if relevant:
        html += f'<h2 style="color: #0a1628; font-size: 16px; margin: 0 0 16px; border-bottom: 2px solid #00bcd4; padding-bottom: 8px;">Artist News ({len(relevant)} articles)</h2>'
        for a in relevant:
            artist_tags = ' '.join(
                f'<span style="display:inline-block;background:#e3f2fd;color:#1565c0;padding:2px 8px;border-radius:12px;font-size:11px;margin-right:4px;">{ar}</span>'
                for ar in a['artists']
            )
            ta = time_ago(a['date'], now)
            html += f"""<div style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #eee;">
    <a href="{a['link']}" style="color: #1a1a2e; text-decoration: none; font-weight: 600; font-size: 15px; line-height: 1.3;">{a['title']}</a>
    <div style="margin-top: 4px; font-size: 13px; color: #666; line-height: 1.4;">{a['description'][:200]}</div>
    <div style="margin-top: 6px;">{artist_tags} <span style="color: #999; font-size: 12px;">{a['source']} &middot; {ta}</span></div>
</div>"""
    else:
        html += '<p style="color: #999;">No articles mentioning tracked artists in the last 48 hours.</p>'

    others = [a for a in all_recent if not a['artists']][:15]
    if others:
        html += f'<h2 style="color: #0a1628; font-size: 16px; margin: 24px 0 16px; border-bottom: 2px solid #888; padding-bottom: 8px;">Other Music News ({len(others)} recent)</h2>'
        for a in others:
            ta = time_ago(a['date'], now)
            html += f"""<div style="margin-bottom: 12px;">
    <a href="{a['link']}" style="color: #444; text-decoration: none; font-size: 14px;">{a['title']}</a>
    <span style="color: #999; font-size: 12px;"> &middot; {a['source']} &middot; {ta}</span>
</div>"""

    html += """
    <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #eee; text-align: center;">
        <a href="https://toddlburns.github.io/yt-tracker/" style="color: #00bcd4; text-decoration: none; font-size: 13px;">Open Priority Artist Hub</a>
    </div>
</div></div></body></html>"""

    return html, len(relevant)


def send_email(html, count):
    if not GMAIL_APP_PASSWORD:
        print("ERROR: GMAIL_APP_PASSWORD not set. Cannot send email.")
        sys.exit(1)

    subject = f"Music News Digest - {datetime.now().strftime('%b %d')} ({count} artist mentions)"

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = GMAIL_ADDRESS
    msg.attach(MIMEText(html, 'html'))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
    print(f"Email sent to {GMAIL_ADDRESS} ({count} artist articles)")


if __name__ == '__main__':
    print(f"Music News Digest - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    html, count = build_email()
    send_email(html, count)

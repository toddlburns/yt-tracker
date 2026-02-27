#!/usr/bin/env python3
"""YouTube Digest Email - fetches new videos from tracked channels and emails a digest."""

import json, os, sys, time, re, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError
from xml.etree import ElementTree as ET
from html import escape

GMAIL_ADDRESS = os.environ.get('GMAIL_ADDRESS', 'todd.burns@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

PIPED_INSTANCES = [
    'pipedapi.kavin.rocks',
    'pipedapi.adminforge.de',
    'pipedapi-libre.kavin.rocks',
    'piped-api.codespace.cz',
]

ATOM_NS = 'http://www.w3.org/2005/Atom'
YT_NS = 'http://www.youtube.com/xml/schemas/2015'
MEDIA_NS = 'http://search.yahoo.com/mrss/'
NS = {'atom': ATOM_NS, 'yt': YT_NS, 'media': MEDIA_NS}


CHANNELS_API = os.environ.get('CHANNELS_API', 'https://x5clvswqw7.execute-api.us-east-1.amazonaws.com/prod/channels?key=racine456')


def load_channels():
    # Try loading from cloud API first
    try:
        req = Request(CHANNELS_API, headers={'User-Agent': 'YouTubeDigest/1.0'})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if isinstance(data, list) and len(data) > 0:
            print(f'  Loaded {len(data)} channels from cloud API')
            return data
    except Exception as e:
        print(f'  Cloud API error: {e}, falling back to channels.json')

    # Fallback to local channels.json
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.join(script_dir, '..', '..')
    channels_path = os.path.join(repo_root, 'channels.json')
    with open(channels_path) as f:
        return json.load(f)


def fetch_rss(channel_id):
    url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    req = Request(url, headers={'User-Agent': 'YouTubeDigest/1.0'})
    try:
        with urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        channel_name = ''
        author = root.find('atom:author/atom:name', NS)
        if author is not None:
            channel_name = author.text or ''

        videos = []
        for entry in root.findall('atom:entry', NS):
            video_id_el = entry.find('yt:videoId', NS)
            title_el = entry.find('atom:title', NS)
            published_el = entry.find('atom:published', NS)
            stats_el = entry.find('.//media:group/media:community/media:statistics', NS)
            thumb_el = entry.find('.//media:group/media:thumbnail', NS)

            video_id = video_id_el.text if video_id_el is not None else ''
            title = title_el.text if title_el is not None else ''
            published = published_el.text if published_el is not None else ''
            views = int(stats_el.get('views', '0')) if stats_el is not None else 0
            thumbnail = thumb_el.get('url', '') if thumb_el is not None else ''

            try:
                uploaded = datetime.fromisoformat(published.replace('Z', '+00:00'))
            except Exception:
                uploaded = None

            videos.append({
                'videoId': video_id,
                'title': title,
                'channel': channel_name,
                'channelId': channel_id,
                'uploaded': uploaded,
                'views': views,
                'thumbnail': thumbnail,
                'duration': 0,
            })
        return videos
    except Exception as e:
        print(f'  RSS error for {channel_id}: {e}')
        return []


def enrich_durations(videos):
    """Try Piped API instances to get video durations."""
    if not videos:
        return
    channel_id = videos[0]['channelId']
    for instance in PIPED_INSTANCES:
        try:
            url = f'https://{instance}/channel/{channel_id}'
            req = Request(url, headers={'User-Agent': 'YouTubeDigest/1.0'})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if 'relatedStreams' not in data:
                continue
            duration_map = {}
            for v in data['relatedStreams']:
                vid = v.get('url', '').replace('/watch?v=', '')
                if vid and v.get('duration'):
                    duration_map[vid] = v['duration']
            for video in videos:
                if video['videoId'] in duration_map:
                    video['duration'] = duration_map[video['videoId']]
            return
        except Exception:
            continue

    # Fallback: try individual video endpoints for videos still missing duration
    missing = [v for v in videos if v['duration'] == 0]
    for video in missing:
        for instance in PIPED_INSTANCES:
            try:
                url = f'https://{instance}/streams/{video["videoId"]}'
                req = Request(url, headers={'User-Agent': 'YouTubeDigest/1.0'})
                with urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                if data.get('duration'):
                    video['duration'] = data['duration']
                    break
            except Exception:
                continue

    still_missing = sum(1 for v in videos if v['duration'] == 0)
    if still_missing:
        print(f'  Duration enrichment: {still_missing} videos still missing for {channel_id}')


def format_views(n):
    if n >= 1e9:
        return f'{n/1e9:.1f}B'
    if n >= 1e6:
        return f'{n/1e6:.1f}M'
    if n >= 1e3:
        return f'{n/1e3:.1f}K'
    return str(n)


def format_duration(seconds):
    if not seconds:
        return ''
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def build_email(channels, cutoff):
    artist_names_lower = [c['name'].lower() for c in channels if c.get('type') == 'artist']
    all_videos = []
    processed = 0

    for ch in channels:
        processed += 1
        print(f'  [{processed}/{len(channels)}] {ch["name"]}...')
        videos = fetch_rss(ch['channelId'])

        if videos:
            enrich_durations(videos)
            time.sleep(0.3)

        for v in videos:
            if not v['uploaded'] or v['uploaded'] < cutoff:
                continue
            # Exclude videos 60 seconds or shorter (also exclude if duration unknown)
            if v['duration'] <= 60:
                continue
            # For omni channels, only include videos mentioning a tracked artist
            if ch.get('type') == 'omni':
                title_lower = v['title'].lower()
                if not any(name in title_lower for name in artist_names_lower):
                    continue
            all_videos.append(v)

    # Sort by views (most viewed first)
    all_videos.sort(key=lambda v: v['views'], reverse=True)

    now = datetime.now(timezone.utc)
    today_str = now.strftime('%B %d, %Y')
    is_monday = now.weekday() == 0

    if not all_videos:
        html = f'''<html><body style="font-family: -apple-system, Arial, sans-serif; background: #f5f5f5; padding: 20px; margin: 0;">
<div style="max-width: 640px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
<div style="background: linear-gradient(135deg, #0a1628, #1a0a20); padding: 24px 20px; color: white;">
    <h1 style="margin:0; font-size: 22px; font-weight: 700;">YouTube Digest</h1>
    <p style="margin: 4px 0 0; opacity: 0.7; font-size: 14px;">{today_str}</p>
</div>
<div style="padding: 20px;">
    <p style="color: #666; font-size: 14px;">No new videos found since the last digest.</p>
    <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #eee; text-align: center;">
        <a href="https://toddlburns.github.io/yt-tracker/" style="color: #00bcd4; text-decoration: none; font-size: 13px;">Manage Channels</a>
    </div>
</div></div></body></html>'''
        return html, 0

    weekend_label = ' (includes weekend)' if is_monday else ''

    html = f'''<html><body style="font-family: -apple-system, Arial, sans-serif; background: #f5f5f5; padding: 20px; margin: 0;">
<div style="max-width: 640px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
<div style="background: linear-gradient(135deg, #0a1628, #1a0a20); padding: 24px 20px; color: white;">
    <h1 style="margin:0; font-size: 22px; font-weight: 700;">YouTube Digest</h1>
    <p style="margin: 4px 0 0; opacity: 0.7; font-size: 14px;">{today_str} &middot; {len(all_videos)} video{"s" if len(all_videos) != 1 else ""}{weekend_label}</p>
</div>
<div style="padding: 20px;">
'''

    for v in all_videos:
        views_str = format_views(v['views'])
        dur_str = format_duration(v['duration'])
        dur_line = f'<div style="margin-top: 2px; font-size: 12px; color: #888;">Duration: {dur_str}</div>' if dur_str else ''
        yt_url = f'https://www.youtube.com/watch?v={v["videoId"]}'
        thumb_url = f'https://img.youtube.com/vi/{v["videoId"]}/hqdefault.jpg'
        title_escaped = escape(v['title'])
        channel_escaped = escape(v['channel'])

        html += f'''<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #eee;">
<tr>
<td width="130" valign="top" style="padding-right: 12px;">
    <a href="{yt_url}"><img src="{thumb_url}" width="120" height="68" style="border-radius: 6px; display: block; object-fit: cover;" alt=""></a>
</td>
<td valign="top">
    <a href="{yt_url}" style="color: #1a1a2e; text-decoration: none; font-weight: 600; font-size: 14px; line-height: 1.3;">{title_escaped}</a>
    <div style="margin-top: 4px; font-size: 12px; color: #666;"><span style="color: #DC143C; font-weight: 600;">{channel_escaped}</span> &middot; {views_str} views</div>
    {dur_line}
</td>
</tr>
</table>
'''

    html += '''
    <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #eee; text-align: center;">
        <a href="https://toddlburns.github.io/yt-tracker/" style="color: #00bcd4; text-decoration: none; font-size: 13px;">Manage Channels</a>
    </div>
</div></div></body></html>'''

    return html, len(all_videos)


def send_email(html, count):
    if not GMAIL_APP_PASSWORD:
        print('ERROR: GMAIL_APP_PASSWORD not set. Cannot send email.')
        sys.exit(1)

    now = datetime.now(timezone.utc)
    is_monday = now.weekday() == 0
    weekend_note = ' (incl. weekend)' if is_monday else ''
    subject = f'YouTube Digest - {now.strftime("%b %d")}{weekend_note} ({count} video{"s" if count != 1 else ""})'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = GMAIL_ADDRESS
    msg.attach(MIMEText(html, 'html'))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
    print(f'Email sent to {GMAIL_ADDRESS} ({count} videos)')


if __name__ == '__main__':
    now = datetime.now(timezone.utc)
    print(f'YouTube Digest - {now.strftime("%Y-%m-%d %H:%M UTC")}')

    # Monday: look back 72h (cover the weekend), otherwise 24h
    if now.weekday() == 0:
        lookback_hours = 72
    else:
        lookback_hours = 24

    cutoff = now - timedelta(hours=lookback_hours)

    channels = load_channels()
    print(f'Loaded {len(channels)} channels, looking back {lookback_hours}h')

    html, count = build_email(channels, cutoff)
    send_email(html, count)

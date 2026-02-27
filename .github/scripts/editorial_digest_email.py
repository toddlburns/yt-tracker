#!/usr/bin/env python3
"""Upcoming uDiscover Editorial Options - daily email with items 3 weeks away."""

import json, os, re, sys, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone, date
from html import escape

GMAIL_ADDRESS = os.environ.get('GMAIL_ADDRESS', 'todd.burns@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')


def parse_js_data(filepath, var_name):
    """Parse a JS file to extract a variable's JSON value."""
    with open(filepath, 'r') as f:
        content = f.read()

    # Find the variable assignment
    pattern = rf'(?:const|var|let)\s+{var_name}\s*=\s*'
    match = re.search(pattern, content)
    if not match:
        return None

    start = match.end()
    # Find matching bracket/brace
    if content[start] == '[':
        open_char, close_char = '[', ']'
    elif content[start] == '{':
        open_char, close_char = '{', '}'
    else:
        return None

    depth = 0
    end = start
    for i in range(start, len(content)):
        if content[i] == open_char:
            depth += 1
        elif content[i] == close_char:
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    json_str = content[start:end]
    # Remove trailing semicolons, clean up for JSON parsing
    json_str = json_str.rstrip().rstrip(';')
    return json.loads(json_str)


def get_ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def find_items_for_date(target_date, editorial_events, birthdays):
    """Find editorial events and birthdays that fall on the target date."""
    target_month = target_date.month
    target_day = target_date.day
    current_year = target_date.year
    items = []

    # Birthdays
    for name, info in birthdays.items():
        if info.get('month') == target_month and info.get('day') == target_day:
            age = current_year - info.get('birthYear', current_year)
            band_name = info.get('bandName')
            member_name = info.get('memberName')
            display_artist = band_name if band_name else name
            desc_label = f"{member_name} — Birthday" if band_name else 'Birthday'
            items.append({
                'type': 'birthday',
                'artist': display_artist,
                'description': desc_label,
                'detail': f"{get_ordinal(age)} Birthday (born {info.get('birthYear', '?')})",
                'icon': '\U0001F382',
                'articleUrl': info.get('articleUrl'),
                'artistPageUrl': info.get('artistPageUrl'),
            })

    # Editorial events
    for ev in editorial_events:
        if ev.get('month') == target_month and ev.get('day') == target_day:
            orig_year = ev.get('origYear')
            anniv_year = current_year - orig_year if orig_year else None
            occasion = ev.get('occasion', 'Release')

            icon_map = {
                'Chart': '\U0001F4C8',
                'Performance': '\U0001F3A4',
                'Recording': '\U0001F3A7',
                'Video': '\U0001F3AC',
                'uDiscover Video': '\U0001F3AC',
                'Anniversary': '\u2B50',
            }
            icon = icon_map.get(occasion, '\U0001F3B5')

            detail = f"{get_ordinal(anniv_year)} Anniversary ({orig_year})" if anniv_year else occasion
            items.append({
                'type': 'event',
                'artist': ev.get('artist', ''),
                'description': ev.get('name', ''),
                'detail': detail,
                'icon': icon,
                'articleUrl': ev.get('articleUrl'),
                'artistPageUrl': ev.get('artistPageUrl'),
            })

    return items


def build_email(target_dates, editorial_events, birthdays):
    """Build the HTML email for the given target dates."""
    now = datetime.now(timezone.utc)
    today_str = now.strftime('%B %d, %Y')

    all_items = []
    for td in target_dates:
        items = find_items_for_date(td, editorial_events, birthdays)
        for item in items:
            item['target_date'] = td
        all_items.extend(items)

    # Sort by date, then by type (birthdays first)
    all_items.sort(key=lambda x: (x['target_date'], 0 if x['type'] == 'birthday' else 1))

    count = len(all_items)
    date_range = target_dates[0].strftime('%b %d')
    if len(target_dates) > 1:
        date_range += f" - {target_dates[-1].strftime('%b %d')}"

    if not all_items:
        html = f'''<html><body style="font-family: -apple-system, Arial, sans-serif; background: #f5f5f5; padding: 20px; margin: 0;">
<div style="max-width: 640px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
<div style="background: linear-gradient(135deg, #1a0a28, #0a1628); padding: 24px 20px; color: white;">
    <h1 style="margin:0; font-size: 22px; font-weight: 700;">Upcoming uDiscover Editorial Options</h1>
    <p style="margin: 4px 0 0; opacity: 0.7; font-size: 14px;">{today_str} &middot; Looking ahead to {date_range}</p>
</div>
<div style="padding: 20px;">
    <p style="color: #666; font-size: 14px;">No editorial events found for {date_range}.</p>
</div></div></body></html>'''
        return html, 0

    html = f'''<html><body style="font-family: -apple-system, Arial, sans-serif; background: #f5f5f5; padding: 20px; margin: 0;">
<div style="max-width: 640px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
<div style="background: linear-gradient(135deg, #1a0a28, #0a1628); padding: 24px 20px; color: white;">
    <h1 style="margin:0; font-size: 22px; font-weight: 700;">Upcoming uDiscover Editorial Options</h1>
    <p style="margin: 4px 0 0; opacity: 0.7; font-size: 14px;">{today_str} &middot; {count} item{"s" if count != 1 else ""} for {date_range}</p>
</div>
<div style="padding: 20px;">
'''

    current_date = None
    for item in all_items:
        td = item['target_date']
        if td != current_date:
            current_date = td
            day_label = td.strftime('%A, %B %d, %Y')
            html += f'<h2 style="font-size: 15px; color: #1a1a2e; margin: 20px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #8B5CF6;">{day_label}</h2>\n'

        artist = escape(item['artist'])
        desc = escape(item['description'])
        detail = escape(item['detail'])
        icon = item['icon']

        links_html = ''
        if item.get('articleUrl'):
            links_html += f' <a href="{item["articleUrl"]}" style="color: #8B5CF6; text-decoration: none; font-size: 12px;">[Article]</a>'
        if item.get('artistPageUrl'):
            links_html += f' <a href="{item["artistPageUrl"]}" style="color: #00bcd4; text-decoration: none; font-size: 12px;">[Artist Page]</a>'

        html += f'''<div style="margin-bottom: 14px; padding: 12px; background: #f8f7ff; border-radius: 8px; border-left: 3px solid #8B5CF6;">
    <div style="font-weight: 600; font-size: 14px; color: #1a1a2e;">{icon} {artist}</div>
    <div style="font-size: 13px; color: #444; margin-top: 3px;">{desc}</div>
    <div style="font-size: 12px; color: #888; margin-top: 3px;">{detail}{links_html}</div>
</div>
'''

    html += '''
</div></div></body></html>'''
    return html, count


def send_email(html, count, target_dates):
    if not GMAIL_APP_PASSWORD:
        print('ERROR: GMAIL_APP_PASSWORD not set.')
        sys.exit(1)

    date_range = target_dates[0].strftime('%b %d')
    if len(target_dates) > 1:
        date_range += f"-{target_dates[-1].strftime('%b %d')}"

    subject = f'Upcoming uDiscover Editorial Options — {date_range} ({count} item{"s" if count != 1 else ""})'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = GMAIL_ADDRESS
    msg.attach(MIMEText(html, 'html'))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
    print(f'Email sent to {GMAIL_ADDRESS} ({count} items)')


if __name__ == '__main__':
    now = datetime.now(timezone.utc)
    # Convert to PST for day-of-week logic
    pst = timezone(timedelta(hours=-8))
    now_pst = now.astimezone(pst)
    today = now_pst.date()
    weekday = today.weekday()  # 0=Mon, 4=Fri

    print(f'Editorial Digest - {now.strftime("%Y-%m-%d %H:%M UTC")} (PST: {now_pst.strftime("%A")})')

    # 3 weeks from today
    base_target = today + timedelta(days=21)

    # Determine target dates:
    # Monday: cover Saturday + Sunday (2 days: the Sat and Sun 3 weeks from now)
    # Friday: cover Saturday + Sunday (2 days: the Sat and Sun 3 weeks from now)
    # Other weekdays: just the single day 3 weeks from now
    if weekday == 0:  # Monday — cover upcoming Sat+Sun
        target_dates = [base_target, base_target + timedelta(days=1)]  # covers Sat+Sun
        # Actually: 3 weeks from Monday = Monday. We want Sat+Sun.
        # Mon + 21 = Mon. We need the preceding Sat+Sun: Mon+19=Sat, Mon+20=Sun
        target_dates = [today + timedelta(days=19), today + timedelta(days=20)]
    elif weekday == 4:  # Friday — cover upcoming Sat+Sun
        # Fri + 21 = Fri. We need Sat+Sun after that: Fri+22=Sat, Fri+23=Sun
        target_dates = [today + timedelta(days=22), today + timedelta(days=23)]
    else:
        target_dates = [base_target]

    print(f'Target dates: {", ".join(d.strftime("%b %d (%A)") for d in target_dates)}')

    # Load data
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.join(script_dir, '..', '..')
    data_file = os.path.join(repo_root, 'editorial_data.js')

    editorial_events = parse_js_data(data_file, 'EDITORIAL_EVENTS')
    birthdays = parse_js_data(data_file, 'ARTIST_BIRTHDAYS')

    if editorial_events is None:
        editorial_events = []
    if birthdays is None:
        birthdays = {}

    print(f'Loaded {len(editorial_events)} events, {len(birthdays)} birthdays')

    html, count = build_email(target_dates, editorial_events, birthdays)
    send_email(html, count, target_dates)

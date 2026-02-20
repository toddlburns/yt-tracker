#!/usr/bin/env python3
"""
Scrape Wikipedia/Wikidata for artist birthdays to fill in artists_missing_birthdays.csv.
For solo artists: finds date of birth.
For bands: finds ALL members' birthdays as separate rows.
"""

import csv
import json
import re
import time
import urllib.request
import urllib.parse
import os

INPUT_PATH = os.path.join(os.path.dirname(__file__), "artists_missing_birthdays.csv")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "artists_missing_birthdays.csv")

WIKI_API = "https://en.wikipedia.org/w/api.php"
UA = {'User-Agent': 'EditorialHubBot/1.0 (https://github.com/toddlburns/yt-tracker)'}


def wiki_fetch(url):
    """Fetch a URL with proper User-Agent."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def wiki_search(query, limit=5):
    """Search Wikipedia and return result titles."""
    params = urllib.parse.urlencode({
        'action': 'opensearch', 'search': query, 'limit': limit, 'format': 'json',
    })
    try:
        data = wiki_fetch(f"{WIKI_API}?{params}")
        return data[1] if data[1] else []
    except Exception:
        return []


def wiki_get_wikidata_id(title):
    """Get the Wikidata entity ID for a Wikipedia page."""
    params = urllib.parse.urlencode({
        'action': 'query', 'titles': title, 'prop': 'pageprops',
        'ppprop': 'wikibase_item', 'format': 'json', 'redirects': '1',
    })
    try:
        data = wiki_fetch(f"{WIKI_API}?{params}")
        pages = data.get('query', {}).get('pages', {})
        for page in pages.values():
            wdid = page.get('pageprops', {}).get('wikibase_item')
            if wdid:
                return wdid
    except Exception:
        pass
    return None


def wikidata_get_entity(entity_id):
    """Get full Wikidata entity."""
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
    try:
        data = wiki_fetch(url)
        return data.get('entities', {}).get(entity_id, {})
    except Exception:
        return {}


def wikidata_get_label(entity):
    """Get English label from a Wikidata entity."""
    labels = entity.get('labels', {})
    if 'en' in labels:
        return labels['en']['value']
    return None


def wikidata_get_birth_date(entity):
    """Get birth date from Wikidata entity claims. Returns YYYY-MM-DD or None."""
    claims = entity.get('claims', {})
    if 'P569' not in claims:
        return None
    val = claims['P569'][0].get('mainsnak', {}).get('datavalue', {}).get('value', {})
    time_str = val.get('time', '')
    m = re.match(r'\+?(\d{4})-(\d{2})-(\d{2})', time_str)
    if m:
        year, month, day = m.group(1), m.group(2), m.group(3)
        if month == '00' or day == '00':
            return None  # Year-only, not useful
        return f"{year}-{month}-{day}"
    return None


def wikidata_is_human(entity):
    """Check if entity is a human (Q5)."""
    claims = entity.get('claims', {})
    if 'P31' in claims:
        for claim in claims['P31']:
            qid = claim.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id', '')
            if qid == 'Q5':
                return True
    return False


def wikidata_is_band(entity):
    """Check if entity is a band/group."""
    claims = entity.get('claims', {})
    band_types = {'Q215380', 'Q2088357', 'Q5741069', 'Q4438121'}  # musical group, boy band, girl group, duo
    if 'P31' in claims:
        for claim in claims['P31']:
            qid = claim.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id', '')
            if qid in band_types:
                return True
    return False


MAX_BAND_MEMBERS = 3  # Cap members per band

def wikidata_get_members(entity):
    """Get member entity IDs from a band entity.
    Uses P527 (has part). Skips members with end-date qualifiers (former members)."""
    claims = entity.get('claims', {})
    member_ids = []

    # P527 = has part (members)
    if 'P527' in claims:
        for claim in claims['P527']:
            qid = claim.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id', '')
            if not qid:
                continue
            # Check for end time qualifier (P582) — skip former members if possible
            qualifiers = claim.get('qualifiers', {})
            has_end = 'P582' in qualifiers
            member_ids.append((qid, has_end))

    # Prioritize current members (no end date), then former
    current = [qid for qid, has_end in member_ids if not has_end]
    former = [qid for qid, has_end in member_ids if has_end]

    # Use current first, fill with former if needed
    result = current[:MAX_BAND_MEMBERS]
    if len(result) < MAX_BAND_MEMBERS:
        result.extend(former[:MAX_BAND_MEMBERS - len(result)])

    return result


def wiki_get_page_html(title):
    """Get parsed HTML content of a Wikipedia page."""
    params = urllib.parse.urlencode({
        'action': 'parse', 'page': title, 'prop': 'text',
        'format': 'json', 'redirects': '1',
    })
    try:
        data = wiki_fetch(f"{WIKI_API}?{params}")
        return data.get('parse', {}).get('text', {}).get('*', '')
    except Exception:
        return ''


def extract_birthday_from_html(html):
    """Fallback: extract birthday from Wikipedia page HTML."""
    m = re.search(r'class="bday">(\d{4}-\d{2}-\d{2})<', html)
    if m:
        return m.group(1)

    months = {
        'january': '01', 'february': '02', 'march': '03', 'april': '04',
        'may': '05', 'june': '06', 'july': '07', 'august': '08',
        'september': '09', 'october': '10', 'november': '11', 'december': '12'
    }

    text = re.sub(r'<[^>]+>', ' ', html)
    m = re.search(r'born[^)]{0,40}?(\w+)\s+(\d{1,2}),?\s+(\d{4})', text, re.IGNORECASE)
    if m and m.group(1).lower() in months:
        return f"{m.group(3)}-{months[m.group(1).lower()]}-{int(m.group(2)):02d}"

    m = re.search(r'born[^)]{0,40}?(\d{1,2})\s+(\w+)\s+(\d{4})', text, re.IGNORECASE)
    if m and m.group(2).lower() in months:
        return f"{m.group(3)}-{months[m.group(2).lower()]}-{int(m.group(1)):02d}"

    return None


def find_artist_info(name):
    """Find birthday info for an artist/band.

    Returns list of dicts: [{"member": "Name", "birthday": "YYYY-MM-DD"}, ...]
    For solo artists, returns one entry. For bands, returns one per member.
    Returns empty list if nothing found.
    """
    results = wiki_search(name)
    if not results:
        results = wiki_search(name + " musician")
    if not results:
        results = wiki_search(name + " band")
    if not results:
        return [], "no Wikipedia page"

    for title in results[:3]:
        wdid = wiki_get_wikidata_id(title)
        if not wdid:
            continue

        entity = wikidata_get_entity(wdid)
        if not entity:
            continue

        # Solo artist
        if wikidata_is_human(entity):
            bday = wikidata_get_birth_date(entity)
            if not bday:
                # Try HTML fallback
                html = wiki_get_page_html(title)
                bday = extract_birthday_from_html(html) if html else None
            if bday:
                return [{"member": name, "birthday": bday}], f"solo ({title})"
            return [], f"solo, no date ({title})"

        # Band
        if wikidata_is_band(entity):
            member_ids = wikidata_get_members(entity)
            if not member_ids:
                return [], f"band, no members listed ({title})"

            members = []
            for mid in member_ids[:MAX_BAND_MEMBERS]:
                try:
                    m_entity = wikidata_get_entity(mid)
                    if not m_entity:
                        continue
                    m_name = wikidata_get_label(m_entity) or mid
                    if not wikidata_is_human(m_entity):
                        continue
                    m_bday = wikidata_get_birth_date(m_entity)
                    if m_bday:
                        members.append({"member": m_name, "birthday": m_bday})
                    time.sleep(0.15)
                except Exception:
                    continue

            if members:
                return members, f"band with {len(members)}/{MAX_BAND_MEMBERS} members ({title})"
            return [], f"band, no member birthdays ({title})"

        # Unknown type — try birthday anyway
        bday = wikidata_get_birth_date(entity)
        if not bday:
            html = wiki_get_page_html(title)
            bday = extract_birthday_from_html(html) if html else None
        if bday:
            return [{"member": name, "birthday": bday}], f"other ({title})"

    return [], "no date in any result"


def main():
    artists = []
    with open(INPUT_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            artists.append(row)

    print(f"Processing {len(artists)} artists...")

    output_rows = []
    stats = {"found_solo": 0, "found_band_members": 0, "not_found": 0}
    not_found_list = []

    for i, artist in enumerate(artists):
        name = artist['ARTIST NAME']
        page_url = artist['ARTIST PAGE URL']

        # If already has a birthday, keep it
        if artist.get('BIRTHDAY (YYYY-MM-DD)'):
            output_rows.append({
                'ARTIST NAME': name,
                'MEMBER NAME': name,
                'ARTIST PAGE URL': page_url,
                'BIRTHDAY (YYYY-MM-DD)': artist['BIRTHDAY (YYYY-MM-DD)'],
            })
            stats["found_solo"] += 1
            continue

        print(f"  [{i+1}/{len(artists)}] {name}...", end=' ', flush=True)

        members, note = find_artist_info(name)

        if members:
            if len(members) == 1 and members[0]["member"] == name:
                # Solo artist
                output_rows.append({
                    'ARTIST NAME': name,
                    'MEMBER NAME': name,
                    'ARTIST PAGE URL': page_url,
                    'BIRTHDAY (YYYY-MM-DD)': members[0]["birthday"],
                })
                stats["found_solo"] += 1
                print(f"{members[0]['birthday']} — {note}")
            else:
                # Band with members
                for m in members:
                    output_rows.append({
                        'ARTIST NAME': name,
                        'MEMBER NAME': m["member"],
                        'ARTIST PAGE URL': page_url,
                        'BIRTHDAY (YYYY-MM-DD)': m["birthday"],
                    })
                stats["found_band_members"] += len(members)
                print(f"{len(members)} members — {note}")
        else:
            output_rows.append({
                'ARTIST NAME': name,
                'MEMBER NAME': '',
                'ARTIST PAGE URL': page_url,
                'BIRTHDAY (YYYY-MM-DD)': '',
            })
            stats["not_found"] += 1
            not_found_list.append((name, note))
            print(f"NOT FOUND — {note}")

        time.sleep(0.4)

    # Write updated CSV with member column
    with open(OUTPUT_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'ARTIST NAME', 'MEMBER NAME', 'ARTIST PAGE URL', 'BIRTHDAY (YYYY-MM-DD)'
        ])
        writer.writeheader()
        for row in output_rows:
            writer.writerow(row)

    print(f"\nDone!")
    print(f"  Solo artists with birthdays: {stats['found_solo']}")
    print(f"  Band members with birthdays: {stats['found_band_members']}")
    print(f"  Not found: {stats['not_found']}")
    print(f"  Total rows written: {len(output_rows)}")

    if not_found_list:
        print(f"\nCould not find birthdays for:")
        for name, note in not_found_list:
            print(f"  - {name}: {note}")


if __name__ == "__main__":
    main()

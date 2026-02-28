#!/usr/bin/env python3
"""Newsletter Briefing - reads newsletters from Gmail label, summarizes via Claude,
and sends a daily briefing email with the key headlines."""

import imaplib
import email
import smtplib
import ssl
import os
import re
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import json

GMAIL_ADDRESS = os.environ.get('GMAIL_ADDRESS', 'todd.burns@gmail.com')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GMAIL_LABEL = 'Newsletter Summary'
MAX_NEWSLETTERS = 25


def connect_imap():
    """Connect to Gmail via IMAP and return the connection."""
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    return mail


def get_unread_newsletters(mail):
    """Fetch unread emails from the newsletter-summary label."""
    # Select the label
    status, _ = mail.select(f'"{GMAIL_LABEL}"')
    if status != 'OK':
        # Try with Gmail label format
        status, _ = mail.select(f'"[Gmail]/{GMAIL_LABEL}"')
        if status != 'OK':
            print(f'Could not select label: {GMAIL_LABEL}')
            return []

    # Search for unseen messages
    status, data = mail.search(None, 'UNSEEN')
    if status != 'OK' or not data[0]:
        print('No unread newsletters found.')
        return []

    msg_ids = data[0].split()
    print(f'Found {len(msg_ids)} unread newsletters')

    newsletters = []
    for msg_id in msg_ids[:MAX_NEWSLETTERS]:
        status, msg_data = mail.fetch(msg_id, '(RFC822)')
        if status != 'OK':
            continue

        msg = email.message_from_bytes(msg_data[0][1])
        subject = msg.get('Subject', '(no subject)')
        sender = msg.get('From', '(unknown)')
        date = msg.get('Date', '')

        # Decode subject if encoded
        if subject:
            decoded_parts = email.header.decode_header(subject)
            subject = ''.join(
                part.decode(enc or 'utf-8') if isinstance(part, bytes) else part
                for part, enc in decoded_parts
            )

        # Extract body text
        body = extract_body(msg)
        if body:
            # Truncate very long newsletters to ~4000 chars to stay within context
            if len(body) > 4000:
                body = body[:4000] + '...[truncated]'
            newsletters.append({
                'subject': subject,
                'sender': sender,
                'date': date,
                'body': body,
                'msg_id': msg_id,
            })

    return newsletters


def extract_body(msg):
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        # Try plain text first, fall back to HTML
        plain = None
        html = None
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain' and not plain:
                try:
                    plain = part.get_payload(decode=True).decode('utf-8', errors='replace')
                except Exception:
                    pass
            elif content_type == 'text/html' and not html:
                try:
                    html = part.get_payload(decode=True).decode('utf-8', errors='replace')
                except Exception:
                    pass
        if plain:
            return plain
        if html:
            return strip_html(html)
    else:
        try:
            payload = msg.get_payload(decode=True).decode('utf-8', errors='replace')
            if msg.get_content_type() == 'text/html':
                return strip_html(payload)
            return payload
        except Exception:
            return None
    return None


def strip_html(html):
    """Very basic HTML to text conversion."""
    # Remove style and script blocks
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Convert common elements
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '\n- ', text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    # Decode HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
    return text.strip()


def mark_as_read(mail, msg_ids):
    """Mark messages as read."""
    for msg_id in msg_ids:
        mail.store(msg_id, '+FLAGS', '\\Seen')


def summarize_with_claude(newsletters):
    """Send newsletters to Claude API for summarization."""
    # Build the content to summarize
    newsletter_text = ''
    for i, nl in enumerate(newsletters, 1):
        newsletter_text += f'\n--- NEWSLETTER {i} ---\n'
        newsletter_text += f'From: {nl["sender"]}\n'
        newsletter_text += f'Subject: {nl["subject"]}\n'
        newsletter_text += f'Date: {nl["date"]}\n\n'
        newsletter_text += nl['body']
        newsletter_text += '\n'

    prompt = f"""Below are {len(newsletters)} newsletters received recently. Your job is to distill them into a concise briefing of the key headlines across all topics.

Create a briefing with ONLY the 5-10 most important headlines/stories. For each item:
- Write a clear, concise one-line headline
- Add 1-2 sentences of context underneath
- If multiple newsletters cover the same story, merge them into one item and note the convergence

Rules:
- Focus on what actually matters: major news, important developments, things worth knowing about
- Skip: filler content, listicles, promotional fluff, podcast ads, subscription upsells, boilerplate
- Write in a direct, no-nonsense tone — like a smart colleague giving you the rundown over coffee
- If there's genuinely nothing important, say so — don't inflate minor stories
- Group related items together if it makes the briefing cleaner

Format the output as clean HTML for an email. Use this structure:
<h2 style="color:#333;font-family:Georgia,serif;font-size:20px;margin-bottom:4px;">Daily Briefing</h2>
<p style="color:#888;font-family:Arial,sans-serif;font-size:12px;margin-top:0;">{{date}} &middot; {{count}} newsletters digested</p>
<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">

Then for each item use:
<p style="font-family:Georgia,serif;font-size:15px;margin-bottom:2px;"><strong>Headline here</strong></p>
<p style="font-family:Arial,sans-serif;font-size:13px;color:#555;margin-top:0;margin-bottom:16px;">Context sentences here.</p>

End with:
<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;">
<p style="font-family:Arial,sans-serif;font-size:11px;color:#999;">Sources: list the newsletter names that were digested</p>

Here are the newsletters:
{newsletter_text}"""

    # Call Claude API
    req_body = json.dumps({
        'model': 'claude-sonnet-4-5-20250929',
        'max_tokens': 2000,
        'messages': [{'role': 'user', 'content': prompt}],
    }).encode('utf-8')

    req = Request(
        'https://api.anthropic.com/v1/messages',
        data=req_body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
        },
        method='POST',
    )

    try:
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result['content'][0]['text']
    except Exception as e:
        print(f'Claude API error: {e}')
        return None


def send_briefing_email(html_content, newsletter_count):
    """Send the briefing email."""
    today = datetime.now(timezone.utc).strftime('%B %d, %Y')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'Daily Briefing — {today}'
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = GMAIL_ADDRESS

    # Plain text fallback
    plain = f'Daily Music Briefing — {today}\n\n{newsletter_count} newsletters digested. View this email in HTML for the full briefing.'

    # Wrap HTML in a basic email template
    full_html = f"""<html><body style="max-width:600px;margin:0 auto;padding:20px;background:#fff;">
{html_content}
</body></html>"""

    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(full_html, 'html'))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())

    print(f'Briefing email sent to {GMAIL_ADDRESS}')


def main():
    if not GMAIL_APP_PASSWORD:
        print('ERROR: GMAIL_APP_PASSWORD not set')
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        print('ERROR: ANTHROPIC_API_KEY not set')
        sys.exit(1)

    # Connect and fetch newsletters
    print('Connecting to Gmail...')
    mail = connect_imap()

    print(f'Fetching unread emails from label: {GMAIL_LABEL}')
    newsletters = get_unread_newsletters(mail)

    if not newsletters:
        print('No newsletters to summarize. Exiting.')
        mail.logout()
        return

    print(f'Processing {len(newsletters)} newsletters...')
    for nl in newsletters:
        print(f'  - {nl["subject"][:80]}')

    # Summarize
    print('\nSending to Claude for summarization...')
    briefing_html = summarize_with_claude(newsletters)

    if not briefing_html:
        print('Failed to generate briefing.')
        mail.logout()
        sys.exit(1)

    # Send email
    print('Sending briefing email...')
    send_briefing_email(briefing_html, len(newsletters))

    # Mark originals as read
    print('Marking newsletters as read...')
    mark_as_read(mail, [nl['msg_id'] for nl in newsletters])

    mail.logout()
    print('Done!')


if __name__ == '__main__':
    main()

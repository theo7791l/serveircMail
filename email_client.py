import imaplib
import smtplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
from email.utils import parseaddr
import os
import urllib.request
import urllib.error
import json

def _get_mail_config(user: dict) -> dict:
    from database import get_setting

    imap_host = user.get('imap_host') or get_setting('global_imap_host') or os.getenv('IMAP_HOST', '')
    imap_port = int(user.get('imap_port') or get_setting('global_imap_port', '993') or 993)
    smtp_host = user.get('smtp_host') or get_setting('global_smtp_host') or os.getenv('SMTP_HOST', '')
    smtp_port = int(user.get('smtp_port') or get_setting('global_smtp_port', '465') or 465)
    smtp_enc  = get_setting('global_smtp_encryption', 'SSL')

    # IMAP login = always global admin account (one Gmail inbox)
    mail_user = get_setting('global_imap_user') or os.getenv('IMAP_USER', '')
    mail_pass = get_setting('global_mail_password') or os.getenv('EMAIL_PASSWORD', '')

    # Alias = the address shown as From / used to filter inbox
    alias = (
        user.get('mail_alias')
        or user.get('mail_username')
        or user.get('email', '')
    )

    # Resend API key for outgoing
    resend_key = get_setting('resend_api_key', '')

    return {
        'imap_host': imap_host,
        'imap_port': imap_port,
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
        'smtp_enc':  smtp_enc,
        'mail_user': mail_user,
        'mail_pass': mail_pass,
        'alias':     alias,
        'resend_key': resend_key,
    }

def get_imap_connection(user: dict):
    cfg = _get_mail_config(user)
    mail = imaplib.IMAP4_SSL(cfg['imap_host'], cfg['imap_port'])
    mail.login(cfg['mail_user'], cfg['mail_pass'])
    return mail

def get_folders(user: dict):
    try:
        mail = get_imap_connection(user)
        status, folders = mail.list()
        mail.logout()
        result = []
        for f in folders:
            if isinstance(f, bytes):
                parts = f.decode().split('" ')
                name = parts[-1].strip().strip('"')
                result.append(name)
        return result if result else ['INBOX']
    except Exception:
        return ['INBOX']

def get_mails(user: dict, folder: str = 'INBOX', page: int = 1, per_page: int = 20):
    try:
        mail = get_imap_connection(user)
        mail.select(f'"{folder}"')
        status, data = mail.search(None, 'ALL')
        uids = data[0].split()
        uids.reverse()
        total = len(uids)
        pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        page_uids = uids[start:end]
        mails = []
        for uid in page_uids:
            try:
                status, msg_data = mail.fetch(uid, '(FLAGS BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                flags = msg_data[0][0].decode() if msg_data[0][0] else ''
                seen = '\\Seen' in flags
                subj_raw = msg.get('Subject', '(Sans objet)')
                subj_parts = decode_header(subj_raw)
                subject = ''
                for part, enc in subj_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(enc or 'utf-8', errors='replace')
                    else:
                        subject += str(part)
                from_raw = msg.get('From', '')
                from_parts = decode_header(from_raw)
                from_decoded = ''
                for part, enc in from_parts:
                    if isinstance(part, bytes):
                        from_decoded += part.decode(enc or 'utf-8', errors='replace')
                    else:
                        from_decoded += str(part)
                mails.append({
                    'uid': uid.decode(),
                    'from': from_decoded or from_raw,
                    'to': msg.get('To', ''),
                    'recipients': msg.get('To', '') + msg.get('CC', '') + msg.get('Delivered-To', ''),
                    'subject': subject or '(Sans objet)',
                    'date': msg.get('Date', ''),
                    'seen': seen,
                })
            except Exception:
                continue
        mail.logout()
        return {'mails': mails, 'total': total, 'page': page, 'pages': pages}
    except Exception as e:
        return {'mails': [], 'total': 0, 'page': 1, 'pages': 1, 'error': str(e)}

def get_mail(user: dict, uid: str, folder: str = 'INBOX'):
    try:
        mail = get_imap_connection(user)
        mail.select(f'"{folder}"')
        status, data = mail.fetch(uid.encode(), '(RFC822)')
        raw = data[0][1]
        msg = email_lib.message_from_bytes(raw)
        mail.store(uid.encode(), '+FLAGS', '\\Seen')
        mail.logout()

        subj_parts = decode_header(msg.get('Subject', ''))
        subject = ''
        for part, enc in subj_parts:
            if isinstance(part, bytes):
                subject += part.decode(enc or 'utf-8', errors='replace')
            else:
                subject += str(part)

        from_raw = msg.get('From', '')
        from_parts = decode_header(from_raw)
        from_name = ''
        for part, enc in from_parts:
            if isinstance(part, bytes):
                from_name += part.decode(enc or 'utf-8', errors='replace')
            else:
                from_name += str(part)

        body_html = None
        body_text = ''
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get('Content-Disposition', ''))
                if 'attachment' in cd:
                    continue
                if ct == 'text/html' and not body_html:
                    charset = part.get_content_charset() or 'utf-8'
                    body_html = part.get_payload(decode=True).decode(charset, errors='replace')
                elif ct == 'text/plain' and not body_text:
                    charset = part.get_content_charset() or 'utf-8'
                    body_text = part.get_payload(decode=True).decode(charset, errors='replace')
        else:
            charset = msg.get_content_charset() or 'utf-8'
            payload = msg.get_payload(decode=True)
            if payload:
                body_text = payload.decode(charset, errors='replace')

        return {
            'subject': subject or '(Sans objet)',
            'from': from_name or from_raw,
            'to': msg.get('To', ''),
            'date': msg.get('Date', ''),
            'body_html': body_html,
            'body_text': body_text,
        }
    except Exception as e:
        return {'error': str(e)}

def _send_via_resend(api_key: str, from_addr: str, to: str, subject: str, body: str, html: bool = False) -> tuple:
    """Send email via Resend API — supports any From: alias on verified domain."""
    payload = {
        'from': from_addr,
        'to': [to],
        'subject': subject,
    }
    if html:
        payload['html'] = body
    else:
        payload['text'] = body

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=data,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return True, result.get('id', 'sent')
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors='replace')
        return False, f'Resend HTTP {e.code}: {err_body}'
    except Exception as e:
        return False, str(e)

def send_mail(user: dict, to: str, subject: str, body: str, html: bool = False):
    cfg = _get_mail_config(user)
    from_addr = cfg['alias'] or cfg['mail_user']

    # Prefer Resend if API key configured (supports any @domain alias)
    if cfg.get('resend_key'):
        return _send_via_resend(cfg['resend_key'], from_addr, to, subject, body, html)

    # Fallback: SMTP (From = global mail_user, alias in header only)
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_addr
        msg['To'] = to
        if html:
            msg.attach(MIMEText(body, 'html', 'utf-8'))
        else:
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

        if cfg['smtp_enc'] == 'SSL':
            server = smtplib.SMTP_SSL(cfg['smtp_host'], cfg['smtp_port'])
        else:
            server = smtplib.SMTP(cfg['smtp_host'], cfg['smtp_port'])
            server.starttls()
        server.login(cfg['mail_user'], cfg['mail_pass'])
        server.sendmail(cfg['mail_user'], to, msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)

def delete_mail(user: dict, uid: str, folder: str = 'INBOX'):
    try:
        mail = get_imap_connection(user)
        mail.select(f'"{folder}"')
        mail.store(uid.encode(), '+FLAGS', '\\Deleted')
        mail.expunge()
        mail.logout()
        return True, None
    except Exception as e:
        return False, str(e)

def test_imap_connection(imap_host: str, imap_port: int, mail_user: str, mail_pass: str):
    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        mail.login(mail_user, mail_pass)
        status, data = mail.select('INBOX')
        count = data[0].decode() if data[0] else '0'
        mail.logout()
        return True, f'INBOX ({count} messages)'
    except Exception as e:
        return False, str(e)

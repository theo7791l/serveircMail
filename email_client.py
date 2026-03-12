import imaplib
import smtplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
from email.utils import parseaddr
import os

def _get_mail_config(user: dict) -> dict:
    """
    Resolve mail config for a user.
    Priority: user-level > global DB settings > env vars
    """
    from database import get_setting

    imap_host = user.get('imap_host') or get_setting('global_imap_host') or os.getenv('IMAP_HOST', '')
    imap_port = int(user.get('imap_port') or get_setting('global_imap_port', '993') or 993)
    smtp_host = user.get('smtp_host') or get_setting('global_smtp_host') or os.getenv('SMTP_HOST', '')
    smtp_port = int(user.get('smtp_port') or get_setting('global_smtp_port', '465') or 465)
    smtp_enc  = get_setting('global_smtp_encryption', 'SSL')

    # Username: user-level mail_username > global_imap_user > user email
    mail_user = (
        user.get('mail_username')
        or get_setting('global_imap_user')
        or user.get('email', '')
    )
    # Password: user-level > global
    mail_pass = user.get('mail_password') or get_setting('global_mail_password') or os.getenv('EMAIL_PASSWORD', '')

    return {
        'imap_host': imap_host,
        'imap_port': imap_port,
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
        'smtp_enc':  smtp_enc,
        'mail_user': mail_user,
        'mail_pass': mail_pass,
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
                status, msg_data = mail.fetch(uid, '(FLAGS BODY[HEADER.FIELDS (FROM SUBJECT DATE)])')
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

def send_mail(user: dict, to: str, subject: str, body: str, html: bool = False):
    try:
        cfg = _get_mail_config(user)
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = cfg['mail_user']
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

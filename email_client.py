import imaplib
import smtplib
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
import os


def _get_mail_config(user: dict) -> dict:
    from database import get_setting

    # IMAP (reception via Gmail + ImprovMX forward)
    imap_host = user.get('imap_host') or get_setting('global_imap_host') or os.getenv('IMAP_HOST', 'imap.gmail.com')
    imap_port = int(user.get('imap_port') or get_setting('global_imap_port', '993') or 993)
    imap_user = get_setting('global_imap_user') or os.getenv('IMAP_USER', '')
    imap_pass = get_setting('global_mail_password') or os.getenv('EMAIL_PASSWORD', '')

    # SMTP (envoi via Mailtrap)
    smtp_host = get_setting('global_smtp_host') or os.getenv('SMTP_HOST', 'live.smtp.mailtrap.io')
    smtp_port = int(get_setting('global_smtp_port', '587') or 587)
    smtp_user = get_setting('global_smtp_user') or os.getenv('SMTP_USER', 'api')
    smtp_pass = get_setting('global_smtp_password') or os.getenv('SMTP_PASSWORD', '')

    # Alias = adresse From affichee au destinataire (ex: jean@youtube.serveirc.com)
    alias = (
        user.get('mail_alias')
        or user.get('mail_username')
        or user.get('email', '')
    )

    return {
        'imap_host': imap_host,
        'imap_port': imap_port,
        'imap_user': imap_user,
        'imap_pass': imap_pass,
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
        'smtp_user': smtp_user,
        'smtp_pass': smtp_pass,
        'alias':     alias,
    }


def get_imap_connection(user: dict):
    cfg = _get_mail_config(user)
    mail = imaplib.IMAP4_SSL(cfg['imap_host'], cfg['imap_port'])
    mail.login(cfg['imap_user'], cfg['imap_pass'])
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
        page_uids = uids[start:start + per_page]
        mails = []
        for uid in page_uids:
            try:
                status, msg_data = mail.fetch(uid, '(FLAGS BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                flags = msg_data[0][0].decode() if msg_data[0][0] else ''
                seen = '\\Seen' in flags

                def _decode_header(value):
                    parts = decode_header(value or '')
                    result = ''
                    for part, enc in parts:
                        if isinstance(part, bytes):
                            result += part.decode(enc or 'utf-8', errors='replace')
                        else:
                            result += str(part)
                    return result

                mails.append({
                    'uid': uid.decode(),
                    'from': _decode_header(msg.get('From', '')),
                    'to': msg.get('To', ''),
                    'subject': _decode_header(msg.get('Subject', '')) or '(Sans objet)',
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

        def _decode_header(value):
            parts = decode_header(value or '')
            result = ''
            for part, enc in parts:
                if isinstance(part, bytes):
                    result += part.decode(enc or 'utf-8', errors='replace')
                else:
                    result += str(part)
            return result

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
            'subject': _decode_header(msg.get('Subject', '')) or '(Sans objet)',
            'from': _decode_header(msg.get('From', '')),
            'to': msg.get('To', ''),
            'date': msg.get('Date', ''),
            'body_html': body_html,
            'body_text': body_text,
        }
    except Exception as e:
        return {'error': str(e)}


def send_mail(user: dict, to: str, subject: str, body: str, html: bool = False):
    """
    Envoi via Mailtrap SMTP (live.smtp.mailtrap.io, port 587, STARTTLS).
    - Login : SMTP_USER="api" + SMTP_PASSWORD=cle_api_mailtrap
    - From: = alias de l'utilisateur (ex: jean@youtube.serveirc.com)
    - Le domaine serveirc.com doit etre verifie dans Mailtrap > Email API/SMTP > Domains
    """
    cfg = _get_mail_config(user)
    from_addr = cfg['alias'] or cfg['imap_user']

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject']  = subject
        msg['From']     = from_addr
        msg['To']       = to
        msg['Reply-To'] = from_addr

        if html:
            msg.attach(MIMEText(body, 'html', 'utf-8'))
        else:
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP(cfg['smtp_host'], cfg['smtp_port'])
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg['smtp_user'], cfg['smtp_pass'])
        # envelope sender = alias (autorise car domaine verifie dans Mailtrap)
        server.sendmail(from_addr, to, msg.as_string())
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

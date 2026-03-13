import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os


def _get_smtp_config() -> dict:
    from database import get_setting
    return {
        'smtp_host': 'smtp.resend.com',
        'smtp_port': 587,
        'smtp_user': 'resend',
        'smtp_pass': get_setting('global_smtp_password') or os.getenv('SMTP_PASSWORD', ''),
        'mail_domain': get_setting('mail_domain') or os.getenv('MAIL_DOMAIN', ''),
    }


def _get_alias(user: dict, cfg: dict) -> str:
    return (
        user.get('mail_alias')
        or user.get('mail_username')
        or user.get('email', '')
    )


# ── Dossiers (statiques — Resend Inbound stocke tout en BDD) ──────────────────

def get_folders(user: dict):
    return ['INBOX', 'Sent', 'Trash']


# ── Lecture des mails (depuis la BDD, alimentée par le webhook Inbound) ────────

def get_mails(user: dict, folder: str = 'INBOX', page: int = 1, per_page: int = 20):
    from database import get_inbound_mails
    alias = (user.get('mail_alias') or user.get('email', '')).lower()
    return get_inbound_mails(mail_to=alias, folder=folder, page=page, per_page=per_page)


def get_mail(user: dict, uid: str, folder: str = 'INBOX'):
    from database import get_inbound_mail_by_id, mark_inbound_mail_seen
    mail = get_inbound_mail_by_id(int(uid))
    if mail:
        mark_inbound_mail_seen(int(uid))
    return mail or {'error': 'Mail introuvable'}


# ── Envoi via Resend SMTP ──────────────────────────────────────────────────────

def send_mail(user: dict, to: str, subject: str, body: str, html: bool = False):
    """
    Envoi via Resend SMTP (smtp.resend.com:587 STARTTLS).
    Login : user="resend" + password=cle_api_resend
    From  : alias de l'utilisateur (ex: jean@tondomaine.com)
    Le domaine doit être vérifié dans Resend > Domains.
    """
    cfg = _get_smtp_config()
    from_addr = _get_alias(user, cfg)

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
        server.sendmail(from_addr, to, msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)


# ── Suppression (BDD) ──────────────────────────────────────────────────────────

def delete_mail(user: dict, uid: str, folder: str = 'INBOX'):
    from database import delete_inbound_mail
    ok = delete_inbound_mail(int(uid))
    return (True, None) if ok else (False, 'Mail introuvable')


# ── Test de connexion SMTP Resend ─────────────────────────────────────────────

def test_smtp_connection(smtp_pass: str):
    try:
        server = smtplib.SMTP('smtp.resend.com', 587, timeout=10)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login('resend', smtp_pass)
        server.quit()
        return True, 'Connexion Resend SMTP réussie'
    except Exception as e:
        return False, str(e)

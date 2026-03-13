import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.headerregistry import Address
from email.utils import formataddr
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


def _format_from(display_name: str, address: str) -> str:
    """
    Retourne une chaîne "Prénom Nom <email@domaine.com>" correctement encodée.
    Resend exige ce format strict pour le champ From.
    """
    if not address:
        return ''
    if display_name:
        return formataddr((display_name.strip(), address.strip().lower()))
    return address.strip().lower()


def get_folders(user: dict):
    return ['INBOX', 'Sent', 'Trash']


def get_mails(user: dict, folder: str = 'INBOX', page: int = 1, per_page: int = 20, address: str = None):
    from database import get_inbound_mails, get_inbound_mails_multi, get_all_addresses_for_user
    if address:
        return get_inbound_mails(mail_to=address, folder=folder, page=page, per_page=per_page)
    addresses = get_all_addresses_for_user(user['id'])
    return get_inbound_mails_multi(addresses=addresses, folder=folder, page=page, per_page=per_page)


def get_mail(user: dict, uid: str, folder: str = 'INBOX'):
    from database import get_inbound_mail_by_id, mark_inbound_mail_seen
    mail = get_inbound_mail_by_id(int(uid))
    if mail:
        mark_inbound_mail_seen(int(uid))
    return mail or {'error': 'Mail introuvable'}


def send_mail(user: dict, to: str, subject: str, body: str, html: bool = False, from_address: str = None):
    """
    Envoi via Resend SMTP (smtp.resend.com:587 STARTTLS).
    'from_address' permet de choisir quelle adresse utiliser comme expéditeur.
    Si non fourni, utilise l'adresse primaire du user.
    Le champ From est toujours formaté "Display Name <email@domaine>" pour Resend.
    """
    cfg = _get_smtp_config()

    if from_address:
        raw_addr = from_address.strip().lower()
    else:
        from database import get_primary_address
        raw_addr = get_primary_address(user['id']) if user.get('id') else user.get('email', '')

    # Formatage strict : "Prénom Nom <email@domaine.com>"
    display_name = user.get('display_name', '') if user else ''
    from_header = _format_from(display_name, raw_addr)

    if not from_header:
        return False, "Adresse expéditeur manquante"

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_header
        msg['To'] = to.strip()
        msg['Reply-To'] = from_header

        msg.attach(MIMEText(body, 'html' if html else 'plain', 'utf-8'))

        server = smtplib.SMTP(cfg['smtp_host'], cfg['smtp_port'], timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg['smtp_user'], cfg['smtp_pass'])
        # sendmail prend l'adresse brute (sans display name) pour l'enveloppe SMTP
        server.sendmail(raw_addr, to.strip(), msg.as_string())
        server.quit()
        return True, None
    except Exception as e:
        return False, str(e)


def delete_mail(user: dict, uid: str, folder: str = 'INBOX'):
    from database import delete_inbound_mail, get_inbound_mail_by_id, get_all_addresses_for_user
    mail = get_inbound_mail_by_id(int(uid))
    if not mail:
        return False, 'Mail introuvable'
    if user:
        addresses = get_all_addresses_for_user(user['id'])
        if mail['to'].lower() not in [a.lower() for a in addresses]:
            return False, 'Accès refusé'
    ok = delete_inbound_mail(int(uid))
    return (True, None) if ok else (False, 'Erreur suppression')


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

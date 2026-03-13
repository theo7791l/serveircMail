import os
import resend
from email.utils import formataddr


def _get_config() -> dict:
    from database import get_setting
    return {
        'api_key': get_setting('global_smtp_password') or os.getenv('RESEND_API_KEY', ''),
        'mail_domain': get_setting('mail_domain') or os.getenv('MAIL_DOMAIN', 'awlor.online'),
    }


def _resolve_from_address(user: dict, from_address: str = None) -> str:
    if from_address and from_address.strip():
        return from_address.strip().lower()
    if user and user.get('id'):
        from database import get_primary_address
        addr = get_primary_address(user['id'])
        if addr and addr.strip():
            return addr.strip().lower()
    from database import get_setting
    domain = get_setting('mail_domain') or os.getenv('MAIL_DOMAIN', 'awlor.online')
    return f'noreply@{domain}'


def _format_from(display_name: str, address: str) -> str:
    address = (address or '').strip().lower()
    if not address:
        return ''
    display_name = (display_name or '').strip()
    if display_name:
        return formataddr((display_name, address))
    return address


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
    Envoi via Resend REST API (SDK officiel).
    La cle API = global_smtp_password en BDD (ou RESEND_API_KEY en env).
    """
    cfg = _get_config()
    api_key = cfg['api_key']

    if not api_key:
        return False, "Cle API Resend manquante (configurez global_smtp_password dans le panel admin)"

    resend.api_key = api_key

    raw_addr = _resolve_from_address(user, from_address)
    display_name = (user or {}).get('display_name', '') or ''
    from_header = _format_from(display_name, raw_addr)

    try:
        params = {
            "from": from_header or raw_addr,
            "to": [to.strip()],
            "subject": subject,
        }
        if html:
            params["html"] = body
        else:
            params["text"] = body

        result = resend.Emails.send(params)
        # SDK retourne un dict avec 'id' si succes, ou leve une exception
        if result and result.get('id'):
            return True, None
        return False, str(result)
    except Exception as e:
        return False, str(e)


def delete_mail(user: dict, uid: str, folder: str = 'INBOX'):
    from database import delete_inbound_mail, get_inbound_mail_by_id, get_all_addresses_for_user
    mail = get_inbound_mail_by_id(int(uid))
    if not mail:
        return False, 'Mail introuvable'
    if user:
        addresses = get_all_addresses_for_user(user['id'])
        if mail['mail_to'].lower() not in [a.lower() for a in addresses]:
            return False, 'Acces refuse'
    ok = delete_inbound_mail(int(uid))
    return (True, None) if ok else (False, 'Erreur suppression')


def test_smtp_connection(api_key: str):
    """
    Teste la cle API Resend en envoyant un email de test a delivered@resend.dev
    (adresse de test officielle Resend qui accepte tout sans erreur).
    """
    if not api_key:
        return False, "Cle API vide"
    try:
        resend.api_key = api_key
        params = {
            "from": "test@resend.dev",
            "to": ["delivered@resend.dev"],
            "subject": "Resend API test",
            "text": "Test de connexion Resend OK",
        }
        result = resend.Emails.send(params)
        if result and result.get('id'):
            return True, f"Connexion Resend API reussie (id={result['id']})"
        return False, str(result)
    except Exception as e:
        return False, str(e)

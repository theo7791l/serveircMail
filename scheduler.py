"""
Scheduler Awlor \u2014 T\u00e2ches d'arri\u00e8re-plan

T\u00e2ches actives:
  - Envoi des mails programm\u00e9s (scheduled_mails)
  - R\u00e9veil des mails snooze\u00e9s
  - Nettoyage des sessions expir\u00e9es
  - Nettoyage des mails expir\u00e9s (expires_at)
  - Nettoyage des pending_users expir\u00e9s
  - Rapport hebdomadaire (digest) par email
"""

import time
import threading
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='[SCHEDULER] %(asctime)s %(message)s')
log = logging.getLogger('scheduler')


def _run_scheduled_mails():
    try:
        import database as db
        import email_client
        import json
        pending = db.get_pending_scheduled_mails()
        for mail in pending:
            try:
                to_lower = mail['mail_to'].lower()
                is_internal = db.address_exists(to_lower)
                body_html = mail['body_html'] or ''
                body_text = mail['body_text'] or ''
                subject = mail['subject'] or ''
                sent_from = mail['mail_from']
                if is_internal:
                    db.save_inbound_mail(mail_to=to_lower, mail_from=sent_from, subject=subject,
                                        body_html=body_html, body_text=body_text, folder='INBOX')
                    ok = True
                else:
                    is_html = bool(body_html)
                    ok, _ = email_client.send_mail(
                        user=None, to=mail['mail_to'], subject=subject,
                        body=body_html if is_html else body_text,
                        html=is_html, from_address=sent_from
                    )
                if ok:
                    db.save_inbound_mail(mail_to=to_lower, mail_from=sent_from, subject=subject,
                                        body_html=body_html, body_text=body_text,
                                        headers=json.dumps({'from': sent_from, 'to': mail['mail_to']}),
                                        folder='Sent')
                    db.mark_scheduled_sent(mail['id'])
                    log.info(f"Mail programm\u00e9 #{mail['id']} envoy\u00e9 \u00e0 {mail['mail_to']}")
                else:
                    log.warning(f"Echec mail programm\u00e9 #{mail['id']}")
            except Exception as e:
                log.error(f"Mail programm\u00e9 #{mail.get('id','?')}: {e}")
    except Exception as e:
        log.error(f"_run_scheduled_mails: {e}")


def _run_snooze_wakeup():
    try:
        import database as db
        count = db.process_snooze_wakeups()
        if count:
            log.info(f"{count} mail(s) snooze\u00e9(s) r\u00e9veill\u00e9(s)")
    except Exception as e:
        log.error(f"_run_snooze_wakeup: {e}")


def _cleanup_sessions():
    try:
        import database as db
        conn = db.get_conn()
        result = conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
        conn.commit()
        deleted = result.rowcount
        conn.close()
        if deleted:
            log.info(f"{deleted} session(s) expir\u00e9e(s) supprim\u00e9e(s)")
    except Exception as e:
        log.error(f"_cleanup_sessions: {e}")


def _cleanup_expired_mails():
    try:
        import database as db
        conn = db.get_conn()
        result = conn.execute(
            "DELETE FROM inbound_mails WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
        )
        conn.commit()
        deleted = result.rowcount
        conn.close()
        if deleted:
            log.info(f"{deleted} mail(s) expir\u00e9(s) supprim\u00e9(s)")
    except Exception as e:
        log.error(f"_cleanup_expired_mails: {e}")


def _cleanup_pending_users():
    try:
        import database as db
        conn = db.get_conn()
        result = conn.execute("DELETE FROM pending_users WHERE expires_at < datetime('now')")
        conn.commit()
        deleted = result.rowcount
        conn.close()
        if deleted:
            log.info(f"{deleted} inscription(s) en attente expir\u00e9e(s) supprim\u00e9e(s)")
    except Exception as e:
        log.error(f"_cleanup_pending_users: {e}")


def _run_weekly_digest():
    """
    Envoie un r\u00e9sum\u00e9 hebdomadaire par email \u00e0 chaque utilisateur qui a activ\u00e9 la pr\u00e9f notif digest.
    Ex\u00e9cut\u00e9 tous les lundis \u00e0 8h00 UTC.
    """
    try:
        import database as db
        import email_client
        users_raw = db.get_all_active_users()
        site_name = db.get_setting("site_name", "Awlor")
        mail_domain = db.get_setting("mail_domain", "awlor.online")
        for user in users_raw:
            try:
                prefs = db.get_notification_prefs(user["id"])
                if not prefs.get("notify_weekly_digest"):
                    continue
                if not user.get("email"):
                    continue
                addresses = db.get_all_addresses_for_user(user["id"])
                stats = db.get_weekly_stats(user["id"], addresses)
                body = (
                    f"Bonjour {user['display_name']},\n\n"
                    f"Voici votre r\u00e9sum\u00e9 de la semaine sur {site_name} :\n\n"
                    f"  \u2022 Mails re\u00e7us cette semaine : {stats.get('received', 0)}\n"
                    f"  \u2022 Mails envoy\u00e9s : {stats.get('sent', 0)}\n"
                    f"  \u2022 Mails non lus : {stats.get('unread', 0)}\n"
                    f"  \u2022 Follow-ups en attente : {stats.get('followups', 0)}\n"
                    f"  \u2022 Mails snooze\u00e9s actifs : {stats.get('snoozed', 0)}\n\n"
                    f"Connectez-vous sur https://awlor.online/inbox pour g\u00e9rer votre messagerie.\n\n"
                    f"L'\u00e9quipe {site_name}\n"
                    f"Pour ne plus recevoir ce rapport : Profil > Notifications"
                )
                email_client.send_mail(
                    user=None,
                    to=user["email"],
                    subject=f"[{site_name}] Rapport hebdomadaire",
                    body=body,
                    from_address=f"noreply@{mail_domain}"
                )
                log.info(f"Digest envoy\u00e9 \u00e0 {user['username']} ({user['email']})")
            except Exception as e:
                log.error(f"Digest user #{user.get('id','?')}: {e}")
    except Exception as e:
        log.error(f"_run_weekly_digest: {e}")


def _weekly_digest_loop():
    """Lance le digest chaque lundi \u00e0 8h00 UTC."""
    while True:
        now = datetime.utcnow()
        # Prochain lundi 8h00 UTC
        days_until_monday = (7 - now.weekday()) % 7 or 7
        next_monday = (now + timedelta(days=days_until_monday)).replace(hour=8, minute=0, second=0, microsecond=0)
        wait_seconds = (next_monday - now).total_seconds()
        log.info(f"Digest hebdo: prochaine ex\u00e9cution dans {int(wait_seconds//3600)}h {int((wait_seconds%3600)//60)}min")
        time.sleep(max(wait_seconds, 1))
        _run_weekly_digest()


TASKS = [
    (_run_scheduled_mails,  60,   'scheduled_mails'),
    (_run_snooze_wakeup,    30,   'snooze_wakeup'),
    (_cleanup_sessions,    900,   'cleanup_sessions'),
    (_cleanup_expired_mails, 300, 'cleanup_expired_mails'),
    (_cleanup_pending_users, 600, 'cleanup_pending_users'),
]


def _task_loop(fn, interval, label):
    while True:
        try:
            fn()
        except Exception as e:
            log.error(f"[{label}] Exception non captur\u00e9e: {e}")
        time.sleep(interval)


def start_scheduler():
    """Lance toutes les t\u00e2ches en daemon threads."""
    for fn, interval, label in TASKS:
        t = threading.Thread(target=_task_loop, args=(fn, interval, label),
                             daemon=True, name=f'sched-{label}')
        t.start()
        log.info(f"T\u00e2che '{label}' d\u00e9marr\u00e9e (intervalle: {interval}s)")
    # Digest hebdo dans son propre thread
    t_digest = threading.Thread(target=_weekly_digest_loop, daemon=True, name='sched-weekly-digest')
    t_digest.start()
    log.info("T\u00e2che 'weekly_digest' d\u00e9marr\u00e9e")


if __name__ == '__main__':
    log.info('Scheduler Awlor d\u00e9marr\u00e9 en mode standalone')
    start_scheduler()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info('Scheduler arr\u00eat\u00e9')

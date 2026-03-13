"""
Scheduler Awlor — Tâches d'arrière-plan
Lancer en parallèle avec uvicorn via start.sh ou via threading au démarrage de main.py

Tâches actives:
  - Envoi des mails programmés (scheduled_mails)
  - Réveil des mails snoozeés
  - Nettoyage des sessions expirées
  - Nettoyage des mails expirés (expires_at)
  - Nettoyage des pending_users expirés
"""

import time
import threading
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='[SCHEDULER] %(asctime)s %(message)s')
log = logging.getLogger('scheduler')


def _run_scheduled_mails():
    """Envoie les mails programmés dont send_at <= maintenant."""
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
                    db.save_inbound_mail(
                        mail_to=to_lower, mail_from=sent_from,
                        subject=subject, body_html=body_html,
                        body_text=body_text, folder='INBOX'
                    )
                    ok = True
                else:
                    is_html = bool(body_html)
                    ok, _ = email_client.send_mail(
                        user=None, to=mail['mail_to'], subject=subject,
                        body=body_html if is_html else body_text,
                        html=is_html, from_address=sent_from
                    )

                if ok:
                    db.save_inbound_mail(
                        mail_to=to_lower, mail_from=sent_from,
                        subject=subject, body_html=body_html,
                        body_text=body_text,
                        headers=json.dumps({'from': sent_from, 'to': mail['mail_to']}),
                        folder='Sent'
                    )
                    db.mark_scheduled_sent(mail['id'])
                    log.info(f"Mail programmé #{mail['id']} envoyé à {mail['mail_to']}")
                else:
                    log.warning(f"Echec envoi mail programmé #{mail['id']}")
            except Exception as e:
                log.error(f"Erreur mail programmé #{mail.get('id', '?')}: {e}")
    except Exception as e:
        log.error(f"_run_scheduled_mails: {e}")


def _run_snooze_wakeup():
    """Remet en INBOX les mails dont le snooze est échu."""
    try:
        import database as db
        count = db.process_snooze_wakeups()
        if count:
            log.info(f"{count} mail(s) snoozeé(s) réveillé(s)")
    except Exception as e:
        log.error(f"_run_snooze_wakeup: {e}")


def _cleanup_sessions():
    """Supprime les sessions expirées."""
    try:
        import database as db
        conn = db.get_conn()
        result = conn.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
        conn.commit()
        deleted = result.rowcount
        conn.close()
        if deleted:
            log.info(f"{deleted} session(s) expirée(s) supprimée(s)")
    except Exception as e:
        log.error(f"_cleanup_sessions: {e}")


def _cleanup_expired_mails():
    """Supprime les mails avec expires_at dépassé."""
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
            log.info(f"{deleted} mail(s) expiré(s) supprimé(s)")
    except Exception as e:
        log.error(f"_cleanup_expired_mails: {e}")


def _cleanup_pending_users():
    """Supprime les inscriptions en attente expirées."""
    try:
        import database as db
        conn = db.get_conn()
        result = conn.execute("DELETE FROM pending_users WHERE expires_at < datetime('now')")
        conn.commit()
        deleted = result.rowcount
        conn.close()
        if deleted:
            log.info(f"{deleted} inscription(s) en attente expirée(s) supprimée(s)")
    except Exception as e:
        log.error(f"_cleanup_pending_users: {e}")


TASKS = [
    # (fonction, intervalle_secondes, label)
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
            log.error(f"[{label}] Exception non capturée: {e}")
        time.sleep(interval)


def start_scheduler():
    """Lance toutes les tâches en daemon threads."""
    for fn, interval, label in TASKS:
        t = threading.Thread(target=_task_loop, args=(fn, interval, label), daemon=True, name=f'sched-{label}')
        t.start()
        log.info(f"Tâche '{label}' démarrée (intervalle: {interval}s)")


if __name__ == '__main__':
    log.info('Scheduler Awlor démarré en mode standalone')
    start_scheduler()
    # Boucle principale pour garder le processus vivant
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info('Scheduler arrêté')

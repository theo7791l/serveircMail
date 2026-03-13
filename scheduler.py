"""Background scheduler for snooze, scheduled send, follow-up tracking, mail expiry."""
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def run_scheduler(db_module, email_client_module):
    """Run periodic background tasks every 60 seconds."""
    while True:
        try:
            _process_scheduled_mails(db_module, email_client_module)
            _process_snoozed_mails(db_module)
            _process_expired_mails(db_module)
            _process_followup_tracker(db_module)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        time.sleep(60)


def _process_scheduled_mails(db, email_client):
    """Send mails scheduled for now or past."""
    try:
        conn = db.get_conn()
        now = datetime.utcnow().isoformat()
        rows = conn.execute(
            "SELECT * FROM scheduled_mails WHERE send_at <= ? AND sent=0", (now,)
        ).fetchall()
        for row in rows:
            r = dict(row)
            try:
                ok, err = email_client.send_mail(
                    user=None,
                    to=r["mail_to"],
                    subject=r["subject"],
                    body=r["body"],
                    from_address=r["mail_from"]
                )
                conn.execute("UPDATE scheduled_mails SET sent=1 WHERE id=?", (r["id"],))
                conn.commit()
                logger.info(f"Scheduled mail {r['id']} sent to {r['mail_to']}")
            except Exception as e:
                logger.error(f"Failed to send scheduled mail {r['id']}: {e}")
        conn.close()
    except Exception as e:
        logger.error(f"_process_scheduled_mails error: {e}")


def _process_snoozed_mails(db):
    """Restore snoozed mails whose time has come."""
    try:
        conn = db.get_conn()
        now = datetime.utcnow().isoformat()
        rows = conn.execute(
            "SELECT * FROM mail_snooze WHERE wake_at <= ? AND woken=0", (now,)
        ).fetchall()
        for row in rows:
            r = dict(row)
            conn.execute(
                "UPDATE inbound_mails SET folder='INBOX', seen=0 WHERE id=?",
                (r["mail_id"],)
            )
            conn.execute("UPDATE mail_snooze SET woken=1 WHERE id=?", (r["id"],))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"_process_snoozed_mails error: {e}")


def _process_expired_mails(db):
    """Delete mails past their expiry date."""
    try:
        conn = db.get_conn()
        now = datetime.utcnow().isoformat()
        conn.execute(
            "DELETE FROM inbound_mails WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"_process_expired_mails error: {e}")


def _process_followup_tracker(db):
    """Mark follow-up needed if no reply after threshold."""
    try:
        conn = db.get_conn()
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            UPDATE inbound_mails SET followup_needed=1
            WHERE folder='Sent'
            AND followup_days > 0
            AND followup_needed=0
            AND datetime(created_at, '+' || followup_days || ' days') <= ?
            """,
            (now,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"_process_followup_tracker error: {e}")


def start_scheduler(db_module, email_client_module):
    """Start the scheduler in a daemon thread."""
    t = threading.Thread(
        target=run_scheduler,
        args=(db_module, email_client_module),
        daemon=True
    )
    t.start()
    logger.info("Background scheduler started.")
    return t

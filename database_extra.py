"""Extra DB tables and helpers for new features."""
import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "awlor.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_extra_tables():
    """Create all new feature tables if not exist."""
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mail_stars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_uid TEXT NOT NULL,
        folder TEXT NOT NULL DEFAULT 'INBOX',
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, mail_uid, folder)
    );

    CREATE TABLE IF NOT EXISTS mail_snooze (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_uid TEXT NOT NULL,
        folder TEXT NOT NULL,
        wake_at TEXT NOT NULL,
        woken INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS mail_drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT DEFAULT '',
        body TEXT DEFAULT '',
        mail_to TEXT DEFAULT '',
        mail_cc TEXT DEFAULT '',
        mail_bcc TEXT DEFAULT '',
        is_reply INTEGER DEFAULT 0,
        reply_to_uid TEXT DEFAULT '',
        reply_folder TEXT DEFAULT '',
        encrypted INTEGER DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now')),
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS mail_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        condition_field TEXT NOT NULL,
        condition_op TEXT NOT NULL,
        condition_value TEXT NOT NULL,
        action_type TEXT NOT NULL,
        action_value TEXT DEFAULT '',
        priority INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS mail_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        subject TEXT DEFAULT '',
        body TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS scheduled_mails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_from TEXT NOT NULL,
        mail_to TEXT NOT NULL,
        subject TEXT DEFAULT '',
        body TEXT DEFAULT '',
        send_at TEXT NOT NULL,
        sent INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS mail_followup (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_uid TEXT NOT NULL,
        folder TEXT DEFAULT 'Sent',
        followup_at TEXT NOT NULL,
        triggered INTEGER DEFAULT 0,
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS read_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        mail_uid TEXT NOT NULL,
        sender_user_id INTEGER NOT NULL,
        recipient_email TEXT NOT NULL,
        opened_at TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS auto_destroy_mails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mail_uid TEXT NOT NULL,
        folder TEXT NOT NULL,
        owner_user_id INTEGER NOT NULL,
        destroy_on_read INTEGER DEFAULT 1,
        destroyed INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS ai_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS folder_colors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        folder TEXT NOT NULL,
        color TEXT NOT NULL DEFAULT '#6C63FF',
        UNIQUE(user_id, folder)
    );
    """)
    conn.commit()
    conn.close()


# ===== STARS =====
def toggle_star(user_id: int, mail_uid: str, folder: str) -> bool:
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM mail_stars WHERE user_id=? AND mail_uid=? AND folder=?",
        (user_id, mail_uid, folder)
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM mail_stars WHERE id=?", (existing["id"],))
        conn.commit(); conn.close()
        return False
    else:
        conn.execute(
            "INSERT INTO mail_stars (user_id, mail_uid, folder) VALUES (?,?,?)",
            (user_id, mail_uid, folder)
        )
        conn.commit(); conn.close()
        return True


def get_starred(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT mail_uid, folder FROM mail_stars WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_starred(user_id: int, mail_uid: str, folder: str) -> bool:
    conn = get_conn()
    r = conn.execute(
        "SELECT id FROM mail_stars WHERE user_id=? AND mail_uid=? AND folder=?",
        (user_id, mail_uid, folder)
    ).fetchone()
    conn.close()
    return r is not None


# ===== SNOOZE =====
def snooze_mail(user_id: int, mail_uid: str, folder: str, wake_at: str) -> int:
    conn = get_conn()
    conn.execute(
        "INSERT INTO mail_snooze (user_id, mail_uid, folder, wake_at) VALUES (?,?,?,?)",
        (user_id, mail_uid, folder, wake_at)
    )
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return row_id


def get_snoozed(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mail_snooze WHERE user_id=? AND woken=0 ORDER BY wake_at ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===== DRAFTS =====
def save_draft(user_id: int, data: dict) -> int:
    conn = get_conn()
    draft_id = data.get("id")
    if draft_id:
        conn.execute(
            "UPDATE mail_drafts SET subject=?,body=?,mail_to=?,mail_cc=?,mail_bcc=?,updated_at=datetime('now') WHERE id=? AND user_id=?",
            (data.get("subject",""), data.get("body",""), data.get("to",""), data.get("cc",""), data.get("bcc",""), draft_id, user_id)
        )
    else:
        conn.execute(
            "INSERT INTO mail_drafts (user_id,subject,body,mail_to,mail_cc,mail_bcc) VALUES (?,?,?,?,?,?)",
            (user_id, data.get("subject",""), data.get("body",""), data.get("to",""), data.get("cc",""), data.get("bcc",""))
        )
        draft_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return draft_id


def get_drafts(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mail_drafts WHERE user_id=? ORDER BY updated_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_draft(user_id: int, draft_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM mail_drafts WHERE id=? AND user_id=?", (draft_id, user_id))
    conn.commit(); conn.close()


# ===== RULES =====
def get_rules(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mail_rules WHERE user_id=? ORDER BY priority ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_rule(user_id: int, data: dict) -> int:
    conn = get_conn()
    rule_id = data.get("id")
    if rule_id:
        conn.execute(
            "UPDATE mail_rules SET name=?,condition_field=?,condition_op=?,condition_value=?,action_type=?,action_value=?,priority=?,enabled=? WHERE id=? AND user_id=?",
            (data["name"], data["condition_field"], data["condition_op"], data["condition_value"],
             data["action_type"], data.get("action_value",""), data.get("priority",0), data.get("enabled",1), rule_id, user_id)
        )
    else:
        conn.execute(
            "INSERT INTO mail_rules (user_id,name,condition_field,condition_op,condition_value,action_type,action_value,priority,enabled) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, data["name"], data["condition_field"], data["condition_op"], data["condition_value"],
             data["action_type"], data.get("action_value",""), data.get("priority",0), data.get("enabled",1))
        )
        rule_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return rule_id


def delete_rule(user_id: int, rule_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM mail_rules WHERE id=? AND user_id=?", (rule_id, user_id))
    conn.commit(); conn.close()


# ===== TEMPLATES =====
def get_templates(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mail_templates WHERE user_id=? ORDER BY name ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_template(user_id: int, data: dict) -> int:
    conn = get_conn()
    tmpl_id = data.get("id")
    if tmpl_id:
        conn.execute(
            "UPDATE mail_templates SET name=?,subject=?,body=? WHERE id=? AND user_id=?",
            (data["name"], data.get("subject",""), data["body"], tmpl_id, user_id)
        )
    else:
        conn.execute(
            "INSERT INTO mail_templates (user_id,name,subject,body) VALUES (?,?,?,?)",
            (user_id, data["name"], data.get("subject",""), data["body"])
        )
        tmpl_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return tmpl_id


def delete_template(user_id: int, tmpl_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM mail_templates WHERE id=? AND user_id=?", (tmpl_id, user_id))
    conn.commit(); conn.close()


# ===== SCHEDULED MAILS =====
def schedule_mail(user_id: int, mail_from: str, mail_to: str, subject: str, body: str, send_at: str) -> int:
    conn = get_conn()
    conn.execute(
        "INSERT INTO scheduled_mails (user_id,mail_from,mail_to,subject,body,send_at) VALUES (?,?,?,?,?,?)",
        (user_id, mail_from, mail_to, subject, body, send_at)
    )
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    return row_id


def get_scheduled(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scheduled_mails WHERE user_id=? AND sent=0 ORDER BY send_at ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===== READ RECEIPTS =====
def create_receipt(user_id: int, mail_uid: str, recipient: str) -> str:
    import secrets
    token = secrets.token_urlsafe(16)
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO read_receipts (token,mail_uid,sender_user_id,recipient_email) VALUES (?,?,?,?)",
        (token, mail_uid, user_id, recipient)
    )
    conn.commit(); conn.close()
    return token


def mark_receipt_opened(token: str):
    conn = get_conn()
    conn.execute(
        "UPDATE read_receipts SET opened_at=datetime('now') WHERE token=? AND opened_at IS NULL",
        (token,)
    )
    conn.commit(); conn.close()


# ===== AI CONVERSATION HISTORY =====
def get_ai_history(user_id: int, limit: int = 20) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM ai_conversations WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))


def add_ai_message(user_id: int, role: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO ai_conversations (user_id,role,content) VALUES (?,?,?)",
        (user_id, role, content)
    )
    # Keep only last 100 messages per user
    conn.execute(
        "DELETE FROM ai_conversations WHERE user_id=? AND id NOT IN (SELECT id FROM ai_conversations WHERE user_id=? ORDER BY created_at DESC LIMIT 100)",
        (user_id, user_id)
    )
    conn.commit(); conn.close()


def clear_ai_history(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM ai_conversations WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()


# ===== FOLDER COLORS =====
def get_folder_colors(user_id: int) -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT folder, color FROM folder_colors WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()
    return {r["folder"]: r["color"] for r in rows}


def set_folder_color(user_id: int, folder: str, color: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO folder_colors (user_id,folder,color) VALUES (?,?,?) ON CONFLICT(user_id,folder) DO UPDATE SET color=excluded.color",
        (user_id, folder, color)
    )
    conn.commit(); conn.close()

import sqlite3
import os
import hashlib
import secrets
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "serveircmail.db")

DEFAULT_PERMISSIONS = [
    ("can_send_mail", "Envoyer des mails"),
    ("can_delete_mail", "Supprimer des mails"),
    ("can_manage_users", "Gérer les utilisateurs"),
    ("can_manage_roles", "Gérer les rôles"),
    ("can_view_logs", "Voir les logs d'audit"),
    ("can_suspend_users", "Suspendre des utilisateurs"),
    ("can_change_settings", "Modifier les paramètres système"),
    ("can_view_all_mailboxes", "Voir toutes les boîtes mail"),
    ("can_create_accounts", "Créer des comptes"),
    ("can_reset_passwords", "Réinitialiser les mots de passe"),
    ("can_view_stats", "Voir les statistiques"),
    ("can_export_data", "Exporter les données"),
]

DEFAULT_ROLES = {
    "super_admin": {
        "display_name": "Super Admin",
        "color": "#FF6584",
        "icon": "👑",
        "level": 100,
        "permissions": [p[0] for p in DEFAULT_PERMISSIONS]
    },
    "admin": {
        "display_name": "Admin",
        "color": "#6C63FF",
        "icon": "🛡️",
        "level": 80,
        "permissions": ["can_send_mail","can_delete_mail","can_manage_users","can_view_logs","can_suspend_users","can_change_settings","can_view_stats","can_create_accounts","can_reset_passwords"]
    },
    "moderator": {
        "display_name": "Modérateur",
        "color": "#3EC6E0",
        "icon": "🔧",
        "level": 50,
        "permissions": ["can_send_mail","can_delete_mail","can_suspend_users","can_view_logs","can_view_stats"]
    },
    "user": {
        "display_name": "Utilisateur",
        "color": "#4ade80",
        "icon": "👤",
        "level": 10,
        "permissions": ["can_send_mail","can_delete_mail"]
    }
}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            color TEXT DEFAULT '#6C63FF',
            icon TEXT DEFAULT '👤',
            level INTEGER DEFAULT 10,
            is_default INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER,
            permission_id INTEGER,
            PRIMARY KEY (role_id, permission_id),
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
            FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            display_name TEXT,
            password_hash TEXT NOT NULL,
            role_id INTEGER,
            imap_host TEXT,
            imap_port INTEGER DEFAULT 993,
            smtp_host TEXT,
            smtp_port INTEGER DEFAULT 587,
            mail_address TEXT,
            mail_password TEXT,
            is_active INTEGER DEFAULT 1,
            is_suspended INTEGER DEFAULT 0,
            suspension_reason TEXT,
            last_login TEXT,
            login_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (role_id) REFERENCES roles(id)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            details TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    for name, desc in DEFAULT_PERMISSIONS:
        c.execute("INSERT OR IGNORE INTO permissions (name, description) VALUES (?, ?)", (name, desc))

    for role_name, role_data in DEFAULT_ROLES.items():
        c.execute("INSERT OR IGNORE INTO roles (name, display_name, color, icon, level) VALUES (?, ?, ?, ?, ?)",
            (role_name, role_data["display_name"], role_data["color"], role_data["icon"], role_data["level"]))
        role_row = c.execute("SELECT id FROM roles WHERE name=?", (role_name,)).fetchone()
        if role_row:
            for perm in role_data["permissions"]:
                perm_row = c.execute("SELECT id FROM permissions WHERE name=?", (perm,)).fetchone()
                if perm_row:
                    c.execute("INSERT OR IGNORE INTO role_permissions VALUES (?, ?)", (role_row[0], perm_row[0]))

    defaults = [
        ("site_name", "serveircMail", "Nom du site"),
        ("allow_registration", "1", "Autoriser les inscriptions"),
        ("maintenance_mode", "0", "Mode maintenance"),
        ("max_mail_size_mb", "25", "Taille max des mails en MB"),
        ("session_lifetime_days", "7", "Durée des sessions en jours"),
        ("default_imap_host", "", "Hôte IMAP par défaut"),
        ("default_imap_port", "993", "Port IMAP par défaut"),
        ("default_smtp_host", "", "Hôte SMTP par défaut"),
        ("default_smtp_port", "587", "Port SMTP par défaut"),
        ("require_mail_config", "1", "Exiger la config mail à l'inscription"),
    ]
    for key, val, desc in defaults:
        c.execute("INSERT OR IGNORE INTO system_settings (key, value, description) VALUES (?, ?, ?)", (key, val, desc))

    existing_super = c.execute("SELECT id FROM users WHERE id=1").fetchone()
    if not existing_super:
        super_role = c.execute("SELECT id FROM roles WHERE name='super_admin'").fetchone()
        if super_role:
            pw_hash = hashlib.sha256("admin1234".encode()).hexdigest()
            c.execute("""
                INSERT INTO users (username, email, display_name, password_hash, role_id, is_active)
                VALUES ('admin', 'admin@localhost', 'Super Admin', ?, ?, 1)
            """, (pw_hash, super_role[0]))

    conn.commit()
    conn.close()

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def verify_password(pw: str, hashed: str) -> bool:
    return hashlib.sha256(pw.encode()).hexdigest() == hashed

def create_session(user_id: int, ip: str = "", ua: str = "", days: int = 7) -> str:
    sid = secrets.token_hex(32)
    from datetime import timedelta
    expires = (datetime.utcnow() + timedelta(days=days)).isoformat()
    conn = get_db()
    conn.execute("INSERT INTO sessions (id, user_id, ip_address, user_agent, expires_at) VALUES (?, ?, ?, ?, ?)",
        (sid, user_id, ip, ua, expires))
    conn.commit()
    conn.close()
    return sid

def get_session_user(sid: str):
    conn = get_db()
    row = conn.execute("""
        SELECT u.*, r.name as role_name, r.display_name as role_display, r.color as role_color,
               r.icon as role_icon, r.level as role_level
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        JOIN roles r ON u.role_id = r.id
        WHERE s.id = ? AND s.expires_at > datetime('now') AND u.is_active = 1 AND u.is_suspended = 0
    """, (sid,)).fetchone()
    conn.close()
    return row

def get_user_permissions(user_id: int):
    conn = get_db()
    rows = conn.execute("""
        SELECT p.name FROM permissions p
        JOIN role_permissions rp ON p.id = rp.permission_id
        JOIN roles r ON rp.role_id = r.id
        JOIN users u ON u.role_id = r.id
        WHERE u.id = ?
    """, (user_id,)).fetchall()
    conn.close()
    return [r["name"] for r in rows]

def log_action(user_id, action, target_type=None, target_id=None, details=None, ip=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_logs (user_id, action, target_type, target_id, details, ip_address) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, target_type, str(target_id) if target_id else None, details, ip)
    )
    conn.commit()
    conn.close()

def get_setting(key: str, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, datetime('now'))", (key, value))
    conn.commit()
    conn.close()

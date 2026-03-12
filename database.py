import sqlite3
import os
import secrets
from passlib.context import CryptContext
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "/home/container/serveircmail.db")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_PERMISSIONS = [
    "can_send_mail",
    "can_delete_mail",
    "can_manage_users",
    "can_manage_roles",
    "can_view_logs",
    "can_suspend_users",
    "can_change_settings",
    "can_view_all_mailboxes",
    "can_create_accounts",
    "can_reset_passwords",
    "can_ban_users",
    "can_view_stats",
    "can_view_all_mails",
]

ROLE_PERMISSIONS = {
    "SUPER_ADMIN": DEFAULT_PERMISSIONS,
    "ADMIN": [
        "can_send_mail", "can_delete_mail", "can_manage_users",
        "can_view_logs", "can_suspend_users", "can_view_all_mailboxes",
        "can_create_accounts", "can_reset_passwords", "can_view_stats",
        "can_view_all_mails",
    ],
    "MODERATOR": [
        "can_send_mail", "can_delete_mail",
        "can_view_logs", "can_suspend_users", "can_view_stats",
        "can_view_all_mails",
    ],
    "USER": ["can_send_mail", "can_delete_mail"],
}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _hash_password(password: str) -> str:
    return pwd_context.hash(password.encode('utf-8')[:72])

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        color TEXT DEFAULT '#6C63FF',
        description TEXT DEFAULT '',
        is_system INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        label TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'general'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS role_permissions (
        role_id INTEGER,
        permission_key TEXT,
        PRIMARY KEY (role_id, permission_key)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role_id INTEGER DEFAULT 4,
        imap_host TEXT DEFAULT '',
        imap_port INTEGER DEFAULT 993,
        smtp_host TEXT DEFAULT '',
        smtp_port INTEGER DEFAULT 587,
        mail_password TEXT DEFAULT '',
        mail_username TEXT DEFAULT '',
        mail_alias TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        is_banned INTEGER DEFAULT 0,
        avatar_color TEXT DEFAULT '#6C63FF',
        last_login TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS pending_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        display_name TEXT NOT NULL,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        mail_alias TEXT NOT NULL,
        verification_code TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT DEFAULT 'system',
        action TEXT NOT NULL,
        target TEXT DEFAULT '',
        details TEXT DEFAULT '',
        ip TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    )""")

    # Migrations colonnes users
    for col, typedef in [
        ("mail_username", "TEXT DEFAULT ''"),
        ("mail_alias", "TEXT DEFAULT ''"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
            conn.commit()
        except:
            pass

    default_roles = [
        ("SUPER_ADMIN", "Super Admin", "#FF6584", "Contrôle total du système", 1),
        ("ADMIN", "Admin", "#6C63FF", "Gestion des comptes et paramètres", 1),
        ("MODERATOR", "Modérateur", "#3EC6E0", "Modération et suspension", 1),
        ("USER", "Utilisateur", "#4ade80", "Accès standard", 1),
    ]
    for r in default_roles:
        c.execute("INSERT OR IGNORE INTO roles (name, display_name, color, description, is_system) VALUES (?,?,?,?,?)", r)

    perm_data = [
        ("can_send_mail", "Envoyer des mails", "Peut envoyer des emails", "mail"),
        ("can_delete_mail", "Supprimer des mails", "Peut supprimer ses propres mails", "mail"),
        ("can_manage_users", "Gérer les utilisateurs", "Créer, modifier, supprimer des comptes", "admin"),
        ("can_manage_roles", "Gérer les rôles", "Créer et modifier des rôles custom", "admin"),
        ("can_view_logs", "Voir les logs", "Accès aux logs d'audit", "admin"),
        ("can_suspend_users", "Suspendre des utilisateurs", "Mettre en pause un compte", "admin"),
        ("can_change_settings", "Modifier les paramètres", "Changer la config système", "admin"),
        ("can_view_all_mailboxes", "Voir toutes les boîtes", "Accès aux boîtes de tous les users", "admin"),
        ("can_create_accounts", "Créer des comptes", "Créer de nouveaux utilisateurs", "admin"),
        ("can_reset_passwords", "Réinitialiser les mdp", "Reset le mot de passe d'un user", "admin"),
        ("can_ban_users", "Bannir des utilisateurs", "Bannir définitivement un compte", "moderation"),
        ("can_view_stats", "Voir les statistiques", "Accès au dashboard de stats", "admin"),
        ("can_view_all_mails", "Voir tous les mails (modération)", "Accès à la boîte de modération globale", "moderation"),
    ]
    for p in perm_data:
        c.execute("INSERT OR IGNORE INTO permissions (key, label, description, category) VALUES (?,?,?,?)", p)

    for role_name, perms in ROLE_PERMISSIONS.items():
        row = c.execute("SELECT id FROM roles WHERE name=?", (role_name,)).fetchone()
        if row:
            for perm in perms:
                c.execute("INSERT OR IGNORE INTO role_permissions (role_id, permission_key) VALUES (?,?)", (row["id"], perm))

    defaults = [
        ("allow_registration", "1"),
        ("maintenance_mode", "0"),
        ("site_name", "serveircMail"),
        ("max_users", "100"),
        # IMAP (reception)
        ("global_imap_host", os.getenv("IMAP_HOST", "imap.gmail.com")),
        ("global_imap_port", os.getenv("IMAP_PORT", "993")),
        ("global_imap_user", os.getenv("IMAP_USER", "")),
        ("global_mail_password", os.getenv("EMAIL_PASSWORD", "")),
        # SMTP (envoi Mailtrap)
        ("global_smtp_host", os.getenv("SMTP_HOST", "live.smtp.mailtrap.io")),
        ("global_smtp_port", os.getenv("SMTP_PORT", "587")),
        ("global_smtp_user", os.getenv("SMTP_USER", "api")),
        ("global_smtp_password", os.getenv("SMTP_PASSWORD", "")),
        ("global_smtp_encryption", "TLS"),
        ("mail_domain", ""),
    ]
    for k, v in defaults:
        c.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)", (k, v))

    conn.commit()
    conn.close()
    _create_super_admin()

def _create_super_admin():
    sa_user = os.getenv("SUPER_ADMIN_USERNAME", "admin")
    sa_pass = os.getenv("SUPER_ADMIN_PASSWORD", "admin1234")
    sa_email = os.getenv("SUPER_ADMIN_EMAIL", "admin@serveircmail.local")
    conn = get_conn()
    c = conn.cursor()
    exists = c.execute("SELECT id FROM users WHERE username=?", (sa_user,)).fetchone()
    if not exists:
        role = c.execute("SELECT id FROM roles WHERE name='SUPER_ADMIN'").fetchone()
        hashed = _hash_password(sa_pass)
        c.execute(
            "INSERT INTO users (username, display_name, email, password_hash, role_id, avatar_color) VALUES (?,?,?,?,?,?)",
            (sa_user, "Super Admin", sa_email, hashed, role["id"], "#FF6584")
        )
        conn.commit()
    conn.close()

# ========== USER CRUD ==========

def get_user_by_id(user_id: int):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_username(username: str):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_email(email: str):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_alias(alias: str):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE mail_alias=?", (alias,)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_all_users(search: str = "", page: int = 1, per_page: int = 20):
    conn = get_conn()
    offset = (page - 1) * per_page
    if search:
        users = conn.execute(
            "SELECT u.*, r.name as role_name, r.color as role_color, r.display_name as role_display FROM users u LEFT JOIN roles r ON u.role_id=r.id WHERE u.username LIKE ? OR u.email LIKE ? OR u.display_name LIKE ? ORDER BY u.created_at DESC LIMIT ? OFFSET ?",
            (f"%{search}%", f"%{search}%", f"%{search}%", per_page, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM users WHERE username LIKE ? OR email LIKE ?", (f"%{search}%", f"%{search}%")).fetchone()[0]
    else:
        users = conn.execute(
            "SELECT u.*, r.name as role_name, r.color as role_color, r.display_name as role_display FROM users u LEFT JOIN roles r ON u.role_id=r.id ORDER BY u.created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return [dict(u) for u in users], total

def create_user(username, display_name, email, password, role_id=4, imap_host="", imap_port=993, smtp_host="", smtp_port=587, mail_password="", mail_username="", mail_alias=""):
    conn = get_conn()
    hashed = _hash_password(password)
    colors = ["#6C63FF", "#3EC6E0", "#FF6584", "#4ade80", "#fbbf24", "#f472b6"]
    import random
    color = random.choice(colors)
    try:
        conn.execute(
            "INSERT INTO users (username, display_name, email, password_hash, role_id, imap_host, imap_port, smtp_host, smtp_port, mail_password, mail_username, mail_alias, avatar_color) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (username, display_name, email, hashed, role_id, imap_host, imap_port, smtp_host, smtp_port, mail_password, mail_username, mail_alias, color)
        )
        conn.commit()
        conn.close()
        return True, None
    except sqlite3.IntegrityError as e:
        conn.close()
        return False, str(e)

def update_user(user_id, **kwargs):
    conn = get_conn()
    if "password" in kwargs:
        kwargs["password_hash"] = _hash_password(kwargs.pop("password"))
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    conn.execute(f"UPDATE users SET {fields} WHERE id=?", values)
    conn.commit()
    conn.close()

def delete_user(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain.encode('utf-8')[:72], hashed)

# ========== PENDING USERS ==========

def create_pending_user(username, display_name, email, password, mail_alias):
    conn = get_conn()
    conn.execute("DELETE FROM pending_users WHERE email=?", (email,))
    code = str(secrets.randbelow(900000) + 100000)
    hashed = _hash_password(password)
    expires = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
    conn.execute(
        "INSERT INTO pending_users (username, display_name, email, password_hash, mail_alias, verification_code, expires_at) VALUES (?,?,?,?,?,?,?)",
        (username, display_name, email, hashed, mail_alias, code, expires)
    )
    conn.commit()
    conn.close()
    return code

def get_pending_user(email: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM pending_users WHERE email=? AND expires_at > datetime('now') ORDER BY created_at DESC LIMIT 1",
        (email,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def confirm_pending_user(email: str, code: str):
    pending = get_pending_user(email)
    if not pending:
        return False, "Code expiré ou introuvable"
    if pending["verification_code"] != code:
        return False, "Code incorrect"
    ok, err = create_user(
        username=pending["username"],
        display_name=pending["display_name"],
        email=pending["email"],
        password="__hashed__",
        mail_alias=pending["mail_alias"],
        mail_username=pending["mail_alias"],
    )
    if not ok:
        return False, err
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE email=?", (pending["password_hash"], pending["email"]))
    conn.execute("DELETE FROM pending_users WHERE email=?", (email,))
    conn.commit()
    conn.close()
    user = get_user_by_email(email)
    return True, user

# ========== SESSIONS ==========

def create_session(user_id: int, days: int = 7) -> str:
    token = secrets.token_urlsafe(48)
    expires = (datetime.utcnow() + timedelta(days=days)).isoformat()
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)", (token, user_id, expires))
    conn.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.utcnow().isoformat(), user_id))
    conn.commit()
    conn.close()
    return token

def get_session_user(token: str):
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=? AND s.expires_at > datetime('now')",
        (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_session(token: str):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()

# ========== PERMISSIONS ==========

def get_user_permissions(user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT role_id FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return []
    perms = conn.execute(
        "SELECT permission_key FROM role_permissions WHERE role_id=?",
        (row["role_id"],)
    ).fetchall()
    conn.close()
    return [p["permission_key"] for p in perms]

def user_has_perm(user_id: int, perm: str) -> bool:
    return perm in get_user_permissions(user_id)

def get_all_roles():
    conn = get_conn()
    roles = conn.execute("SELECT r.*, GROUP_CONCAT(rp.permission_key) as permissions FROM roles r LEFT JOIN role_permissions rp ON r.id=rp.role_id GROUP BY r.id ORDER BY r.id").fetchall()
    conn.close()
    result = []
    for r in roles:
        d = dict(r)
        d["permissions"] = d["permissions"].split(",") if d["permissions"] else []
        result.append(d)
    return result

def get_all_permissions():
    conn = get_conn()
    perms = conn.execute("SELECT * FROM permissions ORDER BY category, key").fetchall()
    conn.close()
    return [dict(p) for p in perms]

def update_role_permissions(role_id: int, perm_keys: list):
    conn = get_conn()
    conn.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
    for k in perm_keys:
        conn.execute("INSERT OR IGNORE INTO role_permissions (role_id, permission_key) VALUES (?,?)", (role_id, k))
    conn.commit()
    conn.close()

def create_role(name, display_name, color, description):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO roles (name, display_name, color, description) VALUES (?,?,?,?)", (name.upper(), display_name, color, description))
        conn.commit()
        conn.close()
        return True, None
    except sqlite3.IntegrityError as e:
        conn.close()
        return False, str(e)

# ========== AUDIT LOGS ==========

def add_audit_log(user_id, username, action, target="", details="", ip=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_logs (user_id, username, action, target, details, ip) VALUES (?,?,?,?,?,?)",
        (user_id, username, action, target, details, ip)
    )
    conn.commit()
    conn.close()

def get_audit_logs(page=1, per_page=50, search=""):
    conn = get_conn()
    offset = (page-1)*per_page
    if search:
        logs = conn.execute(
            "SELECT * FROM audit_logs WHERE username LIKE ? OR action LIKE ? OR target LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (f"%{search}%", f"%{search}%", f"%{search}%", per_page, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE username LIKE ? OR action LIKE ?", (f"%{search}%", f"%{search}%")).fetchone()[0]
    else:
        logs = conn.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    conn.close()
    return [dict(l) for l in logs], total

# ========== SETTINGS ==========

def get_setting(key: str, default=""):
    conn = get_conn()
    row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?,?,datetime('now'))", (key, value))
    conn.commit()
    conn.close()

def get_all_settings():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM system_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

# ========== STATS ==========

def get_global_stats():
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_active=1 AND is_banned=0").fetchone()[0]
    banned_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    suspended_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_active=0 AND is_banned=0").fetchone()[0]
    total_logs = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    recent_logins = conn.execute("SELECT COUNT(*) FROM users WHERE last_login > datetime('now', '-24 hours')").fetchone()[0]
    role_stats = conn.execute("SELECT r.display_name, r.color, COUNT(u.id) as count FROM roles r LEFT JOIN users u ON u.role_id=r.id GROUP BY r.id").fetchall()
    conn.close()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "banned_users": banned_users,
        "suspended_users": suspended_users,
        "total_logs": total_logs,
        "recent_logins": recent_logins,
        "role_stats": [dict(r) for r in role_stats],
    }

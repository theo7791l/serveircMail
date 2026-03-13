import sqlite3
import os
import secrets
from passlib.context import CryptContext
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "/home/container/awlor.db")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_PERMISSIONS = [
    "can_send_mail", "can_delete_mail", "can_manage_users", "can_manage_roles",
    "can_view_logs", "can_suspend_users", "can_change_settings",
    "can_view_all_mailboxes", "can_create_accounts", "can_reset_passwords",
    "can_ban_users", "can_view_stats", "can_view_all_mails", "can_manage_mail_addresses",
    "can_run_tests",
]

ROLE_PERMISSIONS = {
    "SUPER_ADMIN": DEFAULT_PERMISSIONS,
    "ADMIN": [
        "can_send_mail", "can_delete_mail", "can_manage_users", "can_view_logs",
        "can_suspend_users", "can_view_all_mailboxes", "can_create_accounts",
        "can_reset_passwords", "can_view_stats", "can_view_all_mails",
        "can_manage_mail_addresses", "can_run_tests",
    ],
    "MODERATOR": [
        "can_send_mail", "can_delete_mail", "can_view_logs",
        "can_suspend_users", "can_view_stats", "can_view_all_mails",
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
        is_active INTEGER DEFAULT 1,
        is_banned INTEGER DEFAULT 0,
        avatar_color TEXT DEFAULT '#6C63FF',
        last_login TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS mail_addresses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        address TEXT UNIQUE NOT NULL,
        is_primary INTEGER DEFAULT 0,
        label TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS inbound_mails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mail_to TEXT NOT NULL,
        mail_from TEXT NOT NULL,
        subject TEXT DEFAULT '',
        body_html TEXT DEFAULT '',
        body_text TEXT DEFAULT '',
        headers TEXT DEFAULT '',
        seen INTEGER DEFAULT 0,
        starred INTEGER DEFAULT 0,
        folder TEXT DEFAULT 'INBOX',
        expires_at TEXT DEFAULT NULL,
        auto_destroy INTEGER DEFAULT 0,
        received_at TEXT DEFAULT (datetime('now'))
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

    # ===== NOUVELLES TABLES =====

    # Brouillons
    c.execute("""CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_from TEXT DEFAULT '',
        mail_to TEXT DEFAULT '',
        subject TEXT DEFAULT '',
        body_html TEXT DEFAULT '',
        body_text TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Snooze
    c.execute("""CREATE TABLE IF NOT EXISTS snoozed_mails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_id INTEGER NOT NULL,
        snooze_until TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (mail_id) REFERENCES inbound_mails(id) ON DELETE CASCADE
    )""")

    # Envoi programmé
    c.execute("""CREATE TABLE IF NOT EXISTS scheduled_mails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_from TEXT NOT NULL,
        mail_to TEXT NOT NULL,
        subject TEXT DEFAULT '',
        body_html TEXT DEFAULT '',
        body_text TEXT DEFAULT '',
        send_at TEXT NOT NULL,
        sent INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Règles de tri automatique
    c.execute("""CREATE TABLE IF NOT EXISTS mail_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        condition_field TEXT NOT NULL,
        condition_operator TEXT NOT NULL,
        condition_value TEXT NOT NULL,
        action_type TEXT NOT NULL,
        action_value TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Templates de réponses rapides
    c.execute("""CREATE TABLE IF NOT EXISTS reply_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        subject TEXT DEFAULT '',
        body_html TEXT DEFAULT '',
        shortcut TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Follow-up tracker
    c.execute("""CREATE TABLE IF NOT EXISTS followup_tracker (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        mail_id INTEGER NOT NULL,
        followup_after_days INTEGER DEFAULT 3,
        notified INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Read receipts
    c.execute("""CREATE TABLE IF NOT EXISTS read_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mail_id INTEGER NOT NULL,
        opened_at TEXT DEFAULT (datetime('now')),
        ip TEXT DEFAULT '',
        user_agent TEXT DEFAULT ''
    )""")

    # Folder mood colors
    c.execute("""CREATE TABLE IF NOT EXISTS folder_colors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        folder_name TEXT NOT NULL,
        color TEXT DEFAULT '#6C63FF',
        UNIQUE(user_id, folder_name),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # AI conversations
    c.execute("""CREATE TABLE IF NOT EXISTS ai_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Notification preferences
    c.execute("""CREATE TABLE IF NOT EXISTS notification_prefs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        notify_new_mail INTEGER DEFAULT 1,
        notify_weekly_digest INTEGER DEFAULT 0,
        notify_followup INTEGER DEFAULT 1,
        notify_snooze_wakeup INTEGER DEFAULT 1,
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

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
        ("can_manage_mail_addresses", "Gérer les adresses mail", "Créer/supprimer des adresses pour n'importe quel compte", "admin"),
        ("can_run_tests", "Lancer les tests système", "Accès au panel de tests admin", "admin"),
    ]
    for p in perm_data:
        c.execute("INSERT OR IGNORE INTO permissions (key, label, description, category) VALUES (?,?,?,?)", p)

    conn.commit()
    conn.close()

    _sync_system_role_permissions()

    defaults = [
        ("allow_registration", "1"),
        ("maintenance_mode", "0"),
        ("site_name", "Awlor"),
        ("max_users", "100"),
        ("mail_domain", os.getenv("MAIL_DOMAIN", "awlor.online")),
        ("global_smtp_password", os.getenv("RESEND_API_KEY", os.getenv("SMTP_PASSWORD", ""))),
        ("webhook_url", os.getenv("WEBHOOK_URL", "https://awlor.online/webhook/inbound")),
        ("webhook_secret", os.getenv("WEBHOOK_SECRET", "")),
        ("app_port", os.getenv("PORT", "15431")),
        ("db_path", os.getenv("DB_PATH", "/home/container/awlor.db")),
        ("secret_key", os.getenv("SECRET_KEY", secrets.token_urlsafe(48))),
        ("super_admin_username", os.getenv("SUPER_ADMIN_USERNAME", "admin")),
        ("super_admin_password", os.getenv("SUPER_ADMIN_PASSWORD", "admin1234")),
        ("super_admin_email", os.getenv("SUPER_ADMIN_EMAIL", "admin@awlor.online")),
        ("session_days", "7"),
        ("verify_code_expiry", "15"),
        ("require_email_verification", "1"),
        ("groq_api_key", os.getenv("GROQ_API_KEY", "")),
        ("groq_model", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")),
        ("ai_enabled", "1"),
    ]
    conn2 = get_conn()
    for k, v in defaults:
        conn2.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)", (k, v))
    conn2.commit()
    conn2.close()

    _create_super_admin()

def _sync_system_role_permissions():
    conn = get_conn()
    c = conn.cursor()
    for role_name, perms in ROLE_PERMISSIONS.items():
        row = c.execute("SELECT id FROM roles WHERE name=?", (role_name,)).fetchone()
        if not row:
            continue
        role_id = row["id"]
        c.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
        for perm in perms:
            c.execute(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_key) VALUES (?,?)",
                (role_id, perm)
            )
    conn.commit()
    conn.close()

def _create_super_admin():
    sa_user = get_setting("super_admin_username") or os.getenv("SUPER_ADMIN_USERNAME", "admin")
    sa_pass = get_setting("super_admin_password") or os.getenv("SUPER_ADMIN_PASSWORD", "admin1234")
    sa_email = get_setting("super_admin_email") or os.getenv("SUPER_ADMIN_EMAIL", "admin@awlor.online")
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

def create_user(username, display_name, email, password, role_id=4):
    conn = get_conn()
    hashed = _hash_password(password)
    colors = ["#6C63FF", "#3EC6E0", "#FF6584", "#4ade80", "#fbbf24", "#f472b6"]
    import random
    color = random.choice(colors)
    try:
        conn.execute(
            "INSERT INTO users (username, display_name, email, password_hash, role_id, avatar_color) VALUES (?,?,?,?,?,?)",
            (username, display_name, email, hashed, role_id, color)
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
    conn.execute("DELETE FROM mail_addresses WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain.encode('utf-8')[:72], hashed)

# ========== MAIL ADDRESSES ==========

def get_user_addresses(user_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM mail_addresses WHERE user_id=? ORDER BY is_primary DESC, created_at ASC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_primary_address(user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT address FROM mail_addresses WHERE user_id=? AND is_primary=1 LIMIT 1", (user_id,)).fetchone()
    if not row:
        row = conn.execute("SELECT address FROM mail_addresses WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
    conn.close()
    return row["address"] if row else ""

def get_all_addresses_for_user(user_id: int):
    rows = get_user_addresses(user_id)
    return [r["address"] for r in rows]

def address_exists(address: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT id FROM mail_addresses WHERE address=?", (address.lower(),)).fetchone()
    conn.close()
    return row is not None

def get_user_by_address(address: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT u.* FROM mail_addresses ma JOIN users u ON ma.user_id=u.id WHERE ma.address=?",
        (address.lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def add_mail_address(user_id: int, address: str, label: str = "", is_primary: bool = False) -> tuple:
    conn = get_conn()
    try:
        count = conn.execute("SELECT COUNT(*) FROM mail_addresses WHERE user_id=?", (user_id,)).fetchone()[0]
        primary = 1 if (is_primary or count == 0) else 0
        if primary:
            conn.execute("UPDATE mail_addresses SET is_primary=0 WHERE user_id=?", (user_id,))
        conn.execute(
            "INSERT INTO mail_addresses (user_id, address, is_primary, label) VALUES (?,?,?,?)",
            (user_id, address.lower(), primary, label)
        )
        conn.commit()
        conn.close()
        return True, None
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Cette adresse est déjà utilisée"

def remove_mail_address(address_id: int, user_id: int = None) -> bool:
    conn = get_conn()
    if user_id:
        result = conn.execute("DELETE FROM mail_addresses WHERE id=? AND user_id=?", (address_id, user_id))
    else:
        result = conn.execute("DELETE FROM mail_addresses WHERE id=?", (address_id,))
    conn.commit()
    conn.close()
    return result.rowcount > 0

def set_primary_address(address_id: int, user_id: int):
    conn = get_conn()
    conn.execute("UPDATE mail_addresses SET is_primary=0 WHERE user_id=?", (user_id,))
    conn.execute("UPDATE mail_addresses SET is_primary=1 WHERE id=? AND user_id=?", (address_id, user_id))
    conn.commit()
    conn.close()

def count_user_addresses(user_id: int) -> int:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM mail_addresses WHERE user_id=?", (user_id,)).fetchone()[0]
    conn.close()
    return count

# ========== PENDING USERS ==========

def create_pending_user(username, display_name, email, password, mail_alias):
    conn = get_conn()
    conn.execute("DELETE FROM pending_users WHERE email=?", (email,))
    code = str(secrets.randbelow(900000) + 100000)
    hashed = _hash_password(password)
    expiry_minutes = int(get_setting("verify_code_expiry", "15"))
    expires = (datetime.utcnow() + timedelta(minutes=expiry_minutes)).isoformat()
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
    )
    if not ok:
        return False, err
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE email=?", (pending["password_hash"], pending["email"]))
    conn.commit()
    user = dict(conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
    conn.close()
    add_mail_address(user["id"], pending["mail_alias"], label="Principal", is_primary=True)
    conn2 = get_conn()
    conn2.execute("DELETE FROM pending_users WHERE email=?", (email,))
    conn2.commit()
    conn2.close()
    return True, user

# ========== SESSIONS ==========

def create_session(user_id: int, days: int = None) -> str:
    if days is None:
        days = int(get_setting("session_days", "7"))
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

# ========== INBOUND MAILS ==========

def save_inbound_mail(mail_to: str, mail_from: str, subject: str, body_html: str, body_text: str, headers: str = "", folder: str = "INBOX"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO inbound_mails (mail_to, mail_from, subject, body_html, body_text, headers, folder) VALUES (?,?,?,?,?,?,?)",
        (mail_to.lower(), mail_from.lower(), subject, body_html, body_text, headers, folder)
    )
    conn.commit()
    conn.close()

def get_inbound_mails(mail_to: str, folder: str = "INBOX", page: int = 1, per_page: int = 20):
    conn = get_conn()
    offset = (page - 1) * per_page
    total = conn.execute(
        "SELECT COUNT(*) FROM inbound_mails WHERE mail_to=? AND folder=?",
        (mail_to.lower(), folder)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, mail_from, mail_to, subject, seen, starred, received_at FROM inbound_mails WHERE mail_to=? AND folder=? ORDER BY received_at DESC LIMIT ? OFFSET ?",
        (mail_to.lower(), folder, per_page, offset)
    ).fetchall()
    conn.close()
    pages = max(1, (total + per_page - 1) // per_page)
    mails = [{'uid': str(r['id']), 'from': r['mail_from'], 'to': r['mail_to'],
               'subject': r['subject'] or '(Sans objet)', 'date': r['received_at'],
               'seen': bool(r['seen']), 'starred': bool(r['starred'])} for r in rows]
    return {'mails': mails, 'total': total, 'page': page, 'pages': pages}

def get_inbound_mails_multi(addresses: list, folder: str = "INBOX", page: int = 1, per_page: int = 20, filter_type: str = ""):
    if not addresses:
        return {'mails': [], 'total': 0, 'page': 1, 'pages': 1}
    conn = get_conn()
    offset = (page - 1) * per_page
    placeholders = ",".join("?" * len(addresses))
    lower_addrs = [a.lower() for a in addresses]

    if folder == "Sent":
        field = "mail_from"
    else:
        field = "mail_to"

    extra = ""
    if filter_type == "unread":
        extra = " AND seen=0"
    elif filter_type == "starred":
        extra = " AND starred=1"

    total = conn.execute(
        f"SELECT COUNT(*) FROM inbound_mails WHERE {field} IN ({placeholders}) AND folder=?{extra}",
        lower_addrs + [folder]
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, mail_from, mail_to, subject, seen, starred, received_at FROM inbound_mails WHERE {field} IN ({placeholders}) AND folder=?{extra} ORDER BY received_at DESC LIMIT ? OFFSET ?",
        lower_addrs + [folder, per_page, offset]
    ).fetchall()
    conn.close()
    pages = max(1, (total + per_page - 1) // per_page)
    mails = [{'uid': str(r['id']), 'from': r['mail_from'], 'to': r['mail_to'],
               'subject': r['subject'] or '(Sans objet)', 'date': r['received_at'],
               'seen': bool(r['seen']), 'starred': bool(r['starred'])} for r in rows]
    return {'mails': mails, 'total': total, 'page': page, 'pages': pages}

def get_all_inbound_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20):
    conn = get_conn()
    offset = (page - 1) * per_page
    total = conn.execute("SELECT COUNT(*) FROM inbound_mails WHERE folder=?", (folder,)).fetchone()[0]
    rows = conn.execute(
        "SELECT id, mail_from, mail_to, subject, seen, starred, received_at FROM inbound_mails WHERE folder=? ORDER BY received_at DESC LIMIT ? OFFSET ?",
        (folder, per_page, offset)
    ).fetchall()
    conn.close()
    pages = max(1, (total + per_page - 1) // per_page)
    mails = [{'uid': str(r['id']), 'from': r['mail_from'], 'to': r['mail_to'],
               'subject': r['subject'] or '(Sans objet)', 'date': r['received_at'],
               'seen': bool(r['seen']), 'starred': bool(r['starred'])} for r in rows]
    return {'mails': mails, 'total': total, 'page': page, 'pages': pages}

def get_inbound_mail_by_id(mail_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM inbound_mails WHERE id=?", (mail_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {'uid': str(row['id']), 'subject': row['subject'] or '(Sans objet)',
            'from': row['mail_from'], 'to': row['mail_to'], 'date': row['received_at'],
            'body_html': row['body_html'], 'body_text': row['body_text'],
            'seen': bool(row['seen']), 'starred': bool(row['starred']),
            'folder': row['folder'], 'auto_destroy': bool(row['auto_destroy']),
            'expires_at': row['expires_at']}

def mark_inbound_mail_seen(mail_id: int):
    conn = get_conn()
    conn.execute("UPDATE inbound_mails SET seen=1 WHERE id=?", (mail_id,))
    conn.commit()
    conn.close()

def toggle_star(mail_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT starred FROM inbound_mails WHERE id=?", (mail_id,)).fetchone()
    if not row:
        conn.close()
        return False
    new_val = 0 if row["starred"] else 1
    conn.execute("UPDATE inbound_mails SET starred=? WHERE id=?", (new_val, mail_id))
    conn.commit()
    conn.close()
    return bool(new_val)

def toggle_seen(mail_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT seen FROM inbound_mails WHERE id=?", (mail_id,)).fetchone()
    if not row:
        conn.close()
        return False
    new_val = 0 if row["seen"] else 1
    conn.execute("UPDATE inbound_mails SET seen=? WHERE id=?", (new_val, mail_id))
    conn.commit()
    conn.close()
    return bool(new_val)

def bulk_action_mails(mail_ids: list, action: str, user_addresses: list):
    conn = get_conn()
    placeholders = ",".join("?" * len(mail_ids))
    if action == "mark_read":
        conn.execute(f"UPDATE inbound_mails SET seen=1 WHERE id IN ({placeholders})", mail_ids)
    elif action == "mark_unread":
        conn.execute(f"UPDATE inbound_mails SET seen=0 WHERE id IN ({placeholders})", mail_ids)
    elif action == "star":
        conn.execute(f"UPDATE inbound_mails SET starred=1 WHERE id IN ({placeholders})", mail_ids)
    elif action == "unstar":
        conn.execute(f"UPDATE inbound_mails SET starred=0 WHERE id IN ({placeholders})", mail_ids)
    elif action == "trash":
        conn.execute(f"UPDATE inbound_mails SET folder='Trash' WHERE id IN ({placeholders})", mail_ids)
    elif action == "spam":
        conn.execute(f"UPDATE inbound_mails SET folder='Spam' WHERE id IN ({placeholders})", mail_ids)
    elif action == "delete":
        conn.execute(f"DELETE FROM inbound_mails WHERE id IN ({placeholders})", mail_ids)
    conn.commit()
    conn.close()

def move_mail(mail_id: int, folder: str):
    conn = get_conn()
    conn.execute("UPDATE inbound_mails SET folder=? WHERE id=?", (folder, mail_id))
    conn.commit()
    conn.close()

def delete_inbound_mail(mail_id: int):
    conn = get_conn()
    result = conn.execute("DELETE FROM inbound_mails WHERE id=?", (mail_id,))
    conn.commit()
    conn.close()
    return result.rowcount > 0

# ========== DRAFTS ==========

def save_draft(user_id: int, mail_from: str, mail_to: str, subject: str, body_html: str, body_text: str, draft_id: int = None):
    conn = get_conn()
    if draft_id:
        conn.execute(
            "UPDATE drafts SET mail_from=?, mail_to=?, subject=?, body_html=?, body_text=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
            (mail_from, mail_to, subject, body_html, body_text, draft_id, user_id)
        )
        conn.commit()
        conn.close()
        return draft_id
    else:
        cur = conn.execute(
            "INSERT INTO drafts (user_id, mail_from, mail_to, subject, body_html, body_text) VALUES (?,?,?,?,?,?)",
            (user_id, mail_from, mail_to, subject, body_html, body_text)
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return new_id

def get_drafts(user_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM drafts WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_draft_by_id(draft_id: int, user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id)).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_draft(draft_id: int, user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM drafts WHERE id=? AND user_id=?", (draft_id, user_id))
    conn.commit()
    conn.close()

# ========== SNOOZE ==========

def snooze_mail(user_id: int, mail_id: int, snooze_until: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO snoozed_mails (user_id, mail_id, snooze_until) VALUES (?,?,?)", (user_id, mail_id, snooze_until))
    conn.execute("UPDATE inbound_mails SET folder='Snoozed' WHERE id=?", (mail_id,))
    conn.commit()
    conn.close()

def get_snoozed_mails(user_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT sm.*, im.subject, im.mail_from FROM snoozed_mails sm JOIN inbound_mails im ON sm.mail_id=im.id WHERE sm.user_id=? ORDER BY sm.snooze_until ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def process_snooze_wakeups():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM snoozed_mails WHERE snooze_until <= datetime('now')"
    ).fetchall()
    for row in rows:
        conn.execute("UPDATE inbound_mails SET folder='INBOX' WHERE id=?", (row["mail_id"],))
        conn.execute("DELETE FROM snoozed_mails WHERE id=?", (row["id"],))
    conn.commit()
    conn.close()
    return len(rows)

# ========== SCHEDULED MAILS ==========

def save_scheduled_mail(user_id: int, mail_from: str, mail_to: str, subject: str, body_html: str, body_text: str, send_at: str):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO scheduled_mails (user_id, mail_from, mail_to, subject, body_html, body_text, send_at) VALUES (?,?,?,?,?,?,?)",
        (user_id, mail_from, mail_to, subject, body_html, body_text, send_at)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def get_pending_scheduled_mails():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scheduled_mails WHERE sent=0 AND send_at <= datetime('now')"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_scheduled_sent(mail_id: int):
    conn = get_conn()
    conn.execute("UPDATE scheduled_mails SET sent=1 WHERE id=?", (mail_id,))
    conn.commit()
    conn.close()

# ========== MAIL RULES ==========

def get_mail_rules(user_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM mail_rules WHERE user_id=? AND is_active=1 ORDER BY priority ASC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_mail_rules(user_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM mail_rules WHERE user_id=? ORDER BY priority ASC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_mail_rule(user_id: int, name: str, condition_field: str, condition_operator: str, condition_value: str, action_type: str, action_value: str = "", priority: int = 0):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO mail_rules (user_id, name, condition_field, condition_operator, condition_value, action_type, action_value, priority) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, name, condition_field, condition_operator, condition_value, action_type, action_value, priority)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def delete_mail_rule(rule_id: int, user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM mail_rules WHERE id=? AND user_id=?", (rule_id, user_id))
    conn.commit()
    conn.close()

def apply_mail_rules(user_id: int, mail_id: int, mail_from: str, subject: str):
    """Applique les règles auto-triage sur un mail entrant."""
    rules = get_mail_rules(user_id)
    for rule in rules:
        field = rule["condition_field"]
        op = rule["condition_operator"]
        val = rule["condition_value"].lower()
        target = ""
        if field == "from":
            target = mail_from.lower()
        elif field == "subject":
            target = subject.lower()
        match = False
        if op == "contains" and val in target:
            match = True
        elif op == "equals" and val == target:
            match = True
        elif op == "starts_with" and target.startswith(val):
            match = True
        elif op == "ends_with" and target.endswith(val):
            match = True
        if match:
            action = rule["action_type"]
            action_val = rule["action_value"]
            conn = get_conn()
            if action == "move_to_folder":
                conn.execute("UPDATE inbound_mails SET folder=? WHERE id=?", (action_val, mail_id))
            elif action == "mark_read":
                conn.execute("UPDATE inbound_mails SET seen=1 WHERE id=?", (mail_id,))
            elif action == "star":
                conn.execute("UPDATE inbound_mails SET starred=1 WHERE id=?", (mail_id,))
            elif action == "trash":
                conn.execute("UPDATE inbound_mails SET folder='Trash' WHERE id=?", (mail_id,))
            elif action == "spam":
                conn.execute("UPDATE inbound_mails SET folder='Spam' WHERE id=?", (mail_id,))
            conn.commit()
            conn.close()

# ========== REPLY TEMPLATES ==========

def get_reply_templates(user_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM reply_templates WHERE user_id=? ORDER BY name ASC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_reply_template(user_id: int, name: str, subject: str, body_html: str, shortcut: str = ""):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO reply_templates (user_id, name, subject, body_html, shortcut) VALUES (?,?,?,?,?)",
        (user_id, name, subject, body_html, shortcut)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def delete_reply_template(template_id: int, user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM reply_templates WHERE id=? AND user_id=?", (template_id, user_id))
    conn.commit()
    conn.close()

# ========== FOLLOW-UP TRACKER ==========

def set_followup(user_id: int, mail_id: int, days: int = 3):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO followup_tracker (user_id, mail_id, followup_after_days) VALUES (?,?,?)",
        (user_id, mail_id, days)
    )
    conn.commit()
    conn.close()

def get_followup_alerts(user_id: int, addresses: list):
    """Retourne les mails envoyés sans réponse après X jours."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT ft.*, im.subject, im.mail_from, im.mail_to, im.received_at FROM followup_tracker ft "
        "JOIN inbound_mails im ON ft.mail_id=im.id "
        "WHERE ft.user_id=? AND ft.notified=0 "
        "AND datetime(im.received_at, '+' || ft.followup_after_days || ' days') <= datetime('now')",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def dismiss_followup(followup_id: int):
    conn = get_conn()
    conn.execute("UPDATE followup_tracker SET notified=1 WHERE id=?", (followup_id,))
    conn.commit()
    conn.close()

# ========== READ RECEIPTS ==========

def record_read_receipt(mail_id: int, ip: str = "", user_agent: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO read_receipts (mail_id, ip, user_agent) VALUES (?,?,?)",
        (mail_id, ip, user_agent)
    )
    conn.commit()
    conn.close()

def get_read_receipts(mail_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM read_receipts WHERE mail_id=? ORDER BY opened_at DESC", (mail_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ========== FOLDER COLORS ==========

def get_folder_colors(user_id: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM folder_colors WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return {r["folder_name"]: r["color"] for r in rows}

def set_folder_color(user_id: int, folder_name: str, color: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO folder_colors (user_id, folder_name, color) VALUES (?,?,?)",
        (user_id, folder_name, color)
    )
    conn.commit()
    conn.close()

# ========== AI CONVERSATIONS ==========

def save_ai_message(user_id: int, role: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO ai_conversations (user_id, role, content) VALUES (?,?,?)",
        (user_id, role, content)
    )
    conn.commit()
    conn.close()

def get_ai_history(user_id: int, limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM ai_conversations WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))

def clear_ai_history(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM ai_conversations WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ========== NOTIFICATION PREFERENCES ==========

def get_notification_prefs(user_id: int) -> dict:
    """Retourne les préférences de notification d'un utilisateur (avec defaults)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM notification_prefs WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    # Defaults si pas encore de ligne
    return {
        "user_id": user_id,
        "notify_new_mail": 1,
        "notify_weekly_digest": 0,
        "notify_followup": 1,
        "notify_snooze_wakeup": 1,
    }

def save_notification_prefs(user_id: int, data: dict):
    """Sauvegarde (upsert) les préférences de notification d'un utilisateur."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO notification_prefs (user_id, notify_new_mail, notify_weekly_digest, notify_followup, notify_snooze_wakeup, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            notify_new_mail=excluded.notify_new_mail,
            notify_weekly_digest=excluded.notify_weekly_digest,
            notify_followup=excluded.notify_followup,
            notify_snooze_wakeup=excluded.notify_snooze_wakeup,
            updated_at=excluded.updated_at
    """, (
        user_id,
        int(data.get("notify_new_mail", 1)),
        int(data.get("notify_weekly_digest", 0)),
        int(data.get("notify_followup", 1)),
        int(data.get("notify_snooze_wakeup", 1)),
    ))
    conn.commit()
    conn.close()

# ========== EXPORT ==========

def get_all_mails_for_export(addresses: list, folder: str = "INBOX") -> list:
    """Retourne tous les mails d'un dossier pour les adresses données (export CSV/ZIP)."""
    if not addresses:
        return []
    conn = get_conn()
    placeholders = ",".join("?" * len(addresses))
    lower_addrs = [a.lower() for a in addresses]
    field = "mail_from" if folder == "Sent" else "mail_to"
    rows = conn.execute(
        f"SELECT id, received_at, mail_from, mail_to, subject, seen, starred, body_text, body_html, folder "
        f"FROM inbound_mails WHERE {field} IN ({placeholders}) AND folder=? ORDER BY received_at DESC",
        lower_addrs + [folder]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ========== WEEKLY DIGEST ==========

def get_weekly_stats(user_id: int, addresses: list) -> dict:
    """Retourne les statistiques de la semaine courante pour le digest hebdomadaire."""
    if not addresses:
        return {}
    conn = get_conn()
    placeholders = ",".join("?" * len(addresses))
    lower_addrs = [a.lower() for a in addresses]

    received = conn.execute(
        f"SELECT COUNT(*) FROM inbound_mails WHERE mail_to IN ({placeholders}) "
        f"AND folder='INBOX' AND received_at >= datetime('now', '-7 days')",
        lower_addrs
    ).fetchone()[0]

    sent = conn.execute(
        f"SELECT COUNT(*) FROM inbound_mails WHERE mail_from IN ({placeholders}) "
        f"AND folder='Sent' AND received_at >= datetime('now', '-7 days')",
        lower_addrs
    ).fetchone()[0]

    unread = conn.execute(
        f"SELECT COUNT(*) FROM inbound_mails WHERE mail_to IN ({placeholders}) "
        f"AND folder='INBOX' AND seen=0",
        lower_addrs
    ).fetchone()[0]

    followups = conn.execute(
        "SELECT COUNT(*) FROM followup_tracker WHERE user_id=? AND notified=0",
        (user_id,)
    ).fetchone()[0]

    snoozed = conn.execute(
        "SELECT COUNT(*) FROM snoozed_mails WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    conn.close()
    return {
        "received": received,
        "sent": sent,
        "unread": unread,
        "followups": followups,
        "snoozed": snoozed,
    }

def get_all_active_users() -> list:
    """Retourne tous les utilisateurs actifs non bannis (pour le digest admin)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, username, display_name, email FROM users WHERE is_active=1 AND is_banned=0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ========== STATS ==========

def get_global_stats():
    conn = get_conn()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_active=1 AND is_banned=0").fetchone()[0]
    banned_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    suspended_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_active=0 AND is_banned=0").fetchone()[0]
    total_logs = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    recent_logins = conn.execute("SELECT COUNT(*) FROM users WHERE last_login > datetime('now', '-24 hours')").fetchone()[0]
    total_addresses = conn.execute("SELECT COUNT(*) FROM mail_addresses").fetchone()[0]
    total_mails = conn.execute("SELECT COUNT(*) FROM inbound_mails").fetchone()[0]
    role_stats = conn.execute("SELECT r.display_name, r.color, COUNT(u.id) as count FROM roles r LEFT JOIN users u ON u.role_id=r.id GROUP BY r.id").fetchall()
    conn.close()
    return {
        "total_users": total_users, "active_users": active_users, "banned_users": banned_users,
        "suspended_users": suspended_users, "total_logs": total_logs, "recent_logins": recent_logins,
        "total_addresses": total_addresses, "total_mails": total_mails,
        "role_stats": [dict(r) for r in role_stats],
    }

def get_mail_heatmap(addresses: list):
    """Retourne le nombre de mails par heure pour les 7 derniers jours."""
    if not addresses:
        return []
    conn = get_conn()
    placeholders = ",".join("?" * len(addresses))
    rows = conn.execute(
        f"SELECT strftime('%H', received_at) as hour, COUNT(*) as count FROM inbound_mails "
        f"WHERE mail_to IN ({placeholders}) AND received_at > datetime('now', '-7 days') GROUP BY hour ORDER BY hour",
        [a.lower() for a in addresses]
    ).fetchall()
    conn.close()
    result = {str(i).zfill(2): 0 for i in range(24)}
    for r in rows:
        result[r["hour"]] = r["count"]
    return [result[str(i).zfill(2)] for i in range(24)]

def get_mail_timeline(user_id: int, contact_address: str):
    """Timeline de tous les échanges avec un contact."""
    conn = get_conn()
    addresses = [a.lower() for a in get_all_addresses_for_user(user_id)]
    if not addresses:
        conn.close()
        return []
    placeholders = ",".join("?" * len(addresses))
    rows = conn.execute(
        f"SELECT *, CASE WHEN mail_from IN ({placeholders}) THEN 'sent' ELSE 'received' END as direction "
        f"FROM inbound_mails WHERE (mail_from=? OR mail_to=?) AND folder != 'Trash' ORDER BY received_at ASC",
        addresses + [contact_address.lower(), contact_address.lower()]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_unseen_count(addresses: list) -> int:
    if not addresses:
        return 0
    conn = get_conn()
    placeholders = ",".join("?" * len(addresses))
    count = conn.execute(
        f"SELECT COUNT(*) FROM inbound_mails WHERE mail_to IN ({placeholders}) AND seen=0 AND folder='INBOX'",
        [a.lower() for a in addresses]
    ).fetchone()[0]
    conn.close()
    return count

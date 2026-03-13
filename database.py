import sqlite3
import os
import secrets
from passlib.context import CryptContext
from datetime import datetime, timedelta

DB_PATH = os.getenv("DB_PATH", "/home/container/serveircmail.db")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_PERMISSIONS = [
    "can_send_mail", "can_delete_mail", "can_manage_users", "can_manage_roles",
    "can_view_logs", "can_suspend_users", "can_change_settings",
    "can_view_all_mailboxes", "can_create_accounts", "can_reset_passwords",
    "can_ban_users", "can_view_stats", "can_view_all_mails", "can_manage_mail_addresses",
]

ROLE_PERMISSIONS = {
    "SUPER_ADMIN": DEFAULT_PERMISSIONS,
    "ADMIN": [
        "can_send_mail", "can_delete_mail", "can_manage_users", "can_view_logs",
        "can_suspend_users", "can_view_all_mailboxes", "can_create_accounts",
        "can_reset_passwords", "can_view_stats", "can_view_all_mails",
        "can_manage_mail_addresses",
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

    # Table des adresses mail (1 user peut en avoir plusieurs)
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
        folder TEXT DEFAULT 'INBOX',
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
        ("global_smtp_password", os.getenv("SMTP_PASSWORD", "")),
        ("mail_domain", os.getenv("MAIL_DOMAIN", "")),
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
    """Retourne la liste des adresses mail sous forme de strings."""
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
        # Si c'est la première adresse du user, la mettre en primaire automatiquement
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
    """Supprime une adresse. Si user_id fourni, vérifie que l'adresse appartient bien à cet user."""
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
    )
    if not ok:
        return False, err
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE email=?", (pending["password_hash"], pending["email"]))
    conn.commit()
    # Créer l'adresse mail primaire
    user = dict(conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
    conn.close()
    add_mail_address(user["id"], pending["mail_alias"], label="Principal", is_primary=True)
    conn2 = get_conn()
    conn2.execute("DELETE FROM pending_users WHERE email=?", (email,))
    conn2.commit()
    conn2.close()
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

# ========== INBOUND MAILS (Resend webhook) ==========

def save_inbound_mail(mail_to: str, mail_from: str, subject: str, body_html: str, body_text: str, headers: str = "", folder: str = "INBOX"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO inbound_mails (mail_to, mail_from, subject, body_html, body_text, headers, folder) VALUES (?,?,?,?,?,?,?)",
        (mail_to.lower(), mail_from, subject, body_html, body_text, headers, folder)
    )
    conn.commit()
    conn.close()

def get_inbound_mails(mail_to: str, folder: str = "INBOX", page: int = 1, per_page: int = 20):
    """Récupère les mails d'une adresse précise."""
    conn = get_conn()
    offset = (page - 1) * per_page
    total = conn.execute(
        "SELECT COUNT(*) FROM inbound_mails WHERE mail_to=? AND folder=?",
        (mail_to.lower(), folder)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, mail_from, mail_to, subject, seen, received_at FROM inbound_mails WHERE mail_to=? AND folder=? ORDER BY received_at DESC LIMIT ? OFFSET ?",
        (mail_to.lower(), folder, per_page, offset)
    ).fetchall()
    conn.close()
    pages = max(1, (total + per_page - 1) // per_page)
    mails = [{'uid': str(r['id']), 'from': r['mail_from'], 'to': r['mail_to'],
               'subject': r['subject'] or '(Sans objet)', 'date': r['received_at'], 'seen': bool(r['seen'])} for r in rows]
    return {'mails': mails, 'total': total, 'page': page, 'pages': pages}

def get_inbound_mails_multi(addresses: list, folder: str = "INBOX", page: int = 1, per_page: int = 20):
    """Récupère les mails de plusieurs adresses (pour les users avec plusieurs adresses)."""
    if not addresses:
        return {'mails': [], 'total': 0, 'page': 1, 'pages': 1}
    conn = get_conn()
    offset = (page - 1) * per_page
    placeholders = ",".join("?" * len(addresses))
    lower_addrs = [a.lower() for a in addresses]
    total = conn.execute(
        f"SELECT COUNT(*) FROM inbound_mails WHERE mail_to IN ({placeholders}) AND folder=?",
        lower_addrs + [folder]
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, mail_from, mail_to, subject, seen, received_at FROM inbound_mails WHERE mail_to IN ({placeholders}) AND folder=? ORDER BY received_at DESC LIMIT ? OFFSET ?",
        lower_addrs + [folder, per_page, offset]
    ).fetchall()
    conn.close()
    pages = max(1, (total + per_page - 1) // per_page)
    mails = [{'uid': str(r['id']), 'from': r['mail_from'], 'to': r['mail_to'],
               'subject': r['subject'] or '(Sans objet)', 'date': r['received_at'], 'seen': bool(r['seen'])} for r in rows]
    return {'mails': mails, 'total': total, 'page': page, 'pages': pages}

def get_all_inbound_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20):
    """Toutes les adresses — réservé modération."""
    conn = get_conn()
    offset = (page - 1) * per_page
    total = conn.execute("SELECT COUNT(*) FROM inbound_mails WHERE folder=?", (folder,)).fetchone()[0]
    rows = conn.execute(
        "SELECT id, mail_from, mail_to, subject, seen, received_at FROM inbound_mails WHERE folder=? ORDER BY received_at DESC LIMIT ? OFFSET ?",
        (folder, per_page, offset)
    ).fetchall()
    conn.close()
    pages = max(1, (total + per_page - 1) // per_page)
    mails = [{'uid': str(r['id']), 'from': r['mail_from'], 'to': r['mail_to'],
               'subject': r['subject'] or '(Sans objet)', 'date': r['received_at'], 'seen': bool(r['seen'])} for r in rows]
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
            'seen': bool(row['seen']), 'folder': row['folder']}

def mark_inbound_mail_seen(mail_id: int):
    conn = get_conn()
    conn.execute("UPDATE inbound_mails SET seen=1 WHERE id=?", (mail_id,))
    conn.commit()
    conn.close()

def delete_inbound_mail(mail_id: int):
    conn = get_conn()
    result = conn.execute("DELETE FROM inbound_mails WHERE id=?", (mail_id,))
    conn.commit()
    conn.close()
    return result.rowcount > 0

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

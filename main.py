from fastapi import FastAPI, Request, Form, HTTPException, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import uvicorn, os, json
from database import (
    init_db, get_db, hash_password, verify_password,
    create_session, get_setting, set_setting,
    get_user_permissions, log_action
)
from auth import get_current_user, require_user, require_role_level, require_permission
from email_client import EmailClient

app = FastAPI(title="serveircMail", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
async def startup():
    init_db()

def tmpl(name, request, user=None, **ctx):
    perms = get_user_permissions(user["id"]) if user else []
    return templates.TemplateResponse(name, {
        "request": request,
        "current_user": user,
        "permissions": perms,
        "site_name": get_setting("site_name", "serveircMail"),
        **ctx
    })

# ============================================================
# PUBLIC
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if user:
        return RedirectResponse("/inbox")
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if user:
        return RedirectResponse("/inbox")
    error = request.query_params.get("error", "")
    return tmpl("login.html", request, error=error)

@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if get_setting("maintenance_mode") == "1":
        conn = get_db()
        u = conn.execute("SELECT u.*, r.level as role_level FROM users u JOIN roles r ON u.role_id=r.id WHERE u.username=?", (username,)).fetchone()
        conn.close()
        if not u or u["role_level"] < 80:
            return RedirectResponse("/maintenance", status_code=302)
    conn = get_db()
    u = conn.execute("""
        SELECT u.*, r.name as role_name, r.level as role_level
        FROM users u JOIN roles r ON u.role_id=r.id
        WHERE (u.username=? OR u.email=?) AND u.is_active=1
    """, (username, username)).fetchone()
    conn.close()
    if not u or not verify_password(password, u["password_hash"]):
        return RedirectResponse("/login?error=invalid", status_code=302)
    if u["is_suspended"]:
        return RedirectResponse("/login?error=suspended", status_code=302)
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    sid = create_session(u["id"], ip, ua)
    conn = get_db()
    conn.execute("UPDATE users SET last_login=datetime('now'), login_count=login_count+1 WHERE id=?", (u["id"],))
    conn.commit(); conn.close()
    log_action(u["id"], "login", ip=ip)
    resp = RedirectResponse("/inbox", status_code=302)
    resp.set_cookie("session", sid, httponly=True, max_age=86400*7, samesite="lax")
    return resp

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if get_setting("allow_registration") != "1":
        return RedirectResponse("/login?error=registration_closed")
    return tmpl("register.html", request)

@app.post("/register")
async def register_post(request: Request,
    username: str = Form(...), email: str = Form(...),
    display_name: str = Form(...), password: str = Form(...),
    mail_address: str = Form(default=""), mail_password: str = Form(default=""),
    imap_host: str = Form(default=""), smtp_host: str = Form(default="")):
    if get_setting("allow_registration") != "1":
        return RedirectResponse("/login?error=registration_closed")
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username=? OR email=?", (username, email)).fetchone()
    if existing:
        conn.close()
        return tmpl("register.html", request, error="Ce nom d'utilisateur ou email est déjà pris.")
    user_role = conn.execute("SELECT id FROM roles WHERE name='user'").fetchone()
    imap_host_val = imap_host or get_setting("default_imap_host", "")
    smtp_host_val = smtp_host or get_setting("default_smtp_host", "")
    conn.execute("""
        INSERT INTO users (username, email, display_name, password_hash, role_id,
            mail_address, mail_password, imap_host, imap_port, smtp_host, smtp_port)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, email, display_name, hash_password(password), user_role[0],
          mail_address, mail_password, imap_host_val,
          int(get_setting("default_imap_port", 993)),
          smtp_host_val, int(get_setting("default_smtp_port", 587))))
    conn.commit()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    conn.close()
    log_action(uid, "register", details=f"Nouveau compte: {username}")
    return RedirectResponse("/login?success=registered", status_code=302)

@app.get("/logout")
async def logout(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if user:
        log_action(user["id"], "logout")
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE id=?", (session,))
        conn.commit(); conn.close()
    resp = RedirectResponse("/login")
    resp.delete_cookie("session")
    return resp

@app.get("/maintenance", response_class=HTMLResponse)
async def maintenance(request: Request):
    return tmpl("maintenance.html", request)

# ============================================================
# MAIL
# ============================================================

@app.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: return RedirectResponse("/login")
    if get_setting("maintenance_mode") == "1" and user["role_level"] < 80:
        return RedirectResponse("/maintenance")
    return tmpl("inbox.html", request, user, folder=request.query_params.get("folder", "INBOX"))

@app.get("/compose", response_class=HTMLResponse)
async def compose(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: return RedirectResponse("/login")
    return tmpl("compose.html", request, user,
        reply_to=request.query_params.get("reply_to", ""),
        subject=request.query_params.get("subject", ""))

@app.get("/mail/{uid}", response_class=HTMLResponse)
async def read_mail(request: Request, uid: int, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: return RedirectResponse("/login")
    return tmpl("read.html", request, user, uid=uid,
        folder=request.query_params.get("folder", "INBOX"))

@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: return RedirectResponse("/login")
    return tmpl("profile.html", request, user)

@app.post("/profile/update")
async def profile_update(request: Request,
    display_name: str = Form(...), mail_address: str = Form(default=""),
    mail_password: str = Form(default=""), imap_host: str = Form(default=""),
    smtp_host: str = Form(default=""), session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: return RedirectResponse("/login")
    conn = get_db()
    conn.execute("""
        UPDATE users SET display_name=?, mail_address=?, mail_password=?,
        imap_host=?, smtp_host=?, updated_at=datetime('now') WHERE id=?
    """, (display_name, mail_address, mail_password, imap_host, smtp_host, user["id"]))
    conn.commit(); conn.close()
    log_action(user["id"], "profile_update")
    return RedirectResponse("/profile?success=1", status_code=302)

# ============================================================
# MAIL API
# ============================================================

def get_email_client(user):
    return EmailClient(
        imap_host=user["imap_host"] or "",
        imap_port=user["imap_port"] or 993,
        smtp_host=user["smtp_host"] or "",
        smtp_port=user["smtp_port"] or 587,
        email_address=user["mail_address"] or "",
        email_password=user["mail_password"] or ""
    )

@app.get("/api/folders")
async def api_folders(session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: raise HTTPException(401)
    return {"folders": get_email_client(user).get_folders()}

@app.get("/api/mails")
async def api_mails(folder: str = "INBOX", page: int = 1, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: raise HTTPException(401)
    return get_email_client(user).get_mails(folder=folder, page=page)

@app.get("/api/mail/{uid}")
async def api_mail(uid: int, folder: str = "INBOX", session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: raise HTTPException(401)
    return get_email_client(user).get_mail(uid=uid, folder=folder)

@app.post("/api/send")
async def api_send(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: raise HTTPException(401)
    perms = get_user_permissions(user["id"])
    if "can_send_mail" not in perms: raise HTTPException(403, "Permission refusée")
    data = await request.json()
    result = get_email_client(user).send_mail(data.get("to"), data.get("subject"), data.get("body"), data.get("html", False))
    if result.get("success"): log_action(user["id"], "send_mail", details=f"To: {data.get('to')}")
    return result

@app.post("/api/mail/{uid}/delete")
async def api_delete(uid: int, folder: str = "INBOX", session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: raise HTTPException(401)
    perms = get_user_permissions(user["id"])
    if "can_delete_mail" not in perms: raise HTTPException(403)
    return get_email_client(user).delete_mail(uid=uid, folder=folder)

@app.post("/api/mail/{uid}/read")
async def api_mark_read(uid: int, folder: str = "INBOX", session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: raise HTTPException(401)
    return get_email_client(user).mark_read(uid=uid, folder=folder)

@app.get("/api/stats")
async def api_stats(session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user: raise HTTPException(401)
    return get_email_client(user).get_stats()

# ============================================================
# ADMIN PANEL
# ============================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 50: raise HTTPException(403)
    conn = get_db()
    stats = {
        "total_users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "active_users": conn.execute("SELECT COUNT(*) FROM users WHERE is_active=1 AND is_suspended=0").fetchone()[0],
        "suspended_users": conn.execute("SELECT COUNT(*) FROM users WHERE is_suspended=1").fetchone()[0],
        "total_roles": conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0],
        "recent_logs": conn.execute("""
            SELECT a.*, u.username, u.display_name FROM audit_logs a
            LEFT JOIN users u ON a.user_id=u.id
            ORDER BY a.created_at DESC LIMIT 10
        """).fetchall()
    }
    conn.close()
    return tmpl("admin/dashboard.html", request, user, stats=stats)

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 50: raise HTTPException(403)
    conn = get_db()
    users = conn.execute("""
        SELECT u.*, r.display_name as role_display, r.color as role_color, r.icon as role_icon, r.level as role_level
        FROM users u LEFT JOIN roles r ON u.role_id=r.id ORDER BY u.created_at DESC
    """).fetchall()
    roles = conn.execute("SELECT * FROM roles ORDER BY level DESC").fetchall()
    conn.close()
    return tmpl("admin/users.html", request, user, users=users, roles=roles)

@app.post("/admin/users/{uid}/suspend")
async def admin_suspend(uid: int, reason: str = Form(default=""), session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 50: raise HTTPException(403)
    perms = get_user_permissions(user["id"])
    if "can_suspend_users" not in perms: raise HTTPException(403)
    conn = get_db()
    target = conn.execute("SELECT u.*, r.level as role_level FROM users u JOIN roles r ON u.role_id=r.id WHERE u.id=?", (uid,)).fetchone()
    if target and target["role_level"] >= user["role_level"]: raise HTTPException(403, "Impossible de suspendre ce compte")
    conn.execute("UPDATE users SET is_suspended=1, suspension_reason=? WHERE id=?", (reason, uid))
    conn.commit(); conn.close()
    log_action(user["id"], "suspend_user", "user", uid, reason)
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/unsuspend")
async def admin_unsuspend(uid: int, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 50: raise HTTPException(403)
    conn = get_db()
    conn.execute("UPDATE users SET is_suspended=0, suspension_reason=NULL WHERE id=?", (uid,))
    conn.commit(); conn.close()
    log_action(user["id"], "unsuspend_user", "user", uid)
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/role")
async def admin_change_role(uid: int, role_id: int = Form(...), session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    perms = get_user_permissions(user["id"])
    if "can_manage_users" not in perms: raise HTTPException(403)
    conn = get_db()
    target_role = conn.execute("SELECT level FROM roles WHERE id=?", (role_id,)).fetchone()
    if target_role and target_role["level"] >= user["role_level"] and user["role_level"] < 100:
        raise HTTPException(403, "Impossible d'assigner ce rôle")
    conn.execute("UPDATE users SET role_id=? WHERE id=?", (role_id, uid))
    conn.commit(); conn.close()
    log_action(user["id"], "change_role", "user", uid, f"role_id={role_id}")
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/delete")
async def admin_delete_user(uid: int, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    if uid == user["id"]: raise HTTPException(400, "Impossible de se supprimer soi-même")
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit(); conn.close()
    log_action(user["id"], "delete_user", "user", uid)
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/reset-password")
async def admin_reset_password(uid: int, new_password: str = Form(...), session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    conn = get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), uid))
    conn.commit(); conn.close()
    log_action(user["id"], "reset_password", "user", uid)
    return RedirectResponse("/admin/users", status_code=302)

@app.get("/admin/roles", response_class=HTMLResponse)
async def admin_roles(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    conn = get_db()
    roles = conn.execute("SELECT * FROM roles ORDER BY level DESC").fetchall()
    permissions = conn.execute("SELECT * FROM permissions").fetchall()
    role_perms = {}
    for r in roles:
        rp = conn.execute("SELECT p.name FROM permissions p JOIN role_permissions rp ON p.id=rp.permission_id WHERE rp.role_id=?", (r["id"],)).fetchall()
        role_perms[r["id"]] = [x["name"] for x in rp]
    conn.close()
    return tmpl("admin/roles.html", request, user, roles=roles, permissions=permissions, role_perms=role_perms)

@app.post("/admin/roles/create")
async def admin_create_role(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 100: raise HTTPException(403)
    data = await request.form()
    name = data.get("name", "").lower().replace(" ", "_")
    display_name = data.get("display_name", "")
    color = data.get("color", "#6C63FF")
    icon = data.get("icon", "👤")
    level = int(data.get("level", 10))
    conn = get_db()
    conn.execute("INSERT INTO roles (name, display_name, color, icon, level) VALUES (?, ?, ?, ?, ?)", (name, display_name, color, icon, level))
    role_id = conn.execute("SELECT id FROM roles WHERE name=?", (name,)).fetchone()[0]
    perms = data.getlist("permissions")
    for p in perms:
        prow = conn.execute("SELECT id FROM permissions WHERE name=?", (p,)).fetchone()
        if prow: conn.execute("INSERT OR IGNORE INTO role_permissions VALUES (?, ?)", (role_id, prow[0]))
    conn.commit(); conn.close()
    log_action(user["id"], "create_role", "role", role_id, display_name)
    return RedirectResponse("/admin/roles", status_code=302)

@app.post("/admin/roles/{rid}/delete")
async def admin_delete_role(rid: int, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 100: raise HTTPException(403)
    protected = ["super_admin", "admin", "moderator", "user"]
    conn = get_db()
    role = conn.execute("SELECT name FROM roles WHERE id=?", (rid,)).fetchone()
    if role and role["name"] in protected: raise HTTPException(400, "Rôle protégé")
    conn.execute("DELETE FROM roles WHERE id=?", (rid,))
    conn.commit(); conn.close()
    log_action(user["id"], "delete_role", "role", rid)
    return RedirectResponse("/admin/roles", status_code=302)

@app.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 50: raise HTTPException(403)
    page = int(request.query_params.get("page", 1))
    per = 50
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    logs = conn.execute("""
        SELECT a.*, u.username, u.display_name FROM audit_logs a
        LEFT JOIN users u ON a.user_id=u.id
        ORDER BY a.created_at DESC LIMIT ? OFFSET ?
    """, (per, (page-1)*per)).fetchall()
    conn.close()
    return tmpl("admin/logs.html", request, user, logs=logs, page=page, total=total, per=per)

@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    conn = get_db()
    settings_rows = conn.execute("SELECT * FROM system_settings ORDER BY key").fetchall()
    conn.close()
    return tmpl("admin/settings.html", request, user, settings_rows=settings_rows)

@app.post("/admin/settings")
async def admin_settings_save(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    data = await request.form()
    for key, value in data.items():
        set_setting(key, value)
    log_action(user["id"], "update_settings")
    return RedirectResponse("/admin/settings?success=1", status_code=302)

@app.get("/admin/create-user", response_class=HTMLResponse)
async def admin_create_user_page(request: Request, session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    conn = get_db()
    roles = conn.execute("SELECT * FROM roles ORDER BY level DESC").fetchall()
    conn.close()
    return tmpl("admin/create_user.html", request, user, roles=roles)

@app.post("/admin/create-user")
async def admin_create_user_post(request: Request,
    username: str = Form(...), email: str = Form(...),
    display_name: str = Form(...), password: str = Form(...),
    role_id: int = Form(...),
    mail_address: str = Form(default=""), mail_password: str = Form(default=""),
    imap_host: str = Form(default=""), smtp_host: str = Form(default=""),
    session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user or user["role_level"] < 80: raise HTTPException(403)
    conn = get_db()
    conn.execute("""
        INSERT INTO users (username, email, display_name, password_hash, role_id,
            mail_address, mail_password, imap_host, smtp_host)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, email, display_name, hash_password(password), role_id,
          mail_address, mail_password, imap_host, smtp_host))
    conn.commit()
    new_uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    conn.close()
    log_action(user["id"], "create_user", "user", new_uid, username)
    return RedirectResponse("/admin/users", status_code=302)

@app.get("/health")
async def health():
    return {"status": "ok", "app": "serveircMail"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 15431)), reload=False)

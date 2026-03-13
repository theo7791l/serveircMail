from fastapi import FastAPI, Request, Form, HTTPException, Depends, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import uvicorn
import os
import json
import database as db
import auth
import email_client
from config import settings

db.init_db()

app = FastAPI(title="serveircMail", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def render(template, request, ctx={}):
    session = request.cookies.get("session")
    user = db.get_session_user(session)
    perms = db.get_user_permissions(user["id"]) if user else []
    site_name = db.get_setting("site_name", "serveircMail")
    maintenance = db.get_setting("maintenance_mode", "0")
    base = {"request": request, "current_user": user, "user_perms": perms, "site_name": site_name, "maintenance_mode": maintenance}
    base.update(ctx)
    return templates.TemplateResponse(template, base)

# ============================================================
# AUTH ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    session = request.cookies.get("session")
    user = db.get_session_user(session)
    if user:
        return RedirectResponse("/inbox")
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = request.cookies.get("session")
    if db.get_session_user(session):
        return RedirectResponse("/inbox")
    return render("login.html", request, {"error": request.query_params.get("error", "")})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = auth.get_client_ip(request)
    user = db.get_user_by_username(username)
    if not user or not db.verify_password(password, user["password_hash"]):
        db.add_audit_log(None, username, "LOGIN_FAILED", ip=ip, details="Mauvais identifiants")
        return RedirectResponse("/login?error=invalid", status_code=302)
    if user["is_banned"]:
        return RedirectResponse("/login?error=banned", status_code=302)
    if not user["is_active"]:
        return RedirectResponse("/login?error=suspended", status_code=302)
    token = db.create_session(user["id"])
    db.add_audit_log(user["id"], user["username"], "LOGIN", ip=ip)
    resp = RedirectResponse("/inbox", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=86400*7, samesite="lax")
    return resp

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if db.get_setting("allow_registration", "1") != "1":
        return RedirectResponse("/login?error=registration_closed")
    mail_domain = db.get_setting("mail_domain", "")
    return render("register.html", request, {
        "error": request.query_params.get("error", ""),
        "mail_domain": mail_domain,
    })

@app.post("/register")
async def register(request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    mail_alias_prefix: str = Form(default="")):
    if db.get_setting("allow_registration", "1") != "1":
        return RedirectResponse("/login?error=registration_closed", status_code=302)

    mail_domain = db.get_setting("mail_domain", "")
    if mail_domain and mail_alias_prefix:
        mail_alias = f"{mail_alias_prefix.strip().lower()}@{mail_domain}"
    else:
        mail_alias = email

    if mail_domain and mail_alias_prefix:
        existing = db.get_user_by_alias(mail_alias)
        if existing:
            return RedirectResponse("/register?error=alias_taken", status_code=302)

    if db.get_user_by_username(username):
        return RedirectResponse("/register?error=username_taken", status_code=302)
    if db.get_user_by_email(email):
        return RedirectResponse("/register?error=email_taken", status_code=302)

    ip = auth.get_client_ip(request)
    code = db.create_pending_user(username, display_name, email, password, mail_alias)

    mail_domain = db.get_setting("mail_domain", "")
    sender = {"mail_alias": f"noreply@{mail_domain}" if mail_domain else "", "email": ""}
    body = (
        f"Bonjour {display_name},\n\n"
        f"Votre code de v\u00e9rification pour activer votre compte serveircMail est :\n\n"
        f"    {code}\n\n"
        f"Ce code expire dans 15 minutes.\n\n"
        f"Si vous n'avez pas demand\u00e9 cette inscription, ignorez cet email."
    )
    email_client.send_mail(sender, to=email, subject="[serveircMail] Code de v\u00e9rification", body=body)
    db.add_audit_log(None, username, "REGISTER_PENDING", ip=ip, details=f"alias={mail_alias}")
    return render("verify.html", request, {"email": email, "error": ""})

@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str = ""):
    return render("verify.html", request, {"email": email, "error": ""})

@app.post("/verify")
async def verify(request: Request,
    email: str = Form(...),
    code: str = Form(...)):
    ok, result = db.confirm_pending_user(email, code.strip())
    if not ok:
        return render("verify.html", request, {"email": email, "error": result})
    user = result
    token = db.create_session(user["id"])
    db.add_audit_log(user["id"], user["username"], "REGISTER_CONFIRMED", details=f"alias={user.get('mail_alias','')}")
    resp = RedirectResponse("/inbox", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=86400*7, samesite="lax")
    return resp

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    user = db.get_session_user(token)
    if user:
        db.add_audit_log(user["id"], user["username"], "LOGOUT")
    db.delete_session(token)
    resp = RedirectResponse("/login")
    resp.delete_cookie("session")
    return resp

# ============================================================
# MAIL ROUTES
# ============================================================

@app.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request, user=Depends(auth.require_auth), page: int = 1, folder: str = "INBOX"):
    return render("inbox.html", request, {"folder": folder, "page": page})

@app.get("/compose", response_class=HTMLResponse)
async def compose(request: Request, user=Depends(auth.require_auth), reply_to: str = "", subject: str = ""):
    return render("compose.html", request, {"reply_to": reply_to, "subject": subject})

@app.get("/mail/{uid}", response_class=HTMLResponse)
async def read_mail(request: Request, uid: int, folder: str = "INBOX", user=Depends(auth.require_auth)):
    return render("read.html", request, {"uid": uid, "folder": folder})

@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, user=Depends(auth.require_auth)):
    role = db.get_all_roles()
    user_role = next((r for r in role if r["id"] == user["role_id"]), None)
    return render("profile.html", request, {"user_role": user_role})

@app.post("/profile")
async def update_profile(request: Request,
    display_name: str = Form(...),
    new_password: str = Form(default=""),
    user=Depends(auth.require_auth)):
    updates = {"display_name": display_name}
    if new_password:
        updates["password"] = new_password
    db.update_user(user["id"], **updates)
    db.add_audit_log(user["id"], user["username"], "PROFILE_UPDATE")
    return RedirectResponse("/profile?success=1", status_code=302)

# ============================================================
# RESEND INBOUND WEBHOOK
# ============================================================

@app.post("/webhook/inbound")
async def inbound_webhook(request: Request):
    """
    Endpoint appelé par Resend quand un mail est reçu sur le domaine.
    Resend envoie un POST JSON avec les champs :
      to (list), from (dict), subject, html, text, headers
    Configurer dans Resend > Receiving > Webhook URL :
      https://ton-app.serveirc.com/webhook/inbound
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, detail="Payload JSON invalide")

    # Resend format : to = [{"email": "...", "name": "..."}]
    to_list = payload.get("to", [])
    mail_to = to_list[0].get("email", "") if to_list else ""

    from_data = payload.get("from", {})
    if isinstance(from_data, dict):
        mail_from = from_data.get("email", "")
    else:
        mail_from = str(from_data)

    subject  = payload.get("subject", "")
    body_html = payload.get("html", "")
    body_text = payload.get("text", "")
    headers  = json.dumps(payload.get("headers", {}))

    if mail_to:
        db.save_inbound_mail(
            mail_to=mail_to,
            mail_from=mail_from,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            headers=headers,
        )

    return JSONResponse({"ok": True})

# ============================================================
# MODERATION MAILBOX
# ============================================================

@app.get("/moderation/mailbox", response_class=HTMLResponse)
async def moderation_mailbox(request: Request, user=Depends(auth.require_perm("can_view_all_mails")),
    page: int = 1, folder: str = "INBOX"):
    return render("moderation/mailbox.html", request, {"folder": folder, "page": page})

# ============================================================
# ADMIN ROUTES
# ============================================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, user=Depends(auth.require_perm("can_view_stats"))):
    stats = db.get_global_stats()
    logs, _ = db.get_audit_logs(per_page=10)
    return render("admin/dashboard.html", request, {"stats": stats, "recent_logs": logs})

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, user=Depends(auth.require_perm("can_manage_users")),
    page: int = 1, search: str = ""):
    users, total = db.get_all_users(search=search, page=page)
    roles = db.get_all_roles()
    pages = max(1, -(-total // 20))
    return render("admin/users.html", request, {"users": users, "roles": roles, "total": total, "page": page, "pages": pages, "search": search})

@app.post("/admin/users/create")
async def admin_create_user(request: Request, user=Depends(auth.require_perm("can_create_accounts")),
    username: str = Form(...), display_name: str = Form(...), email: str = Form(...),
    password: str = Form(...), role_id: int = Form(4),
    mail_alias: str = Form(default="")):
    ip = auth.get_client_ip(request)
    ok, err = db.create_user(username, display_name, email, password, role_id,
        mail_alias=mail_alias, mail_username=mail_alias)
    db.add_audit_log(user["id"], user["username"], "CREATE_USER", target=username, ip=ip)
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/update")
async def admin_update_user(request: Request, uid: int, user=Depends(auth.require_perm("can_manage_users")),
    display_name: str = Form(...), role_id: int = Form(...), is_active: int = Form(1),
    is_banned: int = Form(0), mail_alias: str = Form(default="")):
    updates = {"display_name": display_name, "role_id": role_id, "is_active": is_active, "is_banned": is_banned}
    if mail_alias:
        updates["mail_alias"] = mail_alias
        updates["mail_username"] = mail_alias
    db.update_user(uid, **updates)
    db.add_audit_log(user["id"], user["username"], "UPDATE_USER", target=str(uid))
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/delete")
async def admin_delete_user(request: Request, uid: int, user=Depends(auth.require_perm("can_manage_users"))):
    target = db.get_user_by_id(uid)
    db.delete_user(uid)
    db.add_audit_log(user["id"], user["username"], "DELETE_USER", target=target["username"] if target else str(uid))
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/suspend")
async def admin_suspend(request: Request, uid: int, user=Depends(auth.require_perm("can_suspend_users"))):
    db.update_user(uid, is_active=0)
    db.add_audit_log(user["id"], user["username"], "SUSPEND_USER", target=str(uid))
    return JSONResponse({"success": True})

@app.post("/admin/users/{uid}/unsuspend")
async def admin_unsuspend(request: Request, uid: int, user=Depends(auth.require_perm("can_suspend_users"))):
    db.update_user(uid, is_active=1)
    db.add_audit_log(user["id"], user["username"], "UNSUSPEND_USER", target=str(uid))
    return JSONResponse({"success": True})

@app.post("/admin/users/{uid}/ban")
async def admin_ban(request: Request, uid: int, user=Depends(auth.require_perm("can_ban_users"))):
    db.update_user(uid, is_banned=1, is_active=0)
    db.add_audit_log(user["id"], user["username"], "BAN_USER", target=str(uid))
    return JSONResponse({"success": True})

@app.post("/admin/users/{uid}/unban")
async def admin_unban(request: Request, uid: int, user=Depends(auth.require_perm("can_ban_users"))):
    db.update_user(uid, is_banned=0, is_active=1)
    db.add_audit_log(user["id"], user["username"], "UNBAN_USER", target=str(uid))
    return JSONResponse({"success": True})

@app.get("/admin/roles", response_class=HTMLResponse)
async def admin_roles(request: Request, user=Depends(auth.require_perm("can_manage_roles"))):
    roles = db.get_all_roles()
    perms = db.get_all_permissions()
    return render("admin/roles.html", request, {"roles": roles, "permissions": perms})

@app.post("/admin/roles/create")
async def admin_create_role(request: Request, user=Depends(auth.require_perm("can_manage_roles")),
    name: str = Form(...), display_name: str = Form(...), color: str = Form(...), description: str = Form(default="")):
    db.create_role(name, display_name, color, description)
    db.add_audit_log(user["id"], user["username"], "CREATE_ROLE", target=name)
    return RedirectResponse("/admin/roles", status_code=302)

@app.post("/admin/roles/{role_id}/permissions")
async def admin_update_role_perms(request: Request, role_id: int, user=Depends(auth.require_perm("can_manage_roles"))):
    form = await request.form()
    perms = form.getlist("permissions")
    db.update_role_permissions(role_id, perms)
    db.add_audit_log(user["id"], user["username"], "UPDATE_ROLE_PERMS", target=str(role_id))
    return RedirectResponse("/admin/roles", status_code=302)

@app.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(request: Request, user=Depends(auth.require_perm("can_view_logs")),
    page: int = 1, search: str = ""):
    logs, total = db.get_audit_logs(page=page, search=search)
    pages = max(1, -(-total // 50))
    return render("admin/logs.html", request, {"logs": logs, "total": total, "page": page, "pages": pages, "search": search})

@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, user=Depends(auth.require_perm("can_change_settings"))):
    s = db.get_all_settings()
    return render("admin/settings.html", request, {"settings": s})

@app.post("/admin/settings")
async def admin_save_settings(request: Request, user=Depends(auth.require_perm("can_change_settings"))):
    form = await request.form()
    for key, value in form.items():
        db.set_setting(key, value)
    db.add_audit_log(user["id"], user["username"], "UPDATE_SETTINGS")
    return RedirectResponse("/admin/settings?success=1", status_code=302)

# ============================================================
# API ROUTES
# ============================================================

@app.get("/api/folders")
async def api_folders(user=Depends(auth.require_auth)):
    return {"folders": email_client.get_folders(user)}

@app.get("/api/mails")
async def api_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20, user=Depends(auth.require_auth)):
    return email_client.get_mails(user, folder=folder, page=page, per_page=per_page)

@app.get("/api/mail/{uid}")
async def api_mail(uid: int, folder: str = "INBOX", user=Depends(auth.require_auth)):
    mail = email_client.get_mail(user, uid=str(uid), folder=folder)
    if "error" in mail:
        raise HTTPException(404, detail=mail["error"])
    alias = (user.get("mail_alias") or user.get("email", "")).lower()
    if alias and mail.get("to") and alias not in mail["to"].lower():
        raise HTTPException(403, detail="Ce mail ne vous est pas adress\u00e9")
    return mail

@app.post("/api/send")
async def api_send(request: Request, user=Depends(auth.require_auth)):
    if not db.user_has_perm(user["id"], "can_send_mail"):
        raise HTTPException(403)
    data = await request.json()
    ok, err = email_client.send_mail(user, to=data.get("to"), subject=data.get("subject"), body=data.get("body"), html=data.get("html", False))
    if ok:
        db.add_audit_log(user["id"], user["username"], "SEND_MAIL", target=data.get("to"))
    return {"success": ok, "error": err}

@app.post("/api/mail/{uid}/delete")
async def api_delete(uid: int, folder: str = "INBOX", user=Depends(auth.require_auth)):
    if not db.user_has_perm(user["id"], "can_delete_mail"):
        raise HTTPException(403)
    ok, err = email_client.delete_mail(user, uid=str(uid), folder=folder)
    return {"success": ok, "error": err}

@app.get("/api/moderation/mails")
async def api_moderation_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20,
    user=Depends(auth.require_perm("can_view_all_mails"))):
    from database import get_inbound_mails
    conn = __import__('database').get_conn()
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

@app.post("/api/admin/test-smtp-connection")
async def api_test_smtp(user=Depends(auth.require_perm("can_change_settings"))):
    smtp_pass = db.get_setting("global_smtp_password", "")
    if not smtp_pass:
        return JSONResponse({"success": False, "error": "Clé API Resend (SMTP_PASSWORD) manquante dans les paramètres"})
    ok, result = email_client.test_smtp_connection(smtp_pass)
    return JSONResponse({"success": ok, "message": result if ok else "", "error": result if not ok else ""})

@app.get("/api/stats")
async def api_stats(user=Depends(auth.require_auth)):
    return {"alias": user.get("mail_alias", "")}

@app.get("/api/admin/stats")
async def api_admin_stats(user=Depends(auth.require_perm("can_view_stats"))):
    return db.get_global_stats()

@app.get("/health")
async def health():
    return {"status": "ok", "app": "serveircMail"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 15431)), reload=False)

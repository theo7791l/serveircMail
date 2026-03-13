from fastapi import FastAPI, Request, Form, HTTPException, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import uvicorn
import os
import json
import time
import httpx
import database as db
import auth
import email_client
import scheduler
from config import settings

db.init_db()
scheduler.start_scheduler()

app = FastAPI(title="Awlor", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def render(template, request, ctx={}):
    session = request.cookies.get("session")
    user = db.get_session_user(session)
    perms = db.get_user_permissions(user["id"]) if user else []
    site_name = db.get_setting("site_name", "Awlor")
    maintenance = db.get_setting("maintenance_mode", "0")
    base = {"request": request, "current_user": user, "user_perms": perms,
            "site_name": site_name, "maintenance_mode": maintenance}
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
        db.add_audit_log(None, username, "LOGIN_FAILED", ip=ip)
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
    mail_prefix: str = Form(...)):

    if db.get_setting("allow_registration", "1") != "1":
        return RedirectResponse("/register?error=registration_closed", status_code=302)

    mail_domain = db.get_setting("mail_domain", "")
    if not mail_domain:
        return RedirectResponse("/register?error=no_domain", status_code=302)

    prefix = mail_prefix.strip().lower()
    import re
    if not re.match(r'^[a-z0-9._+-]+$', prefix):
        return RedirectResponse("/register?error=invalid_prefix", status_code=302)

    mail_alias = f"{prefix}@{mail_domain}"

    if db.address_exists(mail_alias):
        return RedirectResponse("/register?error=alias_taken", status_code=302)
    if db.get_user_by_username(username):
        return RedirectResponse("/register?error=username_taken", status_code=302)
    if db.get_user_by_email(email):
        return RedirectResponse("/register?error=email_taken", status_code=302)

    ip = auth.get_client_ip(request)
    code = db.create_pending_user(username, display_name, email, password, mail_alias)

    site_name = db.get_setting("site_name", "Awlor")
    body = (
        f"Bonjour {display_name},\n\n"
        f"Votre code de v\u00e9rification pour activer votre compte {site_name} est :\n\n"
        f"    {code}\n\n"
        f"Ce code expire dans 15 minutes.\n\n"
        f"L'\u00e9quipe {site_name}"
    )
    email_client.send_mail(
        user=None,
        to=email,
        subject=f"[{site_name}] Code de v\u00e9rification",
        body=body,
        from_address=f"noreply@{mail_domain}"
    )
    db.add_audit_log(None, username, "REGISTER_PENDING", ip=ip, details=f"alias={mail_alias}")
    return render("verify.html", request, {"email": email, "error": ""})

@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str = ""):
    return render("verify.html", request, {"email": email, "error": ""})

@app.post("/verify")
async def verify(request: Request, email: str = Form(...), code: str = Form(...)):
    ok, result = db.confirm_pending_user(email, code.strip())
    if not ok:
        return render("verify.html", request, {"email": email, "error": result})
    user = result
    token = db.create_session(user["id"])
    db.add_audit_log(user["id"], user["username"], "REGISTER_CONFIRMED")
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
# PAGES L\u00c9GALES & SEO
# ============================================================

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

@app.get("/cookies", response_class=HTMLResponse)
async def cookies_page(request: Request):
    return templates.TemplateResponse("cookies.html", {"request": request})

@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    content = """User-agent: *
Disallow: /admin
Disallow: /api
Disallow: /webhook
Disallow: /moderation

Sitemap: https://awlor.online/sitemap.xml
"""
    return PlainTextResponse(content, media_type="text/plain")

@app.get("/sitemap.xml")
async def sitemap_xml():
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://awlor.online/</loc></url>
  <url><loc>https://awlor.online/login</loc></url>
  <url><loc>https://awlor.online/register</loc></url>
  <url><loc>https://awlor.online/privacy</loc></url>
  <url><loc>https://awlor.online/cookies</loc></url>
  <url><loc>https://awlor.online/terms</loc></url>
</urlset>"""
    return PlainTextResponse(content, media_type="application/xml")

# ============================================================
# MAIL ROUTES
# ============================================================

@app.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request, user=Depends(auth.require_auth), page: int = 1, folder: str = "INBOX", address: str = ""):
    addresses = db.get_user_addresses(user["id"])
    ai_enabled = db.get_setting("ai_enabled", "1")
    return render("inbox.html", request, {"folder": folder, "page": page, "addresses": addresses, "current_address": address, "ai_enabled": ai_enabled})

@app.get("/compose", response_class=HTMLResponse)
async def compose(request: Request, user=Depends(auth.require_auth), reply_to: str = "", subject: str = "", draft_id: str = ""):
    addresses = db.get_user_addresses(user["id"])
    primary = db.get_primary_address(user["id"])
    templates_list = db.get_reply_templates(user["id"])
    draft = None
    if draft_id:
        try:
            draft = db.get_draft_by_id(int(draft_id), user["id"])
        except Exception:
            pass
    return render("compose.html", request, {
        "reply_to": reply_to,
        "subject": subject,
        "addresses": addresses,
        "primary_address": primary,
        "templates_list": templates_list,
        "draft": draft,
        "draft_id": draft_id,
    })

@app.get("/mail/{uid}", response_class=HTMLResponse)
async def read_mail(request: Request, uid: int, folder: str = "INBOX", user=Depends(auth.require_auth)):
    ai_enabled = db.get_setting("ai_enabled", "1")
    return render("read.html", request, {"uid": uid, "folder": folder, "ai_enabled": ai_enabled})

@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, user=Depends(auth.require_auth)):
    role = db.get_all_roles()
    user_role = next((r for r in role if r["id"] == user["role_id"]), None)
    addresses = db.get_user_addresses(user["id"])
    notif_prefs = db.get_notification_prefs(user["id"])
    return render("profile.html", request, {"user_role": user_role, "addresses": addresses, "notif_prefs": notif_prefs})

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
# NOUVELLES PAGES
# ============================================================

@app.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request, user=Depends(auth.require_auth)):
    rules = db.get_all_mail_rules(user["id"])
    return render("rules.html", request, {"rules": rules})

@app.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request, user=Depends(auth.require_auth)):
    templates_list = db.get_reply_templates(user["id"])
    return render("templates.html", request, {"templates_list": templates_list})

@app.get("/timeline", response_class=HTMLResponse)
async def timeline_page(request: Request, user=Depends(auth.require_auth), contact: str = ""):
    return render("timeline.html", request, {"contact": contact})

@app.get("/ai", response_class=HTMLResponse)
async def ai_page(request: Request, user=Depends(auth.require_auth)):
    ai_enabled = db.get_setting("ai_enabled", "1")
    groq_key = db.get_setting("groq_api_key", "")
    return render("ai.html", request, {"ai_enabled": ai_enabled, "groq_configured": bool(groq_key)})

# ============================================================
# RESEND INBOUND WEBHOOK
# ============================================================

@app.post("/webhook/inbound")
async def inbound_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, detail="Payload JSON invalide")

    to_list = payload.get("to", [])
    mail_to = to_list[0].get("email", "") if to_list else ""

    from_data = payload.get("from", {})
    mail_from = from_data.get("email", "") if isinstance(from_data, dict) else str(from_data)

    subject   = payload.get("subject", "")
    body_html = payload.get("html", "")
    body_text = payload.get("text", "")
    headers   = json.dumps(payload.get("headers", {}))

    if mail_to:
        recipient_user = db.get_user_by_address(mail_to)
        if recipient_user:
            import sqlite3
            conn_tmp = db.get_conn()
            cur = conn_tmp.execute(
                "INSERT INTO inbound_mails (mail_to, mail_from, subject, body_html, body_text, headers, folder) VALUES (?,?,?,?,?,?,?)",
                (mail_to.lower(), mail_from.lower(), subject, body_html, body_text, headers, "INBOX")
            )
            conn_tmp.commit()
            new_mail_id = cur.lastrowid
            conn_tmp.close()
            db.apply_mail_rules(recipient_user["id"], new_mail_id, mail_from, subject)
            # Notif email si activé
            notif_prefs = db.get_notification_prefs(recipient_user["id"])
            if notif_prefs.get("notify_new_mail") and recipient_user.get("email"):
                site_name = db.get_setting("site_name", "Awlor")
                mail_domain = db.get_setting("mail_domain", "awlor.online")
                notif_body = (
                    f"Bonjour {recipient_user['display_name']},\n\n"
                    f"Vous avez re\u00e7u un nouveau mail de {mail_from} :\n"
                    f"Objet : {subject}\n\n"
                    f"Connectez-vous sur https://awlor.online/inbox pour le lire.\n\n"
                    f"L'\u00e9quipe {site_name}"
                )
                try:
                    email_client.send_mail(
                        user=None,
                        to=recipient_user["email"],
                        subject=f"[{site_name}] Nouveau mail de {mail_from}",
                        body=notif_body,
                        from_address=f"noreply@{mail_domain}"
                    )
                except Exception:
                    pass
        else:
            db.save_inbound_mail(mail_to=mail_to, mail_from=mail_from, subject=subject,
                                 body_html=body_html, body_text=body_text, headers=headers)
    return JSONResponse({"ok": True})

# ============================================================
# READ RECEIPT PIXEL
# ============================================================

@app.get("/track/{mail_id}.png")
async def track_pixel(mail_id: int, request: Request):
    ip = auth.get_client_ip(request)
    ua = request.headers.get("user-agent", "")
    db.record_read_receipt(mail_id, ip=ip, user_agent=ua)
    pixel = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(content=pixel, media_type="image/png")

# ============================================================
# MODERATION
# ============================================================

@app.get("/moderation/mailbox", response_class=HTMLResponse)
async def moderation_mailbox(request: Request, user=Depends(auth.require_perm("can_view_all_mails")),
    page: int = 1, folder: str = "INBOX", filter_address: str = ""):
    return render("moderation/mailbox.html", request, {"folder": folder, "page": page, "filter_address": filter_address})

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
    for u in users:
        u["addresses"] = db.get_user_addresses(u["id"])
    mail_domain = db.get_setting("mail_domain", "")
    return render("admin/users.html", request, {
        "users": users, "roles": roles, "total": total,
        "page": page, "pages": pages, "search": search, "mail_domain": mail_domain
    })

@app.post("/admin/users/create")
async def admin_create_user(request: Request, user=Depends(auth.require_perm("can_create_accounts")),
    username: str = Form(...), display_name: str = Form(...), email: str = Form(...),
    password: str = Form(...), role_id: int = Form(4),
    mail_alias: str = Form(default="")):
    ip = auth.get_client_ip(request)
    ok, err = db.create_user(username, display_name, email, password, role_id)
    if ok and mail_alias:
        new_user = db.get_user_by_username(username)
        if new_user:
            db.add_mail_address(new_user["id"], mail_alias, label="Principal", is_primary=True)
    db.add_audit_log(user["id"], user["username"], "CREATE_USER", target=username, ip=ip)
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/update")
async def admin_update_user(request: Request, uid: int, user=Depends(auth.require_perm("can_manage_users")),
    display_name: str = Form(...), role_id: int = Form(...),
    is_active: int = Form(1), is_banned: int = Form(0)):
    db.update_user(uid, display_name=display_name, role_id=role_id, is_active=is_active, is_banned=is_banned)
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

@app.post("/admin/users/{uid}/addresses/add")
async def admin_add_address(request: Request, uid: int,
    user=Depends(auth.require_perm("can_manage_mail_addresses")),
    address: str = Form(...), label: str = Form(default=""), is_primary: int = Form(default=0)):
    ok, err = db.add_mail_address(uid, address, label=label, is_primary=bool(is_primary))
    if not ok:
        return JSONResponse({"success": False, "error": err})
    db.add_audit_log(user["id"], user["username"], "ADD_MAIL_ADDRESS", target=str(uid), details=address)
    return JSONResponse({"success": True})

@app.get("/admin/users/{uid}/addresses/list")
async def admin_list_addresses(request: Request, uid: int,
    user=Depends(auth.require_perm("can_manage_mail_addresses"))):
    addresses = db.get_user_addresses(uid)
    return JSONResponse({"addresses": addresses})

@app.post("/admin/addresses/{addr_id}/delete")
async def admin_delete_address(request: Request, addr_id: int,
    user=Depends(auth.require_perm("can_manage_mail_addresses"))):
    ok = db.remove_mail_address(addr_id)
    db.add_audit_log(user["id"], user["username"], "DELETE_MAIL_ADDRESS", target=str(addr_id))
    return JSONResponse({"success": ok})

@app.post("/admin/addresses/{addr_id}/set-primary")
async def admin_set_primary(request: Request, addr_id: int,
    uid: int = Form(...),
    user=Depends(auth.require_perm("can_manage_mail_addresses"))):
    db.set_primary_address(addr_id, uid)
    db.add_audit_log(user["id"], user["username"], "SET_PRIMARY_ADDRESS", target=str(addr_id))
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

@app.get("/admin/tests", response_class=HTMLResponse)
async def admin_tests(request: Request, user=Depends(auth.require_perm("can_run_tests"))):
    return render("admin/tests.html", request, {})

# ============================================================
# API ADMIN TESTS
# ============================================================

@app.post("/api/admin/test-smtp-connection")
async def api_test_smtp(request: Request, user=Depends(auth.require_perm("can_change_settings"))):
    data = await request.json()
    smtp_pass = data.get("smtp_pass") or db.get_setting("global_smtp_password", "")
    ok, msg = email_client.test_smtp_connection(smtp_pass)
    return JSONResponse({"success": ok, "message": msg})

@app.post("/api/admin/run-test")
async def api_run_test(request: Request, user=Depends(auth.require_perm("can_run_tests"))):
    data = await request.json()
    test_name = data.get("test", "")
    start = time.time()
    result = {"success": False, "message": "Test inconnu", "duration_ms": 0}

    try:
        if test_name == "db_read":
            count = db.get_conn().execute("SELECT COUNT(*) FROM users").fetchone()[0]
            result = {"success": True, "message": f"DB OK \u2014 {count} utilisateur(s) trouv\u00e9(s)"}

        elif test_name == "db_write":
            conn = db.get_conn()
            conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('_test_write', '1')")
            conn.commit()
            conn.execute("DELETE FROM system_settings WHERE key='_test_write'")
            conn.commit()
            conn.close()
            result = {"success": True, "message": "DB write/delete OK"}

        elif test_name == "auth_session":
            test_user = db.get_user_by_username(db.get_setting("super_admin_username", "admin"))
            if test_user:
                token = db.create_session(test_user["id"])
                check = db.get_session_user(token)
                db.delete_session(token)
                result = {"success": bool(check), "message": f"Session cr\u00e9\u00e9e et valid\u00e9e pour {test_user['username']}"}
            else:
                result = {"success": False, "message": "Aucun super admin trouv\u00e9"}

        elif test_name == "smtp":
            smtp_pass = db.get_setting("global_smtp_password", "")
            ok, msg = email_client.test_smtp_connection(smtp_pass)
            result = {"success": ok, "message": msg}

        elif test_name == "webhook":
            webhook_url = db.get_setting("webhook_url", "")
            if not webhook_url:
                result = {"success": False, "message": "Aucune URL webhook configur\u00e9e"}
            else:
                try:
                    async with httpx.AsyncClient(timeout=5) as client:
                        r = await client.get(webhook_url.replace("/webhook/inbound", "/"))
                        result = {"success": r.status_code < 500, "message": f"HTTP {r.status_code}"}
                except Exception as e:
                    result = {"success": False, "message": str(e)}

        elif test_name == "create_delete_user":
            import secrets as _s
            test_username = f"_test_{_s.token_hex(4)}"
            ok, err = db.create_user(test_username, "Test User", f"{test_username}@test.local", "testpass123")
            if ok:
                u = db.get_user_by_username(test_username)
                if u:
                    db.delete_user(u["id"])
                result = {"success": ok, "message": f"Utilisateur '{test_username}' cr\u00e9\u00e9 puis supprim\u00e9"}
            else:
                result = {"success": False, "message": err}

        elif test_name == "imap_folders":
            test_user_obj = db.get_user_by_username(db.get_setting("super_admin_username", "admin"))
            if test_user_obj:
                folders = email_client.get_folders(test_user_obj)
                result = {"success": bool(folders), "message": f"Dossiers: {', '.join(folders)}"}
            else:
                result = {"success": False, "message": "Aucun utilisateur de test"}

        elif test_name == "internal_send":
            addresses = db.get_all_addresses_for_user(user["id"])
            if not addresses:
                result = {"success": False, "message": "Aucune adresse configur\u00e9e"}
            else:
                addr = addresses[0]
                db.save_inbound_mail(
                    mail_to=addr.lower(),
                    mail_from=addr.lower(),
                    subject="[TEST] Envoi interne automatique",
                    body_html="<p>Test d'envoi interne r\u00e9ussi.</p>",
                    body_text="Test d'envoi interne r\u00e9ussi.",
                    folder="INBOX"
                )
                result = {"success": True, "message": f"Mail de test envoy\u00e9 \u00e0 {addr}"}

        elif test_name == "groq_ai":
            groq_key = db.get_setting("groq_api_key", "")
            if not groq_key:
                result = {"success": False, "message": "Cl\u00e9 Groq API non configur\u00e9e"}
            else:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        r = await client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                            json={"model": db.get_setting("groq_model", "llama-3.3-70b-versatile"),
                                  "messages": [{"role": "user", "content": "R\u00e9ponds juste 'OK' en un mot."}],
                                  "max_tokens": 5}
                        )
                        if r.status_code == 200:
                            reply = r.json()["choices"][0]["message"]["content"].strip()
                            result = {"success": True, "message": f"Groq r\u00e9pond: '{reply}'"}
                        else:
                            result = {"success": False, "message": f"Groq HTTP {r.status_code}: {r.text[:100]}"}
                except Exception as e:
                    result = {"success": False, "message": str(e)}

        elif test_name == "snooze":
            test_user_obj = user
            addresses = db.get_all_addresses_for_user(test_user_obj["id"])
            if not addresses:
                result = {"success": False, "message": "Aucune adresse pour le test"}
            else:
                db.save_inbound_mail(addresses[0].lower(), "test@test.local", "[TEST] Snooze", "", "snooze test")
                conn_t = db.get_conn()
                mail_row = conn_t.execute("SELECT id FROM inbound_mails ORDER BY id DESC LIMIT 1").fetchone()
                conn_t.close()
                if mail_row:
                    from datetime import datetime, timedelta
                    snooze_dt = (datetime.utcnow() + timedelta(seconds=5)).isoformat()
                    db.snooze_mail(test_user_obj["id"], mail_row["id"], snooze_dt)
                    result = {"success": True, "message": f"Mail #{mail_row['id']} snooz\u00e9 jusqu'\u00e0 +5s"}
                else:
                    result = {"success": False, "message": "Impossible de cr\u00e9er le mail de test"}

        elif test_name == "rules":
            rule_id = db.create_mail_rule(
                user["id"], "_test_rule", "from", "contains", "_test_noop_",
                "mark_read", "", 999
            )
            db.delete_mail_rule(rule_id, user["id"])
            result = {"success": True, "message": f"R\u00e8gle cr\u00e9\u00e9e (id={rule_id}) puis supprim\u00e9e"}

        elif test_name == "followup":
            addresses = db.get_all_addresses_for_user(user["id"])
            if not addresses:
                result = {"success": False, "message": "Aucune adresse"}
            else:
                db.save_inbound_mail(addresses[0].lower(), "test@test.local", "[TEST] Followup", "", "followup test")
                conn_t = db.get_conn()
                mail_row = conn_t.execute("SELECT id FROM inbound_mails ORDER BY id DESC LIMIT 1").fetchone()
                conn_t.close()
                if mail_row:
                    db.set_followup(user["id"], mail_row["id"], days=0)
                    alerts = db.get_followup_alerts(user["id"], addresses)
                    result = {"success": True, "message": f"Follow-up OK \u2014 {len(alerts)} alerte(s) d\u00e9tect\u00e9e(s)"}
                else:
                    result = {"success": False, "message": "Mail test introuvable"}

    except Exception as e:
        result = {"success": False, "message": f"Exception: {str(e)}"}

    result["duration_ms"] = round((time.time() - start) * 1000, 1)
    return JSONResponse(result)

# ============================================================
# API ROUTES
# ============================================================

@app.get("/api/folders")
async def api_folders(user=Depends(auth.require_auth)):
    return {"folders": email_client.get_folders(user)}

@app.get("/api/mails")
async def api_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20,
    address: str = "", filter: str = "", user=Depends(auth.require_auth)):
    if address:
        user_addrs = db.get_all_addresses_for_user(user["id"])
        if address.lower() not in [a.lower() for a in user_addrs]:
            raise HTTPException(403, detail="Cette adresse ne vous appartient pas")
    return email_client.get_mails(user, folder=folder, page=page, per_page=per_page,
                                  address=address if address else None, filter_type=filter)

@app.get("/api/mail/{uid}")
async def api_mail(uid: int, user=Depends(auth.require_auth)):
    mail = email_client.get_mail(user, uid=str(uid))
    if "error" in mail:
        raise HTTPException(404, detail=mail["error"])
    user_addrs = [a.lower() for a in db.get_all_addresses_for_user(user["id"])]
    if mail.get("to", "").lower() not in user_addrs and mail.get("from", "").lower() not in user_addrs:
        raise HTTPException(403, detail="Acc\u00e8s refus\u00e9")
    return mail

@app.post("/api/send")
async def api_send(request: Request, user=Depends(auth.require_auth)):
    if not db.user_has_perm(user["id"], "can_send_mail"):
        raise HTTPException(403)
    data = await request.json()
    to = (data.get("to") or "").strip()
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    from_address = (data.get("from_address") or "").strip()
    is_html = data.get("html", False)
    scheduled_at = data.get("scheduled_at", "")

    if not to:
        return JSONResponse({"success": False, "error": "Destinataire manquant"})

    if from_address:
        user_addrs = db.get_all_addresses_for_user(user["id"])
        if from_address.lower() not in [a.lower() for a in user_addrs]:
            raise HTTPException(403, detail="Adresse exp\u00e9ditrice non autoris\u00e9e")

    sent_from = from_address or db.get_primary_address(user["id"]) or f"noreply@{db.get_setting('mail_domain', 'awlor.online')}"
    body_html = body if is_html else ""
    body_text = "" if is_html else body

    if scheduled_at:
        mail_id = db.save_scheduled_mail(user["id"], sent_from, to, subject, body_html, body_text, scheduled_at)
        return JSONResponse({"success": True, "scheduled": True, "id": mail_id})

    to_lower = to.lower()
    is_internal = db.address_exists(to_lower)

    if is_internal:
        db.save_inbound_mail(
            mail_to=to_lower, mail_from=sent_from, subject=subject,
            body_html=body_html, body_text=body_text,
            headers=json.dumps({"from": sent_from, "to": to}), folder="INBOX"
        )
        ok, err = True, None
    else:
        ok, err = email_client.send_mail(
            user=user, to=to, subject=subject, body=body,
            html=is_html, from_address=sent_from
        )

    if ok:
        db.save_inbound_mail(
            mail_to=to_lower, mail_from=sent_from, subject=subject,
            body_html=body_html, body_text=body_text,
            headers=json.dumps({"from": sent_from, "to": to}), folder="Sent"
        )
        db.add_audit_log(user["id"], user["username"], "SEND_MAIL", target=to)

    return {"success": ok, "error": err}

@app.post("/api/mail/{uid}/delete")
async def api_delete(uid: int, user=Depends(auth.require_auth)):
    if not db.user_has_perm(user["id"], "can_delete_mail"):
        raise HTTPException(403)
    ok, err = email_client.delete_mail(user, uid=str(uid))
    return {"success": ok, "error": err}

@app.post("/api/mail/{uid}/move")
async def api_move(uid: int, request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    folder = data.get("folder", "INBOX")
    mail = db.get_inbound_mail_by_id(uid)
    if not mail:
        raise HTTPException(404)
    user_addrs = [a.lower() for a in db.get_all_addresses_for_user(user["id"])]
    if mail.get("to", "").lower() not in user_addrs and mail.get("from", "").lower() not in user_addrs:
        raise HTTPException(403)
    db.move_mail(uid, folder)
    return JSONResponse({"success": True})

@app.post("/api/mail/{uid}/star")
async def api_star(uid: int, user=Depends(auth.require_auth)):
    mail = db.get_inbound_mail_by_id(uid)
    if not mail:
        raise HTTPException(404)
    user_addrs = [a.lower() for a in db.get_all_addresses_for_user(user["id"])]
    if mail.get("to", "").lower() not in user_addrs and mail.get("from", "").lower() not in user_addrs:
        raise HTTPException(403)
    starred = db.toggle_star(uid)
    return JSONResponse({"success": True, "starred": starred})

@app.post("/api/mail/{uid}/seen")
async def api_toggle_seen(uid: int, user=Depends(auth.require_auth)):
    mail = db.get_inbound_mail_by_id(uid)
    if not mail:
        raise HTTPException(404)
    user_addrs = [a.lower() for a in db.get_all_addresses_for_user(user["id"])]
    if mail.get("to", "").lower() not in user_addrs and mail.get("from", "").lower() not in user_addrs:
        raise HTTPException(403)
    seen = db.toggle_seen(uid)
    return JSONResponse({"success": True, "seen": seen})

@app.post("/api/mails/bulk")
async def api_bulk(request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    mail_ids = [int(i) for i in data.get("ids", [])]
    action = data.get("action", "")
    if not mail_ids or not action:
        return JSONResponse({"success": False, "error": "Param\u00e8tres manquants"})
    addresses = db.get_all_addresses_for_user(user["id"])
    db.bulk_action_mails(mail_ids, action, addresses)
    return JSONResponse({"success": True, "count": len(mail_ids)})

@app.post("/api/mail/{uid}/snooze")
async def api_snooze(uid: int, request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    snooze_until = data.get("snooze_until", "")
    if not snooze_until:
        return JSONResponse({"success": False, "error": "Date manquante"})
    mail = db.get_inbound_mail_by_id(uid)
    if not mail:
        raise HTTPException(404)
    user_addrs = [a.lower() for a in db.get_all_addresses_for_user(user["id"])]
    if mail.get("to", "").lower() not in user_addrs:
        raise HTTPException(403)
    db.snooze_mail(user["id"], uid, snooze_until)
    return JSONResponse({"success": True})

@app.get("/api/mails/snoozed")
async def api_snoozed(user=Depends(auth.require_auth)):
    rows = db.get_snoozed_mails(user["id"])
    return JSONResponse({"snoozed": rows})

@app.post("/api/mail/{uid}/followup")
async def api_followup(uid: int, request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    days = int(data.get("days", 3))
    db.set_followup(user["id"], uid, days)
    return JSONResponse({"success": True})

@app.get("/api/followup/alerts")
async def api_followup_alerts(user=Depends(auth.require_auth)):
    addresses = db.get_all_addresses_for_user(user["id"])
    alerts = db.get_followup_alerts(user["id"], addresses)
    return JSONResponse({"alerts": alerts})

@app.post("/api/followup/{fid}/dismiss")
async def api_followup_dismiss(fid: int, user=Depends(auth.require_auth)):
    db.dismiss_followup(fid)
    return JSONResponse({"success": True})

@app.get("/api/my-addresses")
async def api_my_addresses(user=Depends(auth.require_auth)):
    return {"addresses": db.get_user_addresses(user["id"])}

@app.get("/api/stats")
async def api_stats(user=Depends(auth.require_auth)):
    addresses = db.get_all_addresses_for_user(user["id"])
    unseen = db.get_unseen_count(addresses)
    heatmap = db.get_mail_heatmap(addresses)
    followup_alerts = db.get_followup_alerts(user["id"], addresses)
    db.process_snooze_wakeups()
    return {
        "unseen": unseen, "unread": unseen,
        "heatmap": heatmap,
        "followup_count": len(followup_alerts),
        "followup_alerts": followup_alerts[:5],
    }

@app.get("/api/heatmap")
async def api_heatmap(user=Depends(auth.require_auth)):
    addresses = db.get_all_addresses_for_user(user["id"])
    data = db.get_mail_heatmap(addresses)
    return JSONResponse({"heatmap": data})

@app.get("/api/timeline")
async def api_timeline(contact: str = "", user=Depends(auth.require_auth)):
    if not contact:
        return JSONResponse({"timeline": []})
    timeline = db.get_mail_timeline(user["id"], contact)
    return JSONResponse({"timeline": timeline, "contact": contact})

# ============================================================
# API DRAFTS
# ============================================================

@app.get("/api/drafts")
async def api_get_drafts(user=Depends(auth.require_auth)):
    drafts = db.get_drafts(user["id"])
    return JSONResponse({"drafts": drafts})

@app.post("/api/drafts")
async def api_save_draft(request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    draft_id = db.save_draft(
        user_id=user["id"],
        mail_from=data.get("from_address", ""),
        mail_to=data.get("to", ""),
        subject=data.get("subject", ""),
        body_html=data.get("body", ""),
        body_text="",
        draft_id=data.get("draft_id")
    )
    return JSONResponse({"success": True, "draft_id": draft_id})

@app.delete("/api/drafts/{draft_id}")
async def api_delete_draft(draft_id: int, user=Depends(auth.require_auth)):
    db.delete_draft(draft_id, user["id"])
    return JSONResponse({"success": True})

# ============================================================
# API RULES
# ============================================================

@app.get("/api/rules")
async def api_get_rules(user=Depends(auth.require_auth)):
    rules = db.get_all_mail_rules(user["id"])
    return JSONResponse({"rules": rules})

@app.post("/api/rules")
async def api_create_rule(request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    rule_id = db.create_mail_rule(
        user_id=user["id"],
        name=data.get("name", "Nouvelle r\u00e8gle"),
        condition_field=data.get("condition_field", "from"),
        condition_operator=data.get("condition_operator", "contains"),
        condition_value=data.get("condition_value", ""),
        action_type=data.get("action_type", "move_to_folder"),
        action_value=data.get("action_value", ""),
        priority=data.get("priority", 0)
    )
    return JSONResponse({"success": True, "id": rule_id})

@app.delete("/api/rules/{rule_id}")
async def api_delete_rule(rule_id: int, user=Depends(auth.require_auth)):
    db.delete_mail_rule(rule_id, user["id"])
    return JSONResponse({"success": True})

# ============================================================
# API TEMPLATES
# ============================================================

@app.get("/api/templates")
async def api_get_templates(user=Depends(auth.require_auth)):
    tpls = db.get_reply_templates(user["id"])
    return JSONResponse({"templates": tpls})

@app.post("/api/templates")
async def api_create_template(request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    tpl_id = db.create_reply_template(
        user_id=user["id"],
        name=data.get("name", "Nouveau template"),
        subject=data.get("subject", ""),
        body_html=data.get("body_html", ""),
        shortcut=data.get("shortcut", "")
    )
    return JSONResponse({"success": True, "id": tpl_id})

@app.delete("/api/templates/{tpl_id}")
async def api_delete_template(tpl_id: int, user=Depends(auth.require_auth)):
    db.delete_reply_template(tpl_id, user["id"])
    return JSONResponse({"success": True})

# ============================================================
# API FOLDER COLORS
# ============================================================

@app.get("/api/folder-colors")
async def api_get_folder_colors(user=Depends(auth.require_auth)):
    colors = db.get_folder_colors(user["id"])
    return JSONResponse({"colors": colors})

@app.post("/api/folder-colors")
async def api_set_folder_color(request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    db.set_folder_color(user["id"], data.get("folder", ""), data.get("color", "#6C63FF"))
    return JSONResponse({"success": True})

# ============================================================
# API READ RECEIPTS
# ============================================================

@app.get("/api/mail/{uid}/receipts")
async def api_read_receipts(uid: int, user=Depends(auth.require_auth)):
    mail = db.get_inbound_mail_by_id(uid)
    if not mail:
        raise HTTPException(404)
    user_addrs = [a.lower() for a in db.get_all_addresses_for_user(user["id"])]
    if mail.get("from", "").lower() not in user_addrs:
        raise HTTPException(403)
    receipts = db.get_read_receipts(uid)
    return JSONResponse({"receipts": receipts})

# ============================================================
# API AI (GROQ)
# ============================================================

@app.post("/api/ai/chat")
async def api_ai_chat(request: Request, user=Depends(auth.require_auth)):
    ai_enabled = db.get_setting("ai_enabled", "1")
    if ai_enabled != "1":
        return JSONResponse({"success": False, "error": "IA d\u00e9sactiv\u00e9e"})
    groq_key = db.get_setting("groq_api_key", "")
    if not groq_key:
        return JSONResponse({"success": False, "error": "Cl\u00e9 Groq non configur\u00e9e."})
    groq_model = db.get_setting("groq_model", "llama-3.3-70b-versatile")
    data = await request.json()
    user_message = data.get("message", "").strip()
    mail_context = data.get("mail_context", None)
    action = data.get("action", "chat")
    history = db.get_ai_history(user["id"], limit=10)
    addresses = db.get_all_addresses_for_user(user["id"])
    primary_addr = db.get_primary_address(user["id"])
    system_prompt = f"""Tu es Awlor AI, l'assistant intelligent int\u00e9gr\u00e9 \u00e0 la bo\u00eete mail Awlor.
Tu as acc\u00e8s \u00e0 la bo\u00eete mail de {user['display_name']} ({primary_addr}).
Tu peux : r\u00e9sumer des mails, r\u00e9diger des r\u00e9ponses, d\u00e9tecter du spam, traduire, trier, analyser des conversations.
R\u00e9ponds toujours en fran\u00e7ais sauf si l'utilisateur \u00e9crit dans une autre langue.
Sois concis, professionnel et utile. Quand tu g\u00e9n\u00e8res un mail, formate-le clairement avec Objet: et Corps:.
Adresses de l'utilisateur : {', '.join(addresses) if addresses else 'aucune'}"""
    if mail_context:
        system_prompt += f"\n\nCONTEXTE MAIL ACTUEL:\nDe: {mail_context.get('from','')}\nObjet: {mail_context.get('subject','')}\nContenu: {mail_context.get('body','')[:2000]}"
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"]})
    if action == "summarize" and mail_context:
        user_message = "Fais un r\u00e9sum\u00e9 concis de ce mail en 3-4 phrases maximum."
    elif action == "reply" and mail_context:
        user_message = "R\u00e9dige une r\u00e9ponse professionnelle et courtoise \u00e0 ce mail."
    elif action == "spam" and mail_context:
        user_message = "Analyse ce mail et dis-moi s'il s'agit de spam ou d'un mail l\u00e9gitime. Justifie ta r\u00e9ponse."
    elif action == "translate" and mail_context:
        user_message = "Traduis ce mail en fran\u00e7ais de mani\u00e8re naturelle."
    elif action == "compose":
        user_message = data.get("message", "R\u00e9dige un mail professionnel.")
    messages.append({"role": "user", "content": user_message})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={"model": groq_model, "messages": messages, "max_tokens": 1024, "temperature": 0.7}
            )
            if r.status_code != 200:
                return JSONResponse({"success": False, "error": f"Groq API error {r.status_code}"})
            response_data = r.json()
            ai_reply = response_data["choices"][0]["message"]["content"]
            db.save_ai_message(user["id"], "user", user_message)
            db.save_ai_message(user["id"], "assistant", ai_reply)
            return JSONResponse({"success": True, "reply": ai_reply, "model": groq_model,
                                 "tokens": response_data.get("usage", {})})
    except httpx.TimeoutException:
        return JSONResponse({"success": False, "error": "Timeout \u2014 Groq ne r\u00e9pond pas"})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/ai/history")
async def api_ai_history(user=Depends(auth.require_auth)):
    history = db.get_ai_history(user["id"], limit=50)
    return JSONResponse({"history": history})

@app.post("/api/ai/clear")
async def api_ai_clear(user=Depends(auth.require_auth)):
    db.clear_ai_history(user["id"])
    return JSONResponse({"success": True})

# ============================================================
# API MOD\u00c9RATION
# ============================================================

@app.get("/api/moderation/mails")
async def api_moderation_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20,
    filter_address: str = "", user=Depends(auth.require_perm("can_view_all_mails"))):
    if filter_address:
        return db.get_inbound_mails(mail_to=filter_address, folder=folder, page=page, per_page=per_page)
    return db.get_all_inbound_mails(folder=folder, page=page, per_page=per_page)

@app.get("/api/moderation/mail/{uid}")
async def api_moderation_mail(uid: int, user=Depends(auth.require_perm("can_view_all_mails"))):
    mail = db.get_inbound_mail_by_id(uid)
    if not mail:
        raise HTTPException(404)
    db.mark_inbound_mail_seen(uid)
    return mail

@app.post("/api/moderation/mail/{uid}/delete")
async def api_moderation_delete(uid: int, user=Depends(auth.require_perm("can_view_all_mails"))):
    ok = db.delete_inbound_mail(uid)
    return JSONResponse({"success": ok})

# ============================================================
# PARTIE 7 \u2014 EXPORT MAILS (CSV + EML)
# ============================================================

@app.get("/api/export/csv")
async def api_export_csv(folder: str = "INBOX", user=Depends(auth.require_auth)):
    """T\u00e9l\u00e9charge tous les mails d'un dossier au format CSV."""
    import csv
    import io
    addresses = db.get_all_addresses_for_user(user["id"])
    mails = db.get_all_mails_for_export(addresses, folder=folder)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "date", "from", "to", "subject", "folder", "seen", "starred"])
    writer.writeheader()
    for m in mails:
        writer.writerow({
            "id": m.get("id", ""),
            "date": m.get("created_at", ""),
            "from": m.get("mail_from", ""),
            "to": m.get("mail_to", ""),
            "subject": m.get("subject", ""),
            "folder": m.get("folder", ""),
            "seen": m.get("seen", 0),
            "starred": m.get("starred", 0),
        })
    output.seek(0)
    db.add_audit_log(user["id"], user["username"], "EXPORT_CSV", details=f"folder={folder}")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="awlor_export_{folder}.csv"'}
    )

@app.get("/api/export/eml/{uid}")
async def api_export_eml(uid: int, user=Depends(auth.require_auth)):
    """T\u00e9l\u00e9charge un mail unique au format .eml."""
    mail = db.get_inbound_mail_by_id(uid)
    if not mail:
        raise HTTPException(404)
    user_addrs = [a.lower() for a in db.get_all_addresses_for_user(user["id"])]
    if mail.get("mail_to", "").lower() not in user_addrs and mail.get("mail_from", "").lower() not in user_addrs:
        raise HTTPException(403)
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart("alternative")
    msg["Subject"] = mail.get("subject", "")
    msg["From"] = mail.get("mail_from", "")
    msg["To"] = mail.get("mail_to", "")
    msg["Date"] = mail.get("created_at", "")
    msg["Message-ID"] = f"<{uid}@awlor.online>"
    if mail.get("body_text"):
        msg.attach(MIMEText(mail["body_text"], "plain", "utf-8"))
    if mail.get("body_html"):
        msg.attach(MIMEText(mail["body_html"], "html", "utf-8"))
    eml_bytes = msg.as_bytes()
    safe_subject = "".join(c for c in (mail.get("subject", "mail") or "mail") if c.isalnum() or c in "-_ ")[:40].strip()
    db.add_audit_log(user["id"], user["username"], "EXPORT_EML", target=str(uid))
    return Response(
        content=eml_bytes,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{safe_subject}.eml"'}
    )

@app.get("/api/export/zip")
async def api_export_zip(folder: str = "INBOX", user=Depends(auth.require_auth)):
    """T\u00e9l\u00e9charge tous les mails d'un dossier en ZIP de fichiers .eml."""
    import io
    import zipfile
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    addresses = db.get_all_addresses_for_user(user["id"])
    mails = db.get_all_mails_for_export(addresses, folder=folder)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for m in mails:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = m.get("subject", "")
            msg["From"] = m.get("mail_from", "")
            msg["To"] = m.get("mail_to", "")
            msg["Date"] = m.get("created_at", "")
            msg["Message-ID"] = f"<{m['id']}@awlor.online>"
            if m.get("body_text"):
                msg.attach(MIMEText(m["body_text"], "plain", "utf-8"))
            if m.get("body_html"):
                msg.attach(MIMEText(m["body_html"], "html", "utf-8"))
            safe = "".join(c for c in (m.get("subject", "") or "") if c.isalnum() or c in "-_ ")[:40].strip() or str(m["id"])
            zf.writestr(f"{m['id']}_{safe}.eml", msg.as_bytes())
    zip_buffer.seek(0)
    db.add_audit_log(user["id"], user["username"], "EXPORT_ZIP", details=f"folder={folder}")
    return StreamingResponse(
        iter([zip_buffer.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="awlor_export_{folder}.zip"'}
    )

# ============================================================
# PARTIE 7 \u2014 NOTIFICATIONS & DIGEST
# ============================================================

@app.get("/api/notifications/prefs")
async def api_get_notif_prefs(user=Depends(auth.require_auth)):
    prefs = db.get_notification_prefs(user["id"])
    return JSONResponse({"prefs": prefs})

@app.post("/api/notifications/prefs")
async def api_save_notif_prefs(request: Request, user=Depends(auth.require_auth)):
    data = await request.json()
    db.save_notification_prefs(user["id"], data)
    return JSONResponse({"success": True})

@app.post("/api/digest/send")
async def api_send_digest(request: Request, user=Depends(auth.require_perm("can_change_settings"))):
    """Admin: force l'envoi du rapport hebdomadaire pour tous les utilisateurs."""
    from scheduler import _run_weekly_digest
    _run_weekly_digest()
    return JSONResponse({"success": True, "message": "Digest hebdomadaire envoy\u00e9"})

@app.post("/api/digest/preview")
async def api_preview_digest(user=Depends(auth.require_auth)):
    """Pr\u00e9visualise le digest de l'utilisateur courant."""
    addresses = db.get_all_addresses_for_user(user["id"])
    stats = db.get_weekly_stats(user["id"], addresses)
    return JSONResponse({"success": True, "stats": stats})

# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    port = int(db.get_setting("app_port", os.getenv("PORT", "15431")))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

from fastapi import FastAPI, Request, Form, HTTPException, Depends, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import uvicorn
import os
import database as db
import auth
from email_client import EmailClient
from config import settings

db.init_db()

app = FastAPI(title="serveircMail", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
client = EmailClient()

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
    roles = [r for r in db.get_all_roles() if r["name"] == "USER"]
    return render("register.html", request, {"error": request.query_params.get("error", ""), "roles": roles})

@app.post("/register")
async def register(request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    mail_password: str = Form(default="")):
    if db.get_setting("allow_registration", "1") != "1":
        return RedirectResponse("/login?error=registration_closed", status_code=302)
    ip = auth.get_client_ip(request)
    imap_host = db.get_setting("global_imap_host", "")
    smtp_host = db.get_setting("global_smtp_host", "")
    ok, err = db.create_user(username, display_name, email, password,
        imap_host=imap_host, smtp_host=smtp_host, mail_password=mail_password)
    if not ok:
        return RedirectResponse(f"/register?error={err}", status_code=302)
    user = db.get_user_by_username(username)
    db.add_audit_log(user["id"], username, "REGISTER", ip=ip)
    token = db.create_session(user["id"])
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
    mail_password: str = Form(default=""),
    new_password: str = Form(default=""),
    user=Depends(auth.require_auth)):
    updates = {"display_name": display_name}
    if mail_password:
        updates["mail_password"] = mail_password
    if new_password:
        updates["password"] = new_password
    db.update_user(user["id"], **updates)
    db.add_audit_log(user["id"], user["username"], "PROFILE_UPDATE")
    return RedirectResponse("/profile?success=1", status_code=302)

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
    password: str = Form(...), role_id: int = Form(4), mail_password: str = Form(default="")):
    ip = auth.get_client_ip(request)
    imap_host = db.get_setting("global_imap_host", "")
    smtp_host = db.get_setting("global_smtp_host", "")
    ok, err = db.create_user(username, display_name, email, password, role_id,
        imap_host=imap_host, smtp_host=smtp_host, mail_password=mail_password)
    db.add_audit_log(user["id"], user["username"], "CREATE_USER", target=username, ip=ip)
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/users/{uid}/update")
async def admin_update_user(request: Request, uid: int, user=Depends(auth.require_perm("can_manage_users")),
    display_name: str = Form(...), role_id: int = Form(...), is_active: int = Form(1),
    is_banned: int = Form(0), mail_password: str = Form(default="")):
    updates = {"display_name": display_name, "role_id": role_id, "is_active": is_active, "is_banned": is_banned}
    if mail_password:
        updates["mail_password"] = mail_password
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

def get_mail_client(user):
    ec = EmailClient(
        imap_host=user.get("imap_host") or settings.IMAP_HOST,
        imap_port=user.get("imap_port") or settings.IMAP_PORT,
        smtp_host=user.get("smtp_host") or settings.SMTP_HOST,
        smtp_port=user.get("smtp_port") or settings.SMTP_PORT,
        email_address=user.get("email"),
        email_password=user.get("mail_password") or settings.EMAIL_PASSWORD,
    )
    return ec

@app.get("/api/folders")
async def api_folders(user=Depends(auth.require_auth)):
    return {"folders": get_mail_client(user).get_folders()}

@app.get("/api/mails")
async def api_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20, user=Depends(auth.require_auth)):
    return get_mail_client(user).get_mails(folder=folder, page=page, per_page=per_page)

@app.get("/api/mail/{uid}")
async def api_mail(uid: int, folder: str = "INBOX", user=Depends(auth.require_auth)):
    return get_mail_client(user).get_mail(uid=uid, folder=folder)

@app.post("/api/send")
async def api_send(request: Request, user=Depends(auth.require_auth)):
    if not db.user_has_perm(user["id"], "can_send_mail"):
        raise HTTPException(403)
    data = await request.json()
    result = get_mail_client(user).send_mail(to=data.get("to"), subject=data.get("subject"), body=data.get("body"), html=data.get("html", False))
    if result.get("success"):
        db.add_audit_log(user["id"], user["username"], "SEND_MAIL", target=data.get("to"))
    return result

@app.post("/api/mail/{uid}/delete")
async def api_delete(uid: int, folder: str = "INBOX", user=Depends(auth.require_auth)):
    if not db.user_has_perm(user["id"], "can_delete_mail"):
        raise HTTPException(403)
    return get_mail_client(user).delete_mail(uid=uid, folder=folder)

@app.get("/api/stats")
async def api_stats(user=Depends(auth.require_auth)):
    return get_mail_client(user).get_stats()

@app.get("/api/admin/stats")
async def api_admin_stats(user=Depends(auth.require_perm("can_view_stats"))):
    return db.get_global_stats()

@app.get("/health")
async def health():
    return {"status": "ok", "app": "serveircMail"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 15431)), reload=False)

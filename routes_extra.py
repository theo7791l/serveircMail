"""All new feature routes for Awlor."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import json
import time
import os

router = APIRouter()

# ===== MODELS =====

class AIRequest(BaseModel):
    message: str
    context_mail_uid: Optional[str] = None
    context_folder: Optional[str] = None
    action: Optional[str] = None  # summarize, reply, spam, translate, extract, generate
    target_lang: Optional[str] = None
    instruction: Optional[str] = None

class StarRequest(BaseModel):
    uid: str
    folder: str

class SnoozeRequest(BaseModel):
    uid: str
    folder: str
    wake_at: str

class DraftRequest(BaseModel):
    id: Optional[int] = None
    subject: Optional[str] = ""
    body: Optional[str] = ""
    to: Optional[str] = ""
    cc: Optional[str] = ""
    bcc: Optional[str] = ""

class RuleRequest(BaseModel):
    id: Optional[int] = None
    name: str
    condition_field: str  # from, to, subject, body
    condition_op: str  # contains, equals, starts_with, ends_with, not_contains
    condition_value: str
    action_type: str  # move, star, delete, mark_read, mark_spam
    action_value: Optional[str] = ""
    priority: Optional[int] = 0
    enabled: Optional[int] = 1

class TemplateRequest(BaseModel):
    id: Optional[int] = None
    name: str
    subject: Optional[str] = ""
    body: str

class ScheduleRequest(BaseModel):
    mail_to: str
    subject: str
    body: str
    send_at: str

class FolderColorRequest(BaseModel):
    folder: str
    color: str


def get_current_user(request: Request):
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return user


# ===== AI ROUTES =====

@router.post("/api/ai/chat")
async def ai_chat(req: AIRequest, request: Request):
    from ai_client import chat
    from database_extra import get_ai_history, add_ai_message
    user = get_current_user(request)
    history = get_ai_history(user.id)
    history.append({"role": "user", "content": req.message})
    result = chat(history)
    if result["error"]:
        raise HTTPException(status_code=503, detail=result["error"])
    add_ai_message(user.id, "user", req.message)
    add_ai_message(user.id, "assistant", result["content"])
    return {"response": result["content"]}


@router.post("/api/ai/summarize")
async def ai_summarize(req: AIRequest, request: Request):
    from ai_client import summarize_mail
    get_current_user(request)
    subject = req.message
    body = req.instruction or ""
    sender = req.context_folder or ""
    result = summarize_mail(subject, body, sender)
    if result["error"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return {"response": result["content"]}


@router.post("/api/ai/reply")
async def ai_reply(req: AIRequest, request: Request):
    from ai_client import generate_reply
    get_current_user(request)
    result = generate_reply(
        subject=req.message,
        body=req.instruction or "",
        sender=req.context_folder or "",
        instruction=req.target_lang or "réponse professionnelle"
    )
    if result["error"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return {"response": result["content"]}


@router.post("/api/ai/spam")
async def ai_spam(req: AIRequest, request: Request):
    from ai_client import detect_spam
    get_current_user(request)
    result = detect_spam(
        subject=req.message,
        body=req.instruction or "",
        sender=req.context_folder or ""
    )
    if result["error"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return {"response": result["content"]}


@router.post("/api/ai/translate")
async def ai_translate(req: AIRequest, request: Request):
    from ai_client import translate_mail
    get_current_user(request)
    result = translate_mail(
        subject=req.message,
        body=req.instruction or "",
        target_lang=req.target_lang or "français"
    )
    if result["error"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return {"response": result["content"]}


@router.post("/api/ai/extract")
async def ai_extract(req: AIRequest, request: Request):
    from ai_client import extract_actions
    get_current_user(request)
    result = extract_actions(subject=req.message, body=req.instruction or "")
    if result["error"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return {"response": result["content"]}


@router.delete("/api/ai/history")
async def ai_clear_history(request: Request):
    from database_extra import clear_ai_history
    user = get_current_user(request)
    clear_ai_history(user.id)
    return {"ok": True}


@router.get("/api/ai/history")
async def ai_get_history(request: Request):
    from database_extra import get_ai_history
    user = get_current_user(request)
    return {"history": get_ai_history(user.id)}


# ===== STARS =====

@router.post("/api/mails/star")
async def toggle_star(req: StarRequest, request: Request):
    from database_extra import toggle_star as _toggle
    user = get_current_user(request)
    starred = _toggle(user.id, req.uid, req.folder)
    return {"starred": starred}


@router.get("/api/mails/starred")
async def get_starred(request: Request):
    from database_extra import get_starred as _get
    user = get_current_user(request)
    return {"starred": _get(user.id)}


# ===== SNOOZE =====

@router.post("/api/mails/snooze")
async def snooze_mail(req: SnoozeRequest, request: Request):
    from database_extra import snooze_mail as _snooze
    user = get_current_user(request)
    snooze_id = _snooze(user.id, req.uid, req.folder, req.wake_at)
    return {"ok": True, "snooze_id": snooze_id}


@router.get("/api/mails/snoozed")
async def get_snoozed(request: Request):
    from database_extra import get_snoozed as _get
    user = get_current_user(request)
    return {"snoozed": _get(user.id)}


# ===== DRAFTS =====

@router.post("/api/drafts/save")
async def save_draft(req: DraftRequest, request: Request):
    from database_extra import save_draft as _save
    user = get_current_user(request)
    draft_id = _save(user.id, req.dict())
    return {"ok": True, "draft_id": draft_id}


@router.get("/api/drafts")
async def get_drafts(request: Request):
    from database_extra import get_drafts as _get
    user = get_current_user(request)
    return {"drafts": _get(user.id)}


@router.delete("/api/drafts/{draft_id}")
async def delete_draft(draft_id: int, request: Request):
    from database_extra import delete_draft as _del
    user = get_current_user(request)
    _del(user.id, draft_id)
    return {"ok": True}


# ===== RULES =====

@router.get("/api/rules")
async def get_rules(request: Request):
    from database_extra import get_rules as _get
    user = get_current_user(request)
    return {"rules": _get(user.id)}


@router.post("/api/rules")
async def save_rule(req: RuleRequest, request: Request):
    from database_extra import save_rule as _save
    user = get_current_user(request)
    rule_id = _save(user.id, req.dict())
    return {"ok": True, "rule_id": rule_id}


@router.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int, request: Request):
    from database_extra import delete_rule as _del
    user = get_current_user(request)
    _del(user.id, rule_id)
    return {"ok": True}


# ===== TEMPLATES =====

@router.get("/api/templates")
async def get_templates(request: Request):
    from database_extra import get_templates as _get
    user = get_current_user(request)
    return {"templates": _get(user.id)}


@router.post("/api/templates")
async def save_template(req: TemplateRequest, request: Request):
    from database_extra import save_template as _save
    user = get_current_user(request)
    tmpl_id = _save(user.id, req.dict())
    return {"ok": True, "template_id": tmpl_id}


@router.delete("/api/templates/{tmpl_id}")
async def delete_template(tmpl_id: int, request: Request):
    from database_extra import delete_template as _del
    user = get_current_user(request)
    _del(user.id, tmpl_id)
    return {"ok": True}


# ===== SCHEDULED SEND =====

@router.post("/api/mails/schedule")
async def schedule_mail(req: ScheduleRequest, request: Request):
    from database_extra import schedule_mail as _schedule
    user = get_current_user(request)
    from_addr = f"{user.username}@{os.getenv('MAIL_DOMAIN', 'awlor.online')}"
    sid = _schedule(user.id, from_addr, req.mail_to, req.subject, req.body, req.send_at)
    return {"ok": True, "scheduled_id": sid}


@router.get("/api/mails/scheduled")
async def get_scheduled(request: Request):
    from database_extra import get_scheduled as _get
    user = get_current_user(request)
    return {"scheduled": _get(user.id)}


# ===== READ RECEIPT PIXEL =====

@router.get("/track/{token}.png")
async def track_open(token: str):
    from database_extra import mark_receipt_opened
    mark_receipt_opened(token)
    # Return 1x1 transparent PNG
    png = bytes([
        0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,
        0x49,0x48,0x44,0x52,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,
        0x08,0x06,0x00,0x00,0x00,0x1F,0x15,0xC4,0x89,0x00,0x00,0x00,
        0x0A,0x49,0x44,0x41,0x54,0x78,0x9C,0x62,0x00,0x01,0x00,0x00,
        0x05,0x00,0x01,0x0D,0x0A,0x2D,0xB4,0x00,0x00,0x00,0x00,0x49,
        0x45,0x4E,0x44,0xAE,0x42,0x60,0x82
    ])
    return Response(content=png, media_type="image/png")


# ===== FOLDER COLORS =====

@router.get("/api/folder-colors")
async def get_folder_colors(request: Request):
    from database_extra import get_folder_colors as _get
    user = get_current_user(request)
    return {"colors": _get(user.id)}


@router.post("/api/folder-colors")
async def set_folder_color(req: FolderColorRequest, request: Request):
    from database_extra import set_folder_color as _set
    user = get_current_user(request)
    _set(user.id, req.folder, req.color)
    return {"ok": True}


# ===== ADMIN TESTS =====

@router.post("/api/admin/run-test")
async def run_test(request: Request):
    import traceback
    body = await request.json()
    test_name = body.get("test", "")
    user = get_current_user(request)
    # Must be admin
    if not hasattr(user, 'role_id') or user.role_id != 1:
        raise HTTPException(status_code=403, detail="Admin requis")

    start = time.time()
    result = {"ok": False, "detail": "", "ms": 0}

    try:
        if test_name == "db_read":
            from database_extra import get_conn
            conn = get_conn()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            result = {"ok": True, "detail": "Lecture DB OK"}

        elif test_name == "db_write":
            from database_extra import get_conn
            conn = get_conn()
            conn.execute("CREATE TABLE IF NOT EXISTS _test_awlor (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO _test_awlor VALUES (NULL)")
            count = conn.execute("SELECT COUNT(*) FROM _test_awlor").fetchone()[0]
            conn.execute("DROP TABLE _test_awlor")
            conn.commit(); conn.close()
            result = {"ok": True, "detail": f"Écriture DB OK ({count} ligne(s) test)"}

        elif test_name == "smtp":
            import smtplib
            host = os.getenv("SMTP_HOST", "")
            port = int(os.getenv("SMTP_PORT", "587"))
            user_smtp = os.getenv("SMTP_USER", "")
            pwd = os.getenv("SMTP_PASS", "")
            if not host:
                result = {"ok": False, "detail": "SMTP_HOST non configuré"}
            else:
                s = smtplib.SMTP(host, port, timeout=10)
                s.starttls()
                if user_smtp and pwd:
                    s.login(user_smtp, pwd)
                s.quit()
                result = {"ok": True, "detail": f"SMTP connecté à {host}:{port}"}

        elif test_name == "imap":
            import imaplib
            host = os.getenv("IMAP_HOST", "")
            port = int(os.getenv("IMAP_PORT", "993"))
            imap_user = os.getenv("IMAP_USER", "")
            imap_pass = os.getenv("IMAP_PASS", "")
            if not host:
                result = {"ok": False, "detail": "IMAP_HOST non configuré"}
            else:
                m = imaplib.IMAP4_SSL(host, port)
                m.login(imap_user, imap_pass)
                status, folders = m.list()
                m.logout()
                result = {"ok": True, "detail": f"IMAP OK — {len(folders)} dossier(s) trouvés"}

        elif test_name == "auth":
            from auth import create_session_token, verify_session_token
            token = create_session_token(user.id)
            uid = verify_session_token(token)
            if uid == user.id:
                result = {"ok": True, "detail": "Auth session OK — token créé et vérifié"}
            else:
                result = {"ok": False, "detail": "Erreur de vérification du token"}

        elif test_name == "groq":
            from ai_client import chat
            r = chat([{"role": "user", "content": "Dis juste 'OK Awlor' pour confirmer que tu fonctionnes."}])
            if r["error"]:
                result = {"ok": False, "detail": r["error"]}
            else:
                result = {"ok": True, "detail": f"Groq AI répond : {r['content'][:80]}"}

        elif test_name == "internal_send":
            from database_extra import get_conn
            conn = get_conn()
            users = conn.execute("SELECT id, username FROM users LIMIT 2").fetchall()
            conn.close()
            if len(users) < 1:
                result = {"ok": False, "detail": "Aucun utilisateur dans la DB"}
            else:
                result = {"ok": True, "detail": f"Utilisateurs trouvés: {', '.join([u['username'] for u in users])} — envoi interne possible"}

        elif test_name == "create_user_test":
            from database_extra import get_conn
            import secrets
            conn = get_conn()
            test_username = f"_test_{secrets.token_hex(4)}"
            conn.execute(
                "INSERT INTO users (username, email, password_hash, display_name, role_id, verified) VALUES (?,?,?,?,2,1)",
                (test_username, f"{test_username}@test.local", "test_hash", "Test User", )
            )
            uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("DELETE FROM users WHERE id=?", (uid,))
            conn.commit(); conn.close()
            result = {"ok": True, "detail": f"Utilisateur test créé puis supprimé (ID: {uid})"}

        elif test_name == "snooze":
            from database_extra import snooze_mail, get_snoozed
            snooze_mail(user.id, "TEST_UID_999", "INBOX", "2099-12-31T00:00:00")
            snoozed = get_snoozed(user.id)
            result = {"ok": True, "detail": f"Snooze OK — {len(snoozed)} mail(s) endormi(s)"}

        elif test_name == "rules":
            from database_extra import save_rule, get_rules, delete_rule
            rid = save_rule(user.id, {"name":"Test Rule","condition_field":"from","condition_op":"contains","condition_value":"test","action_type":"star"})
            rules = get_rules(user.id)
            delete_rule(user.id, rid)
            result = {"ok": True, "detail": f"Règles OK — {len(rules)} règle(s) définies"}

        elif test_name == "templates":
            from database_extra import save_template, get_templates, delete_template
            tid = save_template(user.id, {"name":"Test","subject":"Test","body":"Bonjour {{nom}}"})
            tmpls = get_templates(user.id)
            delete_template(user.id, tid)
            result = {"ok": True, "detail": f"Templates OK — {len(tmpls)} template(s)"}

        elif test_name == "scheduled_send":
            from database_extra import schedule_mail, get_scheduled
            sid = schedule_mail(user.id, "test@awlor.online", "dest@test.local", "Test", "Corps", "2099-12-31T00:00:00")
            scheduled = get_scheduled(user.id)
            result = {"ok": True, "detail": f"Envoi programmé OK — ID {sid}, {len(scheduled)} mail(s) en attente"}

        elif test_name == "read_receipt":
            from database_extra import create_receipt, mark_receipt_opened, get_conn
            token = create_receipt(user.id, "TEST_UID", "test@test.local")
            mark_receipt_opened(token)
            conn = get_conn()
            r2 = conn.execute("SELECT opened_at FROM read_receipts WHERE token=?", (token,)).fetchone()
            conn.close()
            if r2 and r2["opened_at"]:
                result = {"ok": True, "detail": f"Read receipt OK — ouverture enregistrée à {r2['opened_at']}"}
            else:
                result = {"ok": False, "detail": "Read receipt : échec enregistrement"}

        else:
            result = {"ok": False, "detail": f"Test '{test_name}' inconnu"}

    except Exception as e:
        result = {"ok": False, "detail": f"Exception: {str(e)}"}

    result["ms"] = round((time.time() - start) * 1000)
    return result


@router.get("/admin/tests", response_class=HTMLResponse)
async def admin_tests_page(request: Request):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="templates")
    user = get_current_user(request)
    if user.role_id != 1:
        raise HTTPException(status_code=403, detail="Admin requis")
    return templates.TemplateResponse(
        "admin/tests.html",
        {"request": request, "current_user": user, "site_name": os.getenv("SITE_NAME", "Awlor")}
    )

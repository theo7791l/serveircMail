"""Routes API étendues : IA Groq, snooze, étoile, brouillons, règles, templates, envoi programmé, suivi, heatmap, timeline."""
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from typing import Optional, List
import httpx
import json
import time
from datetime import datetime

import database as db

router = APIRouter()

# ===== AUTH HELPER =====

def get_current_user(request: Request):
    token = request.cookies.get("session_token")
    user = db.get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return user

# ===== AI / GROQ =====

class AIRequest(BaseModel):
    message: str
    mail_context: Optional[dict] = None
    action: Optional[str] = None  # summarize, reply, translate, detect_spam, generate, triage

@router.post("/api/ai/chat")
async def ai_chat(req: AIRequest, request: Request):
    user = get_current_user(request)
    groq_key = db.get_setting("groq_api_key")
    if not groq_key:
        raise HTTPException(status_code=503, detail="Clé Groq non configurée")
    if db.get_setting("ai_enabled") != "1":
        raise HTTPException(status_code=503, detail="IA désactivée")

    model = db.get_setting("groq_model", "llama-3.3-70b-versatile")
    history = db.get_ai_history(user["id"], limit=10)

    addresses = db.get_all_addresses_for_user(user["id"])
    primary = db.get_primary_address(user["id"])
    site_name = db.get_setting("site_name", "Awlor")

    system_prompt = f"""Tu es l'assistant IA intégré à {site_name}, une boîte mail professionnelle.
Tu peux : résumer des mails, rédiger des réponses, traduire, détecter le spam, générer des mails complets, suggérer des règles de tri, et répondre à toutes les questions sur la boîte mail.
L'utilisateur est {user['display_name']} ({primary}). Ses adresses : {', '.join(addresses)}.
Réponds toujours en français sauf si l'utilisateur demande autre chose. Sois concis, professionnel et utile.
Si l'on te demande d'effectuer une action (envoyer un mail, déplacer, etc.), retourne un JSON structuré avec les champs : action, data."""

    if req.mail_context:
        system_prompt += f"\n\nContexte du mail actuel :\nDe : {req.mail_context.get('from','')}\nObjet : {req.mail_context.get('subject','')}\nContenu : {str(req.mail_context.get('body_text',''))[:2000]}"

    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": req.message})

    db.save_ai_message(user["id"], "user", req.message)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.7}
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Erreur Groq : {resp.text}")
        data = resp.json()

    answer = data["choices"][0]["message"]["content"]
    db.save_ai_message(user["id"], "assistant", answer)

    return {"reply": answer, "model": model}

@router.delete("/api/ai/history")
async def clear_ai_history(request: Request):
    user = get_current_user(request)
    db.clear_ai_history(user["id"])
    return {"ok": True}

@router.get("/api/ai/history")
async def get_ai_history_endpoint(request: Request):
    user = get_current_user(request)
    history = db.get_ai_history(user["id"], limit=50)
    return {"history": history}

# ===== STAR / SEEN TOGGLE =====

@router.post("/api/mails/{mail_id}/star")
async def star_mail(mail_id: int, request: Request):
    user = get_current_user(request)
    new_val = db.toggle_star(mail_id)
    return {"starred": new_val}

@router.post("/api/mails/{mail_id}/seen")
async def toggle_seen(mail_id: int, request: Request):
    user = get_current_user(request)
    new_val = db.toggle_seen(mail_id)
    return {"seen": new_val}

@router.post("/api/mails/{mail_id}/move")
async def move_mail(mail_id: int, request: Request):
    user = get_current_user(request)
    body = await request.json()
    folder = body.get("folder", "INBOX")
    db.move_mail(mail_id, folder)
    return {"ok": True, "folder": folder}

# ===== BULK ACTIONS =====

class BulkRequest(BaseModel):
    mail_ids: List[int]
    action: str

@router.post("/api/mails/bulk")
async def bulk_action(req: BulkRequest, request: Request):
    user = get_current_user(request)
    addresses = db.get_all_addresses_for_user(user["id"])
    db.bulk_action_mails(req.mail_ids, req.action, addresses)
    return {"ok": True, "action": req.action, "count": len(req.mail_ids)}

# ===== SNOOZE =====

class SnoozeRequest(BaseModel):
    mail_id: int
    snooze_until: str

@router.post("/api/mails/snooze")
async def snooze_mail(req: SnoozeRequest, request: Request):
    user = get_current_user(request)
    db.snooze_mail(user["id"], req.mail_id, req.snooze_until)
    return {"ok": True}

@router.get("/api/mails/snoozed")
async def get_snoozed(request: Request):
    user = get_current_user(request)
    snoozed = db.get_snoozed_mails(user["id"])
    return {"snoozed": snoozed}

# ===== DRAFTS =====

class DraftRequest(BaseModel):
    mail_from: str = ""
    mail_to: str = ""
    subject: str = ""
    body_html: str = ""
    body_text: str = ""
    draft_id: Optional[int] = None

@router.post("/api/drafts")
async def save_draft(req: DraftRequest, request: Request):
    user = get_current_user(request)
    draft_id = db.save_draft(
        user["id"], req.mail_from, req.mail_to,
        req.subject, req.body_html, req.body_text, req.draft_id
    )
    return {"ok": True, "draft_id": draft_id}

@router.get("/api/drafts")
async def get_drafts(request: Request):
    user = get_current_user(request)
    drafts = db.get_drafts(user["id"])
    return {"drafts": drafts}

@router.get("/api/drafts/{draft_id}")
async def get_draft(draft_id: int, request: Request):
    user = get_current_user(request)
    draft = db.get_draft_by_id(draft_id, user["id"])
    if not draft:
        raise HTTPException(status_code=404, detail="Brouillon introuvable")
    return draft

@router.delete("/api/drafts/{draft_id}")
async def delete_draft(draft_id: int, request: Request):
    user = get_current_user(request)
    db.delete_draft(draft_id, user["id"])
    return {"ok": True}

# ===== SCHEDULED MAILS =====

class ScheduledRequest(BaseModel):
    mail_from: str
    mail_to: str
    subject: str = ""
    body_html: str = ""
    body_text: str = ""
    send_at: str

@router.post("/api/mails/schedule")
async def schedule_mail(req: ScheduledRequest, request: Request):
    user = get_current_user(request)
    if "can_send_mail" not in db.get_user_permissions(user["id"]):
        raise HTTPException(status_code=403, detail="Permission refusée")
    new_id = db.save_scheduled_mail(
        user["id"], req.mail_from, req.mail_to,
        req.subject, req.body_html, req.body_text, req.send_at
    )
    return {"ok": True, "id": new_id}

# ===== MAIL RULES =====

class RuleRequest(BaseModel):
    name: str
    condition_field: str
    condition_operator: str
    condition_value: str
    action_type: str
    action_value: str = ""
    priority: int = 0

@router.get("/api/rules")
async def get_rules(request: Request):
    user = get_current_user(request)
    rules = db.get_all_mail_rules(user["id"])
    return {"rules": rules}

@router.post("/api/rules")
async def create_rule(req: RuleRequest, request: Request):
    user = get_current_user(request)
    new_id = db.create_mail_rule(
        user["id"], req.name, req.condition_field,
        req.condition_operator, req.condition_value,
        req.action_type, req.action_value, req.priority
    )
    return {"ok": True, "id": new_id}

@router.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int, request: Request):
    user = get_current_user(request)
    db.delete_mail_rule(rule_id, user["id"])
    return {"ok": True}

# ===== REPLY TEMPLATES =====

class TemplateRequest(BaseModel):
    name: str
    subject: str = ""
    body_html: str = ""
    shortcut: str = ""

@router.get("/api/templates")
async def get_templates(request: Request):
    user = get_current_user(request)
    templates = db.get_reply_templates(user["id"])
    return {"templates": templates}

@router.post("/api/templates")
async def create_template(req: TemplateRequest, request: Request):
    user = get_current_user(request)
    new_id = db.create_reply_template(user["id"], req.name, req.subject, req.body_html, req.shortcut)
    return {"ok": True, "id": new_id}

@router.delete("/api/templates/{template_id}")
async def delete_template(template_id: int, request: Request):
    user = get_current_user(request)
    db.delete_reply_template(template_id, user["id"])
    return {"ok": True}

# ===== FOLLOW-UP =====

class FollowupRequest(BaseModel):
    mail_id: int
    days: int = 3

@router.post("/api/followup")
async def set_followup(req: FollowupRequest, request: Request):
    user = get_current_user(request)
    db.set_followup(user["id"], req.mail_id, req.days)
    return {"ok": True}

@router.get("/api/followup")
async def get_followups(request: Request):
    user = get_current_user(request)
    addresses = db.get_all_addresses_for_user(user["id"])
    alerts = db.get_followup_alerts(user["id"], addresses)
    return {"alerts": alerts}

@router.post("/api/followup/{followup_id}/dismiss")
async def dismiss_followup(followup_id: int, request: Request):
    user = get_current_user(request)
    db.dismiss_followup(followup_id)
    return {"ok": True}

# ===== READ RECEIPT (pixel) =====

@router.get("/api/receipt/{mail_id}.png")
async def read_receipt_pixel(mail_id: int, request: Request):
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    db.record_read_receipt(mail_id, ip, ua)
    pixel = bytes([
        0x47,0x49,0x46,0x38,0x39,0x61,0x01,0x00,0x01,0x00,0x80,0x00,0x00,
        0xFF,0xFF,0xFF,0x00,0x00,0x00,0x21,0xF9,0x04,0x00,0x00,0x00,0x00,0x00,
        0x2C,0x00,0x00,0x00,0x00,0x01,0x00,0x01,0x00,0x00,0x02,0x02,0x44,0x01,0x00,0x3B
    ])
    return Response(content=pixel, media_type="image/gif")

@router.get("/api/receipts/{mail_id}")
async def get_receipts(mail_id: int, request: Request):
    user = get_current_user(request)
    receipts = db.get_read_receipts(mail_id)
    return {"receipts": receipts}

# ===== FOLDER COLORS =====

class FolderColorRequest(BaseModel):
    folder_name: str
    color: str

@router.get("/api/folder-colors")
async def get_folder_colors(request: Request):
    user = get_current_user(request)
    colors = db.get_folder_colors(user["id"])
    return {"colors": colors}

@router.post("/api/folder-colors")
async def set_folder_color(req: FolderColorRequest, request: Request):
    user = get_current_user(request)
    db.set_folder_color(user["id"], req.folder_name, req.color)
    return {"ok": True}

# ===== HEATMAP =====

@router.get("/api/heatmap")
async def get_heatmap(request: Request):
    user = get_current_user(request)
    addresses = db.get_all_addresses_for_user(user["id"])
    data = db.get_mail_heatmap(addresses)
    return {"heatmap": data}

# ===== TIMELINE =====

@router.get("/api/timeline/{contact}")
async def get_timeline(contact: str, request: Request):
    user = get_current_user(request)
    timeline = db.get_mail_timeline(user["id"], contact)
    return {"timeline": timeline}

# ===== ADMIN TESTS =====

@router.post("/api/admin/run-test")
async def run_admin_test(request: Request):
    user = get_current_user(request)
    if "can_run_tests" not in db.get_user_permissions(user["id"]):
        raise HTTPException(status_code=403, detail="Permission refusée")
    body = await request.json()
    test_name = body.get("test")
    start = time.time()
    result = {"test": test_name, "status": "error", "message": "", "details": "", "duration_ms": 0}

    try:
        if test_name == "database_read":
            conn = db.get_conn()
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            conn.close()
            result.update({"status": "ok", "message": f"Lecture OK — {count} utilisateur(s)", "details": f"SELECT COUNT(*) FROM users = {count}"})

        elif test_name == "database_write":
            conn = db.get_conn()
            conn.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('_test_write', datetime('now'))")
            conn.commit()
            conn.execute("DELETE FROM system_settings WHERE key='_test_write'")
            conn.commit()
            conn.close()
            result.update({"status": "ok", "message": "Lecture/écriture DB réussie"})

        elif test_name == "session_auth":
            sessions_count = db.get_conn().execute("SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now')").fetchone()[0]
            db.get_conn().close()
            result.update({"status": "ok", "message": f"Auth OK — {sessions_count} session(s) actives"})

        elif test_name == "smtp":
            smtp_pass = db.get_setting("global_smtp_password")
            if not smtp_pass:
                result.update({"status": "error", "message": "Clé SMTP/Resend non configurée"})
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {smtp_pass}"}
                    )
                if resp.status_code in [200, 401]:
                    result.update({"status": "ok" if resp.status_code == 200 else "warning",
                                   "message": f"Endpoint Resend répond (HTTP {resp.status_code})",
                                   "details": f"Clé : {'valide' if resp.status_code == 200 else 'invalide ou permissions limitées'}"})
                else:
                    result.update({"status": "error", "message": f"Erreur HTTP {resp.status_code}"})

        elif test_name == "groq_ai":
            groq_key = db.get_setting("groq_api_key")
            if not groq_key:
                result.update({"status": "error", "message": "Clé Groq non configurée"})
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {groq_key}"},
                        json={"model": db.get_setting("groq_model", "llama-3.3-70b-versatile"),
                              "messages": [{"role": "user", "content": "Dis juste OK"}],
                              "max_tokens": 10}
                    )
                if resp.status_code == 200:
                    answer = resp.json()["choices"][0]["message"]["content"]
                    result.update({"status": "ok", "message": f"Groq répond : {answer}"})
                else:
                    result.update({"status": "error", "message": f"Groq HTTP {resp.status_code}: {resp.text[:200]}"})

        elif test_name == "webhook":
            webhook_url = db.get_setting("webhook_url")
            if not webhook_url:
                result.update({"status": "error", "message": "URL webhook non configurée"})
            else:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    try:
                        resp = await client.get(webhook_url)
                        result.update({"status": "ok", "message": f"Webhook accessible (HTTP {resp.status_code})"})
                    except Exception as e:
                        result.update({"status": "error", "message": f"Webhook inaccessible : {str(e)[:100]}"})

        elif test_name == "create_test_user":
            import random, string
            rand = ''.join(random.choices(string.ascii_lowercase, k=6))
            test_username = f"_test_{rand}"
            test_email = f"{test_username}@test.internal"
            ok, err = db.create_user(test_username, "Test User", test_email, "TestPass123!")
            if ok:
                user_row = db.get_user_by_username(test_username)
                db.delete_user(user_row["id"])
                result.update({"status": "ok", "message": f"Création et suppression utilisateur test réussies", "details": f"Username: {test_username}"})
            else:
                result.update({"status": "error", "message": f"Erreur création : {err}"})

        elif test_name == "internal_mail_send":
            addresses = db.get_all_addresses_for_user(user["id"])
            if not addresses:
                result.update({"status": "error", "message": "Aucune adresse trouvée pour l'admin"})
            else:
                test_addr = addresses[0]
                db.save_inbound_mail(
                    test_addr, test_addr, "[TEST] Mail interne système",
                    "<p>Test d'envoi interne système réussi.</p>",
                    "Test d'envoi interne système réussi."
                )
                result.update({"status": "ok", "message": f"Mail interne envoyé à {test_addr}", "details": "Vérifie ta boîte de réception"})

        elif test_name == "snooze":
            mails = db.get_inbound_mails_multi(
                db.get_all_addresses_for_user(user["id"]), folder="INBOX", page=1, per_page=1
            )
            if mails["mails"]:
                mail_id = int(mails["mails"][0]["uid"])
                from datetime import timedelta
                snooze_time = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
                db.snooze_mail(user["id"], mail_id, snooze_time)
                db.process_snooze_wakeups()
                db.move_mail(mail_id, "INBOX")
                result.update({"status": "ok", "message": "Snooze créé et annulé correctement"})
            else:
                result.update({"status": "warning", "message": "Aucun mail dans INBOX pour tester"})

        elif test_name == "rules_engine":
            rule_id = db.create_mail_rule(
                user["id"], "_test_rule", "subject", "contains", "__test__", "star", "", 99
            )
            mails = db.get_inbound_mails_multi(
                db.get_all_addresses_for_user(user["id"]), folder="INBOX", page=1, per_page=1
            )
            if mails["mails"]:
                mail_id = int(mails["mails"][0]["uid"])
                db.apply_mail_rules(user["id"], mail_id, "test@test.com", "__test__ subject")
                result.update({"status": "ok", "message": "Moteur de règles fonctionnel"})
            else:
                result.update({"status": "warning", "message": "Aucun mail pour tester les règles"})
            db.delete_mail_rule(rule_id, user["id"])

        elif test_name == "draft_save":
            addresses = db.get_all_addresses_for_user(user["id"])
            from_addr = addresses[0] if addresses else "test@test.com"
            draft_id = db.save_draft(user["id"], from_addr, "test@test.com", "[TEST] Brouillon", "<p>Test</p>", "Test", None)
            draft = db.get_draft_by_id(draft_id, user["id"])
            db.delete_draft(draft_id, user["id"])
            if draft:
                result.update({"status": "ok", "message": "Brouillon créé et supprimé correctement"})
            else:
                result.update({"status": "error", "message": "Brouillon introuvable après création"})

        elif test_name == "heatmap":
            addresses = db.get_all_addresses_for_user(user["id"])
            data = db.get_mail_heatmap(addresses)
            result.update({"status": "ok", "message": f"Heatmap générée — {sum(data)} mails sur 7j", "details": str(data)})

        elif test_name == "ai_config":
            groq_key = db.get_setting("groq_api_key")
            model = db.get_setting("groq_model")
            enabled = db.get_setting("ai_enabled")
            result.update({"status": "ok" if groq_key else "warning",
                           "message": f"IA {'activée' if enabled=='1' else 'désactivée'} — Modèle : {model}",
                           "details": f"Clé {'configurée' if groq_key else 'MANQUANTE'}"})

        else:
            result.update({"status": "error", "message": f"Test inconnu : {test_name}"})

    except Exception as e:
        result.update({"status": "error", "message": f"Exception : {str(e)[:300]}"})

    result["duration_ms"] = round((time.time() - start) * 1000, 1)
    return result

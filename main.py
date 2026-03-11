from fastapi import FastAPI, Request, Form, HTTPException, Depends, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import uvicorn
import json
from email_client import EmailClient
from config import settings
import hashlib
import os

app = FastAPI(title="serveircMail", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

client = EmailClient()

SESSION_TOKEN = None

def get_session(session: Optional[str] = Cookie(default=None)):
    if session != hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest():
        return None
    return session

@app.get("/", response_class=HTMLResponse)
async def root(request: Request, session=Depends(get_session)):
    if not session:
        return RedirectResponse("/login")
    return RedirectResponse("/inbox")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "site_name": settings.SITE_NAME})

@app.post("/login")
async def login(response: Response, password: str = Form(...)):
    expected = hashlib.sha256(settings.EMAIL_PASSWORD.encode()).hexdigest()
    provided = hashlib.sha256(password.encode()).hexdigest()
    if settings.EMAIL_ADDRESS and provided == expected:
        token = hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest()
        resp = RedirectResponse("/inbox", status_code=302)
        resp.set_cookie("session", token, httponly=True, max_age=86400*7)
        return resp
    return RedirectResponse("/login?error=1", status_code=302)

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("session")
    return resp

@app.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request, session=Depends(get_session), page: int = 1, folder: str = "INBOX"):
    if not session:
        return RedirectResponse("/login")
    return templates.TemplateResponse("inbox.html", {
        "request": request,
        "site_name": settings.SITE_NAME,
        "email": settings.EMAIL_ADDRESS,
        "folder": folder,
        "page": page
    })

@app.get("/compose", response_class=HTMLResponse)
async def compose(request: Request, session=Depends(get_session), reply_to: str = "", subject: str = ""):
    if not session:
        return RedirectResponse("/login")
    return templates.TemplateResponse("compose.html", {
        "request": request,
        "site_name": settings.SITE_NAME,
        "email": settings.EMAIL_ADDRESS,
        "reply_to": reply_to,
        "subject": subject
    })

@app.get("/mail/{uid}", response_class=HTMLResponse)
async def read_mail(request: Request, uid: int, folder: str = "INBOX", session=Depends(get_session)):
    if not session:
        return RedirectResponse("/login")
    return templates.TemplateResponse("read.html", {
        "request": request,
        "site_name": settings.SITE_NAME,
        "email": settings.EMAIL_ADDRESS,
        "uid": uid,
        "folder": folder
    })

# ==================== API ROUTES ====================

@app.get("/api/folders")
async def api_folders(session=Depends(get_session)):
    if not session:
        raise HTTPException(401)
    folders = client.get_folders()
    return {"folders": folders}

@app.get("/api/mails")
async def api_mails(folder: str = "INBOX", page: int = 1, per_page: int = 20, session=Depends(get_session)):
    if not session:
        raise HTTPException(401)
    mails = client.get_mails(folder=folder, page=page, per_page=per_page)
    return mails

@app.get("/api/mail/{uid}")
async def api_mail(uid: int, folder: str = "INBOX", session=Depends(get_session)):
    if not session:
        raise HTTPException(401)
    mail = client.get_mail(uid=uid, folder=folder)
    return mail

@app.post("/api/send")
async def api_send(request: Request, session=Depends(get_session)):
    if not session:
        raise HTTPException(401)
    data = await request.json()
    result = client.send_mail(
        to=data.get("to"),
        subject=data.get("subject"),
        body=data.get("body"),
        html=data.get("html", False)
    )
    return result

@app.post("/api/mail/{uid}/read")
async def api_mark_read(uid: int, folder: str = "INBOX", session=Depends(get_session)):
    if not session:
        raise HTTPException(401)
    return client.mark_read(uid=uid, folder=folder)

@app.post("/api/mail/{uid}/delete")
async def api_delete(uid: int, folder: str = "INBOX", session=Depends(get_session)):
    if not session:
        raise HTTPException(401)
    return client.delete_mail(uid=uid, folder=folder)

@app.get("/api/stats")
async def api_stats(session=Depends(get_session)):
    if not session:
        raise HTTPException(401)
    return client.get_stats()

@app.get("/health")
async def health():
    return {"status": "ok", "app": "serveircMail"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 15431)), reload=False)

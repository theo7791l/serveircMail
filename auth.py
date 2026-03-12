from fastapi import Request, Cookie, HTTPException, Depends
from fastapi.responses import RedirectResponse
from typing import Optional
import database as db

def get_current_user(request: Request, session: Optional[str] = Cookie(default=None)):
    user = db.get_session_user(session)
    return user

def require_auth(request: Request, session: Optional[str] = Cookie(default=None)):
    user = db.get_session_user(session)
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    if user.get("is_banned"):
        raise HTTPException(status_code=403, detail="Compte banni")
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Compte suspendu")
    return user

def require_perm(perm: str):
    def checker(request: Request, session: Optional[str] = Cookie(default=None)):
        user = db.get_session_user(session)
        if not user:
            raise HTTPException(status_code=307, headers={"Location": "/login"})
        if not db.user_has_perm(user["id"], perm):
            raise HTTPException(status_code=403, detail=f"Permission requise : {perm}")
        return user
    return checker

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

from fastapi import Request, Cookie, HTTPException, Depends
from typing import Optional
from database import get_session_user, get_user_permissions

def get_current_user(session: Optional[str] = Cookie(default=None)):
    if not session:
        return None
    user = get_session_user(session)
    return user

def require_user(session: Optional[str] = Cookie(default=None)):
    user = get_current_user(session)
    if not user:
        from fastapi.responses import RedirectResponse
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user

def require_permission(permission: str):
    def dep(session: Optional[str] = Cookie(default=None)):
        user = get_current_user(session)
        if not user:
            raise HTTPException(status_code=307, headers={"Location": "/login"})
        perms = get_user_permissions(user["id"])
        if permission not in perms:
            raise HTTPException(status_code=403, detail="Permission refusée")
        return user
    return dep

def require_role_level(min_level: int):
    def dep(session: Optional[str] = Cookie(default=None)):
        user = get_current_user(session)
        if not user:
            raise HTTPException(status_code=307, headers={"Location": "/login"})
        if user["role_level"] < min_level:
            raise HTTPException(status_code=403, detail="Niveau de rôle insuffisant")
        return user
    return dep
